"""CLI wiring and auditable selection artifacts."""

import json
from pathlib import Path

from ..export import check_available, external_output, publish
from ..patch_context import ContextLimits
from ..patch_context.repository import Repository
from . import SelectionLimits, select_patches
from .provider import ChatCompletionsReviewer, ReviewConfig


def add_select_command(subcommands):
    parser = subcommands.add_parser("select", help="Curate repair patches from history or a commit file")
    parser.add_argument("--repo", type=Path, required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--revision", help="History start or range (default: HEAD), e.g. v6.15..v6.16")
    source.add_argument("--commit-file", type=Path, help="UTF-8 file, one commit per line; no history expansion")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-commits", type=int, help="History scan limit (default: 100); not for --commit-file")
    parser.add_argument("--max-files", type=int, default=8)
    parser.add_argument("--max-changed-lines", type=int, default=300)
    parser.add_argument("--max-functions", type=int, default=6)
    parser.add_argument("--max-context-chars", type=int, default=32_000)
    parser.add_argument("--ai", action="store_true", help="Send eligible context to the configured AI endpoint")
    parser.add_argument("--model", help="AI model override (default: deepseek-flash)")
    parser.add_argument("--base-url", help="API root override (default: https://api.deepseek.com/v1)")
    parser.add_argument("--overwrite", action="store_true")


def run_select(args) -> int:
    if args.commit_file is not None and args.max_commits is not None:
        raise ValueError("--max-commits only applies to history input; omit it with --commit-file")
    if not args.ai and (args.model or args.base_url):
        raise ValueError("--model and --base-url require --ai")
    reviewer = ChatCompletionsReviewer(ReviewConfig.from_env(args.model, args.base_url)) if args.ai else None
    limits = SelectionLimits(100 if args.max_commits is None else args.max_commits, args.max_files, args.max_changed_lines,
                              args.max_functions, ContextLimits(markdown_chars=args.max_context_chars))
    repository = Repository(args.repo)
    output = external_output(repository.root, args.out)
    check_available(output, ("commits.txt", "candidates.txt", "selection.json"), args.overwrite)
    result = select_patches(repository.root, args.revision, commit_file=args.commit_file,
                            limits=limits, reviewer=reviewer)
    report = result.to_dict()
    report["review_mode"] = "ai" if args.ai else "offline"
    publish(output, {
        "commits.txt": "".join(f"{sha}\n" for sha in result.selected_commits),
        "candidates.txt": "".join(f"{sha}\n" for sha in result.candidate_commits),
        "selection.json": json.dumps(report, ensure_ascii=True, indent=2) + "\n",
    }, args.overwrite)
    counts = report["counts"]
    duplicates = f", {counts['duplicate']} duplicate" if "duplicate" in counts else ""
    print(f"Selection: {counts['suitable']} suitable, {counts['needs_review']} need review, "
          f"{counts['out_of_scope']} out of scope, {counts['error']} errors{duplicates}. Output: {output}")
    return 2 if counts["error"] else 0
