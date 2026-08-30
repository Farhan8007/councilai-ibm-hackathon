"""
Diff parser for CouncilAI
Parses raw git diffs and extracts structured information for agent analysis.
Uses python-unidiff library for robust parsing.

Produces two shapes:
  1. ChangedFileInfo objects — used to populate the `changed_files` DB table.
  2. A dict matching schema/diff_schema.json — the structured diff contract
     shared with Person A at the Hour 1 sync. Agents consume this shape
     directly (or via test_diff.json fixture), never the raw git diff.
"""

from typing import List, Dict, Optional, Tuple
from unidiff import PatchSet
import hashlib
import logging
import os
import re

logger = logging.getLogger(__name__)

EXT_TO_LANGUAGE = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".java": "java",
    ".go": "go", ".rb": "ruby", ".php": "php", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp", ".rs": "rust",
    ".sql": "sql", ".yaml": "yaml", ".yml": "yaml", ".json": "json",
    ".md": "markdown", ".html": "html", ".css": "css",
    ".sh": "shell", ".proto": "protobuf", ".tf": "terraform",
}

CONTEXT_WINDOW_LINES = 5  # agreed with Person A at the Hour 1 sync


def detect_language(path: str) -> str:
    _, ext = os.path.splitext(path)
    return EXT_TO_LANGUAGE.get(ext.lower(), "unknown")


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
        self.old_lines = old_lines  # (start, end)
        self.new_lines = new_lines  # (start, end)
        self.hunk_context = hunk_context  # Surrounding code for LLM analysis
        self.hunks = []  # List of unidiff Hunk objects (raw)
        self.structured_hunks: List[Dict] = []  # matches diff_schema.json "hunks"
        self.context_before = ""
        self.context_after = ""

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization (internal / DB shape)."""
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
        """Convert to the diff_schema.json file entry shape shared with Person A."""
        return {
            "path": self.path,
            "language": self.language,
            "change_type": "deleted" if self.is_deleted else ("renamed" if self.is_renamed else "modified"),
            "hunks": self.structured_hunks,
            "context_before": self.context_before,
            "context_after": self.context_after,
        }

    def __repr__(self):
        return f"<ChangedFile {self.path}>"


class DiffParser:
    """
    Parse raw git diffs and extract structured change information.
    """

    def __init__(self, diff_text: str):
        """
        Initialize parser with raw diff text.

        Args:
            diff_text: Raw git diff output (from GitHub webhook or `git diff`)
        """
        self.diff_text = diff_text
        self.patch_set = None
        self._parse()

    def _parse(self):
        """Parse the diff using unidiff."""
        try:
            self.patch_set = PatchSet.from_string(self.diff_text)
        except Exception:
            logger.exception("Failed to parse diff with unidiff")
            raise

    def get_changed_files(self) -> List[ChangedFileInfo]:
        """
        Extract all changed files from the diff.

        Returns:
            List of ChangedFileInfo objects
        """
        changed_files = []

        for patched_file in self.patch_set:
            # Handle binary files
            if patched_file.is_binary_file:
                changed_files.append(
                    ChangedFileInfo(
                        path=patched_file.path,
                        is_binary=True,
                    )
                )
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

    def _get_line_range(self, patched_file, file_type: str) -> Optional[Tuple[int, int]]:
        """
        Get the line range for a file (old or new).
        """
        if not patched_file:
            return None

        start_line = None
        end_line = None

        for hunk in patched_file:
            if file_type == "old":
                hunk_start = hunk.source_start
                hunk_length = hunk.source_length or 0
            else:  # new
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

    def _build_structured_hunks(self, patched_file) -> List[Dict]:
        """
        Build the `hunks: [{lines: [{type, content}]}]` shape from
        diff_schema.json for one file.
        """
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

    def _context_windows(self, patched_file) -> Tuple[str, str]:
        """
        Build the context_before / context_after strings: up to
        CONTEXT_WINDOW_LINES of unchanged (context) lines immediately
        surrounding the first and last hunk, respectively.
        """
        if not patched_file:
            return "", ""

        first_hunk = patched_file[0]
        last_hunk = patched_file[-1]

        before_lines = [l.value.rstrip("\n") for l in first_hunk if l.is_context][:CONTEXT_WINDOW_LINES]
        after_lines_all = [l.value.rstrip("\n") for l in last_hunk if l.is_context]
        after_lines = after_lines_all[-CONTEXT_WINDOW_LINES:] if after_lines_all else []

        return "\n".join(before_lines), "\n".join(after_lines)

    def _extract_hunk_context(self, patched_file) -> Optional[str]:
        """
        Extract hunk context (surrounding code lines) for LLM analysis /
        human-readable audit logging.
        """
        if not patched_file:
            return None

        context_lines = []
        context_lines.append(f"=== File: {patched_file.path} ===\n")

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

    def get_stats(self) -> Dict:
        """
        Get overall diff statistics.
        """
        total_additions = sum(f.added for f in self.patch_set)
        total_deletions = sum(f.removed for f in self.patch_set)
        total_files = len(self.patch_set)

        return {
            "total_files": total_files,
            "total_additions": total_additions,
            "total_deletions": total_deletions,
            "total_changes": total_additions + total_deletions,
        }


def parse_diff(diff_text: str) -> Tuple[List[ChangedFileInfo], Dict]:
    """
    Convenience function to parse a diff and return structured data.

    Raises:
        ValueError: if diff_text is None
    """
    if diff_text is None:
        raise ValueError("diff_text must not be None")
    parser = DiffParser(diff_text)
    changed_files = parser.get_changed_files()
    stats = parser.get_stats()
    return changed_files, stats


def build_diff_schema(
    pr_id: int,
    repo: str,
    diff_text: str,
    change_type: str = "unknown",
    change_confidence: float = 0.0,
) -> Dict:
    """
    Build the full structured diff object matching schema/diff_schema.json.
    This is the exact contract Person A's agents consume — either live via
    the orchestrator or offline via test_diff.json.
    """
    changed_files, _stats = parse_diff(diff_text)
    return {
        "pr_id": pr_id,
        "repo": repo,
        "files": [f.to_schema_dict() for f in changed_files if not f.is_binary],
        "change_type": change_type,
        "change_confidence": change_confidence,
        "diff_text_hash": hashlib.sha256(diff_text.encode("utf-8")).hexdigest(),
    }


# ===== TEST / EXAMPLE =====

if __name__ == "__main__":
    # Example diff for testing — deliberately contains a SQL-injection-shaped
    # auth bug and a hardcoded secret, per the Hour 1 sync fixture agreement.
    example_diff = """diff --git a/auth.py b/auth.py
index e69de29..abc1234 100644
--- a/auth.py
+++ b/auth.py
@@ -0,0 +1,10 @@
+def check_password(password):
+    # VULNERABLE: Direct comparison without hashing
+    if password == "hardcoded_secret":
+        return True
+    return False
+
+def login(username, password):
+    if check_password(password):
+        return {"user": username, "token": "abc123"}
+    return {"error": "Invalid credentials"}
diff --git a/config.yaml b/config.yaml
index 1234567..abcdefg 100644
--- a/config.yaml
+++ b/config.yaml
@@ -1,5 +1,7 @@
 database:
   host: localhost
   port: 5432
+  password: secret123
+  api_key: sk-1234567890
 cache:
   ttl: 3600
"""

    parser = DiffParser(example_diff)

    print("\n=== PARSED FILES ===")
    for file_info in parser.get_changed_files():
        print(f"\nFile: {file_info.path} ({file_info.language})")
        print(f"  Binary: {file_info.is_binary}")
        print(f"  New lines: {file_info.new_lines}")
        if file_info.hunk_context:
            print(f"  Context:\n{file_info.hunk_context[:200]}...")

    print("\n=== STATS ===")
    print(parser.get_stats())

    print("\n=== SCHEMA-SHAPED OUTPUT (excerpt) ===")
    schema = build_diff_schema(pr_id=1, repo="demo/councilai-demo", diff_text=example_diff,
                                change_type="auth_change", change_confidence=0.92)
    import json
    print(json.dumps(schema, indent=2)[:800], "...")

    # Write the fixture file Person A depends on for offline agent testing
    with open("test_diff.json", "w") as f:
        json.dump(schema, f, indent=2)
    print("\n✓ Wrote test_diff.json fixture")
