from archinfo import ArchAArch64
from collections import defaultdict
from arm.librw.container import (DataCell, InstrumentedInstruction, Section,
                             Function)
from arm.librw.util.logging import *
from arm.librw.container import INSTR_SIZE
from arm.librw.util.arm_util import get_reg_size_arm, get_access_size_arm, is_reg_32bits, get_64bits_reg, non_clobbered_registers
import random


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

        instrumentation = trampoline_fmt_arm.format(random=random.randint(0, MAP_SIZE))
        comment = "{}: {}".format(str(instruction), str(free))

        return InstrumentedInstruction(instrumentation, enter_lbl, comment)



    def do_instrument(self):
        for faddr, fn in self.rewriter.container.functions.items():
            for idx, instruction in enumerate(fn.cache):

                if instruction.mnemonic.startswith("b") and idx+1 < len(fn.cache):
                    next_instruction = fn.cache[idx+1] # we need to instrument the instruction after the branch
                    free_registers = fn.analysis['free_registers'][idx+1]
                    iinstr = self.get_mem_instrumentation(next_instruction, idx+1, free_registers)
                    next_instruction.instrument_before(iinstr)

        payload = main_payload_arm.format(FORKSRV_FD=FORKSRV_FD, FORKSRV_FD_1=FORKSRV_FD_1, AFL_STATUS_FLAGS=(FORKSRV_OPT_ENABLED | FS_OPT_MAPSIZE | get_map_size(MAP_SIZE)))
        afl_sec = Section(".afl_sec", 0x200000, 0, None)
        afl_sec.cache.append(DataCell.instrumented(payload, 0))
        # ds.cache.append(DataCell.instrumented(content, 0))
        self.rewriter.container.add_data_section(afl_sec)

def get_map_size(x):
    return (x <= 1 or ((x - 1) << 1))

FORKSRV_FD = 198
FORKSRV_FD_1 = 199
MAP_SIZE = (1 << 16)

# afl/include/types.h
FORKSRV_OPT_ENABLED = 0x80000001
FS_OPT_ENABLED = 0x80000001
FS_OPT_MAPSIZE = 0x40000000
FS_OPT_SNAPSHOT = 0x20000000
FS_OPT_AUTODICT = 0x10000000
FS_OPT_SHDMEM_FUZZ = 0x01000000
FS_OPT_OLD_AFLPP_WORKAROUND = 0x0f000000
# FS_OPT_MAX_MAPSIZE is 8388608 = 0x800000 = 2^23 = 1 << 22
#define FS_OPT_MAX_MAPSIZE ((0x00fffffeU >> 1) + 1)
#define FS_OPT_GET_MAPSIZE(x) (((x & 0x00fffffe) >> 1) + 1)
#define FS_OPT_SET_MAPSIZE(x) \
#  (x <= 1 || x > FS_OPT_MAX_MAPSIZE ? 0 : ((x - 1) << 1))

trampoline_fmt_arm = """
// afl trampoline
stp x0, lr, [sp, #-16]!
mov x0, {random}
bl __afl_maybe_log
ldp x0, lr, [sp], #16
"""

main_payload_arm = """
.section afl_payload, "awx", @progbits
// afl main payload
.type __afl_maybe_log, @function
.globl __afl_maybe_log
__afl_maybe_log:
stp x1, x2, [sp, #-16]!
stp x3, x9, [sp, #-16]!
stp x5, x6, [sp, #-16]!
stp x7, lr, [sp, #-16]!
mrs x7, nzcv
// mrs x7, CPSR

mov x9, x0
ldr x0, =__afl_setup_failure
ldr x0, [x0]
cmp x0, #0
bne __afl_return

ldr x0, =__afl_area_ptr
ldr x0, [x0]
cmp x0, #0
bne __afl_store

ldr x0, =.AFL_SHM_ENV
bl getenv

cmp x0, #0
beq __afl_setup_abort

bl atoi

mov x5, x0
mov x1, #0
mov x2, #0
bl shmat

cmp x0, #0
blt __afl_setup_abort

add x1, x0, #1
cmp x1, #1
bhi __afl_forkserver

.type __afl_setup_abort, @function
.globl __afl_setup_abort
__afl_setup_abort:
ldr x0, =__afl_setup_failure
ldr x1, [x0]
add x1, x1, #1
str x1, [x0]
b __afl_return

.type __afl_forkserver, @function
.globl __afl_forkserver
__afl_forkserver:
ldr x1, =__afl_area_ptr
str x0, [x1]
//ldr x5, =__afl_temp
ldr x5, =.AFL_STATUS_FLAGS
mov x0, #{FORKSRV_FD_1}
mov x1, x5
mov x2, #4
bl write

cmp x0, #4
bne __afl_fork_resume

.type __afl_fork_wait_loop, @function
.globl __afl_fork_wait_loop
__afl_fork_wait_loop:
mov x0, #{FORKSRV_FD}
mov x1, x5
mov x2, #4
bl read

cmp x0, #4
bne __afl_die

bl fork
cmp x0, #0
blt __afl_die  // useless
beq __afl_fork_resume  // I am the child
ldr x1, =__afl_fork_pid // I am the father
str x0, [x1]
mov x6, x0
mov x0, #{FORKSRV_FD_1}
mov x2, #4
bl write
cmp x0, #4
bne __afl_die
mov x0, x6
mov x1, x5
mov x2, #0
bl waitpid
cmp x0, #0
blt __afl_die
mov x0, #{FORKSRV_FD_1}
mov x1, x5
mov x2, #4
bl write
cmp x0, #4
beq __afl_fork_wait_loop
b __afl_die


.type __afl_fork_resume, @function
.globl __afl_fork_resume
__afl_fork_resume:
mov x0, #{FORKSRV_FD}
bl close
mov x0, #{FORKSRV_FD_1}
bl close


.type __afl_store, @function
.globl __afl_store
__afl_store:
ldr x0, =__afl_area_ptr
ldr x0, [x0]
ldr x1, =__afl_prev_loc
ldr x2, [x1]
eor x2, x2, x9
ldrb w3, [x0, x2]
add x3, x3, #1
strb w3, [x0, x2]
mov x0, x9, asr#1
str x0, [x1]


.type __afl_return, @function
.globl __afl_return
__afl_return:
// msr APSR_nzcvq, x7
msr nzcv, x7
ldp x7, lr, [sp], #16
ldp x5, x6, [sp], #16
ldp x3, x9, [sp], #16
ldp x1, x2, [sp], #16
ret


.type __afl_die, @function
.globl __afl_die
__afl_die:
mov x0, #0
bl exit
.AFL_VARS:
.comm __afl_area_ptr, 8, 8
.comm __afl_setup_failure, 4, 4
// #ifndef COVERAGE_ONLY
.comm __afl_prev_loc, 8, 8
// #endif /* !COVERAGE_ONLY */
.comm __afl_fork_pid, 4, 4
.comm __afl_temp, 4, 4
.AFL_STATUS_FLAGS:
.quad {AFL_STATUS_FLAGS}
.AFL_SHM_ENV:
.string \"__AFL_SHM_ID\"
// end
"""
