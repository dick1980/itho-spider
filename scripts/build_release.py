"""Build deterministic local archives from the reviewed file allowlist; never upload."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from check_publication import ROOT, scan_content, source_files, validate


def write_zip(destination, paths, root):
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(paths):
            info = zipfile.ZipInfo(path.relative_to(root).as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            data = path.read_bytes()
            if errors := scan_content(info.filename, data):
                raise ValueError("\n".join(errors))
            archive.writestr(info, data, compresslevel=9)


def build(output, *, prepared=False, root=ROOT):
    errors = validate(root, release=not prepared)
    if errors:
        raise ValueError("\n".join(errors))
    files = source_files(root)
    version = json.loads((root / "custom_components/itho_spider/manifest.json").read_text())["version"]
    suffix = "-prepared" if prepared else ""
    output.mkdir(parents=True, exist_ok=True)
    name = f"itho-spider-{version}{suffix}"
    component = [p for p in files if p.relative_to(root).parts[0] == "custom_components"]
    destinations = (output / f"{name}.zip", output / f"{name}-source.zip")
    if any(p.exists() for p in (*destinations, output / "SHA256SUMS", output / "build.json")):
        raise ValueError("Use an empty output directory; existing review artifacts are not overwritten")
    write_zip(destinations[0], component, root)
    write_zip(destinations[1], files, root)
    sums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in destinations}
    (output / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in sorted(sums.items())))
    report = {
        "version": version, "prepared_only": prepared, "published": False,
        "component_files": len(component), "source_files": len(files), "archives": sums,
        "sha256": {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    }
    (output / "build.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepared", action="store_true", help="Permit explicitly named LOCAL preparation artifacts")
    args = parser.parse_args()
    report = build(args.output, prepared=args.prepared)
    print(f"Built {report['component_files']} component files / {report['source_files']} source files; no upload")


if __name__ == "__main__":
    main()
