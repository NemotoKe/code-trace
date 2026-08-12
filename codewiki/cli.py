from __future__ import annotations

import argparse
import json
import os
import sys

from .index import pipeline
from .query.symbols import QueryError, search_path


def _nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def _parser():
    parser = argparse.ArgumentParser(prog="codewiki")
    commands = parser.add_subparsers(dest="command")
    index = commands.add_parser("index")
    index.add_argument("repo")
    index.add_argument("--out", default=None)
    index.add_argument("--jobs", type=_nonnegative, default=None)
    index.add_argument("--quiet", action="store_true")
    symbol = commands.add_parser("symbol")
    symbol.add_argument("query")
    symbol.add_argument("--out", default=None)
    symbol.add_argument("--json", action="store_true")
    symbol.add_argument("--limit", type=_nonnegative, default=None)
    symbol.add_argument("--kind", default=None)
    return parser


def _inside(child, parent):
    try:
        child = os.path.realpath(os.path.abspath(child))
        parent = os.path.realpath(os.path.abspath(parent))
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


def _index(args):
    root = os.path.abspath(args.repo)
    if not os.path.isdir(root):
        raise ValueError("repository does not exist: %s" % args.repo)
    explicit_out = args.out is not None
    out = os.path.abspath(args.out or os.path.join(os.getcwd(), ".codewiki"))
    # Explicit in-repository output is intentionally permitted.
    if _inside(out, root) and not explicit_out:
        raise ValueError("--out is required when output is inside the scanned repository")

    def progress(stage, message):
        if not args.quiet:
            print("%s: %s" % (stage, message))

    timings = {}
    result = pipeline.run(root, out, jobs=args.jobs, progress=progress, timings=timings)
    print("files scanned: %d" % result.files_scanned)
    print("files analyzed: %d" % result.files_analyzed)
    print("symbols found: %d" % result.symbols_found)
    for reason in sorted(result.skipped):
        count = result.skipped[reason]
        if count:
            print("skipped %s: %d" % (reason, count))
    for stage in ("scan", "symbols", "persist", "total"):
        print("%s: %.3fs" % (stage, timings.get(stage, 0.0)))
    return 0


def _symbol(args):
    out = os.path.abspath(args.out or os.path.join(os.getcwd(), ".codewiki"))
    result = search_path(
        os.path.join(out, "index.sqlite3"), args.query,
        limit=args.limit, kind=args.kind,
    )
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, separators=(",", ":")))
    else:
        for item in result.results:
            end_line = item["end_line"] if item["end_line"] is not None else "?"
            print("%s %s %s:%d-%s" % (
                item["fqn"], item["kind"], item["path"],
                item["line"], end_line,
            ))
        if result.truncated:
            print("truncated: limit reached")
    return 0


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.error("a command is required")
    try:
        if args.command == "index":
            return _index(args)
        return _symbol(args)
    except (OSError, QueryError, RuntimeError, ValueError) as exc:
        message = str(exc)
        print("error: %s" % message, file=sys.stderr)
        if "rerun index" not in message.lower():
            print("rerun index to rebuild the database", file=sys.stderr)
        return 2
