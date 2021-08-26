from archinfo import ArchAArch64
from collections import defaultdict
from arm.librw.container import (DataCell, InstrumentedInstruction, Function, DataSection)
from arm.librw.util.logging import *
from arm.librw.container import INSTR_SIZE
from arm.librw.util.arm_util import get_reg_size_arm, get_access_size_arm, is_reg_32bits, get_64bits_reg, non_clobbered_registers



class Instrument():

    def __init__(self, rewriter):
        self.rewriter = rewriter

    def get_bl_instrumentation(self, instruction, idx, free, is_direct_call):
        # enter_lbl = "COUNTER_%x" % (instruction.address)
        enter_lbl = ""

        target_address = ".LC"+instruction.cs.op_str[3:]
        if not is_direct_call:
            target_address = "["+instruction.cs.op_str+"]"

        instrumentation = f"""
        // CFI check 
        stp x7, x8, [sp, -16]!
        ldr x7, {target_address}
        adrp x8, .value 
        add x8, x8, :lo12:.value
        ldr x8, [x8]
        cmp x7, x8
        b.eq 8 // jump over crash
        .word 0x0 // crash
        ldp x7, x8, [sp], 16 // restore regs and continue
        // END CFI CHECK
        """

        if not is_direct_call: 
            instrumentation += f"add {instruction.cs.op_str}, {instruction.cs.op_str}, 8\n"

        comment = "{}: {}".format(str(instruction), str(free))

        return InstrumentedInstruction(instrumentation, enter_lbl, comment)



    def do_instrument(self):
        for _, fn in self.rewriter.container.functions.items():
            if fn.name in ["_start", "main", "close_stdout"] or len(fn.cache) == 0:
                continue
            first_instr = fn.cache[0]
            first_instr.before.insert(0, InstrumentedInstruction(".quad 0xbaddcafe"))

        for _, fn in self.rewriter.container.functions.items():

            for idx, instruction in enumerate(fn.cache):
                if "bl" == instruction.mnemonic:
                    if "LC" in instruction.op_str:
                        free_registers = fn.analysis['free_registers'][idx]
                        iinstr = self.get_bl_instrumentation(instruction, idx, free_registers, is_direct_call=True)
                        instruction.instrument_before(iinstr)
                        instruction.op_str += "+8"
                if "blr" == instruction.mnemonic:
                    free_registers = fn.analysis['free_registers'][idx]
                    iinstr = self.get_bl_instrumentation(instruction, idx, free_registers, is_direct_call=False)
                    instruction.instrument_before(iinstr)

        ds = DataSection(".counter", 0x100000, 0, None, flags="aw")
        content = """
        .value: .quad 0xbaddcafe
        """
        ds.cache.append(DataCell.instrumented(content, 0))
        self.rewriter.container.add_section(ds)



        # ds = DataSection(".fini", 0x200000, 0, None)
        # ds.align = 0
        # instrumentation = """
        # adrp x1, .perms
        # add x1, x1, :lo12:.perms
        # adrp x0, .file
        # add x0, x0, :lo12:.file
        # bl fopen

        # adrp x2, .counted
        # ldr x2, [x2, :lo12:.counted]
        # adrp x1, .format
        # add x1, x1, :lo12:.format
        # bl fprintf
        # """
        # ds.cache.append( DataCell.instrumented(instrumentation, 0))
        # self.rewriter.container.add_section(ds)

