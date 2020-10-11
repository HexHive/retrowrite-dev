#!/bin/bash

# This script needs to be run in the "retrowrite" source folder

set -ue

[[ -d ~/bins ]] || { echo "~/bins folder not found, exiting..." && exit 1 ; }

mkdir -p bins_rw

for binary_full in ~/bins/*; do
	binary=$(basename $binary_full)
	[[ $binary =~ "ldecod" ]] && continue
	[[ $binary =~ "gcc" ]] && continue
	#[[ $binary =~ "mcf" ]] || continue


	if [[ $1 == "asan" ]]; then
		echo "rewriting ${binary}.s ..."
		python3 -m arm.rwtools.asan.asantool $binary_full bins_rw/prova_${binary}.s

		echo "assembling ${binary}.s ..."
		gcc bins_rw/prova_${binary}.s -lm -fsanitize=address -o bins_rw/${binary}_rw && echo Done

	else
		echo "rewriting ${binary}.s ..."
		python3 -m arm.librw.rw $binary_full bins_rw/prova_${binary}.s

		echo "assembling ${binary}.s ..."
		gcc bins_rw/prova_${binary}.s -lm -o bins_rw/${binary}_rw && echo Done

	fi
done;
