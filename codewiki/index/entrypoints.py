from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple


class _EntrypointRule(NamedTuple):
    kind: str
    type_marker: Optional[Tuple[str, str]]
    method_names: Tuple[str, ...]
    reason_template: str
    method_annotations: Tuple[str, ...] = ()
    parameter_types: Optional[Tuple[str, ...]] = None


# Example: MyAction extends BaseAction with execute:
# _EntrypointRule(kind="my", type_marker=("supertype", "BaseAction"),
#                 method_names=("execute",), reason_template="my:{method_name}")
# type_marker kinds are "supertype"/"annotation"; supertype markers use the written simple name, so unresolved external bases match.
ENTRYPOINT_RULES = (
    _EntrypointRule(
        kind="main",
        type_marker=None,
        method_names=("main",),
        method_annotations=(),
        parameter_types=("String[]",),
        reason_template="main_signature",
    ),
    _EntrypointRule(
        kind="main",
        type_marker=None,
        method_names=("main",),
        method_annotations=(),
        parameter_types=("String...",),
        reason_template="main_signature",
    ),
    _EntrypointRule(
        kind="servlet",
        type_marker=("supertype", "HttpServlet"),
        method_names=(
            "doGet", "doPost", "doPut", "doDelete", "doHead",
            "doOptions", "doTrace", "service", "init", "destroy",
        ),
        method_annotations=(),
        parameter_types=None,
        reason_template="servlet:{method_name}",
    ),
    _EntrypointRule(
        kind="jaxrs",
        type_marker=("annotation", "Path"),
        method_names=(),
        method_annotations=(
            "GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH",
        ),
        parameter_types=None,
        reason_template="jaxrs:{method_annotation}",
    ),
)


@dataclass(frozen=True)
class Entrypoint:
    path: str
    method_fqn: str
    owner_fqn: str
    kind: str
    reason: str
    line: int


def _simple_name(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _supertype_graph(supertype_rows):
    graph: Dict[str, Set[str]] = {}
    written_names: Dict[str, Set[str]] = {}
    for ref, resolved in supertype_rows:
        written_names.setdefault(ref.owner_fqn, set()).add(
            _simple_name(ref.name)
        )
        if resolved.outcome != "resolved" or resolved.resolved_fqn is None:
            continue
        graph.setdefault(ref.owner_fqn, set()).add(resolved.resolved_fqn)
    return (
        {
            owner: tuple(sorted(targets))
            for owner, targets in graph.items()
        },
        written_names,
    )


def _ancestor_types(graph: Dict[str, Tuple[str, ...]], owner_fqn: str) -> List[str]:
    """Walk resolved ancestors breadth-first, including each type only once."""
    visited = {owner_fqn}
    frontier = [owner_fqn]
    ancestors = []
    while frontier:
        next_frontier = []
        for current in frontier:
            for ancestor_fqn in graph.get(current, ()):
                if ancestor_fqn in visited:
                    continue
                visited.add(ancestor_fqn)
                ancestors.append(ancestor_fqn)
                next_frontier.append(ancestor_fqn)
        frontier = next_frontier
    return ancestors


def _supertype_marker_owners(rule: _EntrypointRule,
                             graph: Dict[str, Tuple[str, ...]],
                             written_names: Dict[str, Set[str]]) -> Set[str]:
    if rule.type_marker is None or rule.type_marker[0] != "supertype":
        return set()
    marker = rule.type_marker[1]
    direct_owners = {
        owner for owner, names in written_names.items()
        if marker in names
    }
    owners = set(direct_owners)
    for owner in graph:
        if owner in owners:
            continue
        if any(
                ancestor in direct_owners
                for ancestor in _ancestor_types(graph, owner)):
            owners.add(owner)
    return owners


def _annotations_by_owner(annotations) -> Dict[str, Set[str]]:
    result: Dict[str, Set[str]] = {}
    for annotation in annotations:
        result.setdefault(annotation.owner_fqn, set()).add(
            _simple_name(annotation.name)
        )
    return result


def _type_matches(rule: _EntrypointRule, owner_fqn: str,
                  supertype_marker_owners: Set[str],
                  annotations_by_owner: Dict[str, Set[str]]) -> bool:
    if rule.type_marker is None:
        return True
    marker_kind, marker = rule.type_marker
    if marker_kind == "supertype":
        return owner_fqn in supertype_marker_owners
    if marker_kind == "annotation":
        return marker in annotations_by_owner.get(owner_fqn, set())
    raise ValueError("unknown entrypoint type marker: %s" % marker_kind)


def classify(symbols: Sequence, supertype_rows: Iterable,
             annotations: Iterable) -> List[Entrypoint]:
    """Classify extracted methods without reading from or writing to storage."""
    graph, written_names = _supertype_graph(supertype_rows)
    annotations_by_owner = _annotations_by_owner(annotations)
    methods = sorted(
        (
            symbol for symbol in symbols
            if symbol.kind == "method" and symbol.owner_fqn is not None
        ),
        key=lambda symbol: (
            symbol.path, symbol.line, symbol.name, symbol.fqn, symbol.signature,
        ),
    )
    found = []
    for rule in ENTRYPOINT_RULES:
        supertype_marker_owners = _supertype_marker_owners(
            rule, graph, written_names
        )
        for method in methods:
            if rule.method_names and method.name not in rule.method_names:
                continue
            if rule.parameter_types is not None:
                if method.params is None or tuple(method.params) != rule.parameter_types:
                    continue
            method_annotation = None
            if rule.method_annotations:
                method_annotations = annotations_by_owner.get(method.fqn, set())
                method_annotation = next(
                    (
                        marker for marker in rule.method_annotations
                        if marker in method_annotations
                    ),
                    None,
                )
                if method_annotation is None:
                    continue
            if not _type_matches(
                rule, method.owner_fqn,
                    supertype_marker_owners,
                    annotations_by_owner):
                continue
            found.append(Entrypoint(
                path=method.path,
                method_fqn=method.fqn,
                owner_fqn=method.owner_fqn,
                kind=rule.kind,
                reason=rule.reason_template.format(
                    method_name=method.name,
                    method_annotation=method_annotation or "",
                ),
                line=method.line,
            ))
    return sorted(
        found,
        key=lambda row: (
            row.path, row.line, row.method_fqn, row.owner_fqn,
            row.kind, row.reason,
        ),
    )
