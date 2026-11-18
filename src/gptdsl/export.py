"""Publish context artifacts without implicit overwrites."""

import json
import os
from pathlib import Path
import tempfile


def external_output(repository: str | Path, output: Path) -> Path:
    output = output.resolve()
    if output.is_relative_to(Path(repository).resolve()):
        raise ValueError("Output must be outside the input repository to preserve its worktree")
    return output


def check_available(output: Path, names: tuple[str, ...], overwrite: bool) -> None:
    if not overwrite and any((output / name).exists() or (output / name).is_symlink() for name in names):
        raise FileExistsError("Context output exists; choose another directory or use --overwrite")


def publish(output: Path, payloads: dict[str, str], overwrite: bool) -> None:
    check_available(output, tuple(payloads), overwrite)
    output.mkdir(parents=True, exist_ok=True)
    created = []
    with tempfile.TemporaryDirectory(prefix=".gptdsl-", dir=output) as staging:
        for name, text in payloads.items():
            (Path(staging) / name).write_text(text, encoding="utf-8", newline="\n")
        try:
            for name in payloads:
                temporary, target = Path(staging) / name, output / name
                if overwrite:
                    os.replace(temporary, target)
                else:
                    os.link(temporary, target)  # Atomic no-clobber publication, including races.
                    created.append(target)
        except OSError:
            for target in created:
                target.unlink()
            raise


def export_context(result, output: Path, overwrite: bool) -> None:
    output = external_output(result.repository, output)
    publish(output, {
        "context.json": json.dumps(result.to_dict(), ensure_ascii=True, indent=2) + "\n",
        "context.md": result.markdown,
    }, overwrite)
