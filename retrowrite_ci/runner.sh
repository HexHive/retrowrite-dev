#!/bin/bash

# This file is run by the custom runner on every commit pushed
# It runs SPEC CPU 2017 benchmarks on the aarch64 architecture.
# It supports sending the derived plot on telegram, provinding
# a bot key in ~/.telegram_botkey and your chat ID with the bot
# in ~/.telegram_uid.

# This script is run by .github/workflows/actions.yml
#



set -eux
set -o pipefail

COMMIT_MSG=$(git log -1 --pretty=%B | tr '/. ' '___')
COMMIT_SHA=$(git rev-parse --short HEAD)
WORKDIR=${COMMIT_SHA}_${COMMIT_MSG}
export BENCHDIR=$(find ~ -name "cpu2017_runner" -type d -maxdepth 3 | head -n 1)  # needed by run_test.py # this is peak research code


[[ $(echo $COMMIT_MSG | grep -ic "Experiment") -eq 0 ]] && exit 0  # if "Experiment" is not in the commit message, quit
[[ ${#BENCHDIR} -eq 0 ]] && echo "cpu2017_runner folder not found. Please store it in your home folder!" && exit 1

# prerequisites
sudo apt install libjpeg-dev zlib1g-dev poppler-utils -y 
PIP_IGNORE_INSTALLED=0 pip3 install cython matplotlib pandas capstone pyelftools archinfo intervaltree 

# redirect stdout to log file to avoid cluttering CI console
mkdir -p $WORKDIR
exec 1>$WORKDIR/log

# fail-safe in case of error
mkdir -p ~/error
trap "tar cvf ~/error/$WORKDIR.tar * ; exit 1" ERR


# erase all previous benchmark logs (do not fail)
rm  $BENCHDIR/result/* || true  


# run retrowrite on binaries
cp -r retrowrite_ci/* ./
bash rewrite_all.sh asan      # put rewritten files in folder bins_rw

# prepare spec cpu benchmark
BINARIES=$(find bins_rw -executable -type f)
export ASAN_OPTIONS=detect_leaks=0  # do not print ASAN leak report
python3 run_test.py $BINARIES | tee runcpu_cmd # place those binaries in the spec cpu2017 folder

# run benchmark
tail -n 1 runcpu_cmd | source /dev/stdin

mv bins_rw $WORKDIR/
cp -r plots $WORKDIR/

# gather plot data
cd $WORKDIR
cp $BENCHDIR/result/* plots/
cat plots/CPU2017.001.*.txt > plots/bASAN.txt || true

# generate plot
cd plots
python3 analyze_spec_results.py --inputs baseline.088_099.txt symbolized.090_096.txt source_asan.040.txt bASAN.txt --plot out --pp

pdftoppm -jpeg -r 300 out.pdf plot_image



# send to telegram
if [[ -f ~/.telegram_uid && -f ~/.telegram_botkey ]]; then
	USERID=$(cat ~/.telegram_uid | tr -d "\n")
	KEY=$(cat ~/.telegram_botkey | tr -d "\n")
	TIMEOUT="9"
	URL="https://api.telegram.org/bot$KEY"
	DATE_EXEC="$(date "+%d %b %Y %H:%M")" #Collect date & time.
	TEXT="Heres your plot, you lazy asshole%0aCommit: ${COMMIT_SHA}%0aMsg: $COMMIT_MSG"
	curl -s --max-time $TIMEOUT -d "chat_id=$USERID&disable_web_page_preview=1&text=$TEXT" $URL/sendMessage > /dev/null
	curl -s --max-time $TIMEOUT -F document=@"plot_image-1.jpg" "$URL/sendDocument?chat_id=$USERID" > /dev/null
fi
																		   
# save folder with logs and data to home
cd ../..
mkdir -p ~/result
mv $WORKDIR ~/result/

echo "Finished!"
