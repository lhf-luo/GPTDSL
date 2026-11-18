from gptdsl.patch_context import ContextLimits, prepare_patch_context


def _case(history, files, before="WRAP(x)", after="WRAP(x + 1)"):
    for path, text in files.items():
        history.write(path, text)
    source = '#include "api.h"\nint changed(int x) { return ' + before + "; }\n"
    history.write("sample.c", source)
    history.commit("base")
    history.write("sample.c", source.replace(before, after))
    return history.commit("change use")


def test_historical_headers_macros_and_one_level_callee(history):
    commit = _case(history, {"api.h": "#define WRAP(x) helper(x)\nstatic inline int helper(int x) { return x; }\n"})
    history.write("api.h", "#define WRAP(x) nonexistent_current_version(x)\n")
    context = prepare_patch_context(history.path, commit)
    assert {entry.symbol for entry in context.supplements} == {"WRAP", "helper"}
    assert len(context.supplements) == 4
    assert all("nonexistent_current_version" not in entry.text for entry in context.supplements)
    assert {entry.revision for entry in context.supplements} == {context.parent_commit, commit}
    assert any(entry.reason == "one-level callee of WRAP" for entry in context.supplements)


def test_local_context_mode_omits_recursive_header_collection(history):
    commit = _case(history, {"api.h": "#define WRAP(x) helper(x)\nstatic inline int helper(int x) { return x; }\n"})
    local = prepare_patch_context(history.path, commit, include_supplements=False)
    full = prepare_patch_context(history.path, commit)
    assert local.functions == full.functions and local.fallback == full.fallback
    assert local.files == full.files and local.diff == full.diff
    assert local.supplements == () and full.supplements
    assert local.include_supplements is False and full.include_supplements is True
    assert local.to_dict()["include_supplements"] is False


def test_short_wrapper_follows_one_level_only(history):
    header = ("static inline int bottom(int x) { return x; }\n"
              "static inline int middle(int x) { return bottom(x); }\n"
              "static inline int wrapper(int x) { return middle(x); }\n")
    commit = _case(history, {"api.h": header}, "wrapper(x)", "wrapper(x + 1)")
    context = prepare_patch_context(history.path, commit)
    assert {entry.symbol for entry in context.supplements} == {"wrapper", "middle"}


def test_function_declaration_is_available_without_definition(history):
    commit = _case(history, {"api.h": "extern int library_call(int x);\n"},
                   "library_call(x)", "library_call(x + 1)")
    context = prepare_patch_context(history.path, commit)
    assert all(entry.kind == "declaration" for entry in context.supplements)
    assert len(context.supplements) == 2


def test_missing_or_ambiguous_symbols_do_not_choose_first_definition(history):
    header = ("#ifdef FIRST\nstatic inline int wrapper(int x) { return x; }\n"
              "#else\nstatic inline int wrapper(int x) { return x + 2; }\n#endif\n")
    commit = _case(history, {"api.h": header}, "wrapper(x) + unknown(x)", "wrapper(x + 1) + unknown(x)")
    history.write("unrelated.c", "int unknown(int x) { return x; }\n")
    context = prepare_patch_context(history.path, commit)
    assert not context.supplements
    codes = {item.code for item in context.diagnostics}
    assert {"symbol_ambiguous", "symbol_unresolved"} <= codes


def test_local_include_closure_handles_cycles_relative_paths_and_public_headers(history):
    commit = _case(history, {
        "api.h": '#include "sub/inner.h"\n',
        "sub/inner.h": '#include "../api.h"\n#include <linux/local.h>\n',
        "include/linux/local.h": "#define WRAP(x) (x)\n",
    })
    context = prepare_patch_context(history.path, commit)
    assert len(context.supplements) == 2
    assert all(entry.path == "include/linux/local.h" for entry in context.supplements)


def test_include_and_supplement_limits_are_reported(history):
    commit = _case(history, {
        "api.h": '#include "second.h"\n',
        "second.h": "#define WRAP(x) (x)\n",
    })
    shallow = prepare_patch_context(history.path, commit, limits=ContextLimits(include_depth=1))
    assert "include_depth_limit" in {item.code for item in shallow.diagnostics}
    assert not shallow.supplements
    narrow = prepare_patch_context(history.path, commit, limits=ContextLimits(source_files=1))
    assert "source_file_limit" in {item.code for item in narrow.diagnostics}
    limited = prepare_patch_context(history.path, commit, limits=ContextLimits(supplement_entries=1))
    assert len(limited.supplements) == 1
    assert "supplement_entry_limit" in {item.code for item in limited.diagnostics}


def test_cleanup_attribute_collects_define_free_and_actual_callee(history):
    header = ("static inline void release_item(void *p) {}\n"
              "DEFINE_FREE(item, void *, release_item(_T))\n")
    history.write("api.h", header)
    source = '#include "api.h"\nint changed(void *p)\n{\n    void *item __free(item) = p;\n    return 1;\n}\n'
    history.write("sample.c", source)
    history.commit("base")
    history.write("sample.c", source.replace("return 1", "return 2"))
    context = prepare_patch_context(history.path, history.commit("change cleanup user"))
    assert any(entry.kind == "cleanup" and entry.symbol == "item" for entry in context.supplements)
    assert any(entry.symbol == "release_item" for entry in context.supplements)
    assert all(entry.path == "api.h" for entry in context.supplements)


def test_missing_includes_and_global_api_are_not_silently_filled(history):
    commit = _case(history, {"api.h": '#include <arch/missing.h>\n'}, "external(x)", "external(x + 1)")
    history.write("somewhere.c", "int external(int x) { return x; }\n")
    context = prepare_patch_context(history.path, commit)
    assert not context.supplements
    assert {"include_unresolved", "symbol_unresolved"} <= {item.code for item in context.diagnostics}


def test_indirect_member_call_does_not_resolve_unrelated_same_named_function(history):
    header = "static inline int method(int x) { return x; }\n"
    commit = _case(history, {"api.h": header}, "obj -> method(x)", "obj -> method(x + 1)")
    context = prepare_patch_context(history.path, commit)
    assert not context.supplements


def test_callee_budget_does_not_silently_omit_remaining_calls(history):
    header = ("static inline int leaf_one(int x) { return x; }\n"
              "static inline int leaf_two(int x) { return x; }\n"
              "#define WRAP(x) (leaf_one(x) + leaf_two(x))\n")
    commit = _case(history, {"api.h": header})
    context = prepare_patch_context(history.path, commit, limits=ContextLimits(supplement_entries=3))
    assert len(context.supplements) == 3
    assert "supplement_entry_limit" in {item.code for item in context.diagnostics}
