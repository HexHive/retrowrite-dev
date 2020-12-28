from archinfo import ArchAArch64
from collections import defaultdict
from arm.librw.container import (DataCell, InstrumentedInstruction, DataSection,
                             Function)
from arm.librw.util.logging import *
from arm.librw.container import INSTR_SIZE
from arm.librw.util.arm_util import get_reg_size_arm, get_access_size_arm, is_reg_32bits, get_64bits_reg, non_clobbered_registers


class Instrument():

    def __init__(self, rewriter):
        self.rewriter = rewriter

        # Get the register map
        aarch64 = ArchAArch64()
        self.regmap = defaultdict(lambda: defaultdict(dict))
        for reg in aarch64.register_list:
            if reg.general_purpose:
                self.regmap[reg.name] = reg.subregisters[0][0]



    def get_mem_instrumentation(self, instruction, idx, free):
        enter_lbl = "COUNTER_%x" % (instruction.address)

        instrumentation = """
        stp x0, x8, [sp, -16]!
        movz x8, 0x103
        svc 0
        ldp x0, x8, [sp], 16
        """

        comment = "{}: {}".format(str(instruction), str(free))

        return InstrumentedInstruction(instrumentation, enter_lbl, comment)



    def do_instrument(self):
        for _, fn in self.rewriter.container.functions.items():
            for idx, instruction in enumerate(fn.cache):

                if any("adrp" in str(x) for x in instruction.before):
                    free_registers = fn.analysis['free_registers'][idx]
                    iinstr = self.get_mem_instrumentation(instruction, idx, free_registers)
                    instruction.instrument_before(iinstr)
