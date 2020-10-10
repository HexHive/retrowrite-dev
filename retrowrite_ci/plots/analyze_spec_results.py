import argparse
import os
from collections import defaultdict

import pandas
import matplotlib.pyplot as plt


def results_to_csv(inputs, out):
    results = {}
    all_benchs = set()
    keys = list()

    for fname in inputs:
        with open(fname) as fd:
            data = fd.read()

        data = data.split("\n")
        start = False
        key = os.path.basename(fname)
        key = key.split(".")[0].replace("-", " ").title()
        keys.append(key)

        results[key] = defaultdict(lambda: "NaN")

        for line in data:
            if not line:
                continue
            if start:
                if line[0] == " ": 
                    start = False
                    continue
                line = line.split()
                if len(line) < 2: break
                if line[-1] != "NR":
                    benchmark = line[0].strip()
                    if any([x in benchmark for x in ["x264", "gcc", "nab"]]):
                        continue
                    all_benchs.add(benchmark)
                    results[key][benchmark] = float(line[2].strip())
            elif line.startswith("======="):
                start = True

    csvl = list()
    csvl.append("benchmark,{}".format(','.join(keys)))
    for bench in sorted(all_benchs):
        csvl.extend(
            ["%s,%s" % (bench, ','.join([str(results[k][bench]) for k in keys]))])

    csvf = out + ".csv"
    with open(csvf, "w") as fd:
        fd.write("\n".join(csvl))


def ascii_pp(csvf):
    csvf = csvf + ".csv"
    df = pandas.read_csv(csvf)
    print(df)


def to_latex(outf):
    csvf = outf + ".csv"
    df = pandas.read_csv(csvf)
    latexf = outf + ".tex"
    with open(latexf, "w") as fd:
        fd.write(df.to_latex())


def plot(outf):
    csvf = outf + ".csv"
    df = pandas.read_csv(csvf)
    df = df.set_index("benchmark")
    print(df)

    ax = df.plot.bar(rot=30, figsize=(12, 7))
    ax.set_ylabel("Runtime (seconds)")
    ax.set_title("SPEC CPU 2017 benchmark results\nCompile flags used: -fno-unsafe-math-optimizations -fno-tree-loop-vectorize -O3")

    plot = outf + ".pdf"

    fig = ax.get_figure()
    fig.savefig(plot)


def plot_diff(outf):
    csvf = outf + ".csv"
    df = pandas.read_csv(csvf)
    df = df.set_index("benchmark")
    heads = list(df.columns.values)
    sidx = heads.index("Source Asan")
    bidx = heads.index("Binary Asan")
    vidx = heads.index("Valgrind")

    val = df.values
    bin_vs_src = 100.0 * ((val[:, bidx] - val[:, sidx]) / val[:, sidx])
    bin_vs_vgrind = 100.0 * ((val[:, bidx] - val[:, vidx]) / val[:, bidx])
    print(val)
    print(heads)
    print(bin_vs_src)
    print(bin_vs_vgrind)


if __name__ == "__main__":
    argp = argparse.ArgumentParser()

    argp.add_argument(
        "out", type=str, help="Prefix name for outfile")

    argp.add_argument(
        "--inputs", nargs="+", help="SPEC result files to analyze")

    argp.add_argument(
        "--latex", action='store_true', help="Generate latex tables")

    argp.add_argument(
        "--plot", action='store_true', help="Generate plots")

    argp.add_argument(
        "--pp", action='store_true', help="Pretty print table")

    args = argp.parse_args()

    results_to_csv(args.inputs, args.out)
    if args.latex:
        to_latex(args.out)
    if args.pp:
        ascii_pp(args.out)
    if args.plot:
        plot(args.out)
        # plot_diff(args.out)
