"""Interruptions preserve completed work and resume without duplicate model calls."""

import json

import pytest

from gptdsl.cli import main
from gptdsl.patch_selection import Evidence, SelectionLimits, SelectionResult, SemanticReview
from gptdsl.patch_selection.checkpoint import SelectionStore


@pytest.fixture
def run_input(history, tmp_path, monkeypatch):
    history.write("sample.c", "int value(void) { return 0; }\n")
    root = history.commit("base")
    history.write("sample.c", "int value(void) { return 1; }\n")
    first = history.commit("first adjustment")
    history.write("sample.c", "int value(void) { return 2; }\n")
    second = history.commit("second adjustment")
    path, output = tmp_path / "commits.txt", tmp_path / "selection"
    path.write_text(f"{first}\n{second}\n{first[:12]}\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("GPTDSL_REVIEW_MODEL", raising=False)
    monkeypatch.delenv("GPTDSL_REVIEW_BASE_URL", raising=False)
    args = ["select", "--repo", str(history.path), "--commit-file", str(path), "--out", str(output)]
    return args, output, path, (root, first, second)


def read_report(output):
    return json.loads((output / "selection.json").read_text(encoding="utf-8"))


def suitable(context):
    source = context.functions[0].after
    evidence = Evidence(source.revision, source.path, source.start_line, source.end_line, source.text)
    return SemanticReview("suitable", "error_handling", "Synthetic local adjustment", (evidence,))


def test_ctrl_c_saves_accepted_work_and_resume_skips_completed_and_duplicates(run_input, monkeypatch, capsys):
    args, output, _path, (_root, first, second) = run_input
    calls, interrupt = [], [True]

    class Reviewer:
        def __init__(self, _config):
            pass

        def review(self, context):
            calls.append(context.commit)
            if context.commit == second and interrupt[0]:
                raise KeyboardInterrupt
            return suitable(context)

    monkeypatch.setattr("gptdsl.patch_selection.command.ChatCompletionsReviewer", Reviewer)
    assert main(args + ["--ai"]) == 130
    printed = capsys.readouterr().out
    assert "Starting: 0/3 (0.0%)" in printed and "Progress: 1/3 (33.3%)" in printed
    assert "Progress: 2/3" not in printed
    report = read_report(output)
    assert report["run"]["state"] == "interrupted"
    assert report["run"]["processed"] == 1 and report["run"]["total"] == 3
    assert (output / "commits.txt").read_text(encoding="utf-8") == first + "\n"
    assert "test-key" not in (output / "selection.json").read_text(encoding="utf-8")
    calls.clear()
    interrupt[0] = False
    assert main(args + ["--ai", "--resume"]) == 0
    printed = capsys.readouterr().out
    assert "Resuming: 1/3 (33.3%)" in printed
    assert "Progress: 2/3 (66.7%)" in printed and "Progress: 3/3 (100.0%)" in printed
    assert f"[1/3] {first[:12]} | processing" not in printed
    assert calls == [second]
    report = read_report(output)
    assert report["run"]["state"] == "completed" and report["run"]["processed"] == 3
    assert report["counts"]["duplicate"] == 1
    assert (output / "commits.txt").read_text(encoding="utf-8") == first + "\n" + second + "\n"
    calls.clear()
    assert main(args + ["--ai", "--resume"]) == 0
    assert calls == []
    printed = capsys.readouterr().out
    assert "Resuming: 3/3 (100.0%)" in printed and " | processing" not in printed


def test_progress_is_visible_during_review_and_counts_saved_errors_and_duplicates(run_input, monkeypatch, capsys):
    args, output, path, (_root, first, second) = run_input
    path.write_text(f"{first}\n{first[:12]}\nmissing-ref\n{second}\n", encoding="utf-8")
    calls = []

    class Reviewer:
        def __init__(self, _config):
            pass

        def review(self, context):
            calls.append(context.commit)
            printed = capsys.readouterr().out
            processed = 0 if context.commit == first else 3
            if context.commit == first:
                assert "Preparing selection inputs..." in printed
                assert "Starting: 0/4 (0.0%)" in printed
                assert f"[1/4] {first[:12]} | processing" in printed
                assert "Progress: 1/4" not in printed
            else:
                assert "Progress: 1/4 (25.0%)" in printed and "-> suitable | saved" in printed
                assert "Progress: 2/4 (50.0%)" in printed and "-> duplicate | saved" in printed
                assert "Progress: 3/4 (75.0%)" in printed and "-> error | saved" in printed
                assert f"[4/4] {second[:12]} | processing" in printed
            assert read_report(output)["run"]["processed"] == processed
            return suitable(context)

    monkeypatch.setattr("gptdsl.patch_selection.command.ChatCompletionsReviewer", Reviewer)
    assert main(args + ["--ai"]) == 2
    printed = capsys.readouterr().out
    assert "Progress: 4/4 (100.0%)" in printed and "elapsed " in printed
    assert calls == [first, second]


def test_interruption_on_first_model_call_preserves_initial_checkpoint(run_input, monkeypatch):
    args, output, _path, _commits = run_input

    class Reviewer:
        def __init__(self, _config):
            pass

        def review(self, _context):
            raise KeyboardInterrupt

    monkeypatch.setattr("gptdsl.patch_selection.command.ChatCompletionsReviewer", Reviewer)
    assert main(args + ["--ai"]) == 130
    report = read_report(output)
    assert report["run"]["processed"] == 0 and report["entries"] == []
    assert (output / "commits.txt").read_text(encoding="utf-8") == ""


def test_history_resume_after_unexpected_exit_skips_saved_prefix(run_input, monkeypatch):
    args, output, _path, (_root, _first, second) = run_input
    history_args = [arg for arg in args]
    file_index = history_args.index("--commit-file")
    del history_args[file_index:file_index + 2]
    original_save = SelectionStore.save

    def crash_after_save(self, result, state="running"):
        original_save(self, result, state)
        if len(result.entries) == 1:
            raise RuntimeError("simulate process exit after a saved result")

    with monkeypatch.context() as patch:
        patch.setattr(SelectionStore, "save", crash_after_save)
        with pytest.raises(RuntimeError, match="simulate process exit"):
            main(history_args)
    report = read_report(output)
    assert report["run"]["state"] == "running" and report["entries"][0]["commit"] == second
    import gptdsl.patch_selection.select as selection

    original_select = selection._select_one
    processed = []

    def track(repository, commit, limits, reviewer):
        processed.append(commit)
        return original_select(repository, commit, limits, reviewer)

    monkeypatch.setattr(selection, "_select_one", track)
    assert main(history_args + ["--resume"]) == 0
    assert second not in processed and len(processed) == 2


def test_authoritative_report_recovers_when_derived_list_write_fails(run_input, monkeypatch):
    args, output, _path, (_root, first, _second) = run_input
    import gptdsl.patch_selection.checkpoint as checkpoint

    original_publish = checkpoint.publish

    def partial_publish(destination, payloads, overwrite):
        if json.loads(payloads["selection.json"])["run"]["processed"] == 1:
            original_publish(destination, {"selection.json": payloads["selection.json"]}, overwrite)
            raise OSError("simulate failure before derived lists are refreshed")
        original_publish(destination, payloads, overwrite)

    with monkeypatch.context() as patch:
        patch.setattr(checkpoint, "publish", partial_publish)
        assert main(args) == 2
    assert read_report(output)["entries"][0]["commit"] == first
    assert (output / "candidates.txt").read_text(encoding="utf-8") == ""
    assert main(args + ["--resume"]) == 0
    assert (output / "candidates.txt").read_text(encoding="utf-8").startswith(first + "\n")


@pytest.mark.parametrize("change", ["limits", "mode", "file", "model", "endpoint"])
def test_resume_rejects_changed_parameters_without_modifying_report(run_input, monkeypatch, change):
    args, output, path, (_root, first, second) = run_input
    ai = change in ("model", "endpoint")

    class Reviewer:
        def __init__(self, _config):
            pass

        def review(self, _context):
            return SemanticReview("needs_review", "unknown", "Synthetic review")

    monkeypatch.setattr("gptdsl.patch_selection.command.ChatCompletionsReviewer", Reviewer)
    original_args = args + (["--ai"] if ai else [])
    assert main(original_args) == 0
    original = (output / "selection.json").read_bytes()
    extra = {"limits": ["--max-files", "1"], "mode": ["--ai"], "file": [],
             "model": ["--model", "different-model"], "endpoint": ["--base-url", "http://localhost/v1"]}[change]
    if change == "file":
        path.write_text(f"{second}\n{first}\n", encoding="utf-8")
    assert main(original_args + ["--resume"] + extra) == 2
    assert (output / "selection.json").read_bytes() == original


def test_history_resume_rejects_moved_head(run_input, history):
    args, output, _path, _commits = run_input
    file_index = args.index("--commit-file")
    history_args = args[:file_index] + args[file_index + 2:]
    assert main(history_args) == 0
    original = (output / "selection.json").read_bytes()
    history.write("notes.txt", "new history")
    history.commit("new head")
    assert main(history_args + ["--resume"]) == 2
    assert (output / "selection.json").read_bytes() == original


def test_missing_corrupt_and_mutually_exclusive_resume(run_input):
    args, output, _path, _commits = run_input
    assert main(args + ["--resume"]) == 2
    assert not output.exists()
    output.mkdir()
    (output / "selection.json").write_text("broken JSON", encoding="utf-8")
    assert main(args + ["--resume"]) == 2
    assert (output / "selection.json").read_text(encoding="utf-8") == "broken JSON"
    with pytest.raises(SystemExit) as error:
        main(args + ["--resume", "--overwrite"])
    assert error.value.code == 2
    assert main(args + ["--overwrite"]) == 0


def test_output_lock_blocks_second_writer_and_is_released_on_close(tmp_path):
    output = tmp_path / "selection"
    result = SelectionResult("synthetic-repo", "HEAD", SelectionLimits(), ())
    configuration = {"review_mode": "offline"}
    with SelectionStore(output, configuration) as first:
        first.load(result.limits)
        first.save(result)
        with SelectionStore(output, configuration, overwrite=True) as second:
            with pytest.raises(ValueError, match="in use"):
                second.save(result)
    with SelectionStore(output, configuration, overwrite=True) as next_run:
        next_run.save(result, "completed")
    assert read_report(output)["run"]["state"] == "completed"
