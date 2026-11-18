"""Coordinate objective filtering and optional, grounded patch-quality review."""

from dataclasses import asdict, replace
import hashlib
from pathlib import Path

from ..commit_file import read_commit_file
from ..patch_context import PatchContextError, prepare_patch_context
from ..patch_context.repository import Repository
from .history import history_commits, inspect_commit
from .models import CONTEXT_POLICY, SelectionResult
from .review import ReviewError, validate_review


def _review_candidate(repository, item, limits, reviewer):
    item["checks"]["ai_review_attempted"] = False
    context = prepare_patch_context(repository.root, item["commit"], limits=limits.context,
                                    include_supplements=False)
    item["context"] = {
        "mode": CONTEXT_POLICY,
        "functions": [function.name for function in context.functions],
        "diagnostics": [asdict(diagnostic) for diagnostic in context.diagnostics],
        "markdown": context.markdown,
        "sha256": hashlib.sha256(context.markdown.encode("utf-8")).hexdigest(),
    }
    if len(context.functions) > limits.max_functions:
        item.update(status="out_of_scope", reasons=["function_limit"])
        return
    if reviewer is None:
        return
    item["checks"]["ai_review_attempted"] = True
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


def _execute(repository, result, reviewer, progress, previous):
    if previous is not None:
        expected = replace(result, entries=())
        if replace(previous, entries=()) != expected:
            raise ValueError("Checkpoint inputs or parameters changed; use the original inputs or a new output directory")
        if len(previous.entries) > len(result.requests):
            raise ValueError("Checkpoint has more results than input requests")
        for item, request in zip(previous.entries, result.requests):
            if any(item.get(key) != value for key, value in request.items()):
                raise ValueError("Checkpoint entries do not match their input requests")
        result = previous
    if progress:
        progress(result)
    seen_entries = list(result.entries)
    for request in result.requests[len(seen_entries):]:
        item = dict(request)
        if "status" not in item:
            item.update(_select_one(repository, item["commit"], result.limits, reviewer))
        seen_entries.append(item)
        result = replace(result, entries=tuple(seen_entries))
        if progress:
            progress(result)
    return result


def select(repo: str | Path, revision: str, limits, reviewer, progress=None, previous=None) -> SelectionResult:
    repository = Repository(Path(repo))
    commits = history_commits(repository, revision, limits.max_commits)
    result = SelectionResult(str(repository.root), revision, limits, (),
                             requests=tuple({"commit": commit} for commit in commits))
    return _execute(repository, result, reviewer, progress, previous)


def _resolve_request(repository, line, reference, seen):
    item = {"line": line, "input": reference, "commit": None}
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
            item.update(status="duplicate", duplicate_of=seen[commit], checks={"eligible": False})
            return item
        seen[commit] = line
    except (PatchContextError, OSError, ValueError) as exc:
        item.update(status="error", checks={"eligible": False},
                    error={"code": getattr(exc, "code", type(exc).__name__), "message": str(exc)})
    return item


def select_from_file(repo: str | Path, commit_file: Path, limits, reviewer,
                     progress=None, previous=None) -> SelectionResult:
    requests = read_commit_file(commit_file)
    repository = Repository(Path(repo))
    seen = {}
    resolved = tuple(_resolve_request(repository, line, reference, seen) for line, reference in requests)
    result = SelectionResult(str(repository.root), None, limits, (), str(commit_file.resolve()), resolved)
    return _execute(repository, result, reviewer, progress, previous)
