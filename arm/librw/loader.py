#!/usr/bin/env python

import argparse
from collections import defaultdict

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection
from elftools.elf.relocation import RelocationSection
from elftools.elf.constants import SH_FLAGS

from .container import Container, Function, Section
from .disasm import disasm_bytes
from .rw import Rewriter

from arm.librw.util.logging import *


class Loader():
    def __init__(self, fname):
        debug(f"Loading {fname}...")
        self.fd = open(fname, 'rb')
        self.elffile = ELFFile(self.fd)
        self.container = Container()
        print(self.elffile['e_type'])

    def is_stripped(self):
        # Get the symbol table entry for the respective symbol
        symtab = self.elffile.get_section_by_name('.symtab')
        if not symtab:
            print('No symbol table available, this file is probably stripped!')
            return True

        sym = symtab.get_symbol_by_name("main")[0]
        if not sym:
            print('Symbol {} not found')
            return True
        return False

    def is_pie(self):
        base_address = next(seg for seg in self.elffile.iter_segments() 
                if seg['p_type'] == "PT_LOAD")['p_vaddr']
        return self.elffile['e_type'] == 'ET_DYN' and base_address == 0

    def load_functions(self, fnlist):
        debug(f"Loading functions...")
        section = self.elffile.get_section_by_name(".text")
        data = section.data()
        base = section['sh_addr']
        for faddr, fvalue in fnlist.items():
            self.container.section_of_address(faddr).functions += [faddr]

            section_offset = faddr - base
            bytes = data[section_offset:section_offset + fvalue["sz"]]

            fixed_name = fvalue["name"].replace("@", "_")
            bind = fvalue["bind"] if fixed_name != "main" else "STB_GLOBAL" #main should always be global
            function = Function(fixed_name, faddr, fvalue["sz"], bytes, bind)
            self.container.add_function(function)
        # entrypoint = self.elffile.header.e_entry
        # startsize = 80
        # bytes = data[entrypoint - base:entrypoint - base + startsize]
        # start = Function("_start", entrypoint, startsize, bytes, "STB_GLOBAL") #_start is always global
        # self.container.add_function(start)

    def _is_data_section(self, sname, sval):
        # A data section should be present in memory (SHF_ALLOC), and its size should
        # be greater than 0. 
        return (
            sval['sz'] > 0 and
            (sval['flags'] & SH_FLAGS.SHF_ALLOC) != 0 and (
                (sval['flags'] & SH_FLAGS.SHF_EXECINSTR) == 0 or sname not in Rewriter.CODESECTIONS
            ) 
        )

    def _is_code_section(self, sname, sval):
        # A code section should be present in memory (SHF_ALLOC), and its size should
        # be greater than 0. 
        return (
            sval['sz'] > 0 and
            (sval['flags'] & SH_FLAGS.SHF_ALLOC) != 0 and (
                (sval['flags'] & SH_FLAGS.SHF_EXECINSTR) == 1 or sname not in Rewriter.DATASECTIONS
            ) 
        )

    def load_sections(self, seclist, section_filter=lambda x: True):
        debug(f"Loading sections...")
        for sec in [sec for sec in seclist if section_filter(sec)]:
            sval = seclist[sec]
            section = self.elffile.get_section_by_name(sec)
            data = section.data()
            more = bytearray()
            # if sec == ".init_array":
                # if len(data) > 8:
                    # data = data[8:]
                # else:
                    # data = b''
                # more.extend(data)
            # else:
            more.extend(data)
            if len(more) < sval['sz']:
                more.extend(
                    [0x0 for _ in range(0, sval['sz'] - len(more))])

            bytes = more
            print("Adding section: ", sec, hex(sval["base"]), "with size", hex(sval['sz']))
            sec = sec.replace("-","_")
            ds = Section(sec, sval["base"], sval["sz"], bytes,
                             (sval['align']))

            if self._is_data_section(sec, sval):
                self.container.add_data_section(ds)
            elif self._is_code_section(sec, sval):
                self.container.add_code_section(ds)

        # Find if there is a plt section
        for sec in seclist:
            if sec == '.plt':
                self.container.plt_base = seclist[sec]['base']
            if sec == ".plt.got":
                section = self.elffile.get_section_by_name(sec)
                data = section.data()
                entries = list(
                    disasm_bytes(section.data(), seclist[sec]['base']))
                self.container.gotplt_base = seclist[sec]['base']
                self.container.gotplt_sz = seclist[sec]['sz']
                self.container.gotplt_entries = entries

    def load_relocations(self, relocs):
        for reloc_section, relocations in relocs.items():

            # transform stuff like ".rela.dyn" in ".dyn"
            section = reloc_section[5:]

            if reloc_section == ".rela.plt":
                self.container.add_plt_information(relocations)

            if section in self.container.datasections:
                self.container.datasections[section].add_relocations(relocations)
            else:
                print("[*] Relocations for a section that's not loaded:",
                      reloc_section)
                self.container.add_relocations(section, relocations)

    def reloc_list_from_symtab(self):
        relocs = defaultdict(list)

        for section in self.elffile.iter_sections():
            if not isinstance(section, RelocationSection):
                continue

            symtable = self.elffile.get_section(section['sh_link'])

            for rel in section.iter_relocations():
                symbol = None
                if rel['r_info_sym'] != 0:
                    symbol = symtable.get_symbol(rel['r_info_sym'])

                if symbol:
                    if symbol['st_name'] == 0:
                        symsec = self.elffile.get_section(symbol['st_shndx'])
                        symbol_name = symsec.name
                    else:
                        symbol_name = symbol.name
                else:
                    symbol = dict(st_value=None)
                    symbol_name = None

                reloc_i = {
                    'name': symbol_name,
                    'st_value': symbol['st_value'],
                    'offset': rel['r_offset'],
                    'addend': rel['r_addend'],
                    'type': rel['r_info_type'],
                }

                relocs[section.name].append(reloc_i)

        return relocs

    def flist_from_symtab(self):
        symbol_tables = [
            sec for sec in self.elffile.iter_sections()
            if isinstance(sec, SymbolTableSection)
        ]

        function_list = dict()

        for section in symbol_tables:
            if not isinstance(section, SymbolTableSection):
                continue

            if section['sh_entsize'] == 0:
                continue

            for symbol in section.iter_symbols():
                if symbol['st_other']['visibility'] == "STV_HIDDEN":
                    continue

                if (symbol['st_info']['type'] == 'STT_FUNC'
                        and symbol['st_shndx'] != 'SHN_UNDEF'):
                    function_list[symbol['st_value']] = {
                        'name': symbol.name,
                        'sz': symbol['st_size'],
                        'visibility': symbol['st_other']['visibility'],
                        'bind': symbol['st_info']['bind'],
                    }

        return function_list

    def slist_from_symtab(self):
        sections = dict()
        for section in self.elffile.iter_sections():
            sections[section.name] = {
                'base': section['sh_addr'],
                'sz': section['sh_size'],
                'offset': section['sh_offset'],
                'align': section['sh_addralign'],
                'flags': section['sh_flags'],
                'type': section['sh_type'],
            }

        return sections

    def load_globals_from_glist(self, glist):
        self.container.add_globals(glist)

    def global_data_list_from_symtab(self):
        symbol_tables = [
            sec for sec in self.elffile.iter_sections()
            if isinstance(sec, SymbolTableSection)
        ]

        global_list = defaultdict(list)

        for section in symbol_tables:
            if not isinstance(section, SymbolTableSection):
                continue

            if section['sh_entsize'] == 0:
                continue

            for symbol in section.iter_symbols():
                # XXX: HACK
                if "@@GLIBC" in symbol.name:
                    continue
                if symbol['st_other']['visibility'] == "STV_HIDDEN":
                    continue
                if symbol['st_size'] == 0:
                    continue

                if (symbol['st_info']['type'] == 'STT_OBJECT'
                        and symbol['st_shndx'] != 'SHN_UNDEF'):
                    global_list[symbol['st_value']].append({
                        'name':
                        "{}_{:x}".format(symbol.name, symbol['st_value']),
                        'sz':
                        symbol['st_size'],
                    })

        return global_list
