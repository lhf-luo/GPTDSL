"""Read-only repair-commit context preparation."""

from pathlib import Path

from .models import ContextLimits, PatchContext, PatchContextError


def prepare_patch_context(repo: str | Path, commit: str, *, limits: ContextLimits | None = None) -> PatchContext:
    """Prepare historical C source context without changing the input repository."""
    from .prepare import prepare

    return prepare(repo, commit, limits or ContextLimits())


__all__ = ["ContextLimits", "PatchContext", "PatchContextError", "prepare_patch_context"]
