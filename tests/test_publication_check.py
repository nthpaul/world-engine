"""Publication checks keep private vocabulary out of public source and output."""

from __future__ import annotations

import gzip
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_publication.py"
SPEC = importlib.util.spec_from_file_location("publication_check", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize("value", [[], {}, [""], [" "], [True], [2]])
def test_term_list_rejects_malformed_values(tmp_path: Path, value):
    source = tmp_path / "private.json"
    source.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        MODULE.load_terms(source)


def test_case_and_line_breaks_do_not_hide_restricted_text(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "guide.md").write_text("EXAMPLE\ncompany\u2019s implementation")
    (tmp_path / "private.md").write_text("example company's implementation")
    subprocess.run(["git", "add", "guide.md"], cwd=tmp_path, check=True)
    result = MODULE.check(tmp_path, [MODULE.normalize("example company's")])
    assert result["passed"] is False
    assert result["scanned"] == 1
    assert result["findings"] == [{"path": "guide.md", "term_indexes": [0]}]
    assert "EXAMPLE" not in json.dumps(result)


@pytest.mark.parametrize("suffix", [".gz", ".GZ"])
def test_gzip_text_is_inspected_without_modifying_it(tmp_path: Path, suffix: str):
    path = tmp_path / f"records.jsonl{suffix}"
    original = gzip.compress(b"restricted example text\n")
    path.write_bytes(original)
    assert MODULE.inspect_text(path) == "restricted example text\n"
    assert path.read_bytes() == original


def test_binary_media_is_explicitly_out_of_scope(tmp_path: Path):
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG\xff")
    assert MODULE.inspect_text(path) is None


def test_symlink_is_not_followed(tmp_path: Path):
    target = tmp_path / "private.txt"
    target.write_text("private")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlinks"):
        MODULE.inspect_text(link)


@pytest.mark.parametrize("suffix", [".md", ".png"])
def test_restricted_tracked_filename_is_detected_without_printing_it(tmp_path: Path, suffix: str):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    name = f"restricted-example-company{suffix}"
    if suffix == ".png":
        name = name.upper()
    (tmp_path / name).write_bytes(b"Neutral guide" if suffix == ".md" else b"\x89PNG\xff")
    subprocess.run(["git", "add", name], cwd=tmp_path, check=True)
    result = MODULE.check(tmp_path, ["restricted-example-company"])
    assert result["passed"] is False
    assert result["findings"] == [{"path": None, "term_indexes": [0], "tracked_file_index": 0,
                                    "path_term_indexes": [0], "content_term_indexes": []}]
    assert "restricted-example-company" not in json.dumps(result).casefold()
    assert result["scanned"] == (1 if suffix == ".md" else 0)
    assert result["skipped_binary"] == (0 if suffix == ".md" else 1)


@pytest.mark.parametrize("suffix", [".pdf", ".PDF"])
def test_pdf_text_and_links_are_inspected_case_insensitively(tmp_path: Path, suffix: str, monkeypatch):
    path = tmp_path / f"guide{suffix}"
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"document text\n" if command[0] == "pdftotext"
                                           else b"https://example.invalid/\n")

    monkeypatch.setattr(MODULE.subprocess, "run", run)
    assert MODULE.inspect_text(path) == "document text\nhttps://example.invalid/\n"
    assert calls == [["pdftotext", str(path), "-"], ["pdfinfo", "-url", str(path)]]
