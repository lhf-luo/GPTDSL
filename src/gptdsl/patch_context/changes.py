"""Map actual unified-diff edits to historical C source spans."""

import ast
from collections import defaultdict
from dataclasses import replace
import re

from .models import Diagnostic, FileChange, FunctionChange, SourceSnippet
from .syntax import ParsedSource


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _header_path(line: str) -> str | None:
    value = line[4:].rstrip("\t")
    if value.startswith('"'):
        value = ast.literal_eval(value)
    return None if value == "/dev/null" else value[2:]


def _section_edits(lines: list[str]) -> tuple[tuple, tuple[tuple[int, ...], tuple[int, ...]]]:
    before = after = None
    old_lines, new_lines = set(), set()
    old = new = 0
    in_hunk = False
    for line in lines:
        hunk = _HUNK.match(line)
        if hunk:
            old, new = int(hunk[1]), int(hunk[3])
            in_hunk = True
        elif in_hunk:
            if line.startswith("-"):
                old_lines.add(old)
                old += 1
            elif line.startswith("+"):
                new_lines.add(new)
                new += 1
            elif line.startswith(" "):
                old += 1
                new += 1
        elif line.startswith("--- "):
            before = _header_path(line)
        elif line.startswith("+++ "):
            after = _header_path(line)
    return (before, after), (tuple(sorted(old_lines)), tuple(sorted(new_lines)))


def changed_lines(diff: str) -> dict[tuple, tuple[tuple[int, ...], tuple[int, ...]]]:
    result = {}
    section = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            if section:
                key, edits = _section_edits(section)
                result[key] = edits
            section = []
        else:
            section.append(line)
    if section:
        key, edits = _section_edits(section)
        result[key] = edits
    return result


def _selected(parsed: ParsedSource | None, edits: tuple[int, ...]) -> list[SourceSnippet]:
    if parsed is None:
        return []
    return [replace(function, reason="encloses changed source line") for function in parsed.functions
            if any(function.start_line <= line <= function.end_line for line in edits)]


def _by_name(functions: tuple[SourceSnippet, ...] | list[SourceSnippet]) -> dict:
    result = defaultdict(list)
    for function in functions:
        result[function.symbol].append(function)
    return result


def function_changes(change: FileChange, before: ParsedSource | None, after: ParsedSource | None,
                     diagnostics: list[Diagnostic]) -> list[FunctionChange]:
    selected_old = _selected(before, change.before_lines)
    selected_new = _selected(after, change.after_lines)
    all_old = _by_name(before.functions if before else ())
    all_new = _by_name(after.functions if after else ())
    touched = sorted({entry.symbol for entry in selected_old + selected_new})
    result = []
    for name in touched:
        old, new = all_old[name], all_new[name]
        if len(old) <= 1 and len(new) <= 1:
            result.append(FunctionChange(name,
                          replace(old[0], reason="changed function or its pre-fix counterpart") if old else None,
                          replace(new[0], reason="changed function or its post-fix counterpart") if new else None))
        else:
            diagnostics.append(Diagnostic("function_pair_ambiguous", f"Cannot uniquely pair {name}",
                                          path=change.before_path or change.after_path))
            result.extend(FunctionChange(name, item, None) for item in selected_old if item.symbol == name)
            result.extend(FunctionChange(name, None, item) for item in selected_new if item.symbol == name)
    return result


def fallback_spans(revision: str, path: str, text: str, edits: tuple[int, ...],
                   parsed: ParsedSource, diagnostics: list[Diagnostic]) -> list[SourceSnippet]:
    outside = [line for line in edits if not any(fn.start_line <= line <= fn.end_line
                                                for fn in parsed.functions)]
    if not outside:
        return []
    diagnostics.append(Diagnostic("non_function_change", "Using local excerpt for edits outside a parsed function",
                                  revision, path, outside[0]))
    lines = text.splitlines()
    ranges = []
    for line in outside:
        start, end = max(1, line - 8), min(len(lines), line + 8)
        if ranges and start <= ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    return [SourceSnippet(revision, path, start, end, "excerpt", "", "non-function or unparsed changed code",
                           "\n".join(lines[start - 1:end])) for start, end in ranges]
