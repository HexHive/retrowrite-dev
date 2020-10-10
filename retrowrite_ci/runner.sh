#!/bin/bash


set -ex
set -o pipefail

COMMIT_MSG=$(git log -1 --pretty=%B | tr '/. ' '___')
COMMIT_SHA=$(git rev-parse --short HEAD)
WORKDIR=${COMMIT_SHA}_${COMMIT_MSG}
export BENCHDIR=$(find ~ -name "cpu2017_runner" -type d -maxdepth 3 | head -n 1)  # needed by run_test.py # this is peak research code


[[ ${#BENCHDIR} -eq 0 ]] && echo "cpu2017_runner folder not found. Please store it in your home folder!" && exit 1
sudo apt install libjpeg-dev zlib1g-dev poppler-utils -y 
PIP_IGNORE_INSTALLED=0 pip3 install cython matplotlib pandas capstone pyelftools archinfo intervaltree 

mkdir -p $WORKDIR
cd $WORKDIR

exec 1>log

rm  $BENCHDIR/result/*  # erase all previous logs

cd ..
mv ../arm ../bin ../share ../third-party ./
bash rewrite_all.sh asan      # produce rewritten files in folder bins_rw
BINARIES=$(find bins_rw -executable -type f)
python3 run_test.py $BINARIES | tee runcpu_cmd # place those binaries in the spec cpu2017 folder
tail -n 1 runcpu_cmd | source /dev/stdin

mv bins_rw $WORKDIR/
cp -r plots $WORKDIR/
cd $WORKDIR

cp $BENCHDIR/result/* plots/
cat plots/CPU2017.001.*.txt > plots/bASAN.txt || true

cd plots
python3 analyze_spec_results.py --inputs baseline.088_099.txt symbolized.090_096.txt source_asan.040.txt bASAN.txt --plot out --pp

pdftoppm -jpeg -r 300 out.pdf plot_image



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
																		   
cd ../..
mkdir -p ~/result
mv $WORKDIR ~/result/

echo "Finished!"
