from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import List, Optional, Tuple

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


def callers_upward(path: str, fqn: str, max_depth: int = 8,
                   max_nodes: int = 2000) -> Tuple[List[TraceNode], bool]:
    """Return one shortest upward call path for each reachable method."""
    connection = _readonly(path)
    try:
        known = connection.execute(
            "SELECT 1 FROM symbols WHERE fqn = ? LIMIT 1", (fqn,)
        ).fetchone()
        if known is None:
            return [], False
    except sqlite3.DatabaseError as exc:
        raise TypeQueryError("index database missing or stale; rerun index") from exc
    finally:
        connection.close()

    if max_depth <= 0 or max_nodes <= 0:
        return [], True

    nodes = []
    # One visit per FQN keeps cycles finite and preserves one shortest path
    # through heavy call-graph re-convergence.
    visited = {fqn}
    frontier = [(fqn, 0)]
    truncated = False

    while frontier:
        next_frontier = []
        for current_fqn, current_depth in frontier:
            if current_depth >= max_depth:
                truncated = True
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
                    truncated = True
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
                    truncated = True
                    break

            if truncated:
                break

        if truncated:
            break
        frontier = next_frontier

    nodes.sort(key=lambda item: (item.depth, item.fqn, item.path, item.line))
    return nodes, truncated


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
