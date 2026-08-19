from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .calls import callers
from .types import TypeQueryError, _readonly


@dataclass(frozen=True)
class TraceNode:
    fqn: str
    depth: int
    path: str
    line: int
    confidence: str
    via_fqn: Optional[str]
    parent_fqn: Optional[str]


def callers_upward_bounded(path: str, fqn: str, max_depth: int = 8,
                           max_nodes: int = 2000) -> Tuple[List[TraceNode], Optional[str]]:
    """Return one shortest upward call path for each reachable method."""
    connection = _readonly(path)
    try:
        known = connection.execute(
            "SELECT 1 FROM symbols WHERE fqn = ? LIMIT 1", (fqn,)
        ).fetchone()
        if known is None:
            return [], None
    except sqlite3.DatabaseError as exc:
        raise TypeQueryError("index database missing or stale; rerun index") from exc
    finally:
        connection.close()

    if max_depth <= 0 or max_nodes <= 0:
        return [], "depth" if max_depth <= 0 else "nodes"

    nodes = []
    # One visit per FQN keeps cycles finite and preserves one shortest path
    # through heavy call-graph re-convergence.
    visited = {fqn}
    frontier = [(fqn, 0)]
    reason = None

    while frontier:
        next_frontier = []
        for current_fqn, current_depth in frontier:
            if current_depth >= max_depth:
                try:
                    boundary_callers = callers(path, current_fqn)
                except sqlite3.DatabaseError as exc:
                    raise TypeQueryError(
                        "index database missing or stale; rerun index"
                    ) from exc
                if any(
                    result.caller_fqn not in visited
                    for result in boundary_callers
                ):
                    reason = "depth"
                continue

            try:
                current_callers = callers(path, current_fqn)
            except sqlite3.DatabaseError as exc:
                raise TypeQueryError(
                    "index database missing or stale; rerun index"
                ) from exc

            for result in current_callers:
                if result.caller_fqn in visited:
                    continue
                if len(nodes) >= max_nodes:
                    reason = "nodes"
                    break
                visited.add(result.caller_fqn)
                next_frontier.append((result.caller_fqn, current_depth + 1))
                nodes.append(
                    TraceNode(
                        result.caller_fqn,
                        current_depth + 1,
                        result.path,
                        result.line,
                        result.confidence,
                        result.via_fqn,
                        current_fqn,
                    )
                )
                if len(nodes) >= max_nodes:
                    reason = "nodes"
                    break

            if reason is not None:
                break

        if reason is not None:
            break
        frontier = next_frontier

    nodes.sort(key=lambda item: (item.depth, item.fqn, item.path, item.line))
    return nodes, reason


def callers_upward(path: str, fqn: str, max_depth: int = 8,
                   max_nodes: int = 2000) -> Tuple[List[TraceNode], bool]:
    """Return one shortest upward call path for each reachable method."""
    nodes, reason = callers_upward_bounded(
        path, fqn, max_depth=max_depth, max_nodes=max_nodes
    )
    return nodes, reason is not None


def path_to(nodes: List[TraceNode], fqn: str) -> List[TraceNode]:
    """Return the recorded shortest path to ``fqn``, nearest node first."""
    by_fqn = {node.fqn: node for node in nodes}
    current = by_fqn.get(fqn)
    if current is None:
        return []

    result = []
    seen = set()
    while current is not None and current.fqn not in seen:
        seen.add(current.fqn)
        result.append(current)
        if current.parent_fqn is None:
            break
        current = by_fqn.get(current.parent_fqn)
    return result


def entrypoints_among(path: str, fqns: Sequence[str]) -> Dict[str, Tuple[str, ...]]:
    """Return sorted entrypoint kinds for the requested indexed methods."""
    requested = list(dict.fromkeys(fqns))
    if not requested:
        return {}

    connection = _readonly(path)
    try:
        kinds_by_fqn = {}
        for offset in range(0, len(requested), 900):
            batch = requested[offset:offset + 900]
            placeholders = ", ".join("?" for _fqn in batch)
            rows = connection.execute(
                "SELECT method_fqn, kind FROM entrypoints "
                "WHERE method_fqn IN (" + placeholders + ") "
                "ORDER BY method_fqn, kind",
                batch,
            ).fetchall()
            for method_fqn, kind in rows:
                kinds_by_fqn.setdefault(method_fqn, set()).add(kind)
        return {
            method_fqn: tuple(sorted(kinds))
            for method_fqn, kinds in sorted(kinds_by_fqn.items())
        }
    except sqlite3.DatabaseError as exc:
        raise TypeQueryError("index database missing or stale; rerun index") from exc
    finally:
        connection.close()
