import json

import pytest

from gptdsl.cli import main


def _repairs(history):
    history.write("sample.c", "int value(void) { return 1; }\n")
    history.commit("base")
    history.write("sample.c", "int value(void) { return 2; }\n")
    first = history.commit("first adjustment")
    history.write("sample.c", "int value(void) { return 3; }\n")
    return first, history.commit("second adjustment")


def _arguments(history, commit_file, output):
    return ["context", "--repo", str(history.path), "--commit-file", str(commit_file),
            "--out", str(output)]


def test_batch_bom_comments_duplicate_aliases_and_failure_isolation(history, tmp_path):
    first, second = _repairs(history)
    commit_file, output = tmp_path / "commits.txt", tmp_path / "contexts"
    commit_file.write_text(f"# repair commits\n\n{first}\n{first[:12]} # alias\n"
                           f"not-a-commit\n{second}\n{second}\n", encoding="utf-8-sig")
    history.write("sample.c", "keep dirty worktree\n")
    history.write("staged.txt", "keep staged file\n")
    history.git("add", "staged.txt")
    original = (history.git("status", "--porcelain"), (history.path / ".git/index").read_bytes(),
                history.git("rev-parse", "HEAD"))
    assert main(_arguments(history, commit_file, output)) == 2
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"] == {"total": 5, "succeeded": 2, "failed": 1, "duplicates": 2}
    assert [entry["line"] for entry in summary["entries"]] == [3, 4, 5, 6, 7]
    assert summary["entries"][1]["duplicate_of"] == 3
    assert summary["entries"][2]["error"]["code"] == "commit_unavailable"
    for commit in (first, second):
        result = json.loads((output / commit / "context.json").read_text(encoding="utf-8"))
        assert result["commit"] == commit
        assert (output / commit / "context.md").exists()
    assert (history.git("status", "--porcelain"), (history.path / ".git/index").read_bytes(),
            history.git("rev-parse", "HEAD")) == original
    assert (history.path / "sample.c").read_text(encoding="utf-8") == "keep dirty worktree\n"


def test_successful_batch_duplicate_is_not_a_failure_and_overwrite_is_explicit(history, tmp_path):
    first, _second = _repairs(history)
    commit_file, output = tmp_path / "commits.txt", tmp_path / "contexts"
    commit_file.write_text(f"{first}\n{first[:12]}\n", encoding="utf-8")
    arguments = _arguments(history, commit_file, output)
    assert main(arguments) == 0
    summary_bytes = (output / "summary.json").read_bytes()
    (output / first / "context.md").write_text("preserve me", encoding="utf-8")
    assert main(arguments) == 2
    assert (output / "summary.json").read_bytes() == summary_bytes
    assert (output / first / "context.md").read_text(encoding="utf-8") == "preserve me"
    assert main(arguments + ["--overwrite"]) == 0
    assert "preserve me" not in (output / first / "context.md").read_text(encoding="utf-8")
    assert json.loads(summary_bytes)["counts"] == {"total": 2, "succeeded": 1,
                                                   "failed": 0, "duplicates": 1}


@pytest.mark.parametrize("content", ["", "\n# comments only\n", "\ufeff\n"])
def test_empty_commit_file_does_not_create_outputs(tmp_path, content):
    commit_file, output = tmp_path / "empty.txt", tmp_path / "contexts"
    commit_file.write_text(content, encoding="utf-8")
    assert main(["context", "--repo", str(tmp_path), "--commit-file", str(commit_file),
                 "--out", str(output)]) == 2
    assert not output.exists()


def test_missing_file_does_not_create_outputs(tmp_path):
    output = tmp_path / "contexts"
    assert main(["context", "--repo", str(tmp_path), "--commit-file", str(tmp_path / "missing.txt"),
                 "--out", str(output)]) == 2
    assert not output.exists()


def test_all_failed_entries_still_have_summary_and_malformed_lines_are_reported(history, tmp_path):
    _repairs(history)
    commit_file, output = tmp_path / "commits.txt", tmp_path / "contexts"
    commit_file.write_text("missing-ref\ntwo references\n", encoding="utf-8")
    assert main(_arguments(history, commit_file, output)) == 2
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["failed"] == 2
    assert summary["entries"][1]["error"]["code"] == "context_error"
    assert sorted(path.name for path in output.iterdir()) == ["summary.json"]


def test_batch_rejects_output_inside_input_repository(history, tmp_path):
    first, _second = _repairs(history)
    commit_file = tmp_path / "commits.txt"
    commit_file.write_text(first, encoding="utf-8")
    output = history.path / "contexts"
    assert main(_arguments(history, commit_file, output)) == 2
    assert not output.exists()


def test_commit_and_commit_file_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["context", "--repo", str(tmp_path), "--commit", "HEAD",
              "--commit-file", "commits.txt", "--out", "unused"])
    assert error.value.code == 2
