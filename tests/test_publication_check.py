"""Publication checks keep private vocabulary out of public source and output."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_publication.py"
SPEC = importlib.util.spec_from_file_location("publication_check", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def git(root: Path, *arguments: str, input: bytes | None = None) -> bytes:
    return subprocess.run(["git", *arguments], cwd=root, input=input, capture_output=True, check=True).stdout


@pytest.mark.parametrize("value", [[], {}, [""], [" "], [True], [2]])
def test_term_list_rejects_malformed_values(tmp_path: Path, value):
    source = tmp_path / "private.json"
    source.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        MODULE.load_terms(source)


def test_case_and_line_breaks_do_not_hide_restricted_text(tmp_path: Path):
    git(tmp_path, "init", "-q")
    (tmp_path / "guide.md").write_text("EXAMPLE\ncompany\u2019s implementation")
    (tmp_path / "private.md").write_text("example company's implementation")
    git(tmp_path, "add", "guide.md")
    result = MODULE.check(tmp_path, [MODULE.normalize("example company's")])
    assert result["passed"] is False
    assert result["scanned"] == 1
    assert result["findings"] == [{"path": "guide.md", "term_indexes": [0]}]
    assert "EXAMPLE" not in json.dumps(result)


def test_staged_restricted_text_is_not_hidden_by_clean_worktree(tmp_path: Path):
    git(tmp_path, "init", "-q")
    path = tmp_path / "guide.md"
    path.write_text("restricted-example\n")
    git(tmp_path, "add", "guide.md")
    path.write_text("Neutral public contract\n")
    index_before = (tmp_path / ".git/index").read_bytes()
    inventory = git(tmp_path, "ls-files", "--stage", "-z")

    result = MODULE.check(tmp_path, ["restricted-example"])

    assert result["passed"] is False
    assert result["findings"] == [{"path": "guide.md", "term_indexes": [0]}]
    assert result["inspected_source"] == "git-index"
    assert result["index_snapshot_sha256"] == hashlib.sha256(inventory).hexdigest()
    assert (tmp_path / ".git/index").read_bytes() == index_before
    assert path.read_text() == "Neutral public contract\n"


def test_clean_staged_text_is_not_replaced_by_restricted_worktree(tmp_path: Path):
    git(tmp_path, "init", "-q")
    path = tmp_path / "guide.md"
    path.write_text("Neutral public contract\n")
    git(tmp_path, "add", "guide.md")
    path.write_text("restricted-example\n")
    index_before = (tmp_path / ".git/index").read_bytes()

    result = MODULE.check(tmp_path, ["restricted-example"])

    assert result["passed"] is True and result["scanned"] == 1
    assert result["findings"] == []
    assert (tmp_path / ".git/index").read_bytes() == index_before
    assert path.read_text() == "restricted-example\n"


def test_nested_root_inspects_staged_files_outside_subtree(tmp_path: Path):
    git(tmp_path, "init", "-q")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "guide.md").write_text("Neutral guide\n")
    protected = tmp_path / "outside.md"
    protected.write_text("restricted-example\n")
    git(tmp_path, "add", ".")
    protected.write_text("Neutral unstaged replacement\n")
    index_before = (tmp_path / ".git/index").read_bytes()
    inventory = git(tmp_path, "ls-files", "--stage", "-z")

    result = MODULE.check(nested, ["restricted-example"])

    assert result["passed"] is False
    assert result["scanned"] == 2
    assert result["findings"] == [{"path": "outside.md", "term_indexes": [0]}]
    assert result["index_snapshot_sha256"] == hashlib.sha256(inventory).hexdigest()
    assert (tmp_path / ".git/index").read_bytes() == index_before
    assert protected.read_text() == "Neutral unstaged replacement\n"
    assert (nested / "guide.md").read_text() == "Neutral guide\n"


@pytest.mark.parametrize("suffix", [" ", "\n"])
def test_repository_root_preserves_trailing_whitespace(tmp_path: Path, suffix: str):
    repository = tmp_path / f"repository{suffix}"
    repository.mkdir()
    git(repository, "init", "-q")
    path = repository / "guide.md"
    path.write_text("restricted-example\n")
    git(repository, "add", "guide.md")
    nested = repository / "nested"
    nested.mkdir()
    index_before = (repository / ".git/index").read_bytes()

    result = MODULE.check(nested, ["restricted-example"])

    assert result["passed"] is False and result["scanned"] == 1
    assert result["findings"] == [{"path": "guide.md", "term_indexes": [0]}]
    assert (repository / ".git/index").read_bytes() == index_before
    assert path.read_text() == "restricted-example\n"


@pytest.mark.parametrize("explicit_root", [True, False])
def test_nested_cli_inspects_full_index_and_preserves_files(tmp_path: Path, explicit_root: bool):
    git(tmp_path, "init", "-q")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "guide.md").write_text("Neutral guide\n")
    protected = tmp_path / "outside.md"
    protected.write_text("restricted-example\n")
    git(tmp_path, "add", ".")
    protected.write_text("Neutral unstaged replacement\n")
    private = tmp_path.parent / f"{tmp_path.name}-terms.json"
    private.write_text('["restricted-example"]')
    index_before = (tmp_path / ".git/index").read_bytes()
    inventory = git(tmp_path, "ls-files", "--stage", "-z")
    command = [sys.executable, str(SCRIPT), "--terms-file", str(private)]
    if explicit_root:
        command.extend(["--root", str(nested)])

    completed = subprocess.run(command, cwd=nested, capture_output=True, text=True)

    assert completed.returncode == 1 and completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["passed"] is False and result["scanned"] == 2
    assert result["findings"] == [{"path": "outside.md", "term_indexes": [0]}]
    assert result["index_snapshot_sha256"] == hashlib.sha256(inventory).hexdigest()
    assert "restricted-example" not in completed.stdout
    assert (tmp_path / ".git/index").read_bytes() == index_before
    assert protected.read_text() == "Neutral unstaged replacement\n"
    assert (nested / "guide.md").read_text() == "Neutral guide\n"


@pytest.mark.parametrize("repository", [b"", b"relative\n", b"\xff\n"])
def test_malformed_repository_root_fails_before_inventory(tmp_path: Path, monkeypatch, repository: bytes):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=repository)

    monkeypatch.setattr(MODULE.subprocess, "run", run)
    with pytest.raises(ValueError):
        MODULE.check(tmp_path, ["restricted-example"])
    assert calls == [["git", "rev-parse", "--show-toplevel"]]


@pytest.mark.parametrize("replacement", ["missing", "directory", "symlink"])
def test_index_regular_file_ignores_worktree_replacement(tmp_path: Path, replacement: str):
    git(tmp_path, "init", "-q")
    path = tmp_path / "guide.md"
    path.write_text("Neutral public contract\n")
    git(tmp_path, "add", "guide.md")
    path.unlink()
    if replacement == "directory":
        path.mkdir()
    elif replacement == "symlink":
        private = tmp_path / "private.txt"
        private.write_text("restricted-example\n")
        path.symlink_to(private)
    index_before = (tmp_path / ".git/index").read_bytes()

    result = MODULE.check(tmp_path, ["restricted-example"])

    assert result["passed"] is True and result["scanned"] == 1
    assert (tmp_path / ".git/index").read_bytes() == index_before
    if replacement == "symlink":
        assert path.is_symlink()
    elif replacement == "missing":
        assert not path.exists()
    else:
        assert path.is_dir()


def test_index_executable_mode_ignores_later_worktree_mode(tmp_path: Path):
    git(tmp_path, "init", "-q")
    path = tmp_path / "script.sh"
    path.write_text("Neutral executable\n")
    path.chmod(0o755)
    git(tmp_path, "add", "script.sh")
    assert git(tmp_path, "ls-files", "--stage").startswith(b"100755 ")
    path.chmod(0o644)
    index_before = (tmp_path / ".git/index").read_bytes()

    result = MODULE.check(tmp_path, ["restricted-example"])

    assert result["passed"] is True
    assert (tmp_path / ".git/index").read_bytes() == index_before
    assert path.stat().st_mode & 0o777 == 0o644


def test_staged_deletion_is_not_scanned_even_if_worktree_file_returns(tmp_path: Path):
    git(tmp_path, "init", "-q")
    path = tmp_path / "guide.md"
    path.write_text("restricted-example\n")
    git(tmp_path, "add", "guide.md")
    git(tmp_path, "-c", "user.name=Publication test", "-c", "user.email=publication@example.invalid",
        "commit", "-qm", "fixture")
    git(tmp_path, "rm", "guide.md")
    path.write_text("restricted-example\n")
    index_before = (tmp_path / ".git/index").read_bytes()

    result = MODULE.check(tmp_path, ["restricted-example"])

    assert result["passed"] is True and result["scanned"] == 0
    assert result["index_snapshot_sha256"] == hashlib.sha256(b"").hexdigest()
    assert (tmp_path / ".git/index").read_bytes() == index_before
    assert path.read_text() == "restricted-example\n"


def test_captured_index_blobs_survive_later_index_and_worktree_edits(tmp_path: Path, monkeypatch):
    git(tmp_path, "init", "-q")
    path = tmp_path / "guide.md"
    path.write_text("restricted-example\n")
    git(tmp_path, "add", "guide.md")
    inventory = git(tmp_path, "ls-files", "--stage", "-z")
    real_run = subprocess.run
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        result = real_run(command, **kwargs)
        if command == ["git", "ls-files", "--stage", "-z"]:
            path.write_text("Neutral new candidate\n")
            real_run(["git", "add", "guide.md"], cwd=tmp_path, check=True, capture_output=True)
        return result

    monkeypatch.setattr(MODULE.subprocess, "run", run)
    result = MODULE.check(tmp_path, ["restricted-example"])

    assert result["passed"] is False
    assert result["index_snapshot_sha256"] == hashlib.sha256(inventory).hexdigest()
    assert len(calls) == 3 and calls[2][1:4] == ["--no-replace-objects", "cat-file", "blob"]
    assert path.read_text() == "Neutral new candidate\n"


def test_git_replace_does_not_change_inspected_blob_identity(tmp_path: Path):
    git(tmp_path, "init", "-q")
    path = tmp_path / "guide.md"
    path.write_text("restricted-example\n")
    git(tmp_path, "add", "guide.md")
    original = git(tmp_path, "rev-parse", ":guide.md").strip().decode()
    replacement = git(tmp_path, "hash-object", "-w", "--stdin", input=b"Neutral replacement\n").strip().decode()
    git(tmp_path, "replace", original, replacement)

    assert git(tmp_path, "cat-file", "blob", original) == b"Neutral replacement\n"
    assert MODULE.check(tmp_path, ["restricted-example"])["passed"] is False


@pytest.mark.parametrize("suffix", [".gz", ".GZ"])
def test_gzip_text_is_inspected_without_modifying_it(tmp_path: Path, suffix: str):
    path = tmp_path / f"records.jsonl{suffix}"
    original = gzip.compress(b"restricted example text\n")
    path.write_bytes(original)
    assert MODULE.inspect_text(path.name, original) == "restricted example text\n"
    assert path.read_bytes() == original


def test_binary_media_is_explicitly_out_of_scope(tmp_path: Path):
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG\xff")
    assert MODULE.inspect_text(path.name, path.read_bytes()) is None


def test_undecodable_nonmedia_bytes_are_counted_and_limits_are_explicit(tmp_path: Path):
    git(tmp_path, "init", "-q")
    (tmp_path / "guide.txt").write_bytes(b"\xffrestricted-example\n")
    git(tmp_path, "add", "guide.txt")

    result = MODULE.check(tmp_path, ["restricted-example"])

    assert result["passed"] is True and result["scanned"] == 0
    assert result["skipped_binary"] == 1
    assert "Non-UTF-8 data and image/video pixels need separate review" in result["limits"]
    assert "Git/PR history is not erased" in result["limits"]


def test_index_symlink_is_rejected_even_when_worktree_is_regular(tmp_path: Path):
    git(tmp_path, "init", "-q")
    target = tmp_path / "private.txt"
    target.write_text("private")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    git(tmp_path, "add", "link.txt")
    link.unlink()
    link.write_text("Neutral replacement\n")
    with pytest.raises(ValueError, match="symlinks"):
        MODULE.check(tmp_path, ["private"])
    assert link.read_text() == "Neutral replacement\n"


@pytest.mark.parametrize("mode,stage", [("160000", "0"), ("100644", "1")])
def test_entire_index_is_validated_before_any_blob_read(tmp_path: Path, monkeypatch, mode: str, stage: str):
    git(tmp_path, "init", "-q")
    (tmp_path / "a-guide.md").write_text("Neutral guide\n")
    git(tmp_path, "add", "a-guide.md")
    object_id = git(tmp_path, "rev-parse", ":a-guide.md").strip().decode()
    git(tmp_path, "update-index", "--index-info", input=f"{mode} {object_id} {stage}\tz-invalid\n".encode())
    real_run = subprocess.run
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr(MODULE.subprocess, "run", run)
    with pytest.raises(ValueError, match="publication review"):
        MODULE.check(tmp_path, ["restricted-example"])
    assert calls == [["git", "rev-parse", "--show-toplevel"], ["git", "ls-files", "--stage", "-z"]]


@pytest.mark.parametrize("suffix", [".md", ".png"])
def test_restricted_tracked_filename_is_detected_without_printing_it(tmp_path: Path, suffix: str):
    git(tmp_path, "init", "-q")
    name = f"restricted-example-company{suffix}"
    if suffix == ".png":
        name = name.upper()
    (tmp_path / name).write_bytes(b"Neutral guide" if suffix == ".md" else b"\x89PNG\xff")
    git(tmp_path, "add", name)
    result = MODULE.check(tmp_path, ["restricted-example-company"])
    assert result["passed"] is False
    assert result["findings"] == [{"path": None, "term_indexes": [0], "tracked_file_index": 0,
                                    "path_term_indexes": [0], "content_term_indexes": []}]
    assert "restricted-example-company" not in json.dumps(result).casefold()
    assert result["scanned"] == (1 if suffix == ".md" else 0)
    assert result["skipped_binary"] == (0 if suffix == ".md" else 1)


@pytest.mark.parametrize("suffix", [".pdf", ".PDF"])
def test_pdf_text_and_links_are_inspected_case_insensitively(tmp_path: Path, suffix: str, monkeypatch):
    original = b"original PDF candidate bytes"
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        copy = Path(command[1] if command[0] == "pdftotext" else command[2])
        assert copy.read_bytes() == original
        return subprocess.CompletedProcess(command, 0, stdout=b"document text\n" if command[0] == "pdftotext"
                                           else b"https://example.invalid/\n")

    monkeypatch.setattr(MODULE.subprocess, "run", run)
    assert MODULE.inspect_text(f"guide{suffix}", original) == "document text\nhttps://example.invalid/\n"
    assert calls == [["pdftotext", calls[0][1], "-"], ["pdfinfo", "-url", calls[0][1]]]
    assert not Path(calls[0][1]).exists()


@pytest.mark.parametrize("suffix", [".gz", ".GZ"])
def test_gzip_uses_staged_bytes_when_worktree_changes(tmp_path: Path, suffix: str):
    git(tmp_path, "init", "-q")
    path = tmp_path / f"records.jsonl{suffix}"
    path.write_bytes(gzip.compress(b"restricted-example\n"))
    git(tmp_path, "add", path.name)
    path.write_bytes(b"invalid unstaged gzip")

    result = MODULE.check(tmp_path, ["restricted-example"])

    assert result["passed"] is False
    assert result["findings"] == [{"path": path.name, "term_indexes": [0]}]
    assert path.read_bytes() == b"invalid unstaged gzip"


@pytest.mark.parametrize("suffix", [".pdf", ".PDF"])
def test_pdf_tools_use_staged_bytes_when_worktree_changes(tmp_path: Path, suffix: str, monkeypatch):
    git(tmp_path, "init", "-q")
    path = tmp_path / f"guide{suffix}"
    original = b"original PDF candidate bytes"
    path.write_bytes(original)
    git(tmp_path, "add", path.name)
    path.write_bytes(b"different unstaged PDF")
    real_run = subprocess.run
    copies = []

    def run(command, **kwargs):
        if command[0] in {"pdftotext", "pdfinfo"}:
            copy = Path(command[1] if command[0] == "pdftotext" else command[2])
            assert copy.read_bytes() == original and copy != path
            copies.append(copy)
            output = b"Neutral document\n" if command[0] == "pdftotext" else b"https://restricted-example.invalid/\n"
            return subprocess.CompletedProcess(command, 0, stdout=output)
        return real_run(command, **kwargs)

    monkeypatch.setattr(MODULE.subprocess, "run", run)
    result = MODULE.check(tmp_path, ["restricted-example"])

    assert result["passed"] is False
    assert result["findings"] == [{"path": path.name, "term_indexes": [0]}]
    assert len(copies) == 2 and all(not copy.exists() for copy in copies)
    assert path.read_bytes() == b"different unstaged PDF"


def test_pdf_temporary_copy_is_removed_after_tool_failure(monkeypatch):
    copies = []

    def fail(command, **kwargs):
        copies.append(Path(command[1]))
        raise subprocess.CalledProcessError(1, command, stderr=b"restricted-example")

    monkeypatch.setattr(MODULE.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        MODULE.inspect_text("guide.pdf", b"original PDF candidate bytes")
    assert len(copies) == 1 and not copies[0].exists()


@pytest.mark.parametrize("error", [
    OSError("restricted-example"), ValueError("restricted-example"), EOFError("restricted-example"),
    zlib.error("restricted-example"),
    subprocess.CalledProcessError(1, ["restricted-example"], stderr=b"restricted-example"),
    subprocess.TimeoutExpired(["restricted-example"], 30),
])
def test_cli_inspection_errors_fail_closed_and_redact_details(tmp_path: Path, monkeypatch, capsys, error: Exception):
    terms = tmp_path / "terms.json"
    terms.write_text('["restricted-example"]')
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--terms-file", str(terms), "--root", str(tmp_path)])

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(MODULE, "check", fail)
    with pytest.raises(SystemExit) as stopped:
        MODULE.main()
    assert stopped.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "publication inspection failed; review private inputs and available document tools\n"


@pytest.mark.parametrize("terms", ['["restricted-example"]', "malformed restricted-example"])
@pytest.mark.parametrize("explicit_root", [True, False])
def test_real_cli_invalid_repository_or_terms_fail_closed(tmp_path: Path, terms: str, explicit_root: bool):
    private = tmp_path / "terms.json"
    private.write_text(terms)

    command = [sys.executable, str(SCRIPT), "--terms-file", str(private)]
    if explicit_root:
        command.extend(["--root", str(tmp_path)])
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 2 and result.stdout == ""
    assert result.stderr == "publication inspection failed; review private inputs and available document tools\n"
