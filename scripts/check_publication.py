"""Check a Git index snapshot against an operator-owned private term list."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import tempfile
import zlib
from pathlib import Path


def normalize(value: str) -> str:
    return " ".join(value.casefold().replace("\u2019", "'").split())


def load_terms(path: Path) -> list[str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not value or any(not isinstance(term, str) or not term.strip() for term in value):
        raise ValueError("private term list must be a nonempty JSON array of nonempty strings")
    return [normalize(term) for term in value]


def inspect_text(name: str, data: bytes) -> str | None:
    suffix = Path(name).suffix.casefold()
    if suffix == ".pdf":
        with tempfile.TemporaryDirectory(prefix="world-engine-publication-") as folder:
            path = Path(folder) / "document.pdf"
            path.write_bytes(data)
            text = subprocess.run(["pdftotext", str(path), "-"], capture_output=True, check=True, timeout=30).stdout
            links = subprocess.run(["pdfinfo", "-url", str(path)], capture_output=True, check=True, timeout=30).stdout
        return (text + links).decode("utf-8")
    if suffix == ".gz":
        data = gzip.decompress(data)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def check(root: Path, terms: list[str]) -> dict:
    repository = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root,
                                capture_output=True, check=True, timeout=30).stdout
    root = Path(repository.decode("utf-8").removesuffix("\n"))
    if not root.is_absolute():
        raise ValueError("invalid Git repository root")
    output = subprocess.run(["git", "ls-files", "--stage", "-z"], cwd=root,
                            capture_output=True, check=True, timeout=30).stdout
    records = output.split(b"\0")
    if records[-1]:
        raise ValueError("invalid Git index inventory")
    files = []
    # Validate the whole captured inventory before reading its immutable blobs.
    for record in records[:-1]:
        metadata, name = record.split(b"\t", 1)
        mode, object_id, stage = metadata.split()
        if stage != b"0":
            raise ValueError("unmerged index entries need separate publication review")
        if mode not in {b"100644", b"100755"}:
            raise ValueError("index symlinks, gitlinks and other modes need separate publication review")
        if not name or len(object_id) not in {40, 64} or any(char not in b"0123456789abcdef" for char in object_id):
            raise ValueError("invalid Git index entry")
        files.append((name.decode("utf-8"), object_id.decode("ascii")))
    scanned = 0
    skipped_binary = 0
    findings = []
    for file_index, (name, object_id) in enumerate(files):
        normalized_name = normalize(name)
        path_matches = [index for index, term in enumerate(terms) if term in normalized_name]
        data = subprocess.run(["git", "--no-replace-objects", "cat-file", "blob", object_id], cwd=root,
                              capture_output=True, check=True, timeout=30).stdout
        text = inspect_text(name, data)
        if text is None:
            skipped_binary += 1
            content_matches = []
        else:
            scanned += 1
            normalized = normalize(text)
            content_matches = [index for index, term in enumerate(terms) if term in normalized]
        matches = sorted(set(path_matches + content_matches))
        if matches:
            finding = {"path": None if path_matches else name, "term_indexes": matches}
            if path_matches:
                finding.update({"tracked_file_index": file_index, "path_term_indexes": path_matches,
                                "content_term_indexes": content_matches})
            findings.append(finding)
    return {"passed": not findings, "scanned": scanned, "skipped_binary": skipped_binary,
            "findings": findings,
            "inspected_source": "git-index", "index_snapshot_sha256": hashlib.sha256(output).hexdigest(),
            "limits": "Captured Git index only. Non-UTF-8 data and image/video pixels need separate review; "
                      "Git/PR history is not erased."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terms-file", type=Path, required=True,
                        help="Private JSON array; keep the file outside the public repository")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        terms = load_terms(args.terms_file)
        result = check(args.root.resolve(), terms)
    except (OSError, ValueError, EOFError, zlib.error, subprocess.SubprocessError):
        parser.exit(2, "publication inspection failed; review private inputs and available document tools\n")
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
