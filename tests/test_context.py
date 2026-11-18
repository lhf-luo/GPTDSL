import json

from gptdsl.patch_context import ContextLimits, prepare_patch_context


def test_actual_edits_select_function_not_hunk_context(history):
    before = "int unrelated(void) { return 1; }\n\nint changed(int x)\n{\n    return x;\n}\n"
    history.write("sample.c", before)
    parent = history.commit("base")
    history.write("sample.c", before.replace("return x;", "return x + 1;"))
    commit = history.commit("adjust calculation")
    context = prepare_patch_context(history.path, commit[:12])
    assert context.commit == commit and context.parent_commit == parent
    assert [function.name for function in context.functions] == ["changed"]
    function = context.functions[0]
    assert function.before.start_line == 3
    assert function.before.end_line == 6
    assert "return x;" in function.before.text
    assert "return x + 1;" in function.after.text
    assert context.files[0].before_lines == (5,)
    assert context.files[0].after_lines == (5,)
    assert context.complete
    assert json.dumps(context.to_dict())


def test_insertion_only_pairs_pre_fix_function(history):
    history.write("sample.c", "int adjust(int x)\n{\n    return x;\n}\n")
    history.commit("base")
    history.write("sample.c", "int adjust(int x)\n{\n    x += 2;\n    return x;\n}\n")
    commit = history.commit("insert statement")
    context = prepare_patch_context(history.path, commit)
    assert context.files[0].before_lines == ()
    assert context.files[0].after_lines == (3,)
    assert context.functions[0].before.text == "int adjust(int x)\n{\n    return x;\n}"


def test_multiple_hunks_and_function_first_last_lines(history):
    first = "int first(void)\n{\n    return 1;\n}\n"
    gap = "\n" * 60
    last = "int last(void)\n{\n    return 2;\n}\n"
    history.write("sample.c", first + gap + last)
    history.commit("base")
    history.write("sample.c", first.replace("first", "renamed") + gap + last.replace("return 2;", "return 3;"))
    context = prepare_patch_context(history.path, history.commit("two hunks"))
    names = {function.name for function in context.functions}
    assert names == {"first", "renamed", "last"}
    assert next(function for function in context.functions if function.name == "first").after is None
    assert next(function for function in context.functions if function.name == "renamed").before is None


def test_added_deleted_and_renamed_files(history):
    old = "\n".join(f"/* line {i} */" for i in range(40)) + "\nint old(void) { return 0; }\n"
    history.write("old name.c", old)
    history.write("removed.c", "int removed(void) { return 1; }\n")
    history.commit("base")
    (history.path / "old name.c").rename(history.path / "新 name.c")
    history.write("新 name.c", old.replace("return 0", "return 2"))
    (history.path / "removed.c").unlink()
    history.write("added.c", "int added(void) { return 3; }\n")
    context = prepare_patch_context(history.path, history.commit("file changes"))
    rename = next(change for change in context.files if change.status.startswith("R"))
    assert (rename.before_path, rename.after_path) == ("old name.c", "新 name.c")
    assert rename.before_lines == (41,) and rename.after_lines == (41,)
    old_function = next(function for function in context.functions if function.name == "old")
    assert old_function.before.path == "old name.c" and old_function.after.path == "新 name.c"
    assert next(function for function in context.functions if function.name == "added").before is None
    assert next(function for function in context.functions if function.name == "removed").after is None


def test_non_function_changes_and_non_c_metadata(history):
    history.write("api.h", "#define COUNT 2\nstruct item { int size; };\n")
    history.write("notes.txt", "before\n")
    history.commit("base")
    history.write("api.h", "#define COUNT 3\nstruct item { long size; };\n")
    history.write("notes.txt", "after\n")
    context = prepare_patch_context(history.path, history.commit("constants and type"))
    assert not context.functions
    assert len(context.fallback) == 2
    assert "#define COUNT 2" in context.fallback[0].text
    assert any(item.code == "non_function_change" for item in context.diagnostics)
    notes = next(change for change in context.files if change.after_path == "notes.txt")
    assert notes.before_text is None and notes.after_text is None
    assert "notes.txt" in context.diff


def test_unicode_crlf_and_missing_final_newline(history):
    history.write("示例.c", "/* 中文 */\r\nint value(void)\r\n{\r\n    return 1;\r\n}")
    history.commit("base")
    history.write("示例.c", "/* 中文 */\r\nint value(void)\r\n{\r\n    return 2;\r\n}")
    context = prepare_patch_context(history.path, history.commit("Unicode"))
    assert context.files[0].before_lines == (4,)
    assert context.functions[0].before.start_line == 2
    assert "\r\n" in context.functions[0].before.text
    assert "中文" in context.files[0].before_text


def test_worktree_index_and_head_unchanged_and_results_repeat(history):
    history.write("sample.c", "int value(void) { return 1; }\n")
    history.commit("base")
    history.write("sample.c", "int value(void) { return 2; }\n")
    commit = history.commit("adjust")
    history.write("sample.c", "unrelated dirty worktree\n")
    history.write("staged.txt", "staged\n")
    history.git("add", "staged.txt")
    history.write("untracked.txt", "untracked\n")
    before = (history.git("rev-parse", "HEAD"), history.git("status", "--porcelain"),
              (history.path / ".git/index").read_bytes(), (history.path / "sample.c").read_bytes())
    first = prepare_patch_context(history.path, commit)
    second = prepare_patch_context(history.path, commit)
    after = (history.git("rev-parse", "HEAD"), history.git("status", "--porcelain"),
             (history.path / ".git/index").read_bytes(), (history.path / "sample.c").read_bytes())
    assert before == after
    assert first.to_dict() == second.to_dict()
    assert "return 1" in first.functions[0].before.text
    assert "return 2" in first.functions[0].after.text


def test_budget_keeps_changed_region_and_full_json(history):
    lines = ["int long_function(int x)", "{"] + [f"    x += {i};" for i in range(500)] + ["    return x;", "}"]
    history.write("sample.c", "\n".join(lines) + "\n")
    history.commit("base")
    lines[450] = "    x += 123456;"
    history.write("sample.c", "\n".join(lines) + "\n")
    commit = history.commit("late change")
    context = prepare_patch_context(history.path, commit, limits=ContextLimits(markdown_chars=8000))
    assert len(context.markdown) <= 8000
    assert "123456" in context.markdown
    assert "x += 0;" in context.functions[0].after.text
    assert any(item.code == "presentation_truncated" for item in context.diagnostics)
    tiny = prepare_patch_context(history.path, commit, limits=ContextLimits(markdown_chars=512))
    assert len(tiny.markdown) <= 512
    assert "context.json" in tiny.markdown


def test_decrement_source_is_not_misread_as_a_file_header(history):
    history.write("sample.c", "int count(int x)\n{\n-- x;\nreturn x;\n}\n")
    history.commit("base")
    history.write("sample.c", "int count(int x)\n{\n++ x;\nreturn x;\n}\n")
    context = prepare_patch_context(history.path, history.commit("change operator"))
    assert context.files[0].before_lines == (3,)
    assert context.files[0].after_lines == (3,)
    assert context.functions[0].name == "count"


def test_subdirectory_input_and_relative_diff_config_do_not_hide_root_files(history):
    history.write("root.c", "int root(void) { return 1; }\n")
    history.write("sub/sample.c", "int nested(void) { return 1; }\n")
    history.commit("base")
    history.write("root.c", "int root(void) { return 2; }\n")
    history.write("sub/sample.c", "int nested(void) { return 2; }\n")
    commit = history.commit("modify both directories")
    history.git("config", "diff.relative", "true")
    context = prepare_patch_context(history.path / "sub", commit)
    assert {change.after_path for change in context.files} == {"root.c", "sub/sample.c"}
    assert {function.name for function in context.functions} == {"root", "nested"}
    assert context.complete
