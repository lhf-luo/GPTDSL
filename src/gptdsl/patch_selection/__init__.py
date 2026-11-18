"""Curate coherent, locally reviewable repair patches from Git history."""

from pathlib import Path
from typing import Callable

from .models import Evidence, Reviewer, SelectionLimits, SelectionResult, SemanticReview
from .review import ReviewError


def select_patches(repo: str | Path, revision: str | None = None, *,
                   commit_file: str | Path | None = None, limits: SelectionLimits | None = None,
                   reviewer: Reviewer | None = None,
                   progress: Callable[[SelectionResult], None] | None = None,
                   previous: SelectionResult | None = None) -> SelectionResult:
    """Select bounded history (default HEAD), or every listed commit without expanding history."""
    from .select import select, select_from_file

    if commit_file is not None:
        if revision is not None:
            raise ValueError("revision and commit_file are mutually exclusive")
        return select_from_file(repo, Path(commit_file), limits or SelectionLimits(), reviewer, progress, previous)
    return select(repo, "HEAD" if revision is None else revision, limits or SelectionLimits(), reviewer, progress, previous)


__all__ = ["Evidence", "Reviewer", "ReviewError", "SelectionLimits", "SelectionResult",
           "SemanticReview", "select_patches"]
