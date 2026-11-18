"""Lightweight C syntax extraction; no compilation or preprocessor evaluation."""

from dataclasses import dataclass
import re

from tree_sitter import Language, Parser
import tree_sitter_c

from .models import Diagnostic, SourceSnippet


_NON_CODE = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)
_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "typeof", "__typeof__",
             "_Alignof", "alignof", "defined", "__attribute__", "__free", "DEFINE_FREE"}
_INCLUDE = re.compile(r'^[ \t]*#[ \t]*include[ \t]+([<"])([^>"\n]+)[>"]', re.M)
_MACRO = re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)", re.M)


def code_only(text: str) -> str:
    return _NON_CODE.sub(lambda match: re.sub(r"[^\n]", " ", match.group()), text)


def call_names(text: str) -> tuple[str, ...]:
    clean = code_only(text)
    return tuple(dict.fromkeys(match[1] for match in _CALL.finditer(clean)
                               if match[1] not in _KEYWORDS and not match[1].startswith("__builtin_")
                               and not re.search(r"(?:->|\.)\s*$", clean[:match.start()])))


def walk(node):
    pending = [node]
    while pending:
        current = pending.pop()
        yield current
        pending.extend(reversed(current.named_children))


def _declarator_name(node) -> str:
    current = node.child_by_field_name("declarator")
    while current is not None:
        if current.type == "identifier":
            return current.text.decode("utf-8", errors="replace")
        current = current.child_by_field_name("declarator")
    return ""


@dataclass(frozen=True)
class Include:
    path: str
    quoted: bool
    line: int


@dataclass(frozen=True)
class ParsedSource:
    functions: tuple[SourceSnippet, ...]
    definitions: tuple[SourceSnippet, ...]
    includes: tuple[Include, ...]


def _snippet(revision, path, node, kind, symbol) -> SourceSnippet:
    return SourceSnippet(revision, path, node.start_point.row + 1, node.end_point.row + 1,
                         kind, symbol, "local source definition", node.text.decode("utf-8"))


def _tree_definitions(revision: str, path: str, root) -> list[SourceSnippet]:
    definitions = []
    pending = [root]
    while pending:
        node = pending.pop()
        if node.type == "function_definition":
            name = _declarator_name(node)
            if name:
                definitions.append(_snippet(revision, path, node, "function", name))
            continue
        if node.type == "declaration":
            for child in walk(node):
                if child.type == "function_declarator" and (name := _declarator_name(child)):
                    definitions.append(_snippet(revision, path, node, "declaration", name))
            continue
        pending.extend(reversed(node.named_children))
    return definitions


def _macro_definitions(revision: str, path: str, text: str) -> list[SourceSnippet]:
    lines = text.splitlines()
    definitions = []
    for match in _MACRO.finditer(code_only(text)):
        start = text.count("\n", 0, match.start())
        end = start
        while end + 1 < len(lines) and lines[end].rstrip().endswith("\\"):
            end += 1
        definitions.append(SourceSnippet(revision, path, start + 1, end + 1, "macro", match[1],
                                          "local macro definition", "\n".join(lines[start:end + 1])))
    return definitions


def parse_source(revision: str, path: str, text: str, diagnostics: list[Diagnostic]) -> ParsedSource:
    tree = Parser(Language(tree_sitter_c.language())).parse(text.encode("utf-8"))
    if tree.root_node.has_error:
        diagnostics.append(Diagnostic("parse_error", "C parse errors; extracted spans are best effort",
                                      revision, path))
    definitions = _tree_definitions(revision, path, tree.root_node)
    definitions.extend(_macro_definitions(revision, path, text))
    definitions.sort(key=lambda entry: (entry.start_line, entry.end_line, entry.kind, entry.symbol))
    # Include paths are literals, so use AST ranges rather than string-stripped source.
    includes = []
    for node in walk(tree.root_node):
        if node.type == "preproc_include":
            match = _INCLUDE.match(node.text.decode("utf-8", errors="replace"))
            if match:
                includes.append(Include(match[2], match[1] == '"', node.start_point.row + 1))
            else:
                diagnostics.append(Diagnostic("include_unresolved", "Non-literal include is not resolved",
                                              revision, path, node.start_point.row + 1))
    functions = tuple(entry for entry in definitions if entry.kind == "function")
    return ParsedSource(functions, tuple(definitions), tuple(includes))


def balanced_call(text: str, start: int) -> str | None:
    """Return an invocation including balanced parentheses, ignoring strings/comments."""
    clean = code_only(text)
    opening = clean.find("(", start)
    depth = 0
    for index in range(opening, len(clean)):
        if clean[index] == "(":
            depth += 1
        elif clean[index] == ")":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None
