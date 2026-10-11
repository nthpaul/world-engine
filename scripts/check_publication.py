"""Check tracked text and documents against an operator-owned private term list."""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
from pathlib import Path


def normalize(value: str) -> str:
    return " ".join(value.casefold().replace("\u2019", "'").split())


def load_terms(path: Path) -> list[str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not value or any(not isinstance(term, str) or not term.strip() for term in value):
        raise ValueError("private term list must be a nonempty JSON array of nonempty strings")
    return [normalize(term) for term in value]


def inspect_text(path: Path) -> str | None:
    if path.is_symlink():
        raise ValueError("tracked symlinks need separate publication review")
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        text = subprocess.run(["pdftotext", str(path), "-"], capture_output=True, check=True, timeout=30).stdout
        links = subprocess.run(["pdfinfo", "-url", str(path)], capture_output=True, check=True, timeout=30).stdout
        return (text + links).decode("utf-8")
    data = path.read_bytes()
    if suffix == ".gz":
        data = gzip.decompress(data)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def check(root: Path, terms: list[str]) -> dict:
    output = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    files = output.decode("utf-8").split("\0")
    scanned = 0
    skipped_binary = 0
    findings = []
    for file_index, name in enumerate(filter(None, files)):
        normalized_name = normalize(name)
        path_matches = [index for index, term in enumerate(terms) if term in normalized_name]
        text = inspect_text(root / name)
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
            "limits": "Current tracked files only. Binary images/video need separate review; Git/PR history is not erased."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terms-file", type=Path, required=True,
                        help="Private JSON array; keep the file outside the public repository")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        terms = load_terms(args.terms_file)
        result = check(args.root.resolve(), terms)
    except (OSError, ValueError, subprocess.SubprocessError):
        parser.exit(2, "publication inspection failed; review private inputs and available document tools\n")
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
