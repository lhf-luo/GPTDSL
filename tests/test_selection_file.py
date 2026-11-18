"""Explicit commit lists select exact commits, independent of history scan limits."""

import json

import pytest

from gptdsl.cli import main
from gptdsl.patch_selection import ReviewError, SelectionLimits, SemanticReview, select_patches


@pytest.fixture
def revisions(history):
    history.write("sample.c", "int value(void) { return 0; }\n")
    root = history.commit("base")
    history.write("sample.c", "int value(void) { return 1; }\n")
    first = history.commit("first change")
    history.write("sample.c", "int value(void) { return 2; }\n")
    second = history.commit("second change")
    return root, first, second


def test_file_selects_only_listed_commit_without_history_expansion(history, revisions, tmp_path):
    root, first, second = revisions
    path = tmp_path / "commits.txt"
    path.write_text(first + "\n", encoding="utf-8")
    result = select_patches(history.path, commit_file=path)
    assert [item["commit"] for item in result.entries] == [first]
    assert result.revision is None
    assert result.commit_file == str(path.resolve())
    assert result.to_dict()["input_mode"] == "commit_file"
    assert root not in result.candidate_commits and second not in result.candidate_commits
    assert result.selected_commits == ()


def test_bom_comments_aliases_failures_and_file_order(history, revisions, tmp_path):
    root, first, second = revisions
    path = tmp_path / "commits.txt"
    path.write_text(f"# selected commits\n\n{second}\n{first} # older\n{first[:12]}\n"
                    f"missing-ref\ntwo references\n{root}\nHEAD\n--all\n", encoding="utf-8-sig")
    before = (history.git("rev-parse", "HEAD"), history.git("status", "--porcelain"))
    result = select_patches(history.path, commit_file=path, limits=SelectionLimits(max_commits=1))
    assert [item["status"] for item in result.entries] == [
        "needs_review", "needs_review", "duplicate", "error", "error", "out_of_scope", "duplicate", "error"]
    assert [item["line"] for item in result.entries] == list(range(3, 11))
    assert result.entries[2]["duplicate_of"] == 4
    assert result.entries[3]["error"]["code"] == "commit_unavailable"
    assert result.entries[4]["error"]["code"] == "ValueError"
    assert result.entries[5]["reasons"] == ["root_commit"]
    assert result.entries[6]["duplicate_of"] == 3
    assert result.candidate_commits == (second, first)
    counts = result.to_dict()["counts"]
    assert counts == dict(total=8, suitable=0, needs_review=2, out_of_scope=1, duplicate=2, error=3)
    assert before == (history.git("rev-parse", "HEAD"), history.git("status", "--porcelain"))


def test_reviewer_failures_are_not_retried_for_duplicate_aliases(history, revisions, tmp_path):
    _root, first, second = revisions
    path = tmp_path / "commits.txt"
    path.write_text(f"{first}\n{first[:12]}\n{second}\n", encoding="utf-8")

    class Reviewer:
        calls = []

        def review(self, context):
            self.calls.append(context.commit)
            if context.commit == first:
                raise ReviewError("mock review failure")
            return SemanticReview("out_of_scope", "other", "Synthetic refactoring")

    reviewer = Reviewer()
    result = select_patches(history.path, commit_file=path, reviewer=reviewer)
    assert [item["status"] for item in result.entries] == ["error", "duplicate", "out_of_scope"]
    assert reviewer.calls == [first, second]


def test_cli_file_input_and_failure_report(history, revisions, tmp_path):
    _root, first, _second = revisions
    path, output = tmp_path / "commits.txt", tmp_path / "selection"
    path.write_text(f"missing-ref\n{first}\n{first}\n", encoding="utf-8")
    args = ["select", "--repo", str(history.path), "--commit-file", str(path), "--out", str(output)]
    assert main(args) == 2
    report = json.loads((output / "selection.json").read_text(encoding="utf-8"))
    assert report["revision"] is None and report["commit_file"] == str(path.resolve())
    assert report["counts"]["error"] == report["counts"]["duplicate"] == 1
    assert (output / "candidates.txt").read_text(encoding="utf-8") == first + "\n"
    assert (output / "commits.txt").read_text(encoding="utf-8") == ""
    before = (output / "selection.json").read_bytes()
    assert main(args) == 2
    assert (output / "selection.json").read_bytes() == before


def test_cli_file_ai_uses_deepseek_configuration(history, revisions, tmp_path, monkeypatch):
    _root, first, _second = revisions
    path, output = tmp_path / "commits.txt", tmp_path / "selection"
    path.write_text(first, encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("GPTDSL_REVIEW_MODEL", raising=False)

    class Reviewer:
        def __init__(self, config):
            assert config.model == "deepseek-flash" and config.api_key == "test-key"

        def review(self, _context):
            return SemanticReview("needs_review", "unknown", "Human review requested")

    monkeypatch.setattr("gptdsl.patch_selection.command.ChatCompletionsReviewer", Reviewer)
    assert main(["select", "--repo", str(history.path), "--commit-file", str(path),
                 "--ai", "--out", str(output)]) == 0
    report = json.loads((output / "selection.json").read_text(encoding="utf-8"))
    assert report["review_mode"] == "ai" and report["counts"]["needs_review"] == 1


@pytest.mark.parametrize("content", [None, "", "# comments only\n", "\ufeff\n"])
def test_missing_or_empty_file_does_not_publish(history, revisions, tmp_path, content):
    path, output = tmp_path / "commits.txt", tmp_path / "selection"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert main(["select", "--repo", str(history.path), "--commit-file", str(path),
                 "--out", str(output)]) == 2
    assert not output.exists()


def test_file_cannot_be_combined_with_history_options(history, revisions, tmp_path):
    path = tmp_path / "commits.txt"
    path.write_text(revisions[1], encoding="utf-8")
    output = tmp_path / "selection"
    args = ["select", "--repo", str(history.path), "--commit-file", str(path), "--out", str(output)]
    assert main(args + ["--max-commits", "100"]) == 2
    with pytest.raises(SystemExit) as error:
        main(args + ["--revision", "HEAD"])
    assert error.value.code == 2
    with pytest.raises(ValueError, match="mutually exclusive"):
        select_patches(history.path, "HEAD", commit_file=path)
    assert not output.exists()
