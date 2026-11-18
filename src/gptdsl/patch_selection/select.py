"""Coordinate objective filtering and optional, grounded patch-quality review."""

from dataclasses import asdict
import hashlib
from pathlib import Path

from ..commit_file import read_commit_file
from ..patch_context import PatchContextError, prepare_patch_context
from ..patch_context.repository import Repository
from .history import history_commits, inspect_commit
from .models import SelectionResult
from .review import ReviewError, validate_review


_UNCERTAIN = {"source_size_limit", "source_unavailable", "binary_source", "parse_error",
              "function_pair_ambiguous", "presentation_truncated"}


def _review_candidate(repository, item, limits, reviewer):
    context = prepare_patch_context(repository.root, item["commit"], limits=limits.context)
    item["context"] = {
        "functions": [function.name for function in context.functions],
        "diagnostics": [asdict(diagnostic) for diagnostic in context.diagnostics],
        "markdown": context.markdown,
        "sha256": hashlib.sha256(context.markdown.encode("utf-8")).hexdigest(),
    }
    if len(context.functions) > limits.max_functions:
        item.update(status="out_of_scope", reasons=["function_limit"])
        return
    if any(diagnostic.code in _UNCERTAIN for diagnostic in context.diagnostics):
        item["reasons"] = ["context_requires_review"]
        return
    if reviewer is None:
        return
    review = reviewer.review(context)
    validate_review(review, context)
    item.update(status=review.decision, reasons=[review.reason], review=asdict(review))


def _select_one(repository, commit, limits, reviewer):
    item = {"commit": commit, "status": "error", "checks": {"eligible": False}}
    try:
        item = inspect_commit(repository, commit, limits)
        if item["checks"]["eligible"]:
            _review_candidate(repository, item, limits, reviewer)
    except (PatchContextError, ReviewError, OSError, ValueError) as exc:
        item.update(status="error", error={"code": getattr(exc, "code", type(exc).__name__),
                                           "message": str(exc)})
    return item


def select(repo: str | Path, revision: str, limits, reviewer) -> SelectionResult:
    repository = Repository(Path(repo))
    commits = history_commits(repository, revision, limits.max_commits)
    entries = tuple(_select_one(repository, commit, limits, reviewer) for commit in commits)
    return SelectionResult(str(repository.root), revision, limits, entries)


def _select_request(repository, line, reference, limits, reviewer, seen):
    item = {"line": line, "input": reference, "commit": None,
            "status": "error", "checks": {"eligible": False}}
    try:
        if any(character.isspace() for character in reference):
            raise ValueError("Each non-comment line must contain exactly one commit reference")
        try:
            commit = repository.run("rev-parse", "--verify", "--end-of-options",
                                    f"{reference}^{{commit}}").decode("ascii").strip()
        except PatchContextError as exc:
            raise PatchContextError("commit_unavailable", str(exc)) from exc
        item["commit"] = commit
        if commit in seen:
            item.update(status="duplicate", duplicate_of=seen[commit])
            return item
        seen[commit] = line
        item.update(_select_one(repository, commit, limits, reviewer))
    except (PatchContextError, OSError, ValueError) as exc:
        item.update(error={"code": getattr(exc, "code", type(exc).__name__), "message": str(exc)})
    return item


def select_from_file(repo: str | Path, commit_file: Path, limits, reviewer) -> SelectionResult:
    requests = read_commit_file(commit_file)
    repository = Repository(Path(repo))
    seen = {}
    entries = tuple(_select_request(repository, line, reference, limits, reviewer, seen)
                    for line, reference in requests)
    return SelectionResult(str(repository.root), None, limits, entries, str(commit_file.resolve()))
