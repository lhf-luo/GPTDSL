import json
import os
import subprocess
import sys

import pytest

from gptdsl.cli import main
from gptdsl.patch_context import ContextLimits, PatchContextError, prepare_patch_context


def _repair(history):
    history.write("sample.c", "int value(void) { return 1; }\n")
    root = history.commit("base")
    history.write("sample.c", "int value(void) { return 2; }\n")
    return root, history.commit("adjust")


def test_invalid_repo_commit_and_root_are_explicit(history, tmp_path):
    root, _commit = _repair(history)
    with pytest.raises(PatchContextError, match="exactly one parent") as error:
        prepare_patch_context(history.path, root)
    assert error.value.code == "root_commit"
    with pytest.raises(PatchContextError) as error:
        prepare_patch_context(history.path, "nonexistent")
    assert error.value.code == "commit_unavailable"
    with pytest.raises(PatchContextError):
        prepare_patch_context(tmp_path, "HEAD")


def test_shallow_repository_does_not_fetch_missing_parent(history, tmp_path):
    _root, commit = _repair(history)
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "--depth=1", history.path.as_uri(), str(shallow)],
                   check=True, capture_output=True)
    with pytest.raises(PatchContextError) as error:
        prepare_patch_context(shallow, commit)
    assert error.value.code == "parent_unavailable"
    assert (shallow / ".git/shallow").exists()


def test_merge_commit_is_rejected(history):
    _root, _commit = _repair(history)
    history.git("checkout", "-b", "side")
    history.write("side.txt", "side\n")
    history.commit("side")
    history.git("checkout", "main")
    history.write("main.txt", "main\n")
    history.commit("main")
    history.git("merge", "--no-ff", "-m", "merge", "side")
    with pytest.raises(PatchContextError) as error:
        prepare_patch_context(history.path, "HEAD")
    assert error.value.code == "merge_commit"


def test_parse_failure_binary_and_large_sources_return_partial_context(history):
    history.write("broken.c", "this is not C\n")
    history.write("binary.h", b"abc\0old")
    history.write("large.c", "a" * 300)
    history.commit("base")
    history.write("broken.c", "this still is not C\n")
    history.write("binary.h", b"abc\0new")
    history.write("large.c", "b" * 300)
    context = prepare_patch_context(history.path, history.commit("modify"),
                                    limits=ContextLimits(source_bytes=100))
    assert not context.complete
    assert {"parse_error", "non_function_change", "binary_source", "source_size_limit"} <= {
        item.code for item in context.diagnostics}
    assert context.fallback
    assert any(change.after_text is None for change in context.files)


def test_invalid_utf8_is_flagged(history):
    history.write("sample.c", b"/* \xff */\nint f(void) { return 1; }\n")
    history.commit("base")
    history.write("sample.c", b"/* \xff */\nint f(void) { return 2; }\n")
    context = prepare_patch_context(history.path, history.commit("modify"))
    assert "encoding_replaced" in {item.code for item in context.diagnostics}
    assert context.functions[0].before.start_line == 2


def test_cli_export_no_overwrite_and_bounded_markdown(history, tmp_path, capsys):
    _root, commit = _repair(history)
    output = tmp_path / "output"
    args = ["context", "--repo", str(history.path), "--commit", commit, "--out", str(output)]
    assert main(args) == 0
    payload = json.loads((output / "context.json").read_text(encoding="utf-8"))
    assert payload["commit"] == commit
    assert payload["schema_version"] == 1
    assert (output / "context.md").read_text(encoding="utf-8") == payload["markdown"]
    (output / "context.md").write_text("keep me", encoding="utf-8")
    assert main(args) == 2
    assert (output / "context.md").read_text(encoding="utf-8") == "keep me"
    assert "--overwrite" in capsys.readouterr().err
    assert main(args + ["--overwrite"]) == 0
    assert main(args + ["--overwrite", "--max-context-chars", "512"]) == 0
    assert len((output / "context.md").read_text(encoding="utf-8")) <= 512


def test_cli_rejects_output_inside_input_repository(history):
    _root, commit = _repair(history)
    args = ["context", "--repo", str(history.path), "--commit", commit,
            "--out", str(history.path / "output")]
    assert main(args) == 2
    assert not (history.path / "output").exists()


def test_cli_does_not_create_output_for_bad_inputs(history, tmp_path):
    _repair(history)
    output = tmp_path / "missing"
    assert main(["context", "--repo", str(history.path), "--commit", "missing",
                 "--out", str(output)]) == 2
    assert not output.exists()


def test_module_cli_in_subprocess_and_inherited_git_dir_ignored(history, tmp_path):
    _root, commit = _repair(history)
    env = os.environ.copy()
    env["GIT_DIR"] = str(tmp_path / "not-the-repository")
    result = subprocess.run([sys.executable, "-m", "gptdsl", "context", "--repo", str(history.path),
                             "--commit", commit, "--out", str(tmp_path / "export")],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "export/context.json").exists()


@pytest.mark.parametrize("kwargs", [{"source_files": 0}, {"seed_symbols": -1},
                                   {"markdown_chars": 511}, {"include_depth": True}])
def test_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        ContextLimits(**kwargs)
