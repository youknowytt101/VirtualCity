"""Local verification entrypoint for maintainability guardrails."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from maintenance.boundary_guard import BoundaryRule, find_import_violations, format_violations


SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent


def boundary_rules() -> list[BoundaryRule]:
    return [
        BoundaryRule(
            name="acquisition",
            root=SCRIPTS / "acquisition",
            forbidden_prefixes=("cleaning", "houdini_build"),
        ),
        BoundaryRule(
            name="cleaning",
            root=SCRIPTS / "cleaning",
            forbidden_prefixes=("acquisition", "houdini_build", "orchestration"),
        ),
        BoundaryRule(
            name="houdini_build",
            root=SCRIPTS / "houdini_build",
            forbidden_prefixes=("acquisition", "cleaning", "set_area", "refine_data"),
        ),
    ]


def check_boundaries() -> int:
    violations = find_import_violations(boundary_rules())
    if violations:
        print("import-boundaries: FAIL")
        print(format_violations(violations))
        return 1
    print("import-boundaries: OK")
    return 0


def run_pytest() -> int:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=ROOT,
    ).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--boundaries-only",
        action="store_true",
        help="Only run the import-boundary guardrail.",
    )
    args = parser.parse_args(argv)

    boundary_status = check_boundaries()
    if args.boundaries_only or boundary_status:
        return boundary_status
    return run_pytest()


if __name__ == "__main__":
    raise SystemExit(main())
