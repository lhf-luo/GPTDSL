"""Sequential context preparation for a UTF-8 file of commit references."""

from collections import Counter
import json
from pathlib import Path

from .commit_file import read_commit_file
from .export import check_available, export_context, external_output, publish
from .patch_context import ContextLimits, PatchContextError, prepare_patch_context
from .patch_context.repository import Repository


def _prepare_one(repository, reference, line_number, output, limits, overwrite, seen):
    item = {"line": line_number, "input": reference, "commit": None, "status": "error"}
    try:
        if any(character.isspace() for character in reference):
            raise ValueError("Each non-comment line must contain exactly one commit reference")
        commit, _parent, _message = repository.resolve(reference)
        item["commit"] = commit
        if commit in seen:
            item.update(status="duplicate", duplicate_of=seen[commit])
            return item
        seen[commit] = line_number
        destination = external_output(repository.root, output / commit)
        check_available(destination, ("context.json", "context.md"), overwrite)
        result = prepare_patch_context(repository.root, commit, limits=limits)
        export_context(result, destination, overwrite)
        item.update(status="ok", output=commit, complete=result.complete,
                    diagnostics=len(result.diagnostics))
    except PatchContextError as exc:
        item.update(error={"code": exc.code, "message": str(exc)})
    except (ValueError, OSError) as exc:
        item.update(error={"code": "context_error", "message": str(exc)})
    return item


def run_batch(repo: Path, commit_file: Path, output: Path,
              limits: ContextLimits, overwrite: bool) -> int:
    requests = read_commit_file(commit_file)
    repository = Repository(repo)
    output = external_output(repository.root, output)
    check_available(output, ("summary.json",), overwrite)
    entries, seen = [], {}
    for line_number, reference in requests:
        item = _prepare_one(repository, reference, line_number, output, limits, overwrite, seen)
        entries.append(item)
        print(f"Line {line_number}: {reference} — {item['status']}")
    counts = Counter(item["status"] for item in entries)
    summary = {
        "schema_version": 1,
        "repository": str(repository.root),
        "commit_file": str(commit_file.resolve()),
        "counts": {"total": len(entries), "succeeded": counts["ok"],
                   "failed": counts["error"], "duplicates": counts["duplicate"]},
        "entries": entries,
    }
    publish(output, {"summary.json": json.dumps(summary, ensure_ascii=True, indent=2) + "\n"}, overwrite)
    print(f"Batch finished: {counts['ok']} succeeded, {counts['error']} failed, "
          f"{counts['duplicate']} duplicates. Summary: {output / 'summary.json'}")
    return 2 if counts["error"] else 0
