"""Test actual package contents and deterministic builds without publishing."""

import importlib.util
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("spider_release", ROOT / "scripts/build_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_prepared_archives_are_reproducible_and_match_reviewed_source(tmp_path):
    first = release.build(tmp_path / "one", prepared=True)
    second = release.build(tmp_path / "two", prepared=True)
    assert first == second
    files = release.source_files(ROOT)
    for name in first["archives"]:
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()
        with zipfile.ZipFile(tmp_path / "one" / name) as archive:
            expected = files if name.endswith("-source.zip") else [p for p in files if p.relative_to(ROOT).parts[0] == "custom_components"]
            assert set(archive.namelist()) == {p.relative_to(ROOT).as_posix() for p in expected}
            assert not archive.comment
            # Every install artifact must retain license and third-party notices.
            assert archive.read("custom_components/itho_spider/LICENSE") == (ROOT / "LICENSE").read_bytes()
            assert (ROOT / "docs/third-party/ramses_rf-LICENSE.txt").read_bytes() in archive.read("custom_components/itho_spider/THIRD_PARTY_NOTICES.txt")
            for record in archive.infolist():
                assert not record.extra and not record.comment
                assert record.date_time == (2020, 1, 1, 0, 0, 0)
                assert archive.read(record) == (ROOT / record.filename).read_bytes()
                assert not release.scan_content(record.filename, archive.read(record))
    manifest = json.loads((ROOT / "custom_components/itho_spider/manifest.json").read_text())
    assert first["version"] == manifest["version"]
    assert first["published"] is False


def test_missing_release_decisions_block_normal_build(tmp_path):
    # Exercise the real release gate, independent of eventual approved metadata.
    source = tmp_path / "source"
    for path in release.source_files(ROOT):
        dest = source / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    metadata = json.loads((source / "publication.json").read_text())
    metadata["repository"] = None
    (source / "publication.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="Release decision missing: repository"):
        release.build(tmp_path / "release", root=source)
    assert not (tmp_path / "release").exists()


def test_unlisted_files_and_symlinks_are_rejected(tmp_path):
    (tmp_path / "publication-files.txt").write_text("publication-files.txt\n")
    (tmp_path / "capture.log").write_text("private capture")
    with pytest.raises(ValueError, match="Unreviewed"):
        release.source_files(tmp_path)
    (tmp_path / "capture.log").unlink()
    (tmp_path / "publication-files.txt").write_text("leak.py\npublication-files.txt\n")
    (tmp_path / "leak.py").symlink_to(ROOT / "README.md")
    with pytest.raises(ValueError, match="symlinked"):
        release.source_files(tmp_path)
