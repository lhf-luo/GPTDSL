"""Small local Git histories; no kernel checkout or external services required."""

import os
from pathlib import Path
import subprocess

import pytest


class History:
    def __init__(self, path: Path):
        self.path = path
        path.mkdir()
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Context Test")
        self.git("config", "user.email", "context@example.invalid")
        self.git("config", "core.autocrlf", "false")

    def git(self, *args: str) -> str:
        env = os.environ.copy()
        env.update(GIT_OPTIONAL_LOCKS="0", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
            env.pop(key, None)
        result = subprocess.run(["git", *args], cwd=self.path, env=env, capture_output=True, check=True)
        return result.stdout.decode("utf-8", errors="replace").strip()

    def write(self, path: str, content: str | bytes):
        destination = self.path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)

    def commit(self, message: str) -> str:
        self.git("add", "--all")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def history(tmp_path):
    return History(tmp_path / "source")
