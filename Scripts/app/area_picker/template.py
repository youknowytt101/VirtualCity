"""HTML template loader for the VirtualCity area picker."""
from pathlib import Path

FRONTEND_ROOT = Path(__file__).resolve().parent / "frontend"
HTML = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
