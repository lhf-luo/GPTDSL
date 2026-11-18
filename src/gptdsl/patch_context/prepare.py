"""Coordinate read-only context collection behind the public interface."""

from pathlib import Path

from .changes import changed_lines, fallback_spans, function_changes
from .models import ContextLimits, Diagnostic, FileChange, PatchContext
from .render import render_context
from .repository import Repository, SourceReader
from .supplement import LocalSources, SupplementCollector


def _load_changes(repository, reader, parent, commit, edits) -> tuple[FileChange, ...]:
    files = []
    for status, old, new in repository.changes(parent, commit):
        source = any(path is not None and Path(path).suffix in (".c", ".h") for path in (old, new))
        before = reader.read(parent, old, required=True) if source and old else None
        after = reader.read(commit, new, required=True) if source and new else None
        old_lines, new_lines = edits.get((old, new), ((), ()))
        files.append(FileChange(status, old, new, before, after, old_lines, new_lines))
    return tuple(files)


def _extract(files, sources, parent, commit, diagnostics):
    functions, fallback = [], []
    for change in files:
        before = sources.document(parent, change.before_path) if change.before_text is not None else None
        after = sources.document(commit, change.after_path) if change.after_text is not None else None
        functions.extend(function_changes(change, before.parsed if before else None,
                                          after.parsed if after else None, diagnostics))
        for document, edits in ((before, change.before_lines), (after, change.after_lines)):
            if document:
                fallback.extend(fallback_spans(document.revision, document.path, document.text,
                                               edits, document.parsed, diagnostics))
    return tuple(functions), tuple(fallback)


def _supplement(files, functions, fallback, sources, parent, commit, limits, diagnostics):
    texts = {parent: [], commit: []}
    for function in functions:
        for snippet in (function.before, function.after):
            if snippet:
                texts[snippet.revision].append(snippet.text)
    for snippet in fallback:
        texts[snippet.revision].append(snippet.text)
    paths = {
        parent: [change.before_path for change in files if change.before_text is not None],
        commit: [change.after_path for change in files if change.after_text is not None],
    }
    closures = {revision: sources.closure(revision, names) for revision, names in paths.items()}
    excluded = {function.name for function in functions}
    return SupplementCollector(limits, diagnostics).collect(texts, closures, excluded)


def prepare(repo, revision: str, limits: ContextLimits) -> PatchContext:
    repository = Repository(Path(repo))
    commit, parent, message = repository.resolve(revision)
    diff = repository.diff(parent, commit)
    diagnostics: list[Diagnostic] = []
    reader = SourceReader(repository, limits, diagnostics)
    files = _load_changes(repository, reader, parent, commit, changed_lines(diff))
    sources = LocalSources(reader, limits, diagnostics)
    functions, fallback = _extract(files, sources, parent, commit, diagnostics)
    supplements = _supplement(files, functions, fallback, sources, parent, commit, limits, diagnostics)
    diagnostics = list(dict.fromkeys(diagnostics))
    markdown = render_context(commit, parent, message, diff, files, functions, fallback,
                              supplements, diagnostics, limits)
    return PatchContext(str(repository.root), commit, parent, message, diff, files, functions,
                        fallback, supplements, tuple(diagnostics), limits, markdown)
