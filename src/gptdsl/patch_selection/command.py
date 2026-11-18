"""CLI wiring and auditable selection artifacts."""

import hashlib
from pathlib import Path
from time import monotonic

from ..export import external_output
from ..patch_context import ContextLimits
from ..patch_context.repository import Repository
from . import SelectionLimits, select_patches
from .checkpoint import SelectionStore
from .models import CONTEXT_POLICY
from .provider import ChatCompletionsReviewer, PROMPT, ReviewConfig


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
    restart = parser.add_mutually_exclusive_group()
    restart.add_argument("--overwrite", action="store_true", help="Start over, replacing existing results")
    restart.add_argument("--resume", action="store_true", help="Continue from completed entries in selection.json")


def _configuration_from_config(config):
    if config is None:
        return {"review_mode": "offline", "context_policy": CONTEXT_POLICY}
    return {"review_mode": "ai", "model": config.model, "base_url": config.base_url,
            "context_policy": CONTEXT_POLICY, "timeout": config.timeout,
            "prompt_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()}


def _entry_label(item):
    commit = item.get("commit")
    return commit[:12] if commit else ascii(item.get("input", "unknown"))[:80]


def _save_progress(store, resume):
    started = monotonic()
    initialized = False

    def report(result):
        nonlocal initialized
        store.save(result)
        done, total = len(result.entries), len(result.requests)
        percent = 100 * done / total if total else 100.0
        if not initialized:
            action = "Resuming" if resume else "Starting"
            print(f"{action}: {done}/{total} ({percent:.1f}%) completed", flush=True)
            initialized = True
        else:
            item = result.entries[-1]
            ai_status = ("reviewed" if "review" in item else
                         "attempted" if item["checks"].get("ai_review_attempted") else "not_called")
            print(f"Progress: {done}/{total} ({percent:.1f}%) | {_entry_label(item)} -> {item['status']} "
                  f"| saved | ai={ai_status} | elapsed {monotonic() - started:.1f}s", flush=True)
        if done < total:
            print(f"[{done + 1}/{total}] {_entry_label(result.requests[done])} | processing", flush=True)

    return report


def run_select(args) -> int:
    if args.commit_file is not None and args.max_commits is not None:
        raise ValueError("--max-commits only applies to history input; omit it with --commit-file")
    if not args.ai and (args.model or args.base_url):
        raise ValueError("--model and --base-url require --ai")
    config = ReviewConfig.from_env(args.model, args.base_url) if args.ai else None
    reviewer = ChatCompletionsReviewer(config) if config else None
    limits = SelectionLimits(100 if args.max_commits is None else args.max_commits, args.max_files, args.max_changed_lines,
                              args.max_functions, ContextLimits(markdown_chars=args.max_context_chars))
    repository = Repository(args.repo)
    output = external_output(repository.root, args.out)
    configuration = _configuration_from_config(config)
    with SelectionStore(output, configuration, overwrite=args.overwrite, resume=args.resume) as store:
        previous = store.load(limits)
        try:
            print("Preparing selection inputs...", flush=True)
            result = select_patches(repository.root, args.revision, commit_file=args.commit_file,
                                    limits=limits, reviewer=reviewer,
                                    progress=_save_progress(store, args.resume), previous=previous)
            store.save(result, "completed")
        except KeyboardInterrupt:
            if store.latest is not None:
                store.save(store.latest, "interrupted")
                print(f"Selection interrupted. Completed entries saved; use --resume to continue. Output: {output}",
                      flush=True)
            else:
                print("Selection interrupted before checkpoint initialization; no entries completed", flush=True)
            return 130
    counts = result.to_dict()["counts"]
    duplicates = f", {counts['duplicate']} duplicate" if "duplicate" in counts else ""
    print(f"Selection: {counts['suitable']} suitable, {counts['needs_review']} need review, "
          f"{counts['out_of_scope']} out of scope, {counts['error']} errors{duplicates}. Output: {output}", flush=True)
    return 2 if counts["error"] else 0
