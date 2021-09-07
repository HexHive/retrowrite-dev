from archinfo import ArchAArch64
from collections import defaultdict
from arm.librw.container import (DataCell, InstrumentedInstruction, Function, DataSection)
from arm.librw.util.logging import *

class Instrument():

    def __init__(self, rewriter):
        self.rewriter = rewriter

    def get_blr_instrumentation(self, instruction, idx, free, is_direct_call):
        enter_lbl = "CFI_check_0x%x" % (instruction.address)
        comment = ""
        jump_reg = instruction.cs.op_str

        instrumentation = f"""
        // CFI check 
        stp x7, x8, [sp, -16]!
        ldr x7, [{jump_reg}]
        adrp x8, .value 
        add x8, x8, :lo12:.value
        ldr x8, [x8]
        cmp x7, x8
        b.eq 8                        // jump over crash
        .word 0x0                     // crash
        ldp x7, x8, [sp], 16          // restore regs and continue
        // END CFI CHECK
        add {jump_reg}, {jump_reg}, 8 // skip first 8 bytes of known value
        """

        return InstrumentedInstruction(instrumentation, enter_lbl, comment)



    def do_instrument(self):
        for _, fn in self.rewriter.container.functions.items():
            if fn.name in ["_start", "main", "close_stdout"] or len(fn.cache) == 0:
                continue
            first_instr = fn.cache[0]
            first_instr.before.insert(0, InstrumentedInstruction(".quad 0xbaddcafe"))

        for _, fn in self.rewriter.container.functions.items():

            for idx, instruction in enumerate(fn.cache):
                if "b" == instruction.mnemonic and not \
                    fn.start < instruction.cs.operands[0].imm < fn.start + fn.sz:
# branch outside function, skip first 8 bytes of known value
                    instruction.op_str += "+8"
                if "bl" == instruction.mnemonic: # direct call, must skip first 8 bytes of known value
                    if "LC" in instruction.op_str: # exclude imports
                        instruction.op_str += "+8"
                if "blr" == instruction.mnemonic: # indirect call, must skip AND check known value
                    free_registers = fn.analysis['free_registers'][idx]
                    iinstr = self.get_blr_instrumentation(instruction, idx, free_registers, is_direct_call=False)
                    instruction.instrument_before(iinstr)

        ds = DataSection(".counter", 0x100000, 0, None, flags="aw")
        content = """
        .value: .quad 0xbaddcafe
        """
        ds.cache.append(DataCell.instrumented(content, 0))
        self.rewriter.container.add_section(ds)

