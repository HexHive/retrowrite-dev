from capstone import *
from keystone import *
from arm.librw.util.logging import *
import subprocess
import sys
import os
import random

def cmd(text):
    try:
        return subprocess.check_output(text, shell=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        return e.output

c_start = """
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char** argv) {
    int r = atoi(argv[1]);
    printf("start\\n");
    char* array = malloc(1024);
    switch(r) {
"""
c_switch = """
        {switch_inside}
        default:
            printf("default\\n");
"""
c_end = """
    }
    printf("end\\n");
    free(array);
}
"""

c_case = """
        case {case_no}:
            {instrs}
            break;
"""

possible_instrs = [
        "array[17] = 0x44;",
        "array[1023] = 0x41;",
        "free(array); array = malloc(1024);",
        "printf(\"hi\");",
        "printf(\"ok\");",
]


def run_test():
    i = 0
    source_file = f"/tmp/switch_test_{i}.c"
    out_file = f"/tmp/switch_test_{i}.out"

    switch_inside = ""
    for case_no in range(random.randint(10, 500)):
        instructions = ""
        for _ in range(random.randint(1,100)):
            instructions += "\t\t\t" + random.choice(possible_instrs) + "\n"
        switch_inside += f"\t\tcase {case_no}:\n{instructions}"

    with open(source_file, "w") as f:
        f.write(c_start)
        f.write(c_switch.format(switch_inside=switch_inside))
        f.write(c_end)

    cmd(f"gcc -g {source_file} -o {out_file} -O2") #XXX: change compilers and -O2
    cmd(f"python3 -m arm.rwtools.asan.asantool {out_file} {out_file}_rw.s")
    cmd(f"gcc -g -fsanitize=address {out_file}_rw.s -o {out_file}_rw -O2") #XXX: change compilers and -O2

    for testno in range(200):
        args = random.randint(0, 1000)
        output_rw = cmd(f"{out_file}_rw {args}")
        output    = cmd(f"{out_file} {args}")
        if output != output_rw:
            critical(f"Output of {out_file}_rw: {output_rw}")
            critical(f"Output of {out_file}: {output}")
            assert False
        else:
            print(f"{GREEN}PASSED{CLEAR}", testno)


if __name__ == "__main__":
    run_test()
