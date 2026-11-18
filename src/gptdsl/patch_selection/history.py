"""Bounded Git-log discovery and objective eligibility checks."""

from pathlib import PurePosixPath
import re

from ..patch_context.repository import Repository
from .models import SelectionLimits


def history_commits(repository: Repository, revision: str, limit: int) -> tuple[str, ...]:
    raw = repository.run("rev-list", "--topo-order", f"--max-count={limit}",
                         "--end-of-options", revision, "--")
    return tuple(raw.decode("ascii").splitlines())


def _metadata(repository: Repository, commit: str) -> tuple[list[str], str]:
    raw = repository.run("cat-file", "commit", commit).decode("utf-8", errors="replace")
    headers, _, message = raw.partition("\n\n")
    parents = [line[7:] for line in headers.splitlines() if line.startswith("parent ")]
    return parents, message.strip()


def _statistics(repository: Repository, parent: str, commit: str) -> dict:
    raw = repository.run("diff", "--numstat", "-z", "--no-relative", "--find-renames=50%",
                         "--no-ext-diff", "--no-textconv", parent, commit, "--")
    parts, index, added, deleted, binary = raw.split(b"\0"), 0, 0, 0, False
    while index < len(parts) and parts[index]:
        additions, deletions, path = parts[index].split(b"\t", 2)
        index += 3 if not path else 1  # Renames have two further NUL-delimited paths.
        if additions == b"-" or deletions == b"-":
            binary = True
        else:
            added += int(additions)
            deleted += int(deletions)
    return {"added_lines": added, "deleted_lines": deleted, "has_binary_changes": binary}


def inspect_commit(repository: Repository, commit: str, limits: SelectionLimits) -> dict:
    parents, message = _metadata(repository, commit)
    item = {"commit": commit, "subject": message.splitlines()[0] if message else "",
            "message": message, "status": "out_of_scope", "checks": {"eligible": False},
            "reasons": [], "signals": {
                "fixes_tag": bool(re.search(r"^Fixes:\s*\S", message, re.M | re.I)),
                "stable_tag": bool(re.search(r"^Cc:.*stable", message, re.M | re.I)),
                "repair_word": bool(re.search(r"\b(fix|fixes|repair|cleanup|leak|check)\b", message, re.I)),
            }}
    if len(parents) != 1:
        item["reasons"].append("root_commit" if not parents else "merge_commit")
        return item
    _commit, parent, _message = repository.resolve(commit)
    changes = repository.changes(parent, commit)
    stats = _statistics(repository, parent, commit)
    sources = [new or old for _status, old, new in changes
               if any(path and PurePosixPath(path).suffix in (".c", ".h") for path in (old, new))]
    item["checks"].update(stats, parent_commit=parent, files=len(changes), source_files=sources)
    if not sources:
        item["reasons"].append("no_c_or_header_changes")
    if len(changes) > limits.max_files:
        item["reasons"].append("file_limit")
    if stats["added_lines"] + stats["deleted_lines"] > limits.max_changed_lines:
        item["reasons"].append("changed_line_limit")
    if not item["reasons"]:
        item["checks"]["eligible"] = True
        item.update(status="needs_review", reasons=["semantic_review_required"])
    return item
