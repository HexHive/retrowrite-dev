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

        # Save register x8 (syscall number) and x0 (syscall result)
        # instrumentation = """
        # stp x0, x8, [sp, -16]!
        # movz x8, 0x103
        # svc 0
        # ldp x0, x8, [sp], 16
        # """

        instrumentation = """
        stp x7, x8, [sp, -16]!
        adrp x8, .counted 
        add x8, x8, :lo12:.counted
        ldr x7, [x8]
        add x7, x7, 1
        str x7, [x8]
        ldp x7, x8, [sp], 16
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

        ds = DataSection(".counter", 0x100000, 0, None, flags="aw")
        content = """
        .file: .string \"/tmp/countfile\"
        .perms: .string \"w\"
        .format: .string \"%lld\\n\"
        .align 3
        .counted: .quad 0x0
        """
        ds.cache.append(DataCell.instrumented(content, 0))
        self.rewriter.container.add_section(ds)



        ds = DataSection(".fini", 0x200000, 0, None)
        ds.align = 0
        instrumentation = """
        adrp x1, .perms
        add x1, x1, :lo12:.perms
        adrp x0, .file
        add x0, x0, :lo12:.file
        bl fopen

        adrp x2, .counted
        ldr x2, [x2, :lo12:.counted]
        adrp x1, .format
        add x1, x1, :lo12:.format
        bl fprintf
        """
        ds.cache.append( DataCell.instrumented(instrumentation, 0))
        self.rewriter.container.add_section(ds)

