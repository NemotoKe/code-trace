from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .types import TypeQueryError, _readonly


@dataclass(frozen=True)
class CalleeResult:
    line: int
    form: str
    receiver: Optional[str]
    name: str
    target_fqn: Optional[str]
    confidence: str
    reason: str

    def as_dict(self) -> Dict:
        return {
            "line": self.line,
            "form": self.form,
            "receiver": self.receiver,
            "name": self.name,
            "target_fqn": self.target_fqn,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CallerResult:
    caller_fqn: str
    path: str
    line: int
    form: str
    receiver: Optional[str]
    name: str
    confidence: str
    reason: str
    via_fqn: Optional[str]

    def as_dict(self) -> Dict:
        return {
            "caller_fqn": self.caller_fqn,
            "path": self.path,
            "line": self.line,
            "form": self.form,
            "receiver": self.receiver,
            "name": self.name,
            "confidence": self.confidence,
            "reason": self.reason,
            "via_fqn": self.via_fqn,
        }


def callees(path: str, fqn: str) -> List[CalleeResult]:
    """Return all indexed calls made by a method or type, in source order."""
    connection = _readonly(path)
    try:
        known = connection.execute(
            "SELECT 1 FROM symbols WHERE fqn = ? LIMIT 1", (fqn,)
        ).fetchone()
        if known is None:
            return []
        rows = connection.execute(
            "SELECT line, form, receiver, name, target_fqn, confidence, reason "
            "FROM calls WHERE caller_fqn = ? "
            "ORDER BY line, name, call_id",
            (fqn,),
        ).fetchall()
        return [CalleeResult(*row) for row in rows]
    except sqlite3.DatabaseError as exc:
        raise TypeQueryError("index database missing or stale; rerun index") from exc
    finally:
        connection.close()


def _caller_rows(connection: sqlite3.Connection, target_fqn: str,
                 via_fqn: Optional[str]) -> List[Tuple[int, CallerResult]]:
    rows = connection.execute(
        "SELECT c.call_id, c.caller_fqn, f.path, c.line, c.form, c.receiver, "
        "c.name, c.confidence, c.reason "
        "FROM calls AS c JOIN files AS f ON f.file_id = c.file_id "
        "WHERE c.target_fqn = ? "
        "ORDER BY c.caller_fqn, f.path, c.line, c.name, c.call_id",
        (target_fqn,),
    ).fetchall()
    return [
        (
            row[0],
            CallerResult(
                row[1], row[2], row[3], row[4], row[5], row[6], row[7],
                row[8], via_fqn,
            ),
        )
        for row in rows
    ]


def _ancestor_types(
    connection: sqlite3.Connection,
    owner_fqn: str,
    max_hops: Optional[int] = None,
) -> Tuple[List[str], bool]:
    hop_budget = None if max_hops is None else max(0, max_hops)
    visited = {owner_fqn}
    frontier = [owner_fqn]
    ancestors = []
    hops = 0
    truncated = False
    while frontier:
        next_frontier = []
        for current in frontier:
            rows = connection.execute(
                "SELECT target_fqn FROM supertypes "
                "WHERE owner_fqn = ? AND outcome = 'resolved' "
                "AND target_fqn IS NOT NULL "
                "ORDER BY relation, target_fqn, line, supertype_id",
                (current,),
            ).fetchall()
            if hop_budget is not None and hops >= hop_budget:
                if any(
                    ancestor_fqn not in visited for (ancestor_fqn,) in rows
                ):
                    truncated = True
                continue
            for (ancestor_fqn,) in rows:
                if ancestor_fqn in visited:
                    continue
                visited.add(ancestor_fqn)
                ancestors.append(ancestor_fqn)
                next_frontier.append(ancestor_fqn)
        frontier = next_frontier
        hops += 1
    return ancestors, truncated


def callers_bounded(
    path: str,
    fqn: str,
    max_dispatch_hops: Optional[int] = None,
) -> Tuple[List[CallerResult], bool]:
    """Return indexed direct and interface-dispatched callers of a method."""
    connection = _readonly(path)
    try:
        method = connection.execute(
            "SELECT name, owner_fqn FROM symbols "
            "WHERE fqn = ? AND owner_fqn IS NOT NULL "
            "ORDER BY symbol_id LIMIT 1",
            (fqn,),
        ).fetchone()
        if method is None:
            return [], False
        direct = _caller_rows(connection, fqn, None)
        expanded = []
        seen_call_ids = set()
        ancestor_types, truncated = _ancestor_types(
            connection, method[1], max_hops=max_dispatch_hops
        )
        for ancestor_type in ancestor_types:
            ancestor_method = ancestor_type + "." + method[0]
            for call_id, result in _caller_rows(
                connection, ancestor_method, ancestor_method
            ):
                if call_id in seen_call_ids:
                    continue
                seen_call_ids.add(call_id)
                expanded.append((call_id, result))
        expanded.sort(
            key=lambda item: (
                item[1].caller_fqn, item[1].path, item[1].line,
                item[1].name, item[0],
            )
        )
        return [result for _call_id, result in direct + expanded], truncated
    except sqlite3.DatabaseError as exc:
        raise TypeQueryError("index database missing or stale; rerun index") from exc
    finally:
        connection.close()


def callers(path: str, fqn: str) -> List[CallerResult]:
    """Return indexed direct and interface-dispatched callers of a method."""
    results, _truncated = callers_bounded(path, fqn)
    return results
