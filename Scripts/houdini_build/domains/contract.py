"""Domain contracts for Houdini asset build modules."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainContract:
    key: str
    label: str
    depends_on: tuple[str, ...]
    final_nodes: tuple[str, ...]
    no_op: bool = False

    def display_name(self) -> str:
        suffix = " (no-op)" if self.no_op else ""
        return f"{self.label}{suffix}"
