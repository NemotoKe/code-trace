from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .calls import CallSite
from .declarations import Declaration
from .resolution import ResolutionIndex, TypeInfo, resolve_type
from .symbols import Symbol


@dataclass(frozen=True)
class CallResolution:
    site: CallSite
    owner_fqn: Optional[str]
    targets: Tuple[str, ...]
    confidence: str
    reason: str


@dataclass
class _DeclarationIndex:
    source: Sequence[Declaration]
    methods: Dict[Tuple[str, str, str], Tuple[Tuple[int, int, Declaration], ...]]
    fields: Dict[Tuple[str, str, str], Declaration]


@dataclass
class _TypeIndex:
    source: Sequence[TypeInfo]
    by_fqn: Dict[str, TypeInfo]
    groups: Dict[str, Tuple[TypeInfo, ...]]


# The public function intentionally keeps the requested compact signature.  These
# caches index the caller-owned in-memory collections while their identity and
# length remain unchanged; they do not persist anything and retain the source
# object so an id cannot be reused incorrectly.
_DECLARATION_INDEX_CACHE: Dict[
    int, Tuple[Sequence[Declaration], int, _DeclarationIndex]
] = {}
_TYPE_INDEX_CACHE: Dict[
    int, Tuple[Sequence[TypeInfo], int, _TypeIndex]
] = {}


def _result(site: CallSite, owner_fqn: Optional[str], targets,
            confidence: str, reason: str) -> CallResolution:
    return CallResolution(
        site, owner_fqn, tuple(targets), confidence, reason,
    )


def _declaration_index(declarations: Sequence[Declaration]) -> _DeclarationIndex:
    cached = _DECLARATION_INDEX_CACHE.get(id(declarations))
    if (cached is not None and cached[0] is declarations
            and cached[1] == len(declarations)):
        return cached[2]

    method_groups = {}
    field_groups = {}
    for index, declaration in enumerate(declarations):
        key = (declaration.path, declaration.scope_fqn, declaration.name)
        if declaration.kind in ("parameter", "local"):
            method_groups.setdefault(key, []).append((declaration.line, index, declaration))
        elif declaration.kind == "field":
            field_groups.setdefault(key, []).append((declaration.line, index, declaration))

    methods = {}
    for key, values in method_groups.items():
        methods[key] = tuple(sorted(values, key=lambda item: (item[0], item[1])))
    fields = {
        key: min(values, key=lambda item: (item[0], item[2].type_name, item[1]))[2]
        for key, values in field_groups.items()
    }
    result = _DeclarationIndex(declarations, methods, fields)
    _DECLARATION_INDEX_CACHE[id(declarations)] = (
        declarations, len(declarations), result,
    )
    return result


def _method_declaration(site: CallSite, index: _DeclarationIndex) -> Optional[Declaration]:
    candidates = index.methods.get((site.path, site.enclosing_fqn, site.receiver), ())
    if not candidates:
        return None
    position = bisect_right(candidates, (site.line, float("inf")))
    if position == 0:
        return None
    return candidates[position - 1][2]


def _field_declaration(path: str, name: Optional[str], owner_fqn: str,
                       index: _DeclarationIndex) -> Optional[Declaration]:
    return index.fields.get((path, owner_fqn, name))


def _type_index(types: Sequence[TypeInfo]) -> _TypeIndex:
    cached = _TYPE_INDEX_CACHE.get(id(types))
    if cached is not None and cached[0] is types and cached[1] == len(types):
        return cached[2]

    groups = {}
    by_fqn = {}
    for item in types:
        groups.setdefault(item.fqn, []).append(item)
        by_fqn[item.fqn] = item
    result = _TypeIndex(
        types,
        by_fqn,
        {fqn: tuple(items) for fqn, items in groups.items()},
    )
    _TYPE_INDEX_CACHE[id(types)] = (types, len(types), result)
    return result


def _enclosing_type(site: CallSite, index: _TypeIndex) -> Optional[TypeInfo]:
    enclosing_fqn = site.enclosing_fqn
    if site.enclosing_kind in ("method", "constructor"):
        enclosing_fqn = enclosing_fqn.rsplit(".", 1)[0]

    exact = index.groups.get(enclosing_fqn, ())
    if exact:
        return min(exact, key=lambda item: (item.path, item.name))

    parts = site.enclosing_fqn.split(".")
    for end in range(len(parts), 0, -1):
        candidates = index.groups.get(".".join(parts[:end]), ())
        if candidates:
            return max(candidates, key=lambda item: (len(item.fqn), item.fqn))
    return None


def _visible_declaration(site: CallSite, declarations: Sequence[Declaration],
                         types: Sequence[TypeInfo]) -> Optional[Declaration]:
    declaration_index = _declaration_index(declarations)
    type_index = _type_index(types)
    declaration = _method_declaration(site, declaration_index)
    if declaration is not None:
        return declaration

    current_type = _enclosing_type(site, type_index)
    if current_type is None:
        return None

    owner = current_type
    while owner is not None:
        declaration = _field_declaration(
            site.path, site.receiver, owner.fqn, declaration_index,
        )
        if declaration is not None:
            return declaration
        owner = type_index.by_fqn.get(owner.owner_fqn)
    return None


def _matching_members(site: CallSite, owner_fqn: str,
                      members_by_owner: Mapping[str, Sequence[Symbol]]) -> List[Symbol]:
    return [
        symbol for symbol in members_by_owner.get(owner_fqn, ())
        if symbol.kind == "method" and symbol.name == site.name
    ]


def resolve_receiver_call(
    site: CallSite,
    declarations: Sequence[Declaration],
    file_packages: Dict[str, Optional[str]],
    types: Sequence[TypeInfo],
    imports_by_file: Dict[str, Sequence],
    lookup: ResolutionIndex,
    members_by_owner: Mapping[str, Sequence[Symbol]],
) -> CallResolution:
    """Resolve one receiver-form call through the variable visible at its site."""
    if site.form != "receiver":
        return _result(site, None, (), "UNRESOLVED", "no_declaration")

    declaration = _visible_declaration(site, declarations, types)
    if declaration is None:
        return _result(site, None, (), "UNRESOLVED", "no_declaration")

    type_resolution = resolve_type(
        site.path, declaration.type_name, file_packages, types,
        imports_by_file, lookup,
    )
    owner_fqn = type_resolution.resolved_fqn
    if type_resolution.outcome != "resolved" or owner_fqn is None:
        return _result(site, None, (), "UNRESOLVED", "type_unresolved")

    members = _matching_members(site, owner_fqn, members_by_owner)
    targets = sorted(set(member.fqn for member in members))
    if len(members) == 1:
        return _result(site, owner_fqn, targets, "CONFIRMED", "single_member")
    if len(members) > 1:
        return _result(site, owner_fqn, targets, "POSSIBLE", "overloaded")
    return _result(site, owner_fqn, (), "UNRESOLVED", "member_absent")
