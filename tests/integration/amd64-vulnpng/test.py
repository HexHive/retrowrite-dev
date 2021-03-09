
import unittest
import os
import subprocess
import shutil
from nose.tools import *

from librw.loader import Loader
from librw.rw import Rewriter
from librw.analysis.register import RegisterAnalysis
from librw.analysis.stackframe import StackFrameAnalysis

CC="clang"

def retrowrite(input_file, output_file):
    loader = Loader(input_file)

    flist = loader.flist_from_symtab()
    loader.load_functions(flist)

    slist = loader.slist_from_symtab()
    loader.load_data_sections(slist, lambda x: x in Rewriter.DATASECTIONS)

    reloc_list = loader.reloc_list_from_symtab()
    loader.load_relocations(reloc_list)

    global_list = loader.global_data_list_from_symtab()
    loader.load_globals_from_glist(global_list)

    loader.container.attach_loader(loader)

    rw = Rewriter(loader.container, output_file)
    rw.symbolize()

    return rw


def setup_func():
    print(os.getcwd())
    source_dir = os.path.join(os.getcwd(), "src")
    work_dir = os.path.join(os.getcwd(), "work")
    try:
        os.mkdir(work_dir)
    except FileExistsError:
        pass # ignore if the directory still exists.

    subprocess.call(["make", "clean"], cwd=source_dir)
    subprocess.call(["make"], cwd=source_dir)
    shutil.copy(os.path.join(source_dir, "storepng"), os.path.join(work_dir, "storepng"))
    shutil.copy(os.path.join(source_dir, "libz.a"), os.path.join(work_dir, "libz.a"))

def teardown_func():
    "tear down test fixtures"
    source_dir = os.path.join(os.getcwd(), "src")
    work_dir = os.path.join(os.getcwd(), "work")
    subprocess.call(["make", "clean"], cwd=source_dir)
    shutil.rmtree(work_dir, ignore_errors=True)

@with_setup(setup_func, teardown_func)
def test_rewrite():
    work_dir = os.path.join(os.getcwd(), "work")

    def work_file(filename):
        return os.path.join(work_dir, filename)
    
    
    rw = retrowrite(work_file("storepng"), work_file("storepng.s"))
    rw.dump()

    subprocess.call([CC, "-o", "storepng_rebuild", "storepng.s", "libz.a"], cwd=work_dir)
    returncode = subprocess.call(["./storepng_rebuild"], cwd=work_dir)
    assert(returncode == 1)

