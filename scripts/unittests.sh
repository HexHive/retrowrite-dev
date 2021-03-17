#!/bin/sh

pushd tests/unit
nosetests -v --all-modules
popd
