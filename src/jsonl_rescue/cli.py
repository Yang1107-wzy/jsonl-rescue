"""Scan and clean JSONL datasets from the terminal."""

import argparse
import json
import sqlite3
import sys
import zlib

from . import __version__
from .core import process


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate JSONL objects and preserve rejected rows."
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "clean"):
        p = sub.add_parser(name)
        p.add_argument("source", help="UTF-8 JSONL or .jsonl.gz file")
        p.add_argument(
            "--required",
            action="append",
            default=[],
            metavar="KEY",
            help="Required top-level key; repeat for multiple keys",
        )
        p.add_argument(
            "--dedupe",
            action="store_true",
            help="Reject canonical-JSON duplicates using temporary SQLite",
        )
        p.add_argument("--max-issues", type=int, default=100)
        p.add_argument("--format", choices=["text", "json"], default="text")
        if name == "clean":
            p.add_argument("--output", required=True, help="New clean JSONL path")
            p.add_argument("--rejects", required=True, help="New rejection archive JSONL path")
    args = parser.parse_args(argv)
    try:
        report = process(
            args.source,
            required=args.required,
            dedupe=args.dedupe,
            output=getattr(args, "output", None),
            rejects=getattr(args, "rejects", None),
            max_issues=args.max_issues,
        )
    except (OSError, ValueError, EOFError, zlib.error, sqlite3.Error) as exc:
        print("jsonl-rescue: " + str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(
            f"{report['total']} rows | {report['accepted']} accepted | {report['rejected']} rejected | {report['duplicates']} duplicates"
        )
        for code, count in report["issue_counts"].items():
            print(f"{code}: {count}")
    # A completed cleanup succeeds even when its quarantine is nonempty.
    return int(args.command == "scan" and report["rejected"] > 0)
