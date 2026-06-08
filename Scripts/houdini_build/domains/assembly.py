"""Final assembly domain contract."""
from __future__ import annotations

from .contract import DomainContract


CONTRACT = DomainContract(
    key="assembly",
    label="总装",
    depends_on=("terrain", "buildings", "roads", "nature"),
    final_nodes=("merge_all", "OUT_city"),
)
