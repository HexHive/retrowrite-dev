
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

"""
pkgdir finds code relative to this file, for example in the src folder 
in this directory. It will find absolute paths and join your provided 
relath as required. 
If relpath is not supplied, it simply returns the path to the current 
directory
"""
def pkgdir(relpath=None):

    filedir = os.path.dirname(os.path.abspath(__file__))
    if relpath == None:
        return filedir

    return os.path.join(filedir, relpath)

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

    source_dir = pkgdir("src") 
    work_dir = pkgdir("work")
    try:
        os.mkdir(work_dir)
    except FileExistsError:
        pass # ignore if the directory still exists.

    shutil.copy(os.path.join(source_dir, "hellostatic.arm32hf"), os.path.join(work_dir, "hellostatic.arm32hf"))
    shutil.copy(os.path.join(source_dir, "hellostatic.ppc64le"), os.path.join(work_dir, "hellostatic.ppc64le"))
    shutil.copy(os.path.join(source_dir, "hellostatic.rv64gc"), os.path.join(work_dir, "hellostatic.rv64gc"))

def teardown_func():
    "tear down test fixtures"
    source_dir = pkgdir("src")
    work_dir = pkgdir("work")
    shutil.rmtree(work_dir, ignore_errors=True)

@with_setup(setup_func, teardown_func)
def test_rewrite():
    work_dir = pkgdir("work")

    def work_file(filename):
        return os.path.join(work_dir, filename)
    
    
    rwa = retrowrite(work_file("hellostatic.arm32hf"), work_file("hellostatic_arm32hf.s"))
    rwb = retrowrite(work_file("hellostatic.rv64gc"), work_file("hellostatic_rv64gc.s"))
    rwc = retrowrite(work_file("hellostatic.ppc64le"), work_file("hellostatic_ppc64le.s"))
    rwa.dump()
    rwb.dump()
    rwc.dump()

    
