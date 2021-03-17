
# Creating a new integration test

## Intro

There are a number of python packages for test frameworks, such as pytest and 
nosetests. We have chosen nosetests somewhat arbitrarily.

It works by examining the current module and recursively walking the package 
free for things that look like test modules, e.g. because they are named 
`test.py` or contain instances of `unittest.TestCase`, etc. Then it runs those 
functions or classes and collects the results.

## New test

As a result, your new test must be a python module. Therefore, please follow 
python module naming conventions. In particular, your submodule must contain 
an `__init__.py`.

An example has been created that contains a `test.py` file, which will be 
picked up by nosetests.

## Attaching file/sample data

I do not think it is necessary to perform compilation of the source material. 
However it is absolutely necessary to recompile and test if execution worked 
successfully for that platform.

As a consequence most tests likely require: a source binary, some intermediate 
disassembly output from retrowrite and a recompiled binary. 

To find these files we include the helper function

```python
def pkgdir(relpath=None):

    filedir = os.path.dirname(os.path.abspath(__file__))
    if relpath == None:
        return filedir

    return os.path.join(filedir, relpath)
```

and suggest you duplicate it to your code. This allows you to look up relative 
to the current file, so the `src` and `work` directories in the example can 
be found irrespective of where nosetests is executed.

## Tests themselves.

Tests themselves should be marked with the following decorator:

```python
@with_setup(setup_func, teardown_func)
def test_mytestname():
```

`setup_func` and `teardown_func` can be used for initial setup and cleanup 
respectively, as needed, and may be shared between multiple different tests in 
the same file if required (e.g. if you want to test slightly different 
variants of retrowrite passes on the same file).

All that remains is to write the logic of these files.


## What is todo?

Currently, nosetests will execute everything it finds with no knowledge of the 
architecture it runs on.

We plan to write a custom runner that will identify what it can and can't run, 
possibly by means of some annotation to the package or to individual functions.
