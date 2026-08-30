"""
diff_parser.py — Parse unified diffs into structured FileDiff objects.

Uses the ``unidiff`` library.  A ``PatchSet`` is a list of ``PatchedFile``
objects; each ``PatchedFile`` **is itself** a list of ``Hunk`` objects.
There is no ``.hunks`` attribute — iterating the ``PatchedFile`` directly
yields the hunks.

Incorrect (raises AttributeError on real PatchSet objects):
    for hunk in patched_file.hunks:   # AttributeError: 'PatchedFile' has no 'hunks'

Correct:
    for hunk in patched_file:         # PatchedFile is a list[Hunk]

Also exposes the full Fatima-authored interface (build_diff_schema, parse_diff,
ChangedFileInfo, and the constructor-form DiffParser) so that any import of
``diff_parser`` from within the agents/ package finds all public symbols.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from unidiff import PatchSet

logger = logging.getLogger(__name__)


@dataclass
class HunkSummary:
    """A single changed block extracted from a file."""

    source_start: int
    source_length: int
    target_start: int
    target_length: int
    added_lines: int
    removed_lines: int
    section_header: str


@dataclass
class FileDiff:
    """Structured representation of one changed file in a diff."""

    path: str
    is_added_file: bool
    is_removed_file: bool
    is_modified_file: bool
    total_added: int
    total_removed: int
    hunks: list[HunkSummary] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Language detection (from root diff_parser.py)
# ---------------------------------------------------------------------------

EXT_TO_LANGUAGE = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".java": "java",
    ".go": "go", ".rb": "ruby", ".php": "php", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp", ".rs": "rust",
    ".sql": "sql", ".yaml": "yaml", ".yml": "yaml", ".json": "json",
    ".md": "markdown", ".html": "html", ".css": "css",
    ".sh": "shell", ".proto": "protobuf", ".tf": "terraform",
}

CONTEXT_WINDOW_LINES = 5


def detect_language(path: str) -> str:
    _, ext = os.path.splitext(path)
    return EXT_TO_LANGUAGE.get(ext.lower(), "unknown")


# ---------------------------------------------------------------------------
# ChangedFileInfo — used by build_diff_schema / parse_diff
# ---------------------------------------------------------------------------

class ChangedFileInfo:
    """Information about a single changed file in a diff."""

    def __init__(
        self,
        path: str,
        is_binary: bool = False,
        is_renamed: bool = False,
        is_deleted: bool = False,
        old_lines: Optional[Tuple[int, int]] = None,
        new_lines: Optional[Tuple[int, int]] = None,
        hunk_context: Optional[str] = None,
    ):
        self.path = path
        self.language = detect_language(path)
        self.is_binary = is_binary
        self.is_renamed = is_renamed
        self.is_deleted = is_deleted
        self.old_lines = old_lines
        self.new_lines = new_lines
        self.hunk_context = hunk_context
        self.hunks: list = []
        self.structured_hunks: List[Dict] = []
        self.context_before = ""
        self.context_after = ""

    def to_dict(self) -> Dict:
        return {
            "path": self.path,
            "language": self.language,
            "is_binary": self.is_binary,
            "is_renamed": self.is_renamed,
            "is_deleted": self.is_deleted,
            "old_lines": self.old_lines,
            "new_lines": self.new_lines,
            "hunk_context": self.hunk_context,
        }

    def to_schema_dict(self) -> Dict:
        return {
            "path": self.path,
            "language": self.language,
            "change_type": (
                "deleted" if self.is_deleted
                else ("renamed" if self.is_renamed else "modified")
            ),
            "hunks": self.structured_hunks,
            "context_before": self.context_before,
            "context_after": self.context_after,
        }

    def __repr__(self):
        return f"<ChangedFile {self.path}>"


# ---------------------------------------------------------------------------
# DiffParser — constructor form (Fatima's interface) + method form (original)
# ---------------------------------------------------------------------------

class DiffParser:
    """Parse a unified diff.

    Supports two usage patterns:

    *Constructor form* (Fatima's interface, used by tests & build_diff_schema):

        parser = DiffParser(diff_text)
        files  = parser.get_changed_files()
        stats  = parser.get_stats()

    *Method form* (original agents/ interface):

        parser  = DiffParser()
        results = parser.parse(diff_text)
    """

    def __init__(self, diff_text: str = "") -> None:
        self.diff_text = diff_text
        self.patch_set = None
        if diff_text:
            self._parse()

    # ------------------------------------------------------------------
    # Constructor-form public API
    # ------------------------------------------------------------------

    def _parse(self) -> None:
        try:
            self.patch_set = PatchSet.from_string(self.diff_text)
        except Exception:
            logger.exception("Failed to parse diff with unidiff")
            raise

    def get_changed_files(self) -> List[ChangedFileInfo]:
        if self.patch_set is None:
            return []
        changed_files = []
        for patched_file in self.patch_set:
            if patched_file.is_binary_file:
                changed_files.append(ChangedFileInfo(path=patched_file.path, is_binary=True))
                continue
            is_renamed = bool(patched_file.is_rename)
            is_deleted = bool(patched_file.is_removed_file)
            old_lines = self._get_line_range(patched_file, "old")
            new_lines = self._get_line_range(patched_file, "new")
            hunk_context = self._extract_hunk_context(patched_file)
            file_info = ChangedFileInfo(
                path=patched_file.path,
                is_binary=False,
                is_renamed=is_renamed,
                is_deleted=is_deleted,
                old_lines=old_lines,
                new_lines=new_lines,
                hunk_context=hunk_context,
            )
            file_info.hunks = list(patched_file)
            file_info.structured_hunks = self._build_structured_hunks(patched_file)
            before, after = self._context_windows(patched_file)
            file_info.context_before = before
            file_info.context_after = after
            changed_files.append(file_info)
        return changed_files

    def get_stats(self) -> Dict:
        if self.patch_set is None:
            return {"total_files": 0, "total_additions": 0, "total_deletions": 0, "total_changes": 0}
        total_additions = sum(f.added for f in self.patch_set)
        total_deletions = sum(f.removed for f in self.patch_set)
        total_files = len(self.patch_set)
        return {
            "total_files": total_files,
            "total_additions": total_additions,
            "total_deletions": total_deletions,
            "total_changes": total_additions + total_deletions,
        }

    # ------------------------------------------------------------------
    # Method form (original agents/ interface)
    # ------------------------------------------------------------------

    def parse(self, diff_text: str) -> list[FileDiff]:
        """Return one :class:`FileDiff` per changed file in *diff_text*."""
        patch = PatchSet(diff_text)
        return [self._parse_file_diff(pf) for pf in patch]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_file_diff(patched_file) -> FileDiff:
        hunks: list[HunkSummary] = []
        for hunk in patched_file:
            hunks.append(
                HunkSummary(
                    source_start=hunk.source_start,
                    source_length=hunk.source_length,
                    target_start=hunk.target_start,
                    target_length=hunk.target_length,
                    added_lines=hunk.added,
                    removed_lines=hunk.removed,
                    section_header=hunk.section_header,
                )
            )
        return FileDiff(
            path=patched_file.path,
            is_added_file=patched_file.is_added_file,
            is_removed_file=patched_file.is_removed_file,
            is_modified_file=patched_file.is_modified_file,
            total_added=patched_file.added,
            total_removed=patched_file.removed,
            hunks=hunks,
        )

    @staticmethod
    def _get_line_range(patched_file, file_type: str) -> Optional[Tuple[int, int]]:
        start_line = None
        end_line = None
        for hunk in patched_file:
            if file_type == "old":
                hunk_start = hunk.source_start
                hunk_length = hunk.source_length or 0
            else:
                hunk_start = hunk.target_start
                hunk_length = hunk.target_length or 0
            if hunk_length == 0:
                continue
            hunk_end = hunk_start + hunk_length - 1
            if start_line is None or hunk_start < start_line:
                start_line = hunk_start
            if end_line is None or hunk_end > end_line:
                end_line = hunk_end
        if start_line and end_line:
            return (start_line, end_line)
        return None

    @staticmethod
    def _build_structured_hunks(patched_file) -> List[Dict]:
        structured = []
        for hunk in patched_file:
            lines = []
            for line in hunk:
                if line.is_context:
                    line_type = "ctx"
                elif line.is_added:
                    line_type = "add"
                elif line.is_removed:
                    line_type = "del"
                else:
                    continue
                lines.append({"type": line_type, "content": line.value.rstrip("\n")})
            structured.append({
                "source_start": hunk.source_start,
                "source_length": hunk.source_length,
                "target_start": hunk.target_start,
                "target_length": hunk.target_length,
                "lines": lines,
            })
        return structured

    @staticmethod
    def _context_windows(patched_file) -> Tuple[str, str]:
        if not patched_file:
            return "", ""
        first_hunk = patched_file[0]
        last_hunk = patched_file[-1]
        before_lines = [l.value.rstrip("\n") for l in first_hunk if l.is_context][:CONTEXT_WINDOW_LINES]
        after_lines_all = [l.value.rstrip("\n") for l in last_hunk if l.is_context]
        after_lines = after_lines_all[-CONTEXT_WINDOW_LINES:] if after_lines_all else []
        return "\n".join(before_lines), "\n".join(after_lines)

    @staticmethod
    def _extract_hunk_context(patched_file) -> Optional[str]:
        if not patched_file:
            return None
        context_lines = [f"=== File: {patched_file.path} ===\n"]
        for hunk in patched_file:
            context_lines.append(
                f"@@ Lines {hunk.source_start}-{hunk.source_start + (hunk.source_length or 0)} "
                f"→ {hunk.target_start}-{hunk.target_start + (hunk.target_length or 0)} @@\n"
            )
            for line in hunk:
                if line.is_context:
                    context_lines.append(f"  {line.value}")
                elif line.is_added:
                    context_lines.append(f"+ {line.value}")
                elif line.is_removed:
                    context_lines.append(f"- {line.value}")
            context_lines.append("\n")
        return "".join(context_lines)


# ---------------------------------------------------------------------------
# Module-level convenience functions (Fatima's interface)
# ---------------------------------------------------------------------------

def parse_diff(diff_text: str) -> Tuple[List[ChangedFileInfo], Dict]:
    """Parse *diff_text* and return ``(changed_files, stats)``.

    Raises:
        ValueError: if diff_text is None.
    """
    if diff_text is None:
        raise ValueError("diff_text must not be None")
    parser = DiffParser(diff_text)
    return parser.get_changed_files(), parser.get_stats()


def build_diff_schema(
    pr_id: int,
    repo: str,
    diff_text: str,
    change_type: str = "unknown",
    change_confidence: float = 0.0,
) -> Dict:
    """Build the full structured diff object matching schema/diff_schema.json."""
    changed_files, _stats = parse_diff(diff_text)
    return {
        "pr_id": pr_id,
        "repo": repo,
        "files": [f.to_schema_dict() for f in changed_files if not f.is_binary],
        "change_type": change_type,
        "change_confidence": change_confidence,
        "diff_text_hash": hashlib.sha256(diff_text.encode("utf-8")).hexdigest(),
    }
