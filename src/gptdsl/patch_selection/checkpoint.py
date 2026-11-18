"""Atomic selection snapshots and validated resumption; no credentials are stored."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path

from ..export import check_available, publish
from .models import SelectionResult


OUTPUTS = ("selection.json", "commits.txt", "candidates.txt")
_STATUSES = {"suitable", "needs_review", "out_of_scope", "error", "duplicate"}


def _read_checkpoint(path, configuration, limits):
    raw = path.read_bytes()
    try:
        report = json.loads(raw)
        run = report["run"]
        if report["schema_version"] != 1 or run["checkpoint_version"] != 1:
            raise ValueError("Unsupported checkpoint version")
        if run["configuration"] != configuration or report["limits"] != asdict(limits):
            raise ValueError("Checkpoint review mode, model or selection parameters changed")
        entries, requests = report["entries"], report["requests"]
        if not isinstance(entries, list) or not isinstance(requests, list):
            raise ValueError("Invalid checkpoint entries or requests")
        for item in entries:
            if item["status"] not in _STATUSES or type(item["checks"]["eligible"]) is not bool:
                raise ValueError("Invalid checkpoint entry")
        if not all(isinstance(item, dict) for item in requests):
            raise ValueError("Invalid checkpoint requests")
        result = SelectionResult(report["repository"], report["revision"], limits, tuple(entries),
                                 report["commit_file"], tuple(requests))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Cannot resume selection: {exc}") from exc
    return result, hashlib.sha256(raw).hexdigest()


class SelectionStore:
    """Own one output directory while saving completed prefixes after each entry."""

    def __init__(self, output: Path, configuration: dict, *, overwrite=False, resume=False):
        self.output, self.configuration = output, configuration
        self.overwrite, self.resume = overwrite, resume
        self.expected_hash = None
        self.handle = None
        self.latest = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        if self.handle is not None:
            self.handle.close()  # OS releases the lock even on process termination.
            self.handle = None

    def load(self, limits):
        if not self.resume:
            check_available(self.output, OUTPUTS, self.overwrite)
            return None
        result, self.expected_hash = _read_checkpoint(self.output / "selection.json", self.configuration, limits)
        return result

    def _acquire(self):
        self.output.mkdir(parents=True, exist_ok=True)
        handle = (self.output / ".selection.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise ValueError("Selection output is in use by another process") from exc
        self.handle = handle
        if self.resume:
            current = hashlib.sha256((self.output / "selection.json").read_bytes()).hexdigest()
            if current != self.expected_hash:
                raise ValueError("Checkpoint changed while preparing inputs; run --resume again")
        else:
            check_available(self.output, OUTPUTS, self.overwrite)

    def save(self, result: SelectionResult, state="running"):
        self.latest = result
        if self.handle is None:
            self._acquire()
        report = result.to_dict()
        report["review_mode"] = self.configuration["review_mode"]
        report["run"] = {"checkpoint_version": 1, "state": state,
                         "processed": len(result.entries), "total": len(result.requests),
                         "configuration": self.configuration}
        # The report is authoritative. Derived lists can be regenerated after a crash.
        publish(self.output, {
            "selection.json": json.dumps(report, ensure_ascii=True, indent=2) + "\n",
            "commits.txt": "".join(f"{sha}\n" for sha in result.selected_commits),
            "candidates.txt": "".join(f"{sha}\n" for sha in result.candidate_commits),
        }, overwrite=True)
