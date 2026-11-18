"""Deterministic, bounded presentation separate from complete collected material."""

from dataclasses import dataclass
import re

from .models import Diagnostic


@dataclass(frozen=True)
class Block:
    label: str
    text: str
    language: str = "c"
    focus: tuple[int, ...] = ()
    start_line: int = 1


def _excerpt(block: Block, budget: int) -> tuple[str, bool]:
    if len(block.text) <= budget:
        return block.text, False
    marker = "/* ... omitted; complete material is in context.json ... */"
    if budget < len(marker) + 30:
        return "", True
    lines = block.text.splitlines()
    focuses = [line - block.start_line for line in block.focus
               if block.start_line <= line < block.start_line + len(lines)] or [0]
    order = sorted(range(len(lines)), key=lambda index: (min(abs(index - x) for x in focuses[:64]), index))
    selected, used = set(), len(marker)
    for index in order:
        cost = len(lines[index]) + 40
        if used + cost <= budget:
            selected.add(index)
            used += cost
    if not selected:
        focus = min(focuses[0], len(lines) - 1)
        return lines[focus][:budget - len(marker) - 1] + "\n" + marker, True
    rendered, previous = [], -1
    for index in sorted(selected):
        if index > previous + 1:
            rendered.append(f"/* ... lines {block.start_line + previous + 1}-{block.start_line + index - 1} omitted ... */")
        rendered.append(lines[index])
        previous = index
    if previous < len(lines) - 1:
        rendered.append(marker)
    return "\n".join(rendered), True


def _section(title: str, blocks: list[Block], budget: int) -> tuple[str, bool]:
    if not blocks:
        return "", False
    heading = f"## {title}\n\n"
    active = blocks[:max(1, budget // 350)]
    omitted = len(blocks) - len(active)
    share = max(0, (budget - len(heading) - 100) // len(active))
    parts, clipped = [], bool(omitted)
    for block in active:
        longest = max((len(match[0]) for match in re.finditer(r"`+", block.text)), default=0)
        fence = "`" * max(3, longest + 1)
        prefix = f"### {block.label}\n\n{fence}{block.language}\n"
        suffix = f"\n{fence}\n"
        if len(prefix) + len(suffix) + 80 > share:
            omitted += 1
            clipped = True
            continue
        text, truncated = _excerpt(block, share - len(prefix) - len(suffix))
        parts.append(prefix + text + suffix)
        clipped |= truncated
    if omitted:
        parts.append(f"{omitted} item(s) omitted; see context.json.\n")
    return heading + "\n".join(parts), clipped


def _source_block(snippet, files, parent: str = "") -> Block:
    focus = []
    for change in files:
        if snippet.revision == parent and snippet.path == change.before_path:
            focus.extend(change.before_lines)
        if snippet.revision != parent and snippet.path == change.after_path:
            focus.extend(change.after_lines)
    label = (f"{snippet.kind} {snippet.symbol!r} — {snippet.path!r}:"
             f"{snippet.start_line}-{snippet.end_line} @ {snippet.revision}")
    return Block(label + f" ({snippet.reason})", snippet.text, focus=tuple(focus), start_line=snippet.start_line)


def render_context(commit, parent, message, diff, files, functions, fallback,
                   supplements, diagnostics, limits) -> str:
    header = f"# Repair commit context\n\nCommit: `{commit}`\n\nParent: `{parent}`\n\n"
    primary = [snippet for function in functions for snippet in (function.before, function.after) if snippet]
    primary.extend(fallback)
    diff_focus = tuple(index + 1 for index, line in enumerate(diff.splitlines())
                       if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
    warning_lines = [f"- {item.code}: {item.message!r}\n" for item in diagnostics]
    warning_budget = min(2000, limits.markdown_chars // 8)
    warnings = ""
    for line in warning_lines:
        if len(warnings) + len(line) > warning_budget:
            break
        warnings += line
    footer_reserve = 200
    available = limits.markdown_chars - len(header) - len(warnings) - footer_reserve - 80
    categories = [
        ("Commit message", [Block("Description", message, "text")], 0.08),
        ("Patch diff", [Block("Historical diff", diff, "diff", diff_focus)], 0.22),
        ("Changed source", [_source_block(item, files, parent) for item in primary], 0.50),
        ("Local supplementary source", [_source_block(item, ()) for item in supplements], 0.20),
    ]
    sections, clipped = [], False
    for title, blocks, fraction in categories:
        section, truncated = _section(title, blocks, max(0, int(available * fraction)))
        sections.append(section)
        clipped |= truncated
    if clipped:
        diagnostics.append(Diagnostic("presentation_truncated", "Markdown budget omitted source or diff material"))
    footer = (f"\n## Collection notes\n\n{len(diagnostics)} diagnostic(s). "
              "Full provenance, raw collected material, and diagnostics are in context.json.\n")
    document = header + "\n".join(sections) + "\n" + warnings + footer
    if len(document) > limits.markdown_chars:
        # Tiny budgets may not fit even section labels; emit an explicit summary.
        document = header + "Presentation omitted by character budget; see context.json.\n" + footer
        if not clipped:
            diagnostics.append(Diagnostic("presentation_truncated", "Markdown budget omitted presentation"))
    return document
