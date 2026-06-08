"""Nature domain placeholder contract."""
from __future__ import annotations

from .contract import DomainContract


CONTRACT = DomainContract(
    key="nature",
    label="自然",
    depends_on=("terrain", "buildings", "roads"),
    final_nodes=(),
    no_op=True,
)
