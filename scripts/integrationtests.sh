#!/bin/sh

pushd tests/integration
nosetests -v
popd
