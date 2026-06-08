"""Houdini build domain registry."""
from __future__ import annotations

from .assembly import CONTRACT as ASSEMBLY
from .buildings import CONTRACT as BUILDINGS
from .contract import DomainContract
from .nature import CONTRACT as NATURE
from .roads import CONTRACT as ROADS
from .terrain import CONTRACT as TERRAIN


BUILD_ORDER: tuple[DomainContract, ...] = (
    TERRAIN,
    BUILDINGS,
    ROADS,
    NATURE,
    ASSEMBLY,
)


def domain_summary() -> str:
    return " -> ".join(domain.display_name() for domain in BUILD_ORDER)
