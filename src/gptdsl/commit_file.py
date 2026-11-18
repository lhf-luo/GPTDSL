"""Shared UTF-8 commit-list format for selection and context preparation."""

from pathlib import Path


def read_commit_file(path: Path) -> list[tuple[int, str]]:
    requests = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        reference = line.partition("#")[0].strip()
        if reference:
            requests.append((line_number, reference))
    if not requests:
        raise ValueError("Commit file contains no commit references")
    return requests
