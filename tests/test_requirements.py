"""Check install requirements against Home Assistant's own dependency pins."""

import json
from importlib.resources import files
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def test_serialx_requirement_matches_home_assistant_constraint() -> None:
    """An unconstrained development venv must not hide a live HA install conflict."""
    manifest_path = (
        Path(__file__).parents[1] / "custom_components" / "itho_spider" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())
    requirements = [Requirement(item) for item in manifest["requirements"]]
    declared = next(item for item in requirements if canonicalize_name(item.name) == "serialx")

    # Read the installed HA distribution, not the version of serialx in this venv.
    # HA applies this file when installing custom-component dependencies.
    constraint_file = files("homeassistant").joinpath("package_constraints.txt")
    constraints = [
        Requirement(line)
        for raw_line in constraint_file.read_text().splitlines()
        if (line := raw_line.split("#", 1)[0].strip())
    ]
    constraint = next(item for item in constraints if canonicalize_name(item.name) == "serialx")
    assert declared.specifier == constraint.specifier, (
        f"manifest.json requires {declared}, but Home Assistant package_constraints.txt "
        f"requires {constraint}; installing successfully in a development venv does not "
        "prove compatibility with Home Assistant's dependency installer"
    )
