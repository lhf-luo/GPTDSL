"""Command-line export of read-only historical patch context."""

import argparse
from pathlib import Path
import sys

from .batch import run_batch
from .export import export_context
from .patch_context import ContextLimits, PatchContextError, prepare_patch_context


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gptdsl")
    subcommands = parser.add_subparsers(dest="command", required=True)
    context = subcommands.add_parser("context", help="Prepare repair-commit source context")
    context.add_argument("--repo", type=Path, required=True)
    commits = context.add_mutually_exclusive_group(required=True)
    commits.add_argument("--commit", help="One repair commit reference")
    commits.add_argument("--commit-file", type=Path, help="UTF-8 file, one repair commit reference per line")
    context.add_argument("--out", type=Path, required=True)
    context.add_argument("--overwrite", action="store_true")
    context.add_argument("--max-context-chars", type=int, default=32_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        limits = ContextLimits(markdown_chars=args.max_context_chars)
        if args.commit_file is not None:
            return run_batch(args.repo, args.commit_file, args.out, limits, args.overwrite)
        result = prepare_patch_context(args.repo, args.commit, limits=limits)
        export_context(result, args.out, args.overwrite)
    except PatchContextError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"context_error: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote context.json and context.md to {args.out.resolve()} ({len(result.diagnostics)} diagnostics)")
    return 0
