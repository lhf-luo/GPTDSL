"""Selection artifacts and compatibility with existing batch context export."""

import json

import pytest

from gptdsl.cli import main
from gptdsl.patch_selection import Evidence, SemanticReview


@pytest.fixture
def selection_args(history, tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("GPTDSL_REVIEW_MODEL", raising=False)
    monkeypatch.delenv("GPTDSL_REVIEW_BASE_URL", raising=False)
    history.write("sample.c", "int value(void) { return 1; }\n")
    history.commit("base")
    history.write("sample.c", "int value(void) { return 2; }\n")
    commit = history.commit("adjust")
    output = tmp_path / "selection"
    args = ["select", "--repo", str(history.path), "--out", str(output)]
    return args, output, commit


def test_offline_export_and_no_clobber(selection_args, monkeypatch):
    args, output, commit = selection_args
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def forbidden(*_args, **_kwargs):
        pytest.fail("offline selection must not initialize a provider")

    monkeypatch.setattr("gptdsl.patch_selection.command.ChatCompletionsReviewer", forbidden)
    assert main(args) == 0
    assert (output / "commits.txt").read_text(encoding="utf-8") == ""
    assert (output / "candidates.txt").read_text(encoding="utf-8") == commit + "\n"
    report = json.loads((output / "selection.json").read_text(encoding="utf-8"))
    assert report["review_mode"] == "offline"
    assert report["counts"] == dict(suitable=0, needs_review=1, out_of_scope=1, error=0, total=2)
    assert report["schema_version"] == 1
    before = (output / "selection.json").read_bytes()
    monkeypatch.setattr("gptdsl.patch_selection.command.select_patches", forbidden)
    assert main(args) == 2
    assert (output / "selection.json").read_bytes() == before


def test_ai_accepted_commits_feed_existing_batch(selection_args, history, tmp_path, monkeypatch):
    args, output, commit = selection_args

    class Reviewer:
        def __init__(self, config):
            assert config.model == "deepseek-flash"
            assert config.base_url == "https://api.deepseek.com/v1"
            assert config.api_key == "test-key"

        def review(self, context):
            source = context.functions[0].after
            evidence = Evidence(source.revision, source.path, source.start_line, source.end_line, source.text)
            return SemanticReview("suitable", "error_handling", "Single local change", (evidence,))

    monkeypatch.setattr("gptdsl.patch_selection.command.ChatCompletionsReviewer", Reviewer)
    assert main(args + ["--ai"]) == 0
    assert (output / "commits.txt").read_text(encoding="utf-8") == commit + "\n"
    report = json.loads((output / "selection.json").read_text(encoding="utf-8"))
    assert report["review_mode"] == "ai" and report["counts"]["suitable"] == 1
    batch_output = tmp_path / "context"
    assert main(["context", "--repo", str(history.path), "--commit-file", str(output / "commits.txt"),
                 "--out", str(batch_output)]) == 0
    assert (batch_output / commit / "context.json").is_file()
    assert main(args + ["--overwrite"]) == 0
    assert not (output / "commits.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("extra", [
    ["--max-commits", "0"], ["--max-context-chars", "511"],
    ["--model", "test"], ["--base-url", "http://localhost"],
    ["--revision", "nonexistent"], ["--revision=--all"], ["--ai"],
])
def test_bad_inputs_do_not_create_outputs(selection_args, monkeypatch, extra):
    args, output, _commit = selection_args
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert main(args + extra) == 2
    assert not output.exists()


def test_selection_output_must_be_outside_source(selection_args, history):
    args, _output, _commit = selection_args
    destination = history.path / "output"
    assert main(args + ["--out", str(destination)]) == 2
    assert not destination.exists()


def test_review_failure_exports_report_and_nonzero_status(selection_args, monkeypatch):
    args, output, _commit = selection_args

    class BrokenReviewer:
        def __init__(self, _config):
            pass

        def review(self, _context):
            raise OSError("mock endpoint offline")

    monkeypatch.setattr("gptdsl.patch_selection.command.ChatCompletionsReviewer", BrokenReviewer)
    assert main(args + ["--ai", "--model", "fake-model"]) == 2
    report = json.loads((output / "selection.json").read_text(encoding="utf-8"))
    assert report["counts"]["error"] == 1
    assert not (output / "commits.txt").read_text(encoding="utf-8")
