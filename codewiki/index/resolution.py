from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from ..javalang import JAVA_LANG_TYPES


TYPE_KINDS = {"class", "interface", "enum", "record", "annotation"}
IMPORT_OUTCOMES = ("resolved", "external", "unresolved", "excluded")
TYPE_RESOLUTION_OUTCOMES = ("resolved", "external", "unresolved", "excluded")


@dataclass(frozen=True)
class TypeInfo:
    path: str
    name: str
    fqn: str
    package: Optional[str]
    owner_fqn: Optional[str]


@dataclass(frozen=True)
class TypeResolution:
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


@dataclass(frozen=True)
class ImportResolution:
    target_fqn: Optional[str]
    internal_target: Optional[str]
    outcome: str
    candidates: List[str]


@dataclass(frozen=True)
class ResolutionIndex:
    """Repository-wide lookup tables used by the ordered resolution rules."""

    types: Tuple[TypeInfo, ...]
    internal: FrozenSet[str]
    owners_by_fqn: Dict[str, FrozenSet[Optional[str]]]
    same_file: Dict[Tuple[str, str], Tuple[str, ...]]
    same_package: Dict[Tuple[Optional[str], str], Tuple[str, ...]]
    wildcard_types: Dict[Tuple[Optional[str], str], Tuple[str, ...]]
    names_by_path: Dict[str, FrozenSet[str]]
    names_by_package: Dict[Optional[str], FrozenSet[str]]
    wildcard_names_by_package: Dict[Optional[str], FrozenSet[str]]
    packages_with_types: FrozenSet[Optional[str]]
    packages: FrozenSet[str] = frozenset()
    analyzable_packages: FrozenSet[str] = frozenset()


@dataclass(frozen=True)
class _FileImports:
    explicit: Dict[str, Tuple[str, ...]]
    wildcard_packages: Tuple[str, ...]


def type_infos(symbols: Iterable) -> List[TypeInfo]:
    result = [
        TypeInfo(symbol.path, symbol.name, symbol.fqn, symbol.package, symbol.owner_fqn)
        for symbol in symbols
        if symbol.kind in TYPE_KINDS
    ]
    return sorted(result, key=lambda item: (item.fqn, item.path, item.name))


def build_lookup(types: Sequence[TypeInfo], packages: Iterable = (),
                 analyzable_packages: Optional[Iterable] = None) -> ResolutionIndex:
    """Build repository-wide indexes once for the resolution pass."""
    ordered_types = tuple(types)
    package_names = {package for package in packages if package}
    package_names.update(item.package for item in ordered_types if item.package)
    if analyzable_packages is None:
        analyzable_package_names = {
            item.package for item in ordered_types if item.package
        }
    else:
        analyzable_package_names = {
            package for package in analyzable_packages if package
        }
    same_file = {}
    same_package = {}
    wildcard_types = {}
    names_by_path = {}
    names_by_package = {}
    wildcard_names_by_package = {}
    packages_with_types = set()
    owners_by_fqn = {}

    for item in ordered_types:
        same_file.setdefault((item.path, item.name), []).append(item.fqn)
        names_by_path.setdefault(item.path, set()).add(item.name)
        names_by_package.setdefault(item.package, set()).add(item.name)
        packages_with_types.add(item.package)
        owners_by_fqn.setdefault(item.fqn, set()).add(item.owner_fqn)
        if item.owner_fqn is None:
            same_package.setdefault((item.package, item.name), []).append(item.fqn)
            wildcard_types.setdefault((item.package, item.name), []).append(item.fqn)
            wildcard_names_by_package.setdefault(item.package, set()).add(item.name)

    def sorted_values(values):
        return {key: tuple(sorted(items)) for key, items in values.items()}

    return ResolutionIndex(
        types=ordered_types,
        internal=frozenset(item.fqn for item in ordered_types),
        owners_by_fqn={
            key: frozenset(value) for key, value in owners_by_fqn.items()
        },
        same_file=sorted_values(same_file),
        same_package=sorted_values(same_package),
        wildcard_types=sorted_values(wildcard_types),
        names_by_path={key: frozenset(value) for key, value in names_by_path.items()},
        names_by_package={key: frozenset(value) for key, value in names_by_package.items()},
        wildcard_names_by_package={
            key: frozenset(value) for key, value in wildcard_names_by_package.items()
        },
        packages_with_types=frozenset(packages_with_types),
        packages=frozenset(package_names),
        analyzable_packages=frozenset(analyzable_package_names),
    )


def _prepare_file_imports(items: Iterable) -> _FileImports:
    explicit = {}
    wildcard_packages = set()
    for item in items:
        if item.is_static:
            continue
        if item.is_wildcard:
            wildcard_packages.add(item.name)
            continue
        explicit.setdefault(item.name.rsplit(".", 1)[-1], set()).add(item.name)
    return _FileImports(
        explicit={key: tuple(sorted(value)) for key, value in explicit.items()},
        wildcard_packages=tuple(sorted(wildcard_packages)),
    )


def _prepare_imports(imports_by_file: Dict[str, Sequence]) -> Dict[str, _FileImports]:
    return {
        path: _prepare_file_imports(items)
        for path, items in imports_by_file.items()
    }


def _longest_existing_package(name: str, packages: FrozenSet[str]) -> Optional[str]:
    """Return the most specific repository package prefix in an import name."""
    parts = name.split(".")
    for length in range(len(parts) - 1, 0, -1):
        candidate = ".".join(parts[:length])
        if candidate in packages:
            return candidate
    return None


def _unique(values: Iterable[str]) -> List[str]:
    return sorted(set(value for value in values if value))


def _unresolved(file_path: str, name: str, rule: Optional[int], candidates) -> TypeResolution:
    return TypeResolution(
        file_path, name, None, rule, "unresolved",
        sorted(candidate for candidate in candidates if candidate),
    )


def _classify_candidates(file_path: str, name: str, candidates,
                         lookup: ResolutionIndex,
                         rule: Optional[int] = None) -> TypeResolution:
    """Classify possible qualified targets using repository package prefixes."""
    candidates = _unique(candidates)
    matching_packages = [
        _longest_existing_package(candidate, lookup.packages)
        for candidate in candidates
    ]
    if any(package in lookup.analyzable_packages for package in matching_packages):
        return TypeResolution(file_path, name, None, rule, "unresolved", candidates)
    if any(package is not None for package in matching_packages):
        return TypeResolution(file_path, name, None, rule, "excluded", candidates)
    return TypeResolution(file_path, name, None, rule, "external", candidates)


def resolve_type(
    file_path: str,
    name: str,
    file_packages: Dict[str, Optional[str]],
    types: Sequence[TypeInfo],
    imports_by_file: Dict[str, Sequence],
    lookup: Optional[ResolutionIndex] = None,
    prepared_imports: Optional[_FileImports] = None,
) -> TypeResolution:
    """Resolve a simple Java type name using conservative ordered rules."""
    lookup = lookup or build_lookup(types, file_packages.values())
    prepared_imports = prepared_imports or _prepare_file_imports(
        imports_by_file.get(file_path, ())
    )
    current_package = file_packages.get(file_path)

    same_file = lookup.same_file.get((file_path, name), ())
    if same_file:
        candidates = [value for value in same_file if value]
        if len(candidates) == 1:
            return TypeResolution(file_path, name, candidates[0], 1, "resolved", candidates)
        return _unresolved(file_path, name, 1, candidates)

    explicit = prepared_imports.explicit.get(name, ())
    if explicit:
        existing = _unique(value for value in explicit if value in lookup.internal)
        if len(existing) == 1 and len(explicit) == 1:
            return TypeResolution(file_path, name, existing[0], 2, "resolved", existing)
        if len(explicit) == 1 and not existing:
            package = _longest_existing_package(explicit[0], lookup.packages)
            if package is None:
                return TypeResolution(file_path, name, None, None, "external", explicit)
            if package not in lookup.analyzable_packages:
                return TypeResolution(file_path, name, None, 2, "excluded", explicit)
            return _unresolved(file_path, name, 2, explicit)
        return _unresolved(file_path, name, 2, explicit)

    same_package = [
        value for value in lookup.same_package.get((current_package, name), ()) if value
    ]
    if same_package:
        if len(same_package) == 1:
            return TypeResolution(file_path, name, same_package[0], 3, "resolved", same_package)
        return _unresolved(file_path, name, 3, same_package)

    wildcard_packages = prepared_imports.wildcard_packages
    wildcard_candidates = sorted(
        candidate
        for package in wildcard_packages
        for candidate in lookup.wildcard_types.get((package, name), ())
    )
    if wildcard_candidates:
        unique_wildcard_candidates = _unique(wildcard_candidates)
        if len(wildcard_candidates) == 1:
            return TypeResolution(
                file_path, name, unique_wildcard_candidates[0], 4,
                "resolved", unique_wildcard_candidates
            )
        return _unresolved(file_path, name, 4, unique_wildcard_candidates)

    if wildcard_packages:
        possible = [package + "." + name for package in wildcard_packages]
        if name in JAVA_LANG_TYPES:
            return TypeResolution(
                file_path, name, None, 7, "external",
                ["java.lang." + name],
            )
        matching_packages = [
            _longest_existing_package(candidate, lookup.packages)
            for candidate in possible
        ]
        if any(package in lookup.analyzable_packages for package in matching_packages):
            return _unresolved(file_path, name, 4, possible)
        if any(package is not None for package in matching_packages):
            return TypeResolution(file_path, name, None, 4, "excluded", _unique(possible))
        return TypeResolution(file_path, name, None, None, "external", _unique(possible))

    if name in JAVA_LANG_TYPES:
        return TypeResolution(
            file_path, name, None, 7, "external", ["java.lang." + name]
        )
    return _unresolved(file_path, name, None, [])


def resolve_supertype(
    ref,
    file_packages: Dict[str, Optional[str]],
    types: Sequence[TypeInfo],
    imports_by_file: Dict[str, Sequence],
    lookup: Optional[ResolutionIndex] = None,
    prepared_imports: Optional[_FileImports] = None,
) -> TypeResolution:
    """Resolve a supertype reference, including qualified Java type names."""
    lookup = lookup or build_lookup(types, file_packages.values())
    if "." not in ref.name:
        return resolve_type(
            ref.path, ref.name, file_packages, types, imports_by_file,
            lookup, prepared_imports,
        )
    if ref.name in lookup.internal:
        return TypeResolution(
            ref.path, ref.name, ref.name, 5, "resolved", [ref.name]
        )
    outer_name, rest = ref.name.split(".", 1)
    outer = resolve_type(
        ref.path, outer_name, file_packages, types, imports_by_file,
        lookup, prepared_imports,
    )
    if outer.outcome == "resolved" and outer.resolved_fqn:
        candidate = outer.resolved_fqn + "." + rest
        if (candidate in lookup.internal and
                outer.resolved_fqn in lookup.owners_by_fqn.get(candidate, ())):
            return TypeResolution(
                ref.path, ref.name, candidate, 6, "resolved", [candidate]
            )
        return _classify_candidates(ref.path, ref.name, [candidate], lookup, 6)
    if outer.candidates:
        candidates = [candidate + "." + rest for candidate in outer.candidates]
        return _classify_candidates(ref.path, ref.name, candidates, lookup, 6)
    return _classify_candidates(ref.path, ref.name, [ref.name], lookup)


def resolve_import(record, types: Sequence[TypeInfo], packages: Iterable = (),
                   lookup: Optional[ResolutionIndex] = None) -> ImportResolution:
    """Classify an import target without guessing a missing internal type."""
    lookup = lookup or build_lookup(types, packages)
    target = record.name
    if record.is_wildcard and not record.is_static:
        if target in lookup.packages_with_types:
            return ImportResolution(target, target, "resolved", [target])
        if target in lookup.packages:
            if target in lookup.analyzable_packages:
                return ImportResolution(target, None, "unresolved", [target])
            return ImportResolution(target, None, "excluded", [target])
        return ImportResolution(target, None, "external", [target])

    internal_target = target
    if record.is_static and not record.is_wildcard:
        internal_target = target.rsplit(".", 1)[0] if "." in target else target
    if internal_target in lookup.internal:
        return ImportResolution(target, internal_target, "resolved", [internal_target])

    package = _longest_existing_package(target, lookup.packages)
    if package is None:
        return ImportResolution(target, None, "external", [target])
    if package not in lookup.analyzable_packages:
        return ImportResolution(target, None, "excluded", [target])
    return ImportResolution(target, None, "unresolved", [target])


def resolution_names(
    file_path: str,
    file_packages: Dict[str, Optional[str]],
    types: Sequence[TypeInfo],
    imports_by_file: Dict[str, Sequence],
    lookup: Optional[ResolutionIndex] = None,
    prepared_imports: Optional[_FileImports] = None,
) -> List[str]:
    lookup = lookup or build_lookup(types, file_packages.values())
    prepared_imports = prepared_imports or _prepare_file_imports(
        imports_by_file.get(file_path, ())
    )
    names = set(lookup.names_by_path.get(file_path, ()))
    names.update(lookup.names_by_package.get(file_packages.get(file_path), ()))
    for package in prepared_imports.wildcard_packages:
        names.update(lookup.wildcard_names_by_package.get(package, ()))
    names.update(prepared_imports.explicit)
    return sorted(names)


def build_resolutions(files, symbols, imports_by_file,
                      lookup: Optional[ResolutionIndex] = None):
    packages = {record.path: record.package for record in files}
    types = lookup.types if lookup is not None else type_infos(symbols)
    lookup = lookup or build_lookup(types, packages.values())
    prepared_imports = _prepare_imports(imports_by_file)
    rows = []
    for record in sorted(files, key=lambda item: item.path):
        if record.language != "java" or record.is_generated:
            continue
        file_imports = prepared_imports.get(record.path)
        for name in resolution_names(
                record.path, packages, types, imports_by_file, lookup, file_imports):
            rows.append(resolve_type(
                record.path, name, packages, types, imports_by_file, lookup, file_imports
            ))
    return rows
