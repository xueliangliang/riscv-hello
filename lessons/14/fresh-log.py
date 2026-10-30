#!/usr/bin/env python3
"""Truncate every PATH argument so a previous run's PASS cannot survive."""
import sys


def truncate(path):
    try:
        with open(path, "wb"):
            pass
    except OSError as error:
        raise SystemExit(f"fresh-log: cannot truncate {path}: {error}")


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: fresh-log.py PATH [PATH ...]")
    for path in argv[1:]:
        truncate(path)


if __name__ == "__main__":
    main(sys.argv)
