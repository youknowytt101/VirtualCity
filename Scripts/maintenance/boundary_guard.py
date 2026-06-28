"""AST-based import boundary checks for the physical pipeline modules."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BoundaryRule:
    """A module root and the import prefixes it must not depend on."""

    name: str
    root: Path
    forbidden_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class ImportViolation:
    """One forbidden import found in a source file."""

    rule: str
    file: Path
    line: int
    imported: str


def _iter_python_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix == ".py" else []
    return sorted(
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _imports_from_tree(tree: ast.AST) -> list[tuple[int, str]]:
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.append((node.lineno, node.module))
    return sorted(imports, key=lambda item: item[0])


def _is_forbidden(imported: str, prefixes: tuple[str, ...]) -> bool:
    return any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in prefixes)


def find_import_violations(rules: list[BoundaryRule]) -> list[ImportViolation]:
    """Return forbidden imports for the configured module boundaries."""
    violations: list[ImportViolation] = []
    for rule in rules:
        for path in _iter_python_files(rule.root):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for line, imported in _imports_from_tree(tree):
                if _is_forbidden(imported, rule.forbidden_prefixes):
                    violations.append(ImportViolation(rule.name, path, line, imported))
    return violations


def format_violations(violations: list[ImportViolation]) -> str:
    """Format violations as stable, actionable file-line messages."""
    return "\n".join(
        f"{violation.file.as_posix()}:{violation.line} imports {violation.imported} "
        f"(forbidden in {violation.rule})"
        for violation in violations
    )

