"""Validate a semantic assessment against source evidence shown to the reviewer."""

from .models import Evidence, SemanticReview


class ReviewError(Exception):
    """A provider failure or an assessment that cannot be grounded."""


def parse_review(payload: dict) -> SemanticReview:
    try:
        if not isinstance(payload, dict):
            raise ValueError("Review must be an object")
        decision, category, reason = payload["decision"], payload["category"], payload["reason"]
        if not isinstance(payload.get("evidence", []), list):
            raise ValueError("Evidence must be a list")
        evidence = tuple(Evidence(**entry) for entry in payload.get("evidence", []))
        result = SemanticReview(decision, category, reason, evidence)
        _validate_fields(result)
        return result
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewError(f"Invalid review response: {exc}") from exc


def _validate_fields(review: SemanticReview) -> None:
    if review.decision not in ("suitable", "needs_review", "out_of_scope"):
        raise ValueError("Unknown decision")
    if review.category not in ("error_handling", "resource_cleanup", "other", "unknown"):
        raise ValueError("Unknown category")
    if not isinstance(review.reason, str) or not review.reason.strip():
        raise ValueError("Review must explain its decision")
    for item in review.evidence:
        if not isinstance(item, Evidence) or not all(isinstance(value, str) and value.strip()
                for value in (item.revision, item.path, item.quote)):
            raise ValueError("Evidence needs a revision, path, and quote")
        if type(item.start_line) is not int or type(item.end_line) is not int:
            raise ValueError("Evidence line numbers must be integers")
        if item.start_line < 1 or item.end_line < item.start_line:
            raise ValueError("Invalid evidence line range")


def validate_review(review: SemanticReview, context) -> None:
    try:
        _validate_fields(review)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ReviewError(f"Invalid review response: {exc}") from exc
    if review.decision == "suitable":
        if review.category not in ("error_handling", "resource_cleanup") or not review.evidence:
            raise ReviewError("Suitable patches need a supported category and source evidence")
    snippets = [snippet for function in context.functions
                for snippet in (function.before, function.after) if snippet]
    snippets.extend(context.fallback + context.supplements)
    visible = context.markdown.replace("\r\n", "\n")
    for item in review.evidence:
        grounded = False
        quote = item.quote.replace("\r\n", "\n")
        for snippet in snippets:
            if (snippet.revision == item.revision and snippet.path == item.path
                    and snippet.start_line <= item.start_line <= item.end_line <= snippet.end_line):
                lines = snippet.text.splitlines()
                excerpt = "\n".join(lines[item.start_line - snippet.start_line:
                                          item.end_line - snippet.start_line + 1])
                grounded |= quote in excerpt and quote in visible
        if not grounded:
            raise ReviewError("Evidence is not grounded in visible historical source")
