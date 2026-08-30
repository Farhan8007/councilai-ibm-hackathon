"""
CouncilAI GitHub / Ingestion layer test suite.
Tests HMAC validation, diff_parser, and the /webhook/github endpoint.
Does NOT contact real GitHub.
"""

import hashlib
import hmac
import json
import os
import sys
import types
import unittest.mock as mock

import jsonschema
import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WEBHOOK_SECRET = "test-secret"

SAMPLE_DIFF = """\
diff --git a/auth.py b/auth.py
index e69de29..abc1234 100644
--- a/auth.py
+++ b/auth.py
@@ -0,0 +1,6 @@
+def check_password(password):
+    if password == "hardcoded_secret":
+        return True
+    return False
+
+# end
diff --git a/config.yaml b/config.yaml
index 1234567..abcdefg 100644
--- a/config.yaml
+++ b/config.yaml
@@ -1,3 +1,5 @@
 database:
   host: localhost
   port: 5432
+  password: secret123
+  api_key: sk-1234567890
"""

BINARY_DIFF = """\
diff --git a/image.png b/image.png
index e69de29..abc1234 100644
Binary files a/image.png and b/image.png differ
"""

NO_HUNK_DIFF = """\
diff --git a/empty.py b/empty.py
index 0000000..e69de29 100644
--- a/empty.py
+++ b/empty.py
"""

GARBAGE_TEXT = "this is not a diff at all, just garbage text 12345 !!!"

WEBHOOK_PAYLOAD = json.dumps(
    {
        "action": "opened",
        "pull_request": {
            "number": 99,
            "title": "Test PR",
            "html_url": "https://github.com/org/repo/pull/99",
            "head": {"sha": "abc123def"},
        },
        "repository": {
            "name": "repo",
            "owner": {"login": "org"},
        },
    }
).encode()

CLOSED_PAYLOAD = json.dumps(
    {
        "action": "closed",
        "pull_request": {
            "number": 99,
            "title": "Test",
            "html_url": "",
            "head": {"sha": "abc"},
        },
        "repository": {"name": "repo", "owner": {"login": "org"}},
    }
).encode()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sig(body: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def _load_diff_schema():
    schema_path = os.path.join(os.path.dirname(__file__), "..", "schema", "diff_schema.json")
    with open(schema_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# FastAPI TestClient fixture (mocks DB + orchestrator to avoid real I/O)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app_client():
    """
    Returns a TestClient for the FastAPI app. Stubs out:
      - orchestrator.run_pipeline  (async, returns dummy result)
      - precedent_engine           (seed helper)
      - relevance_weights          (get/reload)
      - models                     (DB session, init_db)
    """
    fake_session = mock.MagicMock()

    for mod_name, attrs in {
        "orchestrator": {
            "run_pipeline": mock.AsyncMock(
                return_value={"review_id": 1, "status": "complete", "verdicts": []}
            )
        },
        "precedent_engine": {"seed_demo_precedents": mock.MagicMock(return_value=0)},
        "relevance_weights": {
            "get_all_weights": mock.MagicMock(return_value={}),
            "reload": mock.MagicMock(return_value={"weights": {}}),
        },
    }.items():
        m = types.ModuleType(mod_name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[mod_name] = m

    models_mod = types.ModuleType("models")
    for cls_name in [
        "AuditLog", "ChangedFile", "Conflict", "Opinion",
        "PrecedentDecision", "Review", "Verdict",
    ]:
        setattr(models_mod, cls_name, mock.MagicMock())
    models_mod.get_db_session = mock.MagicMock(return_value=fake_session)
    models_mod.init_db = mock.MagicMock()

    # backend/main.py imports Pydantic models from 'models'; add them to the stub.
    import os as _os, importlib, importlib.util as _ilu
    _backend_dir = _os.path.join(_os.path.dirname(__file__), "..", "backend")
    _spec = _ilu.spec_from_file_location("_backend_models", _os.path.join(_backend_dir, "models.py"))
    _bmod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_bmod)
    for _attr in ("AgentResult", "AgentRole", "HealthResponse", "ReviewRequest", "ReviewResponse"):
        setattr(models_mod, _attr, getattr(_bmod, _attr))

    sys.modules["models"] = models_mod

    # Patch dotenv so main.py's load_dotenv() is a no-op
    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda: None
    sys.modules.setdefault("dotenv", dotenv_mod)

    # Re-import main after stubs are in place.
    # Always load the root main.py explicitly to avoid picking up backend/main.py
    # when backend/ has been added to sys.path by other test modules.
    sys.modules.pop("main", None)
    import importlib.util as _main_ilu, os as _main_os
    _main_spec = _main_ilu.spec_from_file_location(
        "main",
        _main_os.path.join(_main_os.path.dirname(__file__), "..", "main.py"),
    )
    council_main = _main_ilu.module_from_spec(_main_spec)
    sys.modules["main"] = council_main
    _main_spec.loader.exec_module(council_main)

    async def _fake_get_db():
        yield fake_session

    council_main.app.dependency_overrides[council_main.get_db] = _fake_get_db

    with TestClient(council_main.app, raise_server_exceptions=False) as c:
        yield c


# ===========================================================================
# SECTION 1 — HMAC Signature Validation (unit, no HTTP)
# ===========================================================================

class TestHMACValidation:
    """Direct unit tests of validate_github_webhook_signature."""

    def setup_method(self):
        # Ensure a clean env before each test
        os.environ["GITHUB_WEBHOOK_SECRET"] = WEBHOOK_SECRET

    def teardown_method(self):
        os.environ.pop("GITHUB_WEBHOOK_SECRET", None)

    def test_T1_valid_signature_accepted(self):
        """T1 — Valid HMAC-SHA256 signature → True."""
        from github_client import validate_github_webhook_signature
        sig = _make_sig(WEBHOOK_PAYLOAD, WEBHOOK_SECRET)
        assert validate_github_webhook_signature(WEBHOOK_PAYLOAD, sig) is True

    def test_T2_wrong_secret_rejected(self):
        """T2 — Signature computed with a different secret → False."""
        from github_client import validate_github_webhook_signature
        bad_sig = _make_sig(WEBHOOK_PAYLOAD, "wrong-secret")
        assert validate_github_webhook_signature(WEBHOOK_PAYLOAD, bad_sig) is False

    def test_T3_tampered_body_rejected(self):
        """T3 — Correct secret but signature is for different body → False."""
        from github_client import validate_github_webhook_signature
        bad_sig = _make_sig(b"tampered-body", WEBHOOK_SECRET)
        assert validate_github_webhook_signature(WEBHOOK_PAYLOAD, bad_sig) is False

    def test_T4_bogus_hex_rejected(self):
        """T4 — sha256=deadbeef (64 zeroes) → False."""
        from github_client import validate_github_webhook_signature
        assert validate_github_webhook_signature(
            WEBHOOK_PAYLOAD,
            "sha256=" + "0" * 64
        ) is False

    def test_T5_wrong_algorithm_rejected(self):
        """T5 — sha1=... prefix → False (only sha256 accepted)."""
        from github_client import validate_github_webhook_signature
        assert validate_github_webhook_signature(WEBHOOK_PAYLOAD, "sha1=abc123") is False

    def test_T6_missing_signature_with_secret_rejected(self):
        """T6 — Empty signature header when secret IS set → False."""
        from github_client import validate_github_webhook_signature
        assert validate_github_webhook_signature(WEBHOOK_PAYLOAD, "") is False

    def test_T7_missing_signature_no_secret_dev_mode_accepted(self):
        """T7 — No signature + GITHUB_WEBHOOK_SECRET unset → True (dev mode)."""
        from github_client import validate_github_webhook_signature
        os.environ.pop("GITHUB_WEBHOOK_SECRET", None)
        assert validate_github_webhook_signature(WEBHOOK_PAYLOAD, "") is True

    def test_T8_malformed_header_no_equals_rejected(self):
        """T8 — Malformed header with no '=' separator → False."""
        from github_client import validate_github_webhook_signature
        assert validate_github_webhook_signature(WEBHOOK_PAYLOAD, "sha256NODIVIDER") is False


# ===========================================================================
# SECTION 2 — diff_parser: normal diff → schema validation
# ===========================================================================

class TestDiffParserNormal:
    """Tests that diff_parser produces the correct schema from a real diff."""

    def setup_method(self):
        self.schema = _load_diff_schema()

    def test_T9_file_count(self):
        """T9 — SAMPLE_DIFF contains exactly 2 changed files."""
        from diff_parser import DiffParser
        parser = DiffParser(SAMPLE_DIFF)
        assert len(parser.get_changed_files()) == 2

    def test_T10_language_detection(self):
        """T10 — auth.py → python, config.yaml → yaml."""
        from diff_parser import DiffParser
        files = DiffParser(SAMPLE_DIFF).get_changed_files()
        langs = {f.path: f.language for f in files}
        assert langs["auth.py"] == "python"
        assert langs["config.yaml"] == "yaml"

    def test_T11_schema_validates(self):
        """T11 — build_diff_schema output is valid against diff_schema.json."""
        from diff_parser import build_diff_schema
        obj = build_diff_schema(
            pr_id=42, repo="org/repo", diff_text=SAMPLE_DIFF,
            change_type="auth_change", change_confidence=0.95,
        )
        jsonschema.validate(instance=obj, schema=self.schema)  # raises on failure

    def test_T12_hunk_line_types(self):
        """T12 — All hunk line types are one of {add, del, ctx}."""
        from diff_parser import build_diff_schema
        obj = build_diff_schema(pr_id=1, repo="x/y", diff_text=SAMPLE_DIFF)
        for file_entry in obj["files"]:
            for hunk in file_entry["hunks"]:
                for line in hunk["lines"]:
                    assert line["type"] in {"add", "del", "ctx"}, (
                        f"Unexpected line type '{line['type']}' in {file_entry['path']}"
                    )

    def test_T13_diff_text_hash(self):
        """T13 — diff_text_hash is SHA-256(diff_text)."""
        from diff_parser import build_diff_schema
        obj = build_diff_schema(pr_id=1, repo="x/y", diff_text=SAMPLE_DIFF)
        expected = hashlib.sha256(SAMPLE_DIFF.encode()).hexdigest()
        assert obj["diff_text_hash"] == expected

    def test_T14_change_type_in_schema_enum(self):
        """T14 — change_type value is one of the schema enum entries."""
        from diff_parser import build_diff_schema
        valid_types = [
            "auth_change", "schema_migration", "perf_critical", "ui_only",
            "config_change", "feature_addition", "bug_fix", "refactor", "unknown",
        ]
        obj = build_diff_schema(pr_id=1, repo="x/y", diff_text=SAMPLE_DIFF,
                                change_type="auth_change", change_confidence=0.8)
        assert obj["change_type"] in valid_types

    def test_T15_file_change_type_is_modified(self):
        """T15 — A plain edit produces change_type='modified' for each file."""
        from diff_parser import build_diff_schema
        obj = build_diff_schema(pr_id=1, repo="x/y", diff_text=SAMPLE_DIFF)
        for f in obj["files"]:
            assert f["change_type"] == "modified"


# ===========================================================================
# SECTION 3 — diff_parser: malformed / edge-case input
# ===========================================================================

class TestDiffParserEdgeCases:

    def setup_method(self):
        self.schema = _load_diff_schema()

    def test_T16_empty_diff_no_crash(self):
        """T16 — Empty string → files=[], no exception."""
        from diff_parser import build_diff_schema
        obj = build_diff_schema(pr_id=1, repo="x/y", diff_text="")
        assert obj["files"] == []

    def test_T17_empty_diff_schema_valid(self):
        """T17 — Empty diff still produces a schema-valid document."""
        from diff_parser import build_diff_schema
        obj = build_diff_schema(pr_id=1, repo="x/y", diff_text="")
        jsonschema.validate(instance=obj, schema=self.schema)

    def test_T18_garbage_input_no_crash(self):
        """T18 — Completely non-diff text → handled gracefully (files=[])."""
        from diff_parser import build_diff_schema
        obj = build_diff_schema(pr_id=1, repo="x/y", diff_text=GARBAGE_TEXT)
        assert isinstance(obj["files"], list)

    def test_T19_no_hunk_diff_schema_valid(self):
        """T19 — Diff header with no @@ hunks → valid schema, no crash."""
        from diff_parser import build_diff_schema
        obj = build_diff_schema(pr_id=1, repo="x/y", diff_text=NO_HUNK_DIFF)
        jsonschema.validate(instance=obj, schema=self.schema)

    def test_T20_binary_file_excluded(self):
        """T20 — Binary file diff → binary files excluded from schema files[]."""
        from diff_parser import build_diff_schema
        obj = build_diff_schema(pr_id=1, repo="x/y", diff_text=BINARY_DIFF)
        assert obj["files"] == [], f"Expected empty files for binary diff, got {obj['files']}"


# ===========================================================================
# SECTION 4 — FastAPI Webhook Endpoint
# ===========================================================================

class TestWebhookEndpoint:

    def setup_method(self):
        os.environ["GITHUB_WEBHOOK_SECRET"] = WEBHOOK_SECRET

    def teardown_method(self):
        os.environ.pop("GITHUB_WEBHOOK_SECRET", None)

    def test_T21_valid_signature_returns_200(self, app_client):
        """T21 — Valid HMAC signature on PR opened → HTTP 200, status=processing."""
        os.environ["GITHUB_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        sig = _make_sig(WEBHOOK_PAYLOAD, WEBHOOK_SECRET)
        resp = app_client.post(
            "/webhook/github",
            content=WEBHOOK_PAYLOAD,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"

    def test_T22_invalid_signature_returns_401(self, app_client):
        """T22 — Wrong HMAC hex → HTTP 401."""
        os.environ["GITHUB_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        resp = app_client.post(
            "/webhook/github",
            content=WEBHOOK_PAYLOAD,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": "sha256=" + "0" * 64,
            },
        )
        assert resp.status_code == 401

    def test_T23_missing_signature_with_secret_returns_401(self, app_client):
        """T23 — No X-Hub-Signature-256 header when secret IS set → HTTP 401."""
        os.environ["GITHUB_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        resp = app_client.post(
            "/webhook/github",
            content=WEBHOOK_PAYLOAD,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
            },
        )
        assert resp.status_code == 401

    def test_T24_missing_signature_no_secret_dev_mode_returns_200(self, app_client):
        """T24 — No signature + GITHUB_WEBHOOK_SECRET unset → HTTP 200 (dev mode)."""
        os.environ.pop("GITHUB_WEBHOOK_SECRET", None)
        resp = app_client.post(
            "/webhook/github",
            content=WEBHOOK_PAYLOAD,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
            },
        )
        assert resp.status_code == 200

    def test_T25_non_pr_event_ignored(self, app_client):
        """T25 — X-GitHub-Event: push → HTTP 200, status=ignored."""
        os.environ["GITHUB_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        sig = _make_sig(WEBHOOK_PAYLOAD, WEBHOOK_SECRET)
        resp = app_client.post(
            "/webhook/github",
            content=WEBHOOK_PAYLOAD,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    def test_T26_closed_action_ignored(self, app_client):
        """T26 — PR action=closed → HTTP 200, status=ignored."""
        os.environ["GITHUB_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        sig = _make_sig(CLOSED_PAYLOAD, WEBHOOK_SECRET)
        resp = app_client.post(
            "/webhook/github",
            content=CLOSED_PAYLOAD,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
