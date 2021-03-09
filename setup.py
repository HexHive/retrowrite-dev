import os
from setuptools import setup

def get_packages(rel_dir):
    packages = [rel_dir]
    for x in os.walk(rel_dir):
        # break into parts
        base = list(os.path.split(x[0]))
        if base[0] == "":
            del base[0]

        for mod_name in x[1]:
            packages.append(".".join(base + [mod_name]))

    return packages

setup(
    name='retrowrite',
    version='0.9',
    description='Binary Rewriting Framework',
    author='...',
    author_email='',
    url='https://hexhive.epfl.ch',
    # as is, the python package will be imported via `import librw`.
    # if we want it to be called retrowrite, it needs to be in such 
    # a folder.
    packages=get_packages('librw'),
    entry_points = {
        'console_scripts': [
        ]
        },
    requires = [
        'capstone',
        'pyelftools',
        'nose'],
    test_suite='nose.collector',
    tests_require=['nose'],
)

