"""Patch corpus selection on synthetic histories; reviewers never call a model."""

from dataclasses import replace
import subprocess

import pytest

from gptdsl.patch_context import ContextLimits
from gptdsl.patch_selection import (
    Evidence, ReviewError, SelectionLimits, SemanticReview, select_patches,
)


@pytest.fixture
def repair(history):
    history.write("sample.c", "int value(void) { return 1; }\n")
    root = history.commit("base")
    history.write("sample.c", "int value(void) { return 2; }\n")
    commit = history.commit("Fix result handling\n\nFixes: 123456789abc (base)\nCc: stable@example.invalid")
    return root, commit


def grounded_review(context):
    source = context.functions[0].after
    evidence = Evidence(source.revision, source.path, source.start_line, source.end_line, source.text)
    return SemanticReview("suitable", "error_handling", "One local return-value change", (evidence,))


class FakeReviewer:
    def __init__(self, answer=grounded_review):
        self.answer = answer
        self.calls = []

    def review(self, context):
        self.calls.append(context.commit)
        return self.answer(context)


def test_offline_keywords_are_weak_signals_and_source_stays_unchanged(history, repair):
    root, commit = repair
    history.write("sample.c", "uncommitted local content\n")
    history.git("add", "sample.c")
    history.write("untracked.txt", "preserve me")
    snapshot = (history.git("rev-parse", "HEAD"), history.git("status", "--porcelain"),
                history.git("diff", "--cached"), (history.path / "sample.c").read_bytes())
    result = select_patches(history.path)
    assert result.to_dict() == select_patches(history.path).to_dict()
    assert result.selected_commits == ()
    assert result.candidate_commits == (commit,)
    candidate, excluded = result.entries
    assert candidate["status"] == "needs_review"
    assert candidate["signals"] == dict(fixes_tag=True, stable_tag=True, repair_word=True)
    assert "uncommitted" not in candidate["context"]["markdown"]
    assert excluded["commit"] == root and excluded["reasons"] == ["root_commit"]
    assert snapshot == (history.git("rev-parse", "HEAD"), history.git("status", "--porcelain"),
                        history.git("diff", "--cached"), (history.path / "sample.c").read_bytes())


def test_bounded_history_range_and_grounded_acceptance(history, repair):
    root, commit = repair
    history.write("notes.txt", "documentation only")
    docs = history.commit("fix a typo")
    reviewer = FakeReviewer()
    result = select_patches(history.path, f"{root}..HEAD", reviewer=reviewer)
    assert [item["commit"] for item in result.entries] == [docs, commit]
    assert result.entries[0]["reasons"] == ["no_c_or_header_changes"]
    assert result.selected_commits == (commit,)
    assert reviewer.calls == [commit]
    bounded = select_patches(history.path, limits=SelectionLimits(max_commits=1))
    assert len(bounded.entries) == 1 and bounded.entries[0]["commit"] == docs


@pytest.mark.parametrize("decision", ["needs_review", "out_of_scope"])
def test_reviewer_can_defer_or_exclude(history, repair, decision):
    reviewer = FakeReviewer(lambda _: SemanticReview(decision, "other", "Not a reusable local repair"))
    result = select_patches(history.path, limits=SelectionLimits(max_commits=1), reviewer=reviewer)
    assert result.entries[0]["status"] == decision
    assert not result.selected_commits


@pytest.mark.parametrize("mutation", [
    lambda r: replace(r, evidence=()),
    lambda r: replace(r, category="other"),
    lambda r: replace(r, evidence=(replace(r.evidence[0], revision="invented"),)),
    lambda r: replace(r, evidence=(replace(r.evidence[0], path="missing.c"),)),
    lambda r: replace(r, evidence=(replace(r.evidence[0], quote="fabricated code"),)),
    lambda r: replace(r, evidence=(replace(r.evidence[0], start_line=100, end_line=101),)),
    lambda r: replace(r, reason=""),
    lambda r: None,
])
def test_invalid_or_fabricated_review_never_enters_selected(history, repair, mutation):
    reviewer = FakeReviewer(lambda context: mutation(grounded_review(context)))
    result = select_patches(history.path, limits=SelectionLimits(max_commits=1), reviewer=reviewer)
    assert result.entries[0]["status"] == "error"
    assert result.entries[0]["error"]["code"] == "ReviewError"
    assert not result.selected_commits


def test_provider_failure_is_isolated(history, repair):
    history.write("sample.c", "int value(void) { return 3; }\n")
    newest = history.commit("another adjustment")

    def review(context):
        if context.commit == newest:
            raise ReviewError("Temporary provider failure")
        return grounded_review(context)

    result = select_patches(history.path, reviewer=FakeReviewer(review))
    assert result.entries[0]["status"] == "error"
    assert result.selected_commits == (repair[1],)


@pytest.mark.parametrize("limits,reason", [
    (SelectionLimits(max_files=1), "file_limit"),
    (SelectionLimits(max_changed_lines=1), "changed_line_limit"),
    (SelectionLimits(max_functions=1), "function_limit"),
])
def test_size_limits_block_review(history, repair, limits, reason):
    history.write("sample.c", "int value(void) { return 3; }\n")
    history.write("second.c", "int second(void) { return 0; }\n")
    history.commit("two functions")
    reviewer = FakeReviewer()
    result = select_patches(history.path, limits=replace(limits, max_commits=1), reviewer=reviewer)
    assert result.entries[0]["status"] == "out_of_scope"
    assert reason in result.entries[0]["reasons"]
    assert not reviewer.calls


@pytest.mark.parametrize("source,context_limits,diagnostic", [
    (b"abc\0new", ContextLimits(), "binary_source"),
    ("this is not C\n", ContextLimits(), "parse_error"),
    ("int f(void) { return 2; }\n", ContextLimits(source_bytes=4), "source_size_limit"),
    ("int f(void) { return 2; }\n", ContextLimits(markdown_chars=512), "presentation_truncated"),
])
def test_incomplete_source_stays_pending_without_ai(history, source, context_limits, diagnostic):
    history.write("sample.c", "int f(void) { return 1; }\n")
    history.commit("base")
    history.write("sample.c", source)
    history.commit("change")
    reviewer = FakeReviewer()
    result = select_patches(history.path, limits=SelectionLimits(max_commits=1, context=context_limits),
                            reviewer=reviewer)
    item = result.entries[0]
    assert item["status"] == "needs_review"
    assert item["reasons"] == ["context_requires_review"]
    assert diagnostic in {d["code"] for d in item["context"]["diagnostics"]}
    assert not reviewer.calls


def test_rename_statistics_and_merge_filter(history, repair):
    history.git("mv", "sample.c", "renamed.c")
    rename = history.commit("rename")
    result = select_patches(history.path, limits=SelectionLimits(max_commits=1))
    assert result.entries[0]["commit"] == rename
    assert result.entries[0]["checks"]["added_lines"] == 0
    assert result.entries[0]["checks"]["deleted_lines"] == 0
    history.git("checkout", "-b", "side", repair[1])
    history.write("side.txt", "side")
    history.commit("side")
    history.git("checkout", "main")
    history.git("merge", "--no-ff", "-m", "merge", "side")
    result = select_patches(history.path, limits=SelectionLimits(max_commits=1))
    assert result.entries[0]["reasons"] == ["merge_commit"]


def test_shallow_missing_parent_is_error_without_fetch(history, repair, tmp_path):
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "--depth=1", history.path.as_uri(), str(shallow)],
                   check=True, capture_output=True)
    result = select_patches(shallow)
    assert result.entries[0]["status"] == "error"
    assert result.entries[0]["error"]["code"] == "parent_unavailable"
    assert not result.selected_commits


@pytest.mark.parametrize("field,value", [("max_commits", 0), ("max_files", -1),
                                          ("max_changed_lines", True), ("max_functions", 1.5)])
def test_invalid_selection_limits(field, value):
    with pytest.raises(ValueError):
        SelectionLimits(**{field: value})
