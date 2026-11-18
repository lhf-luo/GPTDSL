"""Read Git objects without changing HEAD, index, worktree, or remotes."""

import os
from pathlib import Path
import subprocess

from .models import ContextLimits, Diagnostic, PatchContextError


class Repository:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.root = Path(self.run("rev-parse", "--show-toplevel").decode().strip())
        self.path = self.root

    def run(self, *args: str, data: bytes | None = None) -> bytes:
        env = os.environ.copy()
        env.update(GIT_NO_LAZY_FETCH="1", GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
        # Do not inherit variables that redirect Git to another repository/index.
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
            env.pop(key, None)
        command = ["git", "--no-pager", "--no-replace-objects", "--literal-pathspecs",
                   "-c", "core.quotePath=false", *args]
        try:
            result = subprocess.run(command, cwd=self.path, env=env, input=data,
                                    capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PatchContextError("git_unavailable", str(exc)) from exc
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise PatchContextError("git_error", detail or "Git command failed")
        return result.stdout

    def resolve(self, revision: str) -> tuple[str, str, str]:
        try:
            sha = self.run("rev-parse", "--verify", "--end-of-options",
                           f"{revision}^{{commit}}").decode().strip()
        except PatchContextError as exc:
            raise PatchContextError("commit_unavailable", str(exc)) from exc
        raw = self.run("cat-file", "commit", sha).decode("utf-8", errors="replace")
        headers, _, message = raw.partition("\n\n")
        parents = [line[7:] for line in headers.splitlines() if line.startswith("parent ")]
        if len(parents) != 1:
            code = "root_commit" if not parents else "merge_commit"
            raise PatchContextError(code, "A repair must have exactly one parent commit")
        try:
            self.run("cat-file", "commit", parents[0])
        except PatchContextError as exc:
            raise PatchContextError("parent_unavailable", "Parent object is missing locally") from exc
        return sha, parents[0], message.strip()

    def changes(self, parent: str, commit: str) -> list[tuple[str, str | None, str | None]]:
        parts = self.run("diff", "--name-status", "-z", "--no-relative", "--find-renames=50%",
                         "--no-ext-diff", "--no-textconv", parent, commit, "--").split(b"\0")
        changes = []
        index = 0
        while index < len(parts) and parts[index]:
            status = parts[index].decode("ascii")
            first = parts[index + 1].decode("utf-8", errors="surrogateescape")
            index += 2
            if status.startswith(("R", "C")):
                second = parts[index].decode("utf-8", errors="surrogateescape")
                index += 1
                changes.append((status, first, second))
            else:
                changes.append((status, None if status == "A" else first,
                                None if status == "D" else first))
        return sorted(changes, key=lambda change: (change[1] or change[2] or "", change[0]))

    def diff(self, parent: str, commit: str, paths: tuple[str, ...] = ()) -> str:
        output = self.run("diff", "--no-ext-diff", "--no-textconv", "--no-color",
                          "--no-relative", "--src-prefix=a/", "--dst-prefix=b/",
                          "--diff-algorithm=myers", "--no-indent-heuristic",
                          "--find-renames=50%", "--unified=20", parent, commit, "--", *paths)
        return output.decode("utf-8", errors="replace")


class SourceReader:
    def __init__(self, repo: Repository, limits: ContextLimits, diagnostics: list[Diagnostic]):
        self.repo, self.limits, self.diagnostics = repo, limits, diagnostics
        self.cache: dict[tuple[str, str], str | None] = {}

    def read(self, revision: str, path: str, *, required: bool = False) -> str | None:
        key = (revision, path)
        if key not in self.cache:
            self.cache[key] = self._read(revision, path, required)
        return self.cache[key]

    def _read(self, revision: str, path: str, required: bool) -> str | None:
        obj = f"{revision}:{path}"
        try:
            size = int(self.repo.run("cat-file", "-s", obj))
        except PatchContextError:
            if required:
                self.diagnostics.append(Diagnostic("source_unavailable", "Source blob unavailable",
                                                   revision, path))
            return None
        if size > self.limits.source_bytes:
            self.diagnostics.append(Diagnostic("source_size_limit", f"Skipped {size}-byte source",
                                               revision, path))
            return None
        raw = self.repo.run("cat-file", "blob", obj)
        if b"\0" in raw:
            self.diagnostics.append(Diagnostic("binary_source", "Skipped binary source", revision, path))
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            self.diagnostics.append(Diagnostic("encoding_replaced", "Invalid UTF-8 replaced",
                                               revision, path))
            return raw.decode("utf-8", errors="replace")
