from __future__ import annotations

import sqlite3
from typing import Dict

from .trace import callers_upward, entrypoints_among
from .types import TypeQueryError, _readonly


_ERROR_MESSAGE = "index database missing or stale; rerun index"
_ENTRYPOINT_KINDS = ("main", "servlet", "jaxrs")


def reach(path: str, depth: int = 8) -> Dict:
    """Measure how many SQL-accessing methods reach an indexed entrypoint."""
    connection = _readonly(path)
    try:
        methods = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT method_fqn FROM sql_accesses "
                "WHERE method_fqn <> '' ORDER BY method_fqn"
            )
        ]
    except sqlite3.DatabaseError as exc:
        raise TypeQueryError(_ERROR_MESSAGE) from exc
    finally:
        connection.close()

    depth_histogram = {
        str(level): 0
        for level in range(1, depth + 1)
    }
    entrypoint_kind_hits = {kind: 0 for kind in _ENTRYPOINT_KINDS}
    entrypoint_kind_hits["other"] = 0
    reached = 0
    no_caller = 0
    truncated = 0

    for method_fqn in methods:
        nodes, walker_truncated = callers_upward(
            path, method_fqn, max_depth=depth
        )
        if not nodes:
            no_caller += 1
        if walker_truncated:
            truncated += 1

        found = entrypoints_among(path, [node.fqn for node in nodes])
        if not found:
            continue

        reached += 1
        shallowest = min(
            node.depth
            for node in nodes
            if node.fqn in found
        )
        depth_histogram[str(shallowest)] += 1
        for kinds in found.values():
            for kind in kinds:
                if kind in _ENTRYPOINT_KINDS:
                    entrypoint_kind_hits[kind] += 1
                else:
                    entrypoint_kind_hits["other"] += 1

    method_count = len(methods)
    return {
        "depth": depth,
        "methods": method_count,
        "reached": reached,
        "reach_rate": (
            float(reached) / method_count if method_count else 0.0
        ),
        "no_caller": no_caller,
        "truncated": truncated,
        "depth_histogram": depth_histogram,
        "entrypoint_kind_hits": entrypoint_kind_hits,
    }

