#!/usr/bin/env python3
import os
import sys
from subprocess import *
import hashlib

if "BENCHDIR" not in os.environ:
    print("BENCHDIR env variable not found. Quitting.")
    exit(1)

PATH_SPECPU = os.environ["BENCHDIR"]
PATH_TESTS = f"{PATH_SPECPU}/benchspec/CPU"

tests = {
"perlbench_r": "500.perlbench_r",
"cpugcc_r"   : "502.gcc_r"      ,
"mcf_r"      : "505.mcf_r"      ,
"lbm_r"      : "519.lbm_r"      ,
"x264_r"     : "525.x264_r"     ,
"imagick_r"  : "538.imagick_r"  ,
"nab_r"      : "544.nab_r"      ,
"xz_r"       : "557.xz_r"       ,
"perlbench_s": "600.perlbench_s",
"gcc_s"      : "602.gcc_s"      ,
"mcf_s"      : "605.mcf_s"      ,
"lbm_s"      : "619.lbm_s"      ,
"x264_s"     : "625.x264_s"     ,
"xz_s"       : "657.xz_s"
}


def quit(msg):
    print(msg)
    exit(1)

def cmd(text):
    try:
        return check_output(text, shell=True, stderr=STDOUT)
    except CalledProcessError as e:
        print(e.output)
        return e.output


def run(command):
    process = Popen(command, stdout=PIPE, shell=True)
    while True:
        line = process.stdout.readline().rstrip()
        if not line:
            break
        yield line


if len(sys.argv) < 2:
    quit("./run_test.py <binaries>")

final_str = ""

for binary_full in sys.argv[1:]:
    binary = os.path.basename(binary_full)
    if not os.path.exists(os.path.expanduser(binary_full)):
        quit(f"{binary} not found")

    if len(binary.split("_")) < 2: 
        quit(f"{binary} wrong format")

    binary_original_name = "_".join(binary.split("_")[:2])

    if binary_original_name not in tests.keys():
        quit(f"{binary_original_name} not found in tests list")

    test_name = tests[binary_original_name]


    md5 = hashlib.md5(open(binary_full, "rb").read()).hexdigest()
    print (f"=== Preparing test {test_name}")
    print (f"=== md5sum {binary} = {md5}")

    cmd(f"rm -rf {PATH_TESTS}/{test_name}/run")
    cmd(f"cp {binary_full} {PATH_TESTS}/{test_name}/exe/{binary_original_name}_base.mytest-64")

    final_str += " " + test_name



# TODO: modify this to write into a file 'benchmark_cmd' and use a Makefile!
print("="*50)
print("Finished. You can now run:")
print(f"cd {PATH_SPECPU} && source shrc && runcpu --nobuild --iterations 3 --config final.cfg {final_str}")
# print(f"cd {PATH_SPECPU} && source shrc && runcpu --nobuild --iterations 1 --size test --loose --fake --config final.cfg {final_str}")

