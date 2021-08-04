import argparse
import copy
import itertools
from collections import defaultdict, deque

from capstone import CS_OP_IMM, CS_GRP_JUMP, CS_GRP_CALL, CS_OP_MEM, CS_OP_REG
from capstone.x86_const import X86_REG_RIP

from elftools.elf.descriptions import describe_reloc_type
from elftools.elf.enums import ENUM_RELOC_TYPE_x64
from elftools.elf.enums import ENUM_RELOC_TYPE_AARCH64

from arm.librw.util.logging import *
from arm.librw.util.arm_util import _is_jump_conditional, is_reg_32bits, get_64bits_reg, memory_replace, get_access_size_arm
from arm.librw.container import InstrumentedInstruction, Jumptable
from arm.librw.emulation import Path, Expr


class Rewriter():
    GCC_FUNCTIONS = [ # functions added by the compiler. No use in rewriting them
        # "_start",
        # "__libc_start_main",
        # "__libc_csu_fini",
        # "__libc_csu_init",
        # "__lib_csu_fini",
        # "_init",
        # "__libc_init_first",
        # "_fini",
        # "_rtld_fini",
        # "_exit",
        # "__get_pc_think_bx",
        # "__do_global_dtors_aux",
        # "__gmon_start",
        # "frame_dummy",
        # "__do_global_ctors_aux",
        # "__register_frame_info",
        # "deregister_tm_clones",
        # "register_tm_clones",
        # "__do_global_dtors_aux",
        # "__frame_dummy_init_array_entry",
        # "__init_array_start",
        # "__do_global_dtors_aux_fini_array_entry",
        # "__init_array_end",
        # "__stack_chk_fail",
        # "__cxa_atexit",
        # "__cxa_finalize",
        # "call_weak_fn" #not really sure about this, but imho we should'nt touch it
    ]

    GCC_RELOCATIONS = [ # relocations added by the compiler. Do not touch em!
        "__gmon_start__",
        "_ITM_deregisterTMCloneTable",
        "_ITM_registerTMCloneTable"
    ]

    # these sections need to be completely regenerated from scracth
    IGNORE_SECTIONS = [
        ".dynsym",
        ".dynstr",
        ".dynamic",
        ".eh_frame_hdr",
        ".eh_frame",
        ".rela.plt",
        ".gnu_version",
        ".gnu.version",
        ".gnu_version_r",
        ".gnu.version_r",
    ]

    literal_saves = 0
    total_globals = 0
    total_text = 0
    impossible_text = 0
    trivial_text = 0
    total_deleted_from_got = 0


    # DATASECTIONS = [".rodata", ".data", ".bss", ".data.rel.ro", ".init_array"]
    # DATASECTIONS = [".got", ".fini_array",  ".rodata", ".data", ".bss", ".data.rel.ro", ".init_array"]
    # DATASECTIONS = [".got", ".rodata", ".data", ".bss", ".data.rel.ro", ".init_array"]
    DATASECTIONS = [".got", ".rodata", ".data", ".bss", ".data.rel.ro", ".init_array", ".fini_array", ".got.plt"]
    CODESECTIONS = [".text", ".init", ".fini", ".plt"]

    def __init__(self, container, outfile):
        #XXX: remove global
        self.container = container
        self.outfile = outfile

        for sec, section in self.container.datasections.items():
            section.load()

        for _, function in self.container.functions.items():
            if function.name in Rewriter.GCC_FUNCTIONS:
                container.ignore_function_addrs += [function.start]
                continue
            function.disasm()

    def symbolize(self):
        symb = Symbolizer()
        symb.symbolize_data_sections(self.container, None)
        symb.symbolize_text_section(self.container, None)

    def dump(self):
        # we fix stuff that gets broken by too much instrumentation added,
        # like 'tbz' short jumps and jump tables.
        # it is *very* important that no further instrumentation is added from now!
        total_jumps_fixed = 0
        for _,function in self.container.functions.items():
            function.update_instruction_count()
            function.fix_literal_pools()
            total_jumps_fixed += function.fix_shortjumps()
            function.update_instruction_count()
            function.fix_jmptbl_size(self.container)

        if total_jumps_fixed:
            info(f"Fixed a total of {total_jumps_fixed} short jumps")

        results = list()
        for sec, section in sorted(
                self.container.datasections.items(), key=lambda x: x[1].base):
            results.append("%s" % (section))



        for section in self.container.codesections.values():
            results.append(f".section {section.name}")
            # results.append(f".align {section.align}") # removed to better fit sections
            data = section.bytes
            last_addr = base = section.base
            for faddr in sorted(section.functions):
                function = self.container.functions[faddr]
                for addr in range(last_addr, faddr): # fill in space between functions.
                    results.append(".LC%x: // filler between functions" % (addr))
                    results.append(f"\t .byte {hex(data[addr - base])}")
                last_addr = faddr + function.sz
                if function.name in Rewriter.GCC_FUNCTIONS:
                    continue
                results.append("\t.text\n%s" % (function))


        # fake sections for trampolines
        for section in self.container.codesections.values():
            results.append(f".section .fake{section.name}, \"ax\", @progbits")
            # results.append(".align 12") # removed to better fit sections
            results.append(f".fake{section.name}_start:")
            # last_addr = self.container.loader.elffile.get_section_by_name(".text")['sh_addr'] - 4
            last_addr = section.base - 4
            for faddr in sorted(section.functions):
                function = self.container.functions[faddr]
                if function.name in Rewriter.GCC_FUNCTIONS:
                    continue
                skip = function.start - last_addr - 4
                if skip > 0: results.append(".skip 0x%x" % (skip))
                last_addr = function.start
                results.append("b .LC%x // %s" % (function.start, function.name))


        # here we insert the list of dependencies of the elf,
        # that the linker will need to know about through lflags
        for dep in self.container.loader.dependencies:
            results.append(f"// DEPENDENCY: {dep}")

        with open(self.outfile, 'w') as outfd:
            outfd.write("\n".join(results + ['']))

        if Rewriter.total_globals > 0:
            info(f"Saved {Rewriter.literal_saves} out of {Rewriter.total_globals} global accesses ({Rewriter.literal_saves / Rewriter.total_globals * 100}% )")
            info(f"Out of {Rewriter.total_text} code pointers, {Rewriter.impossible_text} cannot be saved (of which {Rewriter.impossible_text - Rewriter.trivial_text} are non-trivial, in total {(Rewriter.impossible_text - Rewriter.trivial_text) / Rewriter.total_globals * 100}%) ")
        info(f"Success: retrowritten assembly to {self.outfile}")


# old, needed section alignment
class Symbolizer():
    def __init__(self):
        self.bases = set()
        self.xrefs = defaultdict(list)
        self.symbolized = set()

    # TODO: Use named symbols instead of generic labels when possible.
    # TODO: Replace generic call labels with function names instead
    def symbolize_text_section(self, container, context):
        # Symbolize using relocation information.
        # for rel in container.relocations[".text"]:
        code_relocations = list(map(lambda x: container.relocations[x], Rewriter.CODESECTIONS))
        for rel in list(itertools.chain.from_iterable(code_relocations)):
            fn = container.function_of_address(rel['offset'])
            if not fn or fn.name in Rewriter.GCC_FUNCTIONS:
                continue

            inst = fn.instruction_of_address(rel['offset'])
            if not inst:
                continue

            # Fix up imports
            if "@" in rel['name']:
                suffix = ""
                if rel['st_value'] == 0:
                    suffix = "@PLT"

                # XXX: ARM
                if len(inst.cs.operands) == 1:
                    inst.op_str = "%s%s" % (rel['name'].split("@")[0], suffix)
                else:
                    # Figure out which argument needs to be
                    # converted to a symbol.
                    if suffix:
                        suffix = "@PLT"
                    mem_access, _ = inst.get_mem_access_op()
                    if not mem_access:
                        continue
                    value = hex(mem_access.disp)
                    inst.op_str = inst.op_str.replace(
                        value, "%s%s" % (rel['name'].split("@")[0], suffix))
            else:
                mem_access, _ = inst.get_mem_access_op()
                if not mem_access:
                    # These are probably calls?
                    continue

                # XXX: ARM
                if (rel['type'] in [
                        ENUM_RELOC_TYPE_x64["R_X86_64_PLT32"],
                        ENUM_RELOC_TYPE_x64["R_X86_64_PC32"]
                ]):

                    value = mem_access.disp
                    ripbase = inst.address + inst.sz
                    inst.op_str = inst.op_str.replace(
                        hex(value), ".LC%x" % (ripbase + value))
                    if ".rodata" in rel["name"]:
                        self.bases.add(ripbase + value)
                else:
                    print("[*] Possible incorrect handling of relocation!")
                    value = mem_access.disp
                    inst.op_str = inst.op_str.replace(
                        hex(value), ".LC%x" % (rel['st_value']))

            self.symbolized.add(inst.address)

        self.symbolize_cf_transfer(container, context)
        # Symbolize remaining memory accesses
        self.symbolize_switch_tables(container, context)
        self.symbolize_mem_accesses(container, context)



    def symbolize_cf_transfer(self, container, context=None):
        for _, function in container.functions.items():
            function.addr_to_idx = dict()
            for inst_idx, instruction in enumerate(function.cache):
                function.addr_to_idx[instruction.address] = inst_idx

            for inst_idx, instruction in enumerate(function.cache):
                is_jmp = CS_GRP_JUMP in instruction.cs.groups
                is_call = instruction.cs.mnemonic in ["bl", "blr"]

                if not (is_jmp or is_call):
                    # https://idasuckless.github.io/the-brk-is-a-lie.html
                    if instruction.mnemonic == "brk":
                        function.nexts[inst_idx] = []
                    elif instruction.mnemonic.startswith('ret'):
                        function.nexts[inst_idx].append("ret")
                        instruction.cf_leaves_fn = True
                    # otherwise, if it's a normal istruction, just go to the next
                    else:
                        function.nexts[inst_idx].append(inst_idx + 1)
                    continue

                instruction.cf_leaves_fn = False

                if is_jmp and _is_jump_conditional(instruction.mnemonic):
                    if inst_idx + 1 < len(function.cache):
                        # Add natural flow edge
                        function.nexts[inst_idx].append(inst_idx + 1)
                    else:
                        # Out of function bounds, no idea what to do!
                        function.nexts[inst_idx].append("undef")
                elif is_call:
                    instruction.cf_leaves_fn = True
                    function.nexts[inst_idx].append("call")
                    if inst_idx + 1 < len(function.cache):
                        function.nexts[inst_idx].append(inst_idx + 1)
                    else:
                        # Out of function bounds, no idea what to do!
                        function.nexts[inst_idx].append("undef")

                target = 0
                if instruction.cs.operands[-1].type == CS_OP_IMM: # b 0xf20
                    target = instruction.cs.operands[-1].imm
                elif instruction.cs.operands[-1].type == CS_OP_REG: # br x0
                    function.possible_switches += [instruction.address]
                if target:
                    # Check if the target is in a code section.
                    # we exclude .plt as it means it's a call to an imported function
                    if any([container.is_in_section(x, target) for x in Rewriter.CODESECTIONS if x != ".plt"]):
                        function.bbstarts.add(target)
                        instruction.op_str = instruction.op_str.replace("#0x%x" % target, ".LC%x" % target)
                    elif target in container.plt:
                        name = container.plt[target]
                        instruction.op_str = "{}".format(name)
                        if any(exit in name for exit in ["abort", "exit"]): #XXX: fix this ugly hack
                            function.nexts[inst_idx] = []
                        if name == "__gmon_start__":
                            instruction.before += [InstrumentedInstruction(".weak __gmon_start__")]
                    else:
                        print(hex(target))
                        print(instruction)
                        critical("target outside code section. Aborting.")
                        exit(1)
                        gotent = container.is_target_gotplt(target)
                        if gotent:
                            found = False
                            for relocation in container.relocations[".dyn"]:
                                if gotent == relocation['offset']:
                                    instruction.op_str = "{}@PLT".format(
                                        relocation['name'])
                                    found = True
                                    break
                            if not found:
                                print("[x] Missed GOT entry!")
                        else:
                            print("[x] Missed call target: %x" % (target))

                    if is_jmp:
                        if target in function.addr_to_idx:
                            idx = function.addr_to_idx[target]
                            function.nexts[inst_idx].append(idx)
                        else:
                            instruction.cf_leaves_fn = True
                            function.nexts[inst_idx].append("undef")
                elif is_jmp:
                    function.nexts[inst_idx].append("undef")

        # after we're done, we prepare the prevs list
        self.reverse_nexts(container)

    def reverse_nexts(self, container):
        for _, function in container.functions.items():
            function.prevs = defaultdict(list)
            for idx, nexts in function.nexts.items():
                for nexti in nexts:
                    function.prevs[nexti] = function.prevs.get(nexti, [])
                    function.prevs[nexti].append(idx)

    def resolve_register_value(self, register, function, instr, max_steps=1e6):
        debug(f"Instructions leading up to {hex(instr.address)}")
        inst_idx = function.addr_to_idx[instr.address]
        reg_name = instr.cs.reg_name(register)
        visited = [False]*len(function.cache)
        paths = [Path(function, inst_idx, reg_pool=[reg_name], exprvalue=f"{reg_name}", visited=visited)]
        paths_finished = []
        while len(paths) > 0:
            p = paths[0]
            p.steps += 1
            prevs = function.prevs[p.inst_idx]

            # XXX: fix the ugly 'x' in p.expr hack
            if p.inst_idx == 0 or p.visited[p.inst_idx] or p.steps > max_steps or \
            len(prevs) == 0 or (len(p.reg_pool) == 0 and 'x' not in str(p.expr)):  # we got to the start of the function 
                paths_finished += [paths[0]]
                debug("finished path")
                del paths[0]
                continue

            p.visited[p.inst_idx] = True
            if len(prevs) > 1:
                debug(f"MULTIPLE prevs:  {[hex(function.cache[i].address) for i in prevs]}")
                #XXX: add other paths here
            p.inst_idx = prevs[0]
            instr = function.cache[p.inst_idx]
            regs_write = instr.reg_writes_common()
            # if any([reg in p.reg_pool for reg in regs_write]):

            new_paths = p.emulate(instr)

            if new_paths:
                for pp in new_paths:
                    paths += [pp]

        for p in paths_finished:
            p.expr.simplify()
            debug("FINAL " + str(p.expr))
            return p.expr

    def _memory_read(self, container, addr, size, signed=False):
        sec = container.section_of_address(addr)
        if sec.name != ".rodata": 
            debug(f"WARNING: changing value not in rodata but in {sec.name}")
        return sec.read_at(addr, size, signed)

    def _guess_cases_number(self, container, function, addr):
        max_instrs_before_switch = 30
        start_idx = function.addr_to_idx[addr]
        instr = function.cache[start_idx]
        found = -1
        reg_index = False
        class path:
            def __init__(self, steps=0, reg_index=False, found=-1, idx=start_idx):
                self.steps = steps
                self.reg_index = reg_index
                self.found = found
                self.inst_idx = idx

        paths = [path()]
        paths_finished = []
        while len(paths):
            p = paths[0]
            p.steps += 1
            prevs = function.prevs[p.inst_idx]
            if p.inst_idx == 0 or len(prevs) == 0 or p.steps > max_instrs_before_switch:
                paths_finished += [paths.pop(0)]
                continue
            debug(f"taking path at {hex(function.cache[p.inst_idx].address)}, total paths {len(paths)}")

            for i in prevs:
                debug(f"MULTIPLE prevs: {[hex(function.cache[i].address) for i in prevs]}")

            p.inst_idx = prevs[0]
            instr = function.cache[p.inst_idx]



            if instr.mnemonic.startswith("ldr") and not p.reg_index:
                mem, mem_op_idx = instr.get_mem_access_op()
                if mem.index: p.reg_index = mem.index
            if instr.mnemonic.startswith("cmp") and p.reg_index:
                if instr.cs.operands[0].reg == p.reg_index and \
                   instr.cs.operands[1].type == CS_OP_IMM:
                    p.found = instr.cs.operands[1].imm
                    # adjustments for differenct comparisons
                    # we try to look for the next jump and decide
                    for i in range(10):
                        next_instr = function.cache[p.inst_idx + i]
                        if not next_instr: 
                            break
                        is_jmp = CS_GRP_JUMP in next_instr.cs.groups
                        if is_jmp:
                            if next_instr.mnemonic in ["b.hi", "b.ls", "b.le"]:
                                p.found += 1
                            break
                    # if next_instr and next_instr.mnemonic in ["b.lt"]: p.found -= 1
                    paths_finished += [paths.pop(0)]
                    debug("found path " +  str(len(paths)))
                    continue
            if instr.mnemonic == "movz" and instr.cs.operands[0].reg == p.reg_index:
                # if the register is written with a constant value, we just ignore this path
                paths.pop(0)
                continue
            if instr.mnemonic == "mov" and instr.cs.operands[0].reg == p.reg_index:
                # if the register is substitued by another register, it might be the comparison
                # is done on the new one, so we start another path form scratch with that reg
                paths.pop(0)
                paths += [path(p.steps, instr.cs.operands[1].reg, -1, start_idx)]
                continue

            for prev in prevs[1:]:
                print("adding path", hex(function.cache[prev].address), instr.cs.reg_name(p.reg_index))
                paths += [path(p.steps, p.reg_index, p.found, prev)]

        debug(f"number of cases: {[p.found for p in paths_finished]}")
        true_paths_finished = list(filter(lambda x: x.found != -1, paths_finished))
        if len(true_paths_finished) != len(paths_finished):
            critical(f"Some paths not concluded while guessing cases number for switch at {addr}!")
        if any([p.found != true_paths_finished[0].found for p in true_paths_finished]):
            return -1 # if there are inconsistencies, we quit!
        return true_paths_finished[0].found

    def symbolize_switch_tables(self, container, context):
        rodata = container.datasections.get(".rodata", None)
        if not rodata:
            assert False
        for _, function in container.functions.items():
            for jump in function.possible_switches:
                # we do two tries, changing the number of instructions to analyze before the switch
                # if 20 are enough, then good, otherwise we perform a much deeper analysis. 
                # this is because _very rarely_ too much analysis can break, so we prefer to keep it low if possible
                # an example is the br at 0x77e970 in the gcc_r spec cpu2017 benchmark, it breaks if tries > 50
                for tries in [20, 1000]:
                    inst_idx = function.addr_to_idx[jump]
                    instr = function.cache[inst_idx]
                    reg = instr.cs.operands[0].reg
                    debug(f"Analyzing switch on {instr.cs}, {instr.cs.reg_name(reg)}")
                    expr = self.resolve_register_value(reg, function, instr, max_steps=tries)
                    # print(instr.cs, expr)

                    # Super advanced pattern matching

                    # addr
                    if isinstance(expr.left, int):
                        debug(f"Found a blr at {instr.cs} but it is really a call to {hex(expr.left)}! - ignoring for now")
                        continue

                    # x0
                    if isinstance(expr.left, str):
                        continue

                    # [addr]
                    elif expr.left.mem and expr.left.right == None: 
                        # addr = int(str(expr.left.left))
                        # value = self._memory_read(container, addr, 8)
                        # swlbl = ".LC%x" % (value,)
                        # memory_replace(container, addr, 8, swlbl)
                        continue

                    # addr + ... (no register present in expression)
                    # if all([c not in str(expr) for c in ['x', 'w']]): 
                        # continue

                    # first_case_addr + [ jmptbl_addr + ??? ]
                    elif isinstance(expr.left.right, Expr) and expr.left.right.left \
                        and isinstance(expr.left.right.left, Expr) and expr.left.right.left.mem\
                        and isinstance(expr.left.right.left.left, int):
                        try: #XXX remove this try catch and uncomment (and fix) above expression about not having registers
                             # probably you need to implement multiple path traversal in the switch detection
                            base_case = expr.left.left
                            debug(f"BASE CASE: {base_case}")
                            size = expr.left.right.left.mem
                            jmptbl_addr = int(str(expr.left.right.left.left))
                            shift = expr.left.right.right
                            debug(f"SHIFT: {shift}")
                            debug(f"JMPTBL: {jmptbl_addr}")
                            debug(f"SIZE: {size}")

                            cases = self._guess_cases_number(container, function, instr.address)
                            debug(f"CASES: {cases}")
                            if cases == -1:
                                assert False

                            cases_list = []

                            for i in range(cases):
                                value = self._memory_read(container, jmptbl_addr + i*size, size, signed=True)
                                debug("VALUE:" + str(value))
                                addr = base_case + value*(2**shift)
                                swlbl = "(.LC%x-.LC%x)/%d" % (addr, base_case, 2**shift)
                                memory_replace(container, jmptbl_addr + i*size, size, swlbl)
                                cases_list += [addr]

                            function.add_switch(Jumptable(instr.address, jmptbl_addr, size, base_case, cases_list))
                            break
                        except:
                            critical(f"JUMP TABLE at {hex(instr.address)} recognized but failed to symbolize!")
                            continue

                    else:
                        info(f"JUMP TABLE at {hex(instr.address)} impossible to recognize!")
                        info(f"Potential crashes in function {function.name}")
                        info(f"final expression: {expr}")



    def _adjust_target(self, container, target):
        # Find the nearest section
        sec = None
        for sname, sval in sorted(
                container.datasections.items(), key=lambda x: x[1].base):
            if sval.base >= target:
                break
            sec = sval

        assert sec is not None

        end = sec.base  # + sec.sz - 1
        adjust = target - end

        assert adjust > 0

        return end, adjust

    def _is_target_in_region(self, container, target):
        for sec, sval in container.datasections.items():
            if sval.base <= target < sval.base + sval.sz:
                return True

        for fn, fval in container.functions.items():
            if fval.start <= target < fval.start + fval.sz:
                return True

        return False

    def _adjust_adrp_section_pointer_litpools(self, container, secname, orig_off, instruction):
        # we adjust things like adrp x0, 0x10000 (start of .bss)
        # to stuff like  ldr x0, =(.bss - (offset))
        # to make global variables work
        assert instruction.mnemonic.startswith("adr")
        base = container.datasections[secname].base
        reg_name = instruction.reg_writes()[0]
        diff = base - orig_off
        op = '-' if diff > 0 else '+'
        # if secname == ".got": secname = ".fake_got" # the got is special, as it
        secname = secname + "_start"
        # will get overwritten by the compiler after reassembly. We introduce a 
        # "fake_got" label so that we keep track of where the "old" got section was
        instruction.mnemonic = "ldr"
        instruction.op_str = "%s, =(%s %c 0x%x)"  % (reg_name, secname, op, abs(diff))
        instruction.instrumented = True

    def _adjust_adrp_section_pointer(self, container, secname, orig_off, instruction):
        assert instruction.mnemonic.startswith("adr")
        Rewriter.literal_saves += 1
        if secname in container.codesections:
            base = container.codesections[secname].base
            secname = f".fake{secname}"
        elif secname == ".got":
            # the compiler will add stuff at the start of .got, need to take that into account
            base = container.datasections['.got'].base + Rewriter.total_deleted_from_got
        else:
            base = container.datasections[secname].base
        reg_name = instruction.reg_writes()[0]
        diff = base - orig_off
        op = '-' if diff > 0 else '+'
        secname = secname + "_start"
        # will get overwritten by the compiler after reassembly. We introduce a 
        # "got_start" label so that we keep track of where the "old" got section was
        pages = (abs(diff) // 4096) * 4096
        instruction.instrument_before(InstrumentedInstruction(f"\tadrp {reg_name}, ({secname} {op} {pages})"))
        instruction.instrument_before(InstrumentedInstruction(f"\tadd {reg_name}, {reg_name}, :lo12:{secname}"))
        instruction.mnemonic = "add" if op == "+" else "sub"
        instruction.op_str = "%s, %s, %s"  % (reg_name, reg_name, abs(diff) % 4096)
        # trying to get it shorter, does not work
        # instruction.mnemonic = "add"
        # instruction.op_str = f"{reg_name}, {reg_name}, (:lo12:{secname} {op} {abs(diff)%4096})"
        # instruction.instrumented = True


    def _get_resolved_address(self, function, inst, inst2, path):
        if inst2.cs.mnemonic == "add":
            if not inst2.cs.operands[2].type == CS_OP_IMM:
                return 0
            assert all([op.shift.value == 0 for op in inst2.cs.operands])
            return path.orig_off + inst2.cs.operands[2].imm
        elif inst2.cs.mnemonic.startswith("mov"):
            return inst2.cs.reg_name(inst2.cs.operands[0].reg) # moved to a different reg, new path
        elif inst2.cs.mnemonic.startswith("ldr"):
            assert inst2.cs.operands[1].type == CS_OP_MEM
            if not all([op.shift.value == 0 for op in inst2.cs.operands]):
                return 0
            return path.orig_off + inst2.cs.operands[1].mem.disp
        elif inst2.cs.mnemonic.startswith("str"):
            if inst2.cs.reg_name(inst2.cs.operands[0].reg) == path.orig_reg: # str <orig_reg>, [...]
                if not inst2.cs.reg_name(inst2.cs.operands[1].reg) == "x29":
                    # assert False
                    return 0
                expr = self.resolve_register_value(inst2.cs.operands[0].reg, function, inst2)
                if not isinstance(expr.left, int):
                    return 0
                return (expr.left, inst2.cs.operands[1].mem.disp)
            else:
                if inst2.cs.operands[1].mem.disp != 0: # str ..., [<orig_reg> + ...]
                    return path.orig_off + inst2.cs.operands[1].mem.disp
                else: # str ..., [<orig_reg> + <unknown_reg>]
                    return 0
        elif inst2.cs.mnemonic.startswith("stp"):
            if inst2.cs.reg_name(inst2.cs.operands[0].reg) == path.orig_reg: # stp <orig_reg>, ..., [...]
                op_num, adding = 0, 0
            elif inst2.cs.reg_name(inst2.cs.operands[1].reg) == path.orig_reg: # stp ..., <orig_reg>, [...]
                op_num, adding = 1, get_access_size_arm(inst2.cs)[0] // 2
            else: # stp ..., [<orig_reg> + ...]
                return path.orig_off + inst2.cs.operands[1].mem.disp

            mem, mem_op_idx = inst2.get_mem_access_op()
            if not inst2.cs.reg_name(mem.base) == "x29":
                return 0
            expr = self.resolve_register_value(inst2.cs.operands[op_num].reg, function, inst2)
            if not isinstance(expr.left, int):
                return 0
            return (expr.left, mem.disp + adding)
        else:
            return 0


    def _adjust_global_access(self, container, function, edx, inst):
        # there is an adrp somewhere in the code, this means global variable...
        # global variable addresses are dynamically built in multiple instructions
        # here we try to resolve the address with some capstone trickery and shady assumptions

        Rewriter.total_globals += 1

        orig_off = inst.cs.operands[1].imm
        orig_reg = inst.reg_writes()[0]

        possible_sections = []
        for name,s in container.datasections.items():
            if s.base // 0x1000 == orig_off // 0x1000 or \
               s.base <= orig_off < s.base + s.sz:
                possible_sections += [name]



        # WHAT TO DO
        # so actually this was never implemented? Not sure. I vividly remember testing it though...
        # well, now off to work!




        # WHAT TO DO PART 2
        # part 3
        # ok no to be honest you just need to pass the -lm flag
        # to gcc and he will fix .dynamic for you
        # now the only section that is "wobbly" is the .got.
        # how are we gonna fix the got? Not sure lol

        # WHAT TO DO PART 3
        # updates from the .got: it's the relocations baby
        # is it unsolvable? not sure
        # also I get crashes bc I removed the minimum alignment of 12

        # WHAT TO DO 4
        # adrp has now become 3 instructions, it sucks, but I think I can 
        # do better. let's now try fixing the .got

        # WHAT TO DO 4
        # .got is basically done! amazing job. 
        # it is a super bad hack though
        # on the test binary there is still some difference in the size
        # of .dynamic sections. Need to look into that.




        text = container.text_section # check for .text, as it is not a datasection
        ### FIXME
        ### WARNING:
        ### the text['sh_size'] - 0x320 down below is needed to fix adrp's at
        ### 0x7073e4 and 0x6d8444 and 0x775470 in cpugcc_r, because
        ### they point to .rodata but they also overlap in 0x31c with the .text
        ### since heuristics are broken for the above adrp. We decide to ignore
        ### the last 0x320 bytes of the text as a partial workaround
        ### this will be fixed with the .fake_text directly followed by .rodota
        ### mimicking the same section layout of the original binary
        ### when I get to implement heuristics-free global pointer constructions
        ### XXX
        # if text['sh_addr'] // 0x1000 == orig_off // 0x1000 or \
            # text['sh_addr'] <= orig_off < text['sh_addr'] + text['sh_size'] - 0x320:
            # possible_sections += ['.text']

        if len(possible_sections) == 1:
            secname = possible_sections[0]
            # even if it's text, we rewrite it
            self._adjust_adrp_section_pointer(container, secname, orig_off, inst)
            return

        debug(f"Global access at {inst}, multiple sections possible: {possible_sections}, trying to resolve address...")

        # if we got here, it's bad, as we're not sure which section the global variable is in.
        # We try to resolve all possible addresses by simulating all possible control flow paths.
        # we will also track down stack pushes of global pointers because they can be loaded later

        class path:
            def __init__(self, orig_reg="x0", idx=0, stack_stores=[], orig_off=orig_off,
                               visited={}, function=function):
                self.stack_stores = stack_stores
                self.orig_reg = orig_reg
                self.idx = idx
                self.orig_off = orig_off
                self.visited = visited
                self.function = function

        resolved_addresses = []
        paths = [path(orig_reg, nexti, [], visited=defaultdict(lambda: False)) for nexti in function.nexts[edx]]
        while len(paths):
            p = paths[0]
            inst2 = p.function.cache[p.idx]
            if p.visited[inst2.address]:
                del paths[0]
                continue
            p.visited[inst2.address] = 1

            # check if someone is overwriting one of the saved global pointers on the stack
            # XXX: add support for stp
            if inst2.mnemonic == "str" and inst2.cs.reg_name(inst2.cs.operands[1].reg) == "x29" and\
                    inst2.cs.operands[1].mem.disp in p.stack_stores:
                p.stack_stores.remove(inst2.cs.operands[1].mem.disp)

            # check if we are loading a previously saved global pointer from the stack
            # XXX: add support for ldp
            if inst2.mnemonic == "ldr" and inst2.cs.reg_name(inst2.cs.operands[1].reg) == "x29" and\
                    inst2.cs.operands[1].mem.disp in p.stack_stores:
                debug(f"Found stack load at {inst2}, from {inst}!")
                new_reg = inst2.cs.reg_name(inst2.cs.operands[0].reg)
                paths.append(path(new_reg, p.idx + 1, [], p.orig_off, copy.deepcopy(p.visited)))

            if p.orig_reg in inst2.reg_reads():
                if inst2.instrumented or '=' in inst2.op_str:  # XXX: ugly hack to avoid reinstrumenting instructions
                    del paths[0]
                    continue
                raddr = self._get_resolved_address(p.function, inst, inst2, p)
                if isinstance(raddr, tuple):  # a global pointer was pushed on the stack
                    addr, disp = raddr
                    debug(f"Found new stack store at addr {inst2} from {inst}")
                    p.stack_stores += [disp]
                elif isinstance(raddr, str):  # the register we're tracking has been changed
                    paths.append(path(raddr, p.idx + 1, p.stack_stores[:], p.orig_off, copy.deepcopy(p.visited), function))
                elif raddr:                   # a global pointer was just used normally 
                    resolved_addresses += [(inst2, raddr, p.orig_reg)]
                else:
                    critical(f"Missed global resolved address on {inst2} from {inst}")

            if p.orig_reg in inst2.reg_writes_common():
                if len(p.stack_stores) == 0:
                    del paths[0] # we overwrote the register we're trying to resolve, so abandon this path
                    continue
                else:  # unless we pushed it on the stack
                    p.orig_reg = "None"

            if inst2.mnemonic == "b" and inst2.cs.operands[0].type == CS_OP_IMM:
                # we go across functions!
                # Some restrictions: 1. only through direct jumps 2. do not go back to the original func
                # otherwise we will get stuck in infinite loops
                fun2 = container.function_of_address(inst2.cs.operands[0].imm)
                if fun2 != None and fun2.start != p.function.start:
                    idx = fun2.addr_to_idx[inst2.cs.operands[0].imm]
                    debug(f"Found new trampoline at {inst2} from {inst}")
                    p.function = fun2
                    p.idx = idx
                    # paths.append(path(p.orig_reg, idx, p.stack_stores[:], p.orig_off, p.visited, fun2))

                    # del paths[0]
                    continue

            # print(p.function.nexts[p.idx])
            next_instrs = list(filter(lambda x: isinstance(x, int), p.function.nexts[p.idx]))
            if len(next_instrs) == 0:
                del paths[0]
                continue
            p.idx = next_instrs[0]
            for n in next_instrs[1:]:
                # if n < idx: continue
                if not isinstance(n, int): continue
                if n == 0: continue # avoid recursive calls to same function
                if p.visited[p.function.cache[n].address]: continue
                # count = list(filter(lambda x: x == 1, p.visited))
                # debug(f"Appending to {n}, {len(paths)}, {len(count)}")
                paths.append(path(p.orig_reg, n, p.stack_stores[:], p.orig_off, p.visited, p.function))



        possible_sections = set()
        for r in resolved_addresses[:]:
            (i, addr) = r[0], r[1]
            sec = container.section_of_address(addr)
            if sec:
                debug(f"to_fix: {i.cs}, in section {sec.name}")
                possible_sections.add(sec.name)
            else:
                critical(f"WARNING: no section for resolved addr {hex(addr)} at {i.cs}, ignoring")
                resolved_addresses.remove(r)


        debug(f"After resolving addresses, here are the possible sections: {possible_sections}")
        if len(possible_sections) == 1:
            secname = list(possible_sections)[0]
            if secname not in container.codesections:
                self._adjust_adrp_section_pointer(container, secname, orig_off, inst)
                debug(f"We're good, false alarm, the only possible section is: {secname}. Nice!")
                return
            else: #XXX: remove this else case!!!!
                print("OMGGGGGGGGGGGGGGGG" , inst.address)
                self._adjust_adrp_section_pointer(container, secname, orig_off, inst)
                return
                # Rewriter.total_text += 1
                # no_func = 0
                # for _, functiona in container.functions.items():
                    # if orig_off <= functiona.start <= orig_off + 0x1000:
                        # no_func += 1
                # if no_func > 1:
                    # Rewriter.impossible_text += 1
                    # nexti = function.cache[function.nexts[edx][0]]
                    # if len(function.nexts[edx]) == 1 and nexti.cs.mnemonic == "add" and p.orig_reg in nexti.reg_writes_common() and p.orig_reg in nexti.reg_reads_common():
                        # Rewriter.trivial_text += 1
                    # elif len(function.nexts[function.addr_to_idx[nexti.address]]) == 1:
                        # nexti = function.cache[function.nexts[function.nexts[edx][0]][0]]
                        # if len(function.nexts[edx]) == 1 and nexti.cs.mnemonic == "add" and p.orig_reg in nexti.reg_writes_common() and p.orig_reg in nexti.reg_reads_common():
                            # Rewriter.trivial_text += 1

        # if we got here, it's *very* bad, as we're *still* not sure which
        # section the global variable is in, or that section is the .text
        # section. 
        # As our last hope we try to ugly-hack-patch all instructions that use the register with the
        # global address loaded (instructions in the resolved_addresses list)
        debug(f"WARNING: trying to fix each instruction manually...")

        # we don't really want an ADRP in the middle of code, if possible
        # so we erase it 
        inst.mnemonic = "// " + inst.mnemonic

        for inst2, resolved_address, p_orig_reg in resolved_addresses:

            if inst2.mnemonic not in ["add", "ldr"] and not inst2.mnemonic.startswith("str"):
                debug(f"Warning: skipping {inst2} as not supported in global address emulation")
                continue

            is_an_import = False
            for rel in container.relocations[".dyn"]:
                if rel['st_value'] == resolved_address or rel['offset'] == resolved_address:
                    is_an_import = rel['name']
                    break
                elif resolved_address in container.plt:
                    is_an_import = container.plt[resolved_address]
                    break

            # reg_name2 = inst2.cs.reg_name(inst2.cs.operands[0].reg)
            # reg_name3 = inst2.cs.reg_name(inst2.cs.operands[1].reg)

            # if inst2.mnemonic.startswith("str"):
                # old_mnemonic = inst2.mnemonic
                # # if reg_name2 == orig_reg:  # str <orig_reg>, [...]
                # inst2.instrument_before(InstrumentedInstruction(
                    # "adrp %s, .LC%x" % (reg_name2, resolved_address)))
                # inst2.instrument_before(InstrumentedInstruction(
                    # "add %s, %s, :lo12:.LC%x" % (reg_name2, reg_name2, resolved_address)))
                # # else:                      # str ..., [<orig_reg> + ...]
                    # # inst2.instrument_before(InstrumentedInstruction(
                        # # "adrp %s, .LC%x" % (reg_name2, resolved_address)))
                    # # inst2.instrument_before(InstrumentedInstruction(
                        # # "add %s, %s, :lo12:.LC%x" % (reg_name2, reg_name2, resolved_address)))
                    # # inst2.mnemonic =  "ldr"
                    # # inst2.op_str =  reg_name3 + f", =.LC%x" % (resolved_address)
                    # # inst2.instrument_after(InstrumentedInstruction(
                        # # f"{old_mnemonic} {reg_name2}, [{reg_name3}]"))
            # elif is_an_import:
                # inst2.op_str =  reg_name2 + f", =%s" % (is_an_import)
            # else:
                # if is_reg_32bits(reg_name2):
                    # reg_name2 = get_64bits_reg(reg_name2)
                # if inst2.mnemonic == "add":
                    # inst2.mnemonic = "// " + inst2.mnemonic



            if is_an_import:
                inst2.op_str =  reg_name2 + f", =%s" % (is_an_import)
            else:
                inst2.instrument_before(InstrumentedInstruction(
                    "adrp %s, .LC%x" % (p_orig_reg, resolved_address)))
                inst2.instrument_before(InstrumentedInstruction(
                    "add %s, %s, :lo12:.LC%x" % (p_orig_reg, p_orig_reg, resolved_address)))

                # this is a ugly hack, and slow, but this should get
                # triggered _very rarely_. 
                displace = resolved_address - p.orig_off
                if displace != 0:
                    inst2.instrument_before(InstrumentedInstruction(
                        "sub %s, %s, 0x%x" % (p_orig_reg, p_orig_reg, displace)))




            inst2.op_str += " // from adrp at 0x%x" % (inst.address)

            self.xrefs[resolved_address] += [inst2.address]






    def symbolize_mem_accesses(self, container, context):
        for _, function in container.functions.items():
            for edx, inst in enumerate(function.cache):
                if inst.address in self.symbolized:
                    continue

                if inst.mnemonic == "adrp":
                    self._adjust_global_access(container, function, edx, inst)

                if inst.mnemonic == "adr":
                    value = inst.cs.operands[1].imm
                    if value % 0x1000 == 0: # an adr to a page, probably same as adrp
                        self._adjust_global_access(container, function, edx, inst)
                    else:
                        inst.op_str = inst.op_str.replace("#0x%x" % value, ".LC%x" % value)


                mem_access, _ = inst.get_mem_access_op()
                if not mem_access:
                    continue



                # Now we have a memory access,
                # check if it is rip relative.
                base = mem_access.base
                # XXX: ARM
                if base == X86_REG_RIP:
                    debug(f"INSTRUCTION CHANGED FROM {inst}  ", end="")
                    value = mem_access.disp
                    ripbase = inst.address + inst.sz
                    target = ripbase + value

                    is_an_import = False

                    for relocation in container.relocations[".dyn"]:
                        if relocation['st_value'] == target:
                            is_an_import = relocation['name']
                            sfx = ""
                            break
                        elif target in container.plt:
                            is_an_import = container.plt[target]
                            sfx = "@PLT"
                            break
                        elif relocation['offset'] == target:
                            is_an_import = relocation['name']
                            sfx = "@GOTPCREL"
                            break

                    if is_an_import:
                        print(is_an_import)
                        inst.op_str = inst.op_str.replace(
                            hex(value), "%s%s" % (is_an_import, sfx))
                    else:
                        # Check if target is contained within a known region
                        in_region = self._is_target_in_region(
                            container, target)
                        if in_region:
                            inst.op_str = inst.op_str.replace(
                                hex(value), ".LC%x" % (target))
                        else:
                            target, adjust = self._adjust_target(
                                container, target)
                            inst.op_str = inst.op_str.replace(
                                hex(value), "%d+.LC%x" % (adjust, target))
                            print("[*] Adjusted: %x -- %d+.LC%x" %
                                  (inst.address, adjust, target))

                    debug(f"TO:   {inst}")

    def _handle_relocation(self, container, section, rel):
        reloc_type = rel['type']
        # critical(f"{rel['name']} at {hex(rel['offset'])}")
        # elif reloc_type == ENUM_RELOC_TYPE_x64["R_X86_64_RELATIVE"]:
        if reloc_type == ENUM_RELOC_TYPE_AARCH64["R_AARCH64_RELATIVE"]:
            value = rel['addend']
            label = ".LC%x" % value
            if int(value) in container.ignore_function_addrs:
                return
            section.replace(rel['offset'], 8, label)
        elif reloc_type == ENUM_RELOC_TYPE_AARCH64["R_AARCH64_GLOB_DAT"]:
            if section.name != '.got': return
            if rel['name'] in Rewriter.GCC_RELOCATIONS: return
            section.replace(rel['offset'], 8, rel['name'])
        elif reloc_type == ENUM_RELOC_TYPE_AARCH64["R_AARCH64_ABS64"]:
            if rel['name'] in Rewriter.GCC_RELOCATIONS: return
            section.replace(rel['offset'], 8, rel['name'])

        else:
            print(rel)
            print("[*] Unhandled relocation {}".format(
                describe_reloc_type(reloc_type, container.loader.elffile)))

    def fix_got_section(self, container):
        # gcc will add some stuff to the .got that is already there
        # we want to keep the same size of the .got so here we remove
        # the stuff gcc will add back (relocations, mostly)

        # delete first three entries of .got, it does not seem we need to keep them
        gotsec = container.datasections['.got']
        gotsec.delete(0, 8*3) 
        # we now remove the entries of the got relative to all imports
        for rel in container.relocations['.plt']:
            if rel['type'] == ENUM_RELOC_TYPE_AARCH64["R_AARCH64_JUMP_SLOT"]:
                gotsec.delete(rel['offset'] - gotsec.base, 8)
                Rewriter.total_deleted_from_got += 8
        symtab = container.loader.elffile.get_section_by_name(".symtab")
        # this symbol needs to be removed as gcc adds it back 
        # (stores the address of the .dynamic section)
        dyntable = symtab.get_symbol_by_name("_GLOBAL_OFFSET_TABLE_")
        if len(dyntable) == 1:
            gotsec.delete(dyntable[0]['st_value'] - gotsec.base, 8)

        Rewriter.total_deleted_from_got += 4*8



    def symbolize_data_sections(self, container, context=None):
        # Section specific relocation
        for secname, section in container.datasections.items():
            for rel in section.relocations:
                self._handle_relocation(container, section, rel)

        self.fix_got_section(container)

        # .dyn relocations
        dyn = container.relocations[".dyn"]
        for rel in dyn:
            section = container.section_of_address(rel['offset'])
            if section:
                self._handle_relocation(container, section, rel)
            else:
                print("[x] Couldn't find valid section {:x}".format(
                    rel['offset']))
