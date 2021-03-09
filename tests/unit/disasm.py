
import unittest
from librw import disasm


"""
This is a simple example unit test, to demonstrate the use of the unit test 
framework.
Each test is given a method and self is a testcase, which has assert methods 
that can be used for various checks.

Semantically-speaking, these tests should be self-contained. If you have a 
small function or complicated piece of functionality that can be separated out, 
this is a good way to check it works correctly.
"""
class TestDisassembler(unittest.TestCase):

    """ Dumb example """
    def testDisassemble(self):

        # nop nop nop
        some_asm = b"\x90\x90\x90"
        disassembly = disasm.disasm_bytes(some_asm, 0)

        for instruction in disassembly:
            self.assertEqual(instruction.insn_name(), 'nop')

    """ This test shows what happens when the code test fails """
    def testThatFails(self):

        # mov rax, rdi
        some_asm = b"\x48\x89\xF8"
        disassembly = disasm.disasm_bytes(some_asm, 0)

        for instruction in disassembly:
            # clearly not a nop.
            self.assertEqual(instruction.insn_name(), 'nop')

