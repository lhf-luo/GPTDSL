"""Command-line export of read-only historical patch context."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from .patch_context import ContextLimits, PatchContextError, prepare_patch_context


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gptdsl")
    subcommands = parser.add_subparsers(dest="command", required=True)
    context = subcommands.add_parser("context", help="Prepare repair-commit source context")
    context.add_argument("--repo", type=Path, required=True)
    context.add_argument("--commit", required=True)
    context.add_argument("--out", type=Path, required=True)
    context.add_argument("--overwrite", action="store_true")
    context.add_argument("--max-context-chars", type=int, default=32_000)
    return parser


def _export(result, output: Path, overwrite: bool) -> None:
    output = output.resolve()
    if output.is_relative_to(Path(result.repository).resolve()):
        raise ValueError("Output must be outside the input repository to preserve its worktree")
    targets = [output / "context.json", output / "context.md"]
    if not overwrite and any(target.exists() or target.is_symlink() for target in targets):
        raise FileExistsError("Context output exists; choose another directory or use --overwrite")
    payloads = [json.dumps(result.to_dict(), ensure_ascii=True, indent=2) + "\n", result.markdown]
    output.mkdir(parents=True, exist_ok=True)
    created = []
    with tempfile.TemporaryDirectory(prefix=".gptdsl-", dir=output) as staging:
        temporary = [Path(staging) / target.name for target in targets]
        for path, text in zip(temporary, payloads, strict=True):
            path.write_text(text, encoding="utf-8", newline="\n")
        try:
            for path, target in zip(temporary, targets, strict=True):
                if overwrite:
                    os.replace(path, target)
                else:
                    os.link(path, target)  # Atomic no-clobber publication, including races.
                    created.append(target)
        except OSError:
            for target in created:
                target.unlink()
            raise


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        limits = ContextLimits(markdown_chars=args.max_context_chars)
        result = prepare_patch_context(args.repo, args.commit, limits=limits)
        _export(result, args.out, args.overwrite)
    except PatchContextError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"context_error: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote context.json and context.md to {args.out.resolve()} ({len(result.diagnostics)} diagnostics)")
    return 0
