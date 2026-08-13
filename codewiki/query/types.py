from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import quote

from ..store import db


class TypeQueryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SubtypeResult:
    fqn: str
    kind: str
    path: str
    line: int
    distance: int
    relation: str

    def as_dict(self) -> Dict:
        return {
            "fqn": self.fqn,
            "kind": self.kind,
            "path": self.path,
            "line": self.line,
            "distance": self.distance,
            "relation": self.relation,
        }


@dataclass(frozen=True)
class TypeResolutionResult:
    file: str
    name: str
    resolved_fqn: Optional[str]
    rule: Optional[int]
    outcome: str
    candidates: List[str]

    def as_dict(self) -> Dict:
        return {
            "file": self.file,
            "name": self.name,
            "resolved_fqn": self.resolved_fqn,
            "rule": self.rule,
            "outcome": self.outcome,
            "candidates": list(self.candidates),
        }


def _readonly(path: str) -> sqlite3.Connection:
    absolute = os.path.abspath(path)
    uri = "file:%s?mode=ro" % quote(absolute, safe="/:")
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.execute("PRAGMA foreign_keys = ON")
        db.validate_schema(connection)
        return connection
    except (OSError, sqlite3.DatabaseError, RuntimeError) as exc:
        raise TypeQueryError("index database missing or stale; rerun index") from exc


def resolve_type_path(path: str, name: str, from_path: str) -> TypeResolutionResult:
    """Resolve an indexed simple type name using persisted database rows only."""
    connection = _readonly(path)
    try:
        file_row = connection.execute(
            "SELECT file_id FROM files WHERE path = ?", (from_path,)
        ).fetchone()
        if file_row is None:
            raise TypeQueryError("file is not present in index: %s" % from_path)
        row = connection.execute(
            "SELECT resolved_fqn, rule, outcome, candidates "
            "FROM type_resolutions WHERE file_id = ? AND name = ?",
            (file_row[0], name),
        ).fetchone()
        if row is None:
            wildcard_rows = connection.execute(
                "SELECT name, outcome FROM imports "
                "WHERE file_id = ? AND form = 'wildcard' ORDER BY name",
                (file_row[0],),
            ).fetchall()
            if wildcard_rows:
                candidates = [package + "." + name for package, _outcome in wildcard_rows]
                outcomes = {outcome for _package, outcome in wildcard_rows}
                if "unresolved" in outcomes:
                    return TypeResolutionResult(
                        from_path, name, None, 4, "unresolved", sorted(candidates)
                    )
                if "excluded" in outcomes:
                    return TypeResolutionResult(
                        from_path, name, None, 4, "excluded", sorted(candidates)
                    )
                if outcomes == {"external"}:
                    return TypeResolutionResult(
                        from_path, name, None, None, "external", sorted(candidates)
                    )
            return TypeResolutionResult(from_path, name, None, None, "unresolved", [])
        candidates = json.loads(row[3]) if row[3] else []
        return TypeResolutionResult(
            from_path, name, row[0], row[1], row[2], list(candidates)
        )
    except TypeQueryError:
        raise
    except (sqlite3.DatabaseError, ValueError, TypeError) as exc:
        raise TypeQueryError("index database missing or stale; rerun index") from exc
    finally:
        connection.close()


resolve_type = resolve_type_path


def subtypes(path: str, fqn: str) -> List[SubtypeResult]:
    """Return all indexed subtypes of an indexed type."""
    connection = _readonly(path)
    try:
        frontier = [fqn]
        visited = {fqn}
        distance = 0
        results = []
        while frontier:
            candidates = {}
            for current in frontier:
                rows = connection.execute(
                    "SELECT s.fqn, s.kind, f.path, s.line, st.relation "
                    "FROM supertypes AS st "
                    "JOIN symbols AS s ON s.fqn = st.owner_fqn "
                    "JOIN files AS f ON f.file_id = s.file_id "
                    "WHERE st.target_fqn = ? AND st.outcome = 'resolved' "
                    "AND s.kind IN ('class', 'interface', 'enum', 'record') "
                    "ORDER BY st.relation, st.owner_fqn, f.path, s.line, s.symbol_id",
                    (current,),
                ).fetchall()
                for row in rows:
                    owner_fqn = row[0]
                    if owner_fqn in visited:
                        continue
                    subtype = SubtypeResult(
                        owner_fqn, row[1], row[2], row[3], distance + 1, row[4]
                    )
                    edge_key = (subtype.relation, subtype.fqn)
                    previous = candidates.get(owner_fqn)
                    if previous is None or edge_key < previous[0]:
                        candidates[owner_fqn] = (edge_key, subtype)

            frontier = []
            for owner_fqn in sorted(candidates):
                visited.add(owner_fqn)
                subtype = candidates[owner_fqn][1]
                results.append(subtype)
                frontier.append(owner_fqn)
            distance += 1
        return sorted(results, key=lambda item: (item.distance, item.fqn))
    except sqlite3.DatabaseError as exc:
        raise TypeQueryError("index database missing or stale; rerun index") from exc
    finally:
        connection.close()
