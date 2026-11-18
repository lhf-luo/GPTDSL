"""Public, serializable context results and collection limits."""

from dataclasses import asdict, dataclass, fields


class PatchContextError(Exception):
    """An input or Git failure that prevents preparing a context."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ContextLimits:
    include_depth: int = 3
    source_files: int = 128
    seed_symbols: int = 32
    root_symbols: int = 6
    supplement_entries: int = 12
    wrapper_lines: int = 24
    source_bytes: int = 2 * 1024 * 1024
    markdown_chars: int = 32_000

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{item.name} must be a positive integer")
        if self.markdown_chars < 512:
            raise ValueError("markdown_chars must be at least 512")


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    revision: str | None = None
    path: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class SourceSnippet:
    revision: str
    path: str
    start_line: int
    end_line: int
    kind: str
    symbol: str
    reason: str
    text: str


@dataclass(frozen=True)
class FileChange:
    status: str
    before_path: str | None
    after_path: str | None
    before_text: str | None
    after_text: str | None
    before_lines: tuple[int, ...]
    after_lines: tuple[int, ...]


@dataclass(frozen=True)
class FunctionChange:
    name: str
    before: SourceSnippet | None
    after: SourceSnippet | None


@dataclass(frozen=True)
class PatchContext:
    repository: str
    commit: str
    parent_commit: str
    message: str
    diff: str
    files: tuple[FileChange, ...]
    functions: tuple[FunctionChange, ...]
    fallback: tuple[SourceSnippet, ...]
    supplements: tuple[SourceSnippet, ...]
    diagnostics: tuple[Diagnostic, ...]
    limits: ContextLimits
    markdown: str
    schema_version: int = 1
    include_supplements: bool = True

    @property
    def complete(self) -> bool:
        """False if collection or presentation has any recorded limitation."""
        return not self.diagnostics

    def to_dict(self) -> dict:
        result = asdict(self)
        result["complete"] = self.complete
        return result
