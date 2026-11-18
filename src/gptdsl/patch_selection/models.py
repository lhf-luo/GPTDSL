"""Patch-corpus eligibility and review results, separate from vulnerability labels."""

from dataclasses import asdict, dataclass, field, fields
from typing import Literal, Protocol

from ..patch_context import ContextLimits, PatchContext


Decision = Literal["suitable", "needs_review", "out_of_scope"]
Category = Literal["error_handling", "resource_cleanup", "other", "unknown"]
CONTEXT_POLICY = "local_best_effort_v1"


@dataclass(frozen=True)
class SelectionLimits:
    max_commits: int = 100
    max_files: int = 8
    max_changed_lines: int = 300
    max_functions: int = 6
    context: ContextLimits = field(default_factory=ContextLimits)

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name != "context" and (type(value) is not int or value < 1):
                raise ValueError(f"{item.name} must be a positive integer")


@dataclass(frozen=True)
class Evidence:
    revision: str
    path: str
    start_line: int
    end_line: int
    quote: str


@dataclass(frozen=True)
class SemanticReview:
    decision: Decision
    category: Category
    reason: str
    evidence: tuple[Evidence, ...] = ()
    audit: dict = field(default_factory=dict)


class Reviewer(Protocol):
    """A reviewer returns an assessment; the selector validates its evidence."""

    def review(self, context: PatchContext) -> SemanticReview: ...


@dataclass(frozen=True)
class SelectionResult:
    repository: str
    revision: str | None
    limits: SelectionLimits
    entries: tuple[dict, ...]
    commit_file: str | None = None
    requests: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        result = asdict(self)
        result["schema_version"] = 1
        result["input_mode"] = "commit_file" if self.commit_file is not None else "history"
        result["counts"] = {name: sum(item["status"] == name for item in self.entries)
                            for name in ("suitable", "needs_review", "out_of_scope", "error")}
        result["counts"]["total"] = len(self.entries)
        if self.commit_file is not None:
            result["counts"]["duplicate"] = sum(item["status"] == "duplicate" for item in self.entries)
        return result

    @property
    def selected_commits(self) -> tuple[str, ...]:
        return tuple(item["commit"] for item in self.entries if item["status"] == "suitable")

    @property
    def candidate_commits(self) -> tuple[str, ...]:
        """Git-stat prefilter candidates, including later review exclusions/errors."""
        return tuple(item["commit"] for item in self.entries
                     if item["checks"].get("eligible") is True)
