"""Bounded historical include closures and local symbol evidence."""

from collections import deque
from dataclasses import dataclass, replace
import posixpath
import re

from .models import ContextLimits, Diagnostic, SourceSnippet
from .repository import SourceReader
from .syntax import ParsedSource, balanced_call, call_names, code_only, parse_source


_CLEANUP_USE = re.compile(r"\b__free\s*\(\s*([A-Za-z_]\w*)\s*\)")
_CLEANUP_DEF = re.compile(r"\bDEFINE_FREE\s*\(\s*([A-Za-z_]\w*)\s*,")


@dataclass(frozen=True)
class Document:
    revision: str
    path: str
    text: str
    parsed: ParsedSource


class LocalSources:
    def __init__(self, reader: SourceReader, limits: ContextLimits, diagnostics: list[Diagnostic]):
        self.reader, self.limits, self.diagnostics = reader, limits, diagnostics
        self.cache: dict[tuple[str, str], Document | None] = {}

    def document(self, revision: str, path: str) -> Document | None:
        key = (revision, path)
        if key not in self.cache:
            text = self.reader.read(revision, path)
            self.cache[key] = (Document(revision, path, text,
                              parse_source(revision, path, text, self.diagnostics)) if text is not None else None)
        return self.cache[key]

    def _include_path(self, document: Document, include) -> str | None:
        candidates = [posixpath.join("include", include.path), include.path]
        if include.quoted:
            candidates.insert(0, posixpath.join(posixpath.dirname(document.path), include.path))
        for candidate in dict.fromkeys(candidates):
            normalized = posixpath.normpath(candidate)
            if normalized.startswith(("/", "../")) or normalized == "..":
                continue
            if self.reader.read(document.revision, normalized) is not None:
                return normalized
        return None

    def closure(self, revision: str, paths: list[str]) -> tuple[Document, ...]:
        pending = deque((path, 0) for path in sorted(set(paths)))
        seen, documents = set(), []
        while pending and len(documents) < self.limits.source_files:
            path, depth = pending.popleft()
            if path in seen:
                continue
            seen.add(path)
            document = self.document(revision, path)
            if document is None:
                continue
            documents.append(document)
            if depth >= self.limits.include_depth:
                if document.parsed.includes:
                    self.diagnostics.append(Diagnostic("include_depth_limit", "Include depth budget reached",
                                                       revision, path))
                continue
            for include in document.parsed.includes:
                resolved = self._include_path(document, include)
                if resolved is None:
                    self.diagnostics.append(Diagnostic("include_unresolved", f"Cannot resolve {include.path}",
                                                       revision, path, include.line))
                elif resolved not in seen:
                    pending.append((resolved, depth + 1))
        if any(path not in seen for path, _depth in pending):
            self.diagnostics.append(Diagnostic("source_file_limit", "Local source search file budget reached", revision))
        return tuple(documents)


def _cleanup_definitions(document: Document, symbol: str) -> list[SourceSnippet]:
    result = []
    for match in _CLEANUP_DEF.finditer(code_only(document.text)):
        if match[1] != symbol:
            continue
        invocation = balanced_call(document.text, match.start())
        if invocation:
            start = document.text.count("\n", 0, match.start()) + 1
            result.append(SourceSnippet(document.revision, document.path, start,
                          start + invocation.count("\n"), "cleanup", symbol,
                          f"definition for __free({symbol})", invocation))
    return result


def _lookup(symbol: str, cleanup: bool, documents: tuple[Document, ...]) -> list[SourceSnippet]:
    if cleanup:
        return [entry for document in documents for entry in _cleanup_definitions(document, symbol)]
    matches = [entry for document in documents for entry in document.parsed.definitions if entry.symbol == symbol]
    definitions = [entry for entry in matches if entry.kind != "declaration"]
    return definitions or list(dict.fromkeys(matches))


def _requests(texts: dict[str, list[str]], excluded: set[str], limits: ContextLimits,
              diagnostics: list[Diagnostic]) -> list[tuple[bool, str]]:
    joined = "\n".join(text for items in texts.values() for text in items)
    cleanup = [(True, match[1]) for match in _CLEANUP_USE.finditer(code_only(joined))]
    calls = [(False, name) for name in call_names(joined) if name not in excluded]
    requests = list(dict.fromkeys(cleanup + calls))
    if len(requests) > limits.seed_symbols:
        diagnostics.append(Diagnostic("seed_symbol_limit", "Seed symbol budget reached"))
    return requests[:limits.seed_symbols]


class SupplementCollector:
    def __init__(self, limits: ContextLimits, diagnostics: list[Diagnostic]):
        self.limits, self.diagnostics = limits, diagnostics
        self.entries: list[SourceSnippet] = []
        self.seen: set[tuple] = set()

    def _add(self, entry: SourceSnippet) -> None:
        key = (entry.revision, entry.path, entry.start_line, entry.kind, entry.symbol)
        if key in self.seen:
            return
        if len(self.entries) >= self.limits.supplement_entries:
            self.diagnostics.append(Diagnostic("supplement_entry_limit", "Supplement entry budget reached"))
            return
        self.seen.add(key)
        self.entries.append(entry)

    def _resolve(self, symbol: str, cleanup: bool, revision: str,
                 documents: tuple[Document, ...]) -> SourceSnippet | None:
        matches = _lookup(symbol, cleanup, documents)
        if len(matches) == 1:
            return matches[0]
        code = "symbol_ambiguous" if matches else "symbol_unresolved"
        detail = f"{symbol}: {len(matches)} local matches"
        self.diagnostics.append(Diagnostic(code, detail, revision))
        return None

    def _callees(self, entry: SourceSnippet, documents: tuple[Document, ...]) -> None:
        if entry.kind == "declaration":
            return
        if entry.kind == "function" and entry.end_line - entry.start_line + 1 > self.limits.wrapper_lines:
            return
        for name in call_names(entry.text):
            if name == entry.symbol:
                continue
            if len(self.entries) >= self.limits.supplement_entries:
                self.diagnostics.append(Diagnostic("supplement_entry_limit", "Supplement entry budget reached"))
                break
            callee = self._resolve(name, False, entry.revision, documents)
            if callee:
                self._add(replace(callee, reason=f"one-level callee of {entry.symbol}"))

    def collect(self, texts: dict[str, list[str]], closures: dict[str, tuple[Document, ...]],
                excluded: set[str]) -> tuple[SourceSnippet, ...]:
        roots = 0
        for cleanup, symbol in _requests(texts, excluded, self.limits, self.diagnostics):
            if roots >= self.limits.root_symbols:
                self.diagnostics.append(Diagnostic("root_symbol_limit", "Supplement root budget reached"))
                break
            found = []
            for revision, items in texts.items():
                source = "\n".join(items)
                relevant = (symbol in [m[1] for m in _CLEANUP_USE.finditer(code_only(source))]
                            if cleanup else symbol in call_names(source))
                if relevant:
                    entry = self._resolve(symbol, cleanup, revision, closures[revision])
                    if entry:
                        found.append(entry)
                        self._add(replace(entry, reason=f"referenced by changed code: {symbol}"))
            roots += bool(found)
            for entry in found:
                self._callees(entry, closures[entry.revision])
        return tuple(self.entries)
