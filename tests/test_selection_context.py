"""Best-effort local materials reach review despite parser and include limitations."""

import pytest

from gptdsl.patch_context import prepare_patch_context
from gptdsl.patch_selection import Evidence, SelectionLimits, SemanticReview, select_patches


class Reviewer:
    def __init__(self, assess):
        self.assess = assess
        self.contexts = []

    def review(self, context):
        self.contexts.append(context)
        return self.assess(context)


def accept_changed_source(context):
    source = context.functions[0].after
    evidence = Evidence(source.revision, source.path, source.start_line, source.end_line, source.text)
    return SemanticReview("suitable", "error_handling", "Visible local return adjustment", (evidence,))


def test_unrelated_header_failures_do_not_enter_local_review_context(history):
    history.write("include/linux/api.h", "these are invalid C tokens ???\n")
    before = '#include <linux/api.h>\n#include <asm/irq.h>\nint changed(void) { return 1; }\n'
    history.write("sample.c", before)
    history.commit("base")
    history.write("sample.c", before.replace("return 1", "return 2"))
    commit = history.commit("local adjustment")
    full = prepare_patch_context(history.path, commit)
    assert {"parse_error", "include_unresolved"} <= {item.code for item in full.diagnostics}
    reviewer = Reviewer(accept_changed_source)
    result = select_patches(history.path, limits=SelectionLimits(max_commits=1), reviewer=reviewer)
    assert result.selected_commits == (commit,)
    context = reviewer.contexts[0]
    assert context.include_supplements is False and context.supplements == ()
    assert not any(item.path == "include/linux/api.h" for item in context.diagnostics)
    assert result.entries[0]["context"]["mode"] == "local_best_effort_v1"
    assert result.entries[0]["checks"]["ai_review_attempted"] is True


def test_parse_error_elsewhere_in_touched_file_allows_grounded_review(history):
    before = "invalid tokens ???\nint changed(void) { return 1; }\n"
    history.write("sample.c", before)
    history.commit("base")
    history.write("sample.c", before.replace("return 1", "return 2"))
    commit = history.commit("adjust function")
    reviewer = Reviewer(accept_changed_source)
    result = select_patches(history.path, limits=SelectionLimits(max_commits=1), reviewer=reviewer)
    assert result.selected_commits == (commit,)
    context = reviewer.contexts[0]
    assert "parse_error" in {item.code for item in context.diagnostics}
    assert "parse_error" in context.markdown


def test_failed_function_extraction_provides_changed_source_excerpts(history):
    history.write("sample.c", "not valid C before\n")
    history.commit("base")
    history.write("sample.c", "not valid C after\n")
    commit = history.commit("modify unparsed source")

    def assess(context):
        assert not context.functions
        assert context.fallback
        assert "not valid C before" in context.markdown and "not valid C after" in context.markdown
        assert all(source.start_line == 1 and source.end_line == 1 for source in context.fallback)
        return SemanticReview("needs_review", "unknown", "Visible excerpts lack sufficient repair semantics")

    reviewer = Reviewer(assess)
    result = select_patches(history.path, limits=SelectionLimits(max_commits=1), reviewer=reviewer)
    assert result.entries[0]["status"] == "needs_review"
    assert result.entries[0]["checks"]["ai_review_attempted"] is True
    assert len(reviewer.contexts) == 1 and not result.selected_commits


@pytest.mark.parametrize("fabricate", [False, True])
def test_fallback_source_evidence_stays_grounded(history, fabricate):
    history.write("api.h", "#define LOCAL_VALUE 1\n")
    history.commit("base")
    history.write("api.h", "#define LOCAL_VALUE 2\n")
    commit = history.commit("adjust macro")

    def assess(context):
        source = next(item for item in context.fallback if item.revision == commit)
        evidence = Evidence(source.revision, source.path, source.start_line, source.end_line,
                            "invented source" if fabricate else source.text)
        return SemanticReview("suitable", "error_handling", "Synthetic local macro change", (evidence,))

    result = select_patches(history.path, limits=SelectionLimits(max_commits=1), reviewer=Reviewer(assess))
    assert result.entries[0]["checks"]["ai_review_attempted"] is True
    assert result.entries[0]["status"] == ("error" if fabricate else "suitable")
    assert bool(result.selected_commits) is not fabricate
