from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from .index import pipeline
from .query.calls import callees as query_callees
from .query.calls import callers as query_callers
from .query.sql import column_accesses as query_column_accesses
from .query.sql import accesses as query_accesses
from .query.symbols import QueryError, is_indexed, search_path
from .query.trace import (
    callers_upward as query_callers_upward,
    entrypoints_among as query_entrypoints_among,
    path_to as trace_path_to,
)
from .query.types import TypeQueryError, resolve_type_path, subtypes


def _nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def _column_argument(value):
    if "." not in value:
        raise argparse.ArgumentTypeError("expected TABLE.COLUMN")
    return value


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
    resolve = commands.add_parser("resolve-type")
    resolve.add_argument("name")
    resolve.add_argument("--from", dest="from_path", required=True)
    resolve.add_argument("--out", default=None)
    resolve.add_argument("--json", action="store_true")
    impls = commands.add_parser("impls")
    impls.add_argument("fqn")
    impls.add_argument("--out", default=None)
    impls.add_argument("--json", action="store_true")
    impls.add_argument("--direct", action="store_true")
    impls.add_argument("--limit", type=_nonnegative, default=None)
    callers = commands.add_parser("callers")
    callers.add_argument("fqn")
    callers.add_argument("--out", default=None)
    callers.add_argument("--json", action="store_true")
    callers.add_argument("--limit", type=_nonnegative, default=None)
    callers.add_argument("--confirmed", action="store_true")
    callers.add_argument("--direct", action="store_true")
    trace_up = commands.add_parser("trace-up")
    trace_up.add_argument("fqn")
    trace_up.add_argument("--out", default=None)
    trace_up.add_argument("--json", action="store_true")
    trace_up.add_argument("--limit", type=_nonnegative, default=None)
    trace_up.add_argument("--depth", type=_nonnegative, default=8)
    trace_up.add_argument("--entrypoints", action="store_true")
    table = commands.add_parser("table")
    table.add_argument("table")
    table.add_argument("--out", default=None)
    table.add_argument("--json", action="store_true")
    table.add_argument("--limit", type=_nonnegative, default=None)
    access = table.add_mutually_exclusive_group()
    access.add_argument("--read", dest="access", action="store_const", const="READ")
    access.add_argument("--write", dest="access", action="store_const", const="WRITE")
    column = commands.add_parser("column")
    column.add_argument("table_column", type=_column_argument)
    column.add_argument("--out", default=None)
    column.add_argument("--json", action="store_true")
    column.add_argument("--limit", type=_nonnegative, default=None)
    column_access = column.add_mutually_exclusive_group()
    column_access.add_argument(
        "--read", dest="access", action="store_const", const="READ"
    )
    column_access.add_argument(
        "--write", dest="access", action="store_const", const="WRITE"
    )
    stats = commands.add_parser("stats")
    stats.add_argument("--out", default=None)
    stats.add_argument("--json", action="store_true")
    reach = commands.add_parser("reach")
    reach.add_argument("--out", default=None)
    reach.add_argument("--json", action="store_true")
    reach.add_argument("--depth", type=_nonnegative, default=8)
    sample = commands.add_parser("sample")
    sample.add_argument("kind", choices=("sql", "entrypoints", "calls"))
    sample.add_argument("--out", default=None)
    sample.add_argument("-n", type=int, default=20)
    sample.add_argument("--json", action="store_true")
    callees = commands.add_parser("callees")
    callees.add_argument("fqn")
    callees.add_argument("--out", default=None)
    callees.add_argument("--json", action="store_true")
    callees.add_argument("--limit", type=_nonnegative, default=None)
    callees.add_argument("--confirmed", action="store_true")
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
    print("files flagged generated: %d" % result.files_flagged_generated)
    print("symbols found: %d" % result.symbols_found)
    for reason in sorted(result.skipped):
        count = result.skipped[reason]
        if count:
            print("skipped %s: %d" % (reason, count))
    print("imports found: %d" % result.imports_found)
    for form in sorted(result.import_forms or {}):
        print("imports form %s: %d" % (form, result.import_forms[form]))
    for outcome in sorted(result.import_outcomes or {}):
        print("imports outcome %s: %d" % (outcome, result.import_outcomes[outcome]))
    print("internal resolution rate: %.1f%%" % (result.internal_resolution_rate * 100.0))
    print("supertypes found: %d" % result.supertypes_found)
    for outcome in ("resolved", "external", "unresolved", "excluded"):
        print(
            "supertypes outcome %s: %d"
            % (outcome, (result.supertype_outcomes or {}).get(outcome, 0))
        )
    print("supertype resolution rate: %.1f%%" % (
        result.supertype_resolution_rate * 100.0
    ))
    print("calls found: %d" % result.calls_found)
    if result.calls_rows == result.calls_found:
        print("calls rows: same as call sites")
    else:
        print("calls rows: %d" % result.calls_rows)
    for form in ("receiver", "bare", "chained", "method_ref", "constructor"):
        print("calls form %s: %d" % (
            form, (result.call_forms or {}).get(form, 0)
        ))
    for confidence in ("CONFIRMED", "POSSIBLE", "UNRESOLVED"):
        print("calls confidence %s: %d" % (
            confidence, (result.call_confidences or {}).get(confidence, 0)
        ))
    print("call resolution rate (receiver, bare and chained forms): %.1f%%" % (
        result.call_resolution_rate * 100.0
    ))
    for stage in (
            "scan", "symbols", "imports", "supertypes", "calls", "persist",
            "total"):
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


def _resolve_type(args):
    out = os.path.abspath(args.out or os.path.join(os.getcwd(), ".codewiki"))
    result = resolve_type_path(
        os.path.join(out, "index.sqlite3"), args.name, args.from_path
    )
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, separators=(",", ":")))
        return 0
    print("file: %s" % result.file)
    print("name: %s" % result.name)
    print("resolved FQN: %s" % (
        result.resolved_fqn if result.resolved_fqn is not None else "absent"
    ))
    print("rule: %s" % (result.rule if result.rule is not None else "absent"))
    print("outcome: %s" % result.outcome)
    for candidate in result.candidates:
        print("candidate: %s" % candidate)
    return 0


def _impls(args):
    out = os.path.abspath(args.out or os.path.join(os.getcwd(), ".codewiki"))
    db_path = os.path.join(out, "index.sqlite3")
    results = subtypes(db_path, args.fqn)
    if args.direct:
        results = [item for item in results if item.distance == 1]
    truncated = args.limit is not None and len(results) > max(0, args.limit)
    if args.limit is not None:
        results = results[:max(0, args.limit)]
    indexed = is_indexed(db_path, args.fqn)
    # Reflective calls are visible only from the calling side; impls have no indexed edge to report.
    boundaries = []
    status = (
        "NOT_INDEXED" if not indexed else
        "TRUNCATED" if truncated else
        "STOPPED_AT_BOUNDARY" if boundaries else
        "COMPLETE"
    )
    if args.json:
        print(json.dumps({
            "fqn": args.fqn,
            "direct": args.direct,
            "count": len(results),
            "truncated": truncated,
            "results": [item.as_dict() for item in results],
            "status": status,
            "truncation_reason": "limit" if truncated else None,
            "boundaries": boundaries,
        }, ensure_ascii=False, separators=(",", ":")))
        return 0
    for item in results:
        print("%s %s %d %s %s:%d" % (
            item.fqn, item.kind, item.distance, item.relation, item.path, item.line,
        ))
    if truncated:
        print("truncated: limit reached")
    print("%d subtypes" % len(results))
    return 0


def _callers(args):
    out = os.path.abspath(args.out or os.path.join(os.getcwd(), ".codewiki"))
    db_path = os.path.join(out, "index.sqlite3")
    results = query_callers(db_path, args.fqn)
    if args.confirmed:
        results = [item for item in results if item.confidence == "CONFIRMED"]
    if args.direct:
        results = [item for item in results if item.via_fqn is None]
    truncated = args.limit is not None and len(results) > max(0, args.limit)
    if args.limit is not None:
        results = results[:max(0, args.limit)]
    indexed = is_indexed(db_path, args.fqn)
    # Reflective calls are visible only from the calling side; callers have no indexed edge to report.
    boundaries = []
    status = (
        "NOT_INDEXED" if not indexed else
        "TRUNCATED" if truncated else
        "STOPPED_AT_BOUNDARY" if boundaries else
        "COMPLETE"
    )
    direct = sum(item.via_fqn is None for item in results)
    expanded = len(results) - direct
    if args.json:
        print(json.dumps({
            "fqn": args.fqn,
            "direct_only": args.direct,
            "confirmed_only": args.confirmed,
            "count": len(results),
            "truncated": truncated,
            "direct": direct,
            "expanded": expanded,
            "results": [item.as_dict() for item in results],
            "status": status,
            "truncation_reason": "limit" if truncated else None,
            "boundaries": boundaries,
        }, ensure_ascii=False, separators=(",", ":")))
        return 0
    for item in results:
        via = "  via " + item.via_fqn if item.via_fqn is not None else ""
        print("%s  %s:%d  %s%s" % (
            item.caller_fqn, item.path, item.line, item.confidence, via,
        ))
    if truncated:
        print("truncated: limit reached")
    print("%d callers (%d direct, %d via an overridden method)" % (
        len(results), direct, expanded,
    ))
    return 0


def _trace_up(args):
    out = os.path.abspath(args.out or os.path.join(os.getcwd(), ".codewiki"))
    db_path = os.path.join(out, "index.sqlite3")
    nodes, walker_truncated = query_callers_upward(
        db_path, args.fqn, max_depth=args.depth
    )

    if args.entrypoints:
        kinds_by_fqn = query_entrypoints_among(
            db_path, [node.fqn for node in nodes]
        )
        records = []
        for node in nodes:
            for kind in kinds_by_fqn.get(node.fqn, ()):
                records.append((node, kind))
        records.sort(key=lambda item: (item[0].depth, item[0].fqn, item[1]))
        has_entrypoint_matches = bool(records)

        limit_truncated = (
            args.limit is not None and len(records) > max(0, args.limit)
        )
        if args.limit is not None:
            records = records[:max(0, args.limit)]

        result_records = []
        for node, kind in records:
            chain_nodes = trace_path_to(nodes, node.fqn)
            chain = [asdict(item) for item in chain_nodes]
            chain.append({"fqn": args.fqn})
            result = asdict(node)
            result["kind"] = kind
            result["chain"] = chain
            result_records.append((node, kind, chain_nodes, result))

        truncated = walker_truncated or limit_truncated
        max_depth_reached = max(
            (node.depth for node, _kind, _chain, _result in result_records),
            default=0,
        )
        if args.json:
            print(json.dumps({
                "fqn": args.fqn,
                "depth": args.depth,
                "entrypoints_only": True,
                "count": len(result_records),
                "truncated": truncated,
                "max_depth_reached": max_depth_reached,
                "results": [result for _node, _kind, _chain, result in result_records],
            }, ensure_ascii=False, separators=(",", ":")))
            return 0
        if not has_entrypoint_matches:
            print("no entry point reaches %s" % args.fqn)
            return 0
        for node, kind, chain_nodes, _result in result_records:
            print("%s  %s  %s:%d" % (
                kind, node.fqn, node.path, node.line,
            ))
            for item in chain_nodes[1:]:
                print("    -> %s  %s:%d  %s" % (
                    item.fqn, item.path, item.line, item.confidence,
                ))
            print("    -> %s" % args.fqn)
        if limit_truncated:
            print("truncated: limit reached")
        label = "entry point" if len(result_records) == 1 else "entry points"
        verb = "reaches" if len(result_records) == 1 else "reach"
        print("%d %s %s %s" % (
            len(result_records), label, verb, args.fqn,
        ))
        return 0

    limit_truncated = args.limit is not None and len(nodes) > max(0, args.limit)
    if args.limit is not None:
        nodes = nodes[:max(0, args.limit)]
    truncated = walker_truncated or limit_truncated
    max_depth_reached = max((node.depth for node in nodes), default=0)
    if args.json:
        print(json.dumps({
            "fqn": args.fqn,
            "depth": args.depth,
            "entrypoints_only": False,
            "count": len(nodes),
            "truncated": truncated,
            "max_depth_reached": max_depth_reached,
            "results": [asdict(node) for node in nodes],
        }, ensure_ascii=False, separators=(",", ":")))
        return 0
    for node in nodes:
        print("%d  %s  %s:%d  %s" % (
            node.depth, node.fqn, node.path, node.line, node.confidence,
        ))
    if limit_truncated:
        print("truncated: limit reached")
    label = "method" if len(nodes) == 1 else "methods"
    verb = "reaches" if len(nodes) == 1 else "reach"
    print("%d %s %s %s (max depth %d)" % (
        len(nodes), label, verb, args.fqn, max_depth_reached,
    ))
    return 0


def _table(args):
    out = os.path.abspath(args.out or os.path.join(os.getcwd(), ".codewiki"))
    results = query_accesses(
        os.path.join(out, "index.sqlite3"), args.table, args.access
    )
    truncated = args.limit is not None and len(results) > max(0, args.limit)
    if args.limit is not None:
        results = results[:max(0, args.limit)]
    read = sum(item.access == "READ" for item in results)
    write = sum(item.access == "WRITE" for item in results)
    if args.json:
        print(json.dumps({
            "table": args.table,
            "access": args.access,
            "count": len(results),
            "truncated": truncated,
            "read": read,
            "write": write,
            "results": [item.as_dict() for item in results],
        }, ensure_ascii=False, separators=(",", ":")))
        return 0
    for item in results:
        statement = " ".join(item.statement.split())[:100]
        location = "%s:%d" % (item.path, item.line)
        print("%s  %s  %s  %s  %s" % (
            item.access, item.verb, item.method_fqn, location, statement,
        ))
    if truncated:
        print("truncated: limit reached")
    print("%d accesses (%d read, %d write)" % (len(results), read, write))
    return 0


def _column(args):
    table, column = args.table_column.rsplit(".", 1)
    out = os.path.abspath(args.out or os.path.join(os.getcwd(), ".codewiki"))
    results = query_column_accesses(
        os.path.join(out, "index.sqlite3"), table, column, args.access
    )
    truncated = args.limit is not None and len(results) > max(0, args.limit)
    if args.limit is not None:
        results = results[:max(0, args.limit)]
    read = sum(item.access == "READ" for item in results)
    write = sum(item.access == "WRITE" for item in results)
    if args.json:
        print(json.dumps({
            "table": table,
            "column": column,
            "access": args.access,
            "count": len(results),
            "truncated": truncated,
            "read": read,
            "write": write,
            "results": [item.as_dict() for item in results],
        }, ensure_ascii=False, separators=(",", ":")))
        return 0
    for item in results:
        statement = " ".join(item.statement.split())[:100]
        location = "%s:%d" % (item.path, item.line)
        print("%s  %s  %s  %s  %s" % (
            item.access, item.verb, item.method_fqn, location, statement,
        ))
    if truncated:
        print("truncated: limit reached")
    print("%d accesses (%d read, %d write)" % (len(results), read, write))
    return 0


def _stats(args):
    from .query.stats import stats as query_stats

    out = os.path.abspath(args.out or os.path.join(os.getcwd(), ".codewiki"))
    payload = query_stats(os.path.join(out, "index.sqlite3"))
    if args.json:
        print(json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ))
        return 0

    def print_metrics(prefix, value):
        if isinstance(value, dict):
            for key, nested in value.items():
                print_metrics(prefix + "." + key, nested)
        else:
            print("%s: %s" % (prefix, value))

    for key, value in payload.items():
        print_metrics(key, value)
    return 0


def _reach(args):
    from .query.reach import reach as query_reach

    out = os.path.abspath(args.out or os.path.join(os.getcwd(), ".codewiki"))
    payload = query_reach(os.path.join(out, "index.sqlite3"), depth=args.depth)
    if args.json:
        print(json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ))
        return 0

    def print_metrics(prefix, value):
        if isinstance(value, dict):
            for key, nested in value.items():
                print_metrics(prefix + "." + key, nested)
        else:
            print("%s: %s" % (prefix, value))

    for key, value in payload.items():
        print_metrics(key, value)
    return 0


def _sample(args):
    from .query.sample import sample as query_sample

    out = os.path.abspath(args.out or os.path.join(os.getcwd(), ".codewiki"))
    payload = query_sample(
        os.path.join(out, "index.sqlite3"), args.kind, n=args.n
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return 0

    print("警告: この出力は識別子を含む。実ソース環境の外へ持ち出さないこと。")
    if args.kind == "sql":
        fields = ("method_fqn", "verb", "access", "table_name")
    elif args.kind == "entrypoints":
        fields = ("method_fqn", "kind", "reason")
    else:
        fields = ("caller_fqn", "target_fqn", "confidence", "reason")
    for result in payload["results"]:
        location = "%s:%s" % (result["path"], result["line"])
        print(" ".join([location] + [str(result[field]) for field in fields]))
    return 0


def _callees(args):
    out = os.path.abspath(args.out or os.path.join(os.getcwd(), ".codewiki"))
    db_path = os.path.join(out, "index.sqlite3")
    results = query_callees(db_path, args.fqn)
    if args.confirmed:
        results = [item for item in results if item.confidence == "CONFIRMED"]
    boundaries = [
        {
            "kind": "dynamic_dispatch",
            "reason": item.reason,
            "name": item.name,
            "line": item.line,
        }
        for item in results
        if item.reason == "reflective_dispatch"
    ]
    truncated = args.limit is not None and len(results) > max(0, args.limit)
    if args.limit is not None:
        results = results[:max(0, args.limit)]
    indexed = is_indexed(db_path, args.fqn)
    status = (
        "NOT_INDEXED" if not indexed else
        "TRUNCATED" if truncated else
        "STOPPED_AT_BOUNDARY" if boundaries else
        "COMPLETE"
    )
    resolved = sum(item.target_fqn is not None for item in results)
    unresolved = len(results) - resolved
    if args.json:
        print(json.dumps({
            "fqn": args.fqn,
            "confirmed_only": args.confirmed,
            "count": len(results),
            "truncated": truncated,
            "resolved": resolved,
            "unresolved": unresolved,
            "results": [item.as_dict() for item in results],
            "status": status,
            "truncation_reason": "limit" if truncated else None,
            "boundaries": boundaries,
        }, ensure_ascii=False, separators=(",", ":")))
        return 0
    for item in results:
        called = (
            item.receiver + "." + item.name
            if item.receiver is not None else item.name
        )
        print("%d  %-8s  %-19s%s  %s" % (
            item.line, item.form, called, item.confidence, item.reason,
        ))
    if truncated:
        print("truncated: limit reached")
    print("%d callees (%d resolved, %d unresolved)" % (
        len(results), resolved, unresolved,
    ))
    return 0


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.error("a command is required")
    try:
        if args.command == "index":
            return _index(args)
        if args.command == "symbol":
            return _symbol(args)
        if args.command == "impls":
            return _impls(args)
        if args.command == "callers":
            return _callers(args)
        if args.command == "trace-up":
            return _trace_up(args)
        if args.command == "table":
            return _table(args)
        if args.command == "column":
            return _column(args)
        if args.command == "stats":
            return _stats(args)
        if args.command == "reach":
            return _reach(args)
        if args.command == "sample":
            return _sample(args)
        if args.command == "callees":
            return _callees(args)
        return _resolve_type(args)
    except (OSError, QueryError, TypeQueryError, RuntimeError, ValueError) as exc:
        message = str(exc)
        print("error: %s" % message, file=sys.stderr)
        if "rerun index" not in message.lower():
            print("rerun index to rebuild the database", file=sys.stderr)
        return 2
