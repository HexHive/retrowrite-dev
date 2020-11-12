"""
Implements analysis to look for free registers
"""

import copy
from collections import defaultdict

from archinfo import ArchAArch64, Register
from arm.librw.util.logging import *


class RegisterAnalysis(object):
    KEY = 'free_registers'

    def __init__(self):
        self.regmap = self._init_reg_pool()
        self.reg_pool = frozenset(self.regmap.keys())

        self.free_regs = defaultdict(set)
        self.used_regs = defaultdict(lambda: copy.copy(self.reg_pool))
        self.subregs = dict()

        self._init_subregisters()
        self.closure_list = self._init_closure_list()

        # XXX: ARM
        # Caller saved register list, These are registers that cannot be
        # clobbered and therefore are 'used'.
        # self.used_regs['ret'] = set([
            # "rbx", "rsp", "rbp", "r12", "r13", "r14", "r15",
            # "rax", "rdx", "r10", "r11", "r8", "r9", "rcx", "rdi", "rsi"])
        # self.used_regs['call'] = set([
            # "rbx", "rsp", "rbp", "r12", "r13", "r14", "r15",
            # "rdi", "rsi", "rdx", "rcx", "r8", "r9", "rax"])

    def _init_reg_pool(self):
        # Possible extension: add xmm registers into the pool
        amd64 = ArchAArch64()
        regmap = dict()
        for reg in amd64.register_list:
            if reg.general_purpose:
                regmap[reg.name] = reg

        # Remove xsp, x30 (link register)
        del regmap["xsp"]
        del regmap["x30"]

        # Clobbered registers (reserved by caller, cannot overwrite)
        for i in range(19, 28):
            del regmap["x" + str(i)]

        # Add a fake register for rflags
        # XXX: why?
        # rflags = Register("rflags", 64)
        # regmap["rflags"] = rflags

        return regmap

    def _init_closure_list(self):
        closure_list = defaultdict(lambda: [""])

        # copied from x86, in reality not really needed
        for wrn, wr in self.regmap.items():
            subreg_list = list(enumerate(wr.subregisters))
            for idx, subreg in subreg_list:
                closure_list[wrn][idx] = subreg[0]

            reg32 = closure_list[wrn][0]
            if reg32:
                closure_list[reg32] = []

        # Cleanup
        for k, items in closure_list.items():
            closure_list[k] = frozenset([x for x in items if x])

        return closure_list

    def _init_subregisters(self):
        for rn, reg in self.regmap.items():
            self.subregs[rn] = rn

            # XXX: Not needed by ARM? (archinfo correctly gives subregisters
            # x0, x1, ..., x30
            # if reg.name in ["x" + str(i) for i in range(0, 31)]: 
                # reg.subregisters = [
                    # (reg.name + "d", 0, 4),
                    # (reg.name + "w", 0, 2),
                    # (reg.name + "b", 0, 1)]

            # if reg.name == "rbp":
                # reg.subregisters = [
                    # ("ebp", 0, 4),
                    # ("bp", 0, 2),
                    # ("bpl", 0, 1)]

            for subr in reg.subregisters:
                self.subregs[subr[0]] = rn

    def compute_reg_set_closure(self, regl):
        regset = set(regl)
        for item in regl:
            clist = self.closure_list[item]
            if clist:
                regset.update(clist)
        return regset

    def full_register_of(self, regname):
        return self.subregs.get(regname, None)

    @staticmethod
    def analyze(container):
        for addr, function in container.functions.items():
            ra = RegisterAnalysis()
            debug("Analyzing function " + function.name)
            ra.analyze_function(function)
            function.analysis[RegisterAnalysis.KEY] = ra.free_regs

    def analyze_function(self, function):
        # we will do a reverse-topological order visit to understand
        # which registers are free in a single pass
        queue = []
        for idx, nexts in function.nexts.items():
            no_of_nexts = sum(isinstance(x, int) for x in nexts) # how many actual nexts do we have?
            if no_of_nexts == 0:
                queue += [idx]

        # breadth first search on the cfg
        visited = [False]*function.sz
        while len(queue):
            idx = queue.pop(0)
            visited[idx] = True
            self.analyze_instruction(function, idx)
            prev_instrs = list(filter(lambda x: isinstance(x, int), function.prevs[idx]))
            for idxs in prev_instrs:
                if not visited[idxs]:
                    queue += [idxs]

        self.finalize()


        # old algorithm, ignore

        # change = True
        # iter = 0
        # while change and iter < 8192:
            # change = False
            # for idx in range(len(function.cache)-1, -1, -1): 
                # if self.analyze_instruction(function, idx):
                    # change = True
            # iter += 1


    def analyze_instruction(self, function, instruction_idx):
        current_instruction = function.cache[instruction_idx]
        nexts = function.nexts[instruction_idx]

        reguses = self.reg_pool.intersection(
            ["x"+x if x[0] == "w" else x for x in current_instruction.reg_reads()]
        )
        reguses = self.compute_reg_set_closure(reguses)


        regwrites = ["x"+x if x[0] == "w" else x for x in current_instruction.reg_writes()]
        regwrites = self.compute_reg_set_closure(regwrites)
        regwrites = set(regwrites).difference(reguses)

        if current_instruction.mnemonic.startswith("cmp") \
        or current_instruction.mnemonic.startswith("tst"):
            reguses = reguses.union(regwrites)

        for nexti in nexts:
            if nexti not in self.used_regs: continue
            reguses = reguses.union(
                self.used_regs[nexti].difference(regwrites))

        reguses = self.compute_reg_set_closure(reguses)
        self.used_regs[instruction_idx] = reguses
        return

        # if reguses != self.used_regs[instruction_idx]:
            # self.used_regs[instruction_idx] = reguses
            # return True

        # return False

    # def analyze_function(self, function):
        # change = False
        # change = True
        # iter = 0
        # while change and iter < 8192:
            # change = False
            # for idx, _ in enumerate(function.cache):
                # change = change or self.analyze_instruction(function, idx)
            # iter += 1
        # self.finalize()

    # def analyze_instruction(self, function, instruction_idx):
        # current_instruction = function.cache[instruction_idx]
        # nexts = function.next_of(instruction_idx)

        # reguses = self.reg_pool.intersection(
            # [self.full_register_of(x) for x in current_instruction.reg_reads()]
        # )

        # regwrites = self.reg_pool.intersection(current_instruction.reg_writes()).difference(reguses)

        # if current_instruction.mnemonic.startswith("cmp") \
        # or current_instruction.mnemonic.startswith("tst"):
            # reguses = reguses.union(regwrites)

        # for nexti in nexts:
            # if nexti not in self.used_regs: continue
            # reguses = reguses.union(
                # self.used_regs[nexti].difference(regwrites))

        # reguses = self.compute_reg_set_closure(reguses)

        # if reguses != self.used_regs[instruction_idx]:
            # self.used_regs[instruction_idx] = reguses
            # return True

        # return False


    def debug(self, function):
        print("==== DEBUG")
        for instruction_idx, inst in enumerate(function.cache):
            print(inst, "Used:", sorted(self.used_regs[instruction_idx]))

    def finalize(self):
        for idx, ent in self.used_regs.items():
            #XXX
            #XXX
            #XXX
            #XXX
            self.free_regs[idx] = []
            # self.free_regs[idx] = self.reg_pool.difference(ent)
