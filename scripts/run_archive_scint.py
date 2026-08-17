#!/usr/bin/env python
"""
Run the scintillation estimators over a directory tree of archived SER cubes.

Writes one CSV row per cube: prism throughput, the scintillation index, the two time constants and
the frame accounting. Rows are flushed as they are produced, so an interrupted run keeps everything
computed up to that point and ``--resume`` picks up where it stopped.

Cubes are copied into a scratch directory before being read, and the copy is deleted afterwards.
``load_ser_file`` opens files ``"r+b"``, and an archive is not something to point a read-write open
at. Use ``--in-place`` to skip the copy if the archive is on slow or crowded storage; the run is
then read-write against the originals. Gzipped cubes are staged either way -- they have to be
expanded before they can be parsed, and that is the same code path as the copy.

Typical use:

    python scripts/run_archive_scint.py ~/SAAO/timdimm_data -o ~/archive_scint.csv

Multiple roots are allowed. Failures are recorded in the ``status`` column rather than stopping the
run: a cube too faint for the aperture finder is a normal thing to meet in an archive.
"""

import argparse
import csv
import gzip
import shutil
import socket
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from timdimm_tng.analyze_cube import analyze_dimm_cube            # noqa: E402
from timdimm_tng.scintillation import scintillation_stats         # noqa: E402

STAT_KEYS = (
    "throughput", "scint_index_raw", "frac_rejected", "tau_motion_ms", "tau_scint_ms",
    "tau_scint_censored", "acf1_ratio", "acf2_ratio", "cadence_hz", "n_frames", "n_kept",
    "mean_flux_bright", "mean_flux_faint",
)
COLUMNS = (
    "host", "night", "cube", "path", "status", "seeing", "seeing_valid", "image_shape", "elapsed_s",
) + STAT_KEYS


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("roots", nargs="+", type=Path,
                        help="directories to search recursively for .ser and .ser.gz cubes")
    parser.add_argument("-o", "--output", type=Path, default=Path("archive_scint.csv"),
                        help="CSV to write (default: ./archive_scint.csv)")
    parser.add_argument("--scratch", type=Path, default=None,
                        help="where to stage each cube (default: alongside the output file)")
    parser.add_argument("--resume", action="store_true",
                        help="append to an existing output, skipping cubes already in it")
    parser.add_argument("--in-place", action="store_true",
                        help="read uncompressed cubes directly instead of copying them first; "
                             ".ser.gz is still expanded into scratch")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after this many cubes, for a quick look")
    return parser.parse_args(argv)


def find_cubes(roots):
    cubes = []
    for root in roots:
        root = root.expanduser()
        if not root.is_dir():
            sys.exit(f"not a directory: {root}")
        cubes += list(root.rglob("*.ser")) + list(root.rglob("*.ser.gz"))
    return sorted(set(cubes), key=lambda p: (p.parent.name, p.name))


def already_done(output):
    if not output.exists():
        return set()
    with open(output, newline="") as fp:
        return {row["path"] for row in csv.DictReader(fp)}


def stage(path, work):
    """Copy or decompress the cube into scratch, leaving the original untouched."""
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as src, open(work, "wb") as dst:
            shutil.copyfileobj(src, dst, length=16 << 20)
    else:
        shutil.copyfile(path, work)
    return work


def main(argv=None):
    args = parse_args(argv)
    host = socket.gethostname().split(".")[0]

    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    scratch = (args.scratch or output.parent).expanduser()
    scratch.mkdir(parents=True, exist_ok=True)
    work = scratch / f"_work_{host}.ser"

    cubes = find_cubes(args.roots)
    done = already_done(output) if args.resume else set()
    if done:
        cubes = [c for c in cubes if str(c) not in done]
        print(f"resuming: {len(done)} cubes already recorded", flush=True)
    if args.limit:
        cubes = cubes[:args.limit]

    print(f"{host}: {len(cubes)} cubes to process -> {output}", flush=True)

    mode = "a" if (args.resume and output.exists()) else "w"
    with open(output, mode, newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=COLUMNS)
        if mode == "w":
            writer.writeheader()

        for n, path in enumerate(cubes, 1):
            row = {
                "host": host,
                "night": path.parent.name,
                "cube": path.name.replace(".ser.gz", "").replace(".ser", ""),
                "path": str(path),
            }
            # --in-place skips the *copy*, but a gzipped cube still has to be expanded somewhere:
            # load_ser_file parses raw SER bytes and cannot read a compressed stream, so an
            # unstaged .ser.gz would be recorded as a failure rather than analyzed
            staged = path.suffix == ".gz" or not args.in_place

            start = time.time()
            try:
                results = analyze_dimm_cube(stage(path, work) if staged else path)
                row["seeing"] = round(float(results["seeing"].value), 3)
                row["seeing_valid"] = int(results["seeing_valid"])
                row["image_shape"] = "x".join(str(n) for n in results["image_shape"])
                row["status"] = "ok"
                for key, value in scintillation_stats(results).items():
                    row[key] = round(value, 6) if isinstance(value, float) else value
            except Exception as exc:
                # recorded in the status column, not raised: a cube too faint for the aperture
                # finder is a normal thing to meet in an archive and must not stop the run
                row["status"] = f"{type(exc).__name__}: {exc}"[:120]
            finally:
                if staged:
                    work.unlink(missing_ok=True)

            row["elapsed_s"] = round(time.time() - start, 1)
            writer.writerow(row)
            fp.flush()
            print(f"[{n}/{len(cubes)}] {row['night']}/{row['cube']}: {row['status']} "
                  f"({row['elapsed_s']}s)", flush=True)

    print(f"done: {output}", flush=True)


if __name__ == "__main__":
    main()
