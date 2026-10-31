"""Fail closed on unlisted source files and unresolved release decisions.

This deliberately uses only the Python standard library. It supplements manual
review; it cannot prove the absence of every possible secret or personal detail.
"""

import argparse
import json
import re
import struct
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRS = {".git", ".venv", ".uv-cache", ".pytest_cache", ".ruff_cache", "__pycache__", "dist", "htmlcov"}
IGNORED_FILES = {".coverage", ".DS_Store"}
SECRET_PATTERNS = (
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b",
    r"\bAKIA[A-Z0-9]{16}\b",
    r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b",
    r"/Users/[A-Za-z0-9_.-]+/",
    r"\b192\.168\.\d{1,3}\.\d{1,3}\b",
    r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
    r"https?://[^\s/]+:[^\s/@]+@",
)


def source_files(root=ROOT):
    paths = (root / "publication-files.txt").read_text().splitlines()
    if paths != sorted(set(paths)):
        raise ValueError("publication-files.txt must be sorted and unique")
    files = []
    for name in paths:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"Unsafe publication path: {name}")
        if any(part.startswith(".") for part in relative.parts) and relative.parts[0] not in {".github", ".gitignore"}:
            raise ValueError(f"Unexpected hidden publication path: {name}")
        path = root / relative
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise ValueError(f"Missing or symlinked source: {name}")
        files.append(path)
    actual = {
        p.relative_to(root).as_posix() for p in root.rglob("*")
        if p.is_file() and not IGNORED_DIRS.intersection(p.relative_to(root).parts)
        and p.name not in IGNORED_FILES
    }
    if actual != set(paths):
        raise ValueError(f"Unreviewed/missing source paths: {sorted(actual.symmetric_difference(paths))}")
    return files


def scan_content(name, data):
    errors = []
    if name.endswith(".png"):
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return [f"{name}: invalid PNG"]
        offset = 8
        while offset < len(data):
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            kind = data[offset + 4:offset + 8]
            if kind not in {b"IHDR", b"IDAT", b"IEND", b"PLTE", b"tRNS"}:
                errors.append(f"{name}: unreviewed PNG metadata chunk {kind!r}")
            offset += 12 + length
        return errors
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{name}: unexpected binary file"]
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, content):
            errors.append(f"{name}: possible secret or private installation data (value withheld)")
    if name.endswith(".json"):
        json.loads(content)
    return errors


def validate(root=ROOT, *, release=False):
    errors = []
    files = source_files(root)
    for path in files:
        errors.extend(scan_content(path.relative_to(root).as_posix(), path.read_bytes()))
    manifest = json.loads((root / "custom_components/itho_spider/manifest.json").read_text())
    hacs = json.loads((root / "hacs.json").read_text())
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    publication = json.loads((root / "publication.json").read_text())
    if manifest["domain"] != "itho_spider" or manifest["version"] != project["version"]:
        errors.append("Domain or version mismatch")
    if hacs["homeassistant"] != "2026.10.4":
        errors.append("Re-review the tested Home Assistant minimum")
    if manifest["requirements"] != project["dependencies"]:
        errors.append("Runtime dependency mismatch")
    if set(p.name for p in (root / "custom_components").iterdir() if p.is_dir() and p.name != "__pycache__") != {"itho_spider"}:
        errors.append("Exactly one itho_spider component is required")
    if (root / "custom_components/itho_spider/strings.json").read_bytes() != (root / "custom_components/itho_spider/translations/en.json").read_bytes():
        errors.append("English strings/translations mismatch")
    if release:
        for key in ("repository", "maintainers", "copyright_holder", "license_spdx", "private_vulnerability_reporting_enabled"):
            if not publication.get(key):
                errors.append(f"Release decision missing: {key}")
        repository = publication.get("repository") or ""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            errors.append("Choose the real GitHub owner/repository")
        url = f"https://github.com/{repository}"
        if manifest.get("documentation") != url or manifest.get("issue_tracker") != url + "/issues":
            errors.append("Manifest URLs must match the chosen public repository")
        owners = publication.get("maintainers") or []
        if not owners or manifest["codeowners"] != owners:
            errors.append("Manifest codeowners must match approved maintainers")
        if owners and not any(line.split() == ["*", *owners] for line in (root / ".github/CODEOWNERS").read_text().splitlines()):
            errors.append("CODEOWNERS must match approved maintainers")
        if not (root / "LICENSE").is_file():
            errors.append("Add the chosen project LICENSE and review third-party terms")
        elif (publication.get("copyright_holder") or "UNRESOLVED") not in (root / "LICENSE").read_text():
            errors.append("LICENSE must contain the approved copyright attribution")
        # No release can accidentally retain the preparation URL in runtime metadata.
        if "example.invalid" in json.dumps(manifest):
            errors.append("Placeholder URLs remain")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    try:
        errors = validate(release=args.release)
    except (ValueError, OSError, KeyError) as exc:
        errors = [str(exc)]
    if errors:
        raise SystemExit("\n".join(errors))
    print("Release readiness passed" if args.release else "Source preparation checks passed (publication decisions separate)")


if __name__ == "__main__":
    main()
