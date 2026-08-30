/**
 * Fixture diffs embedded in the frontend for demo scenarios.
 * These diffs pass through the multi-agent review pipeline (/review).
 */

export const DEMO_DIFFS = {
  1: {
    label: 'PR #1 — Safe Code Change',
    description: 'Safe Code Change',
    context: 'Null-guard for format_currency + matching test',
    expectedVerdict: 'APPROVE',
    diff: `diff --git a/utils/formatting.py b/utils/formatting.py
index 1a2b3c4..5d6e7f8 100644
--- a/utils/formatting.py
+++ b/utils/formatting.py
@@ -1,3 +1,5 @@
 def format_currency(amount, currency="USD"):
     symbol = CURRENCY_SYMBOLS.get(currency, "$")
+    if amount is None:
+        return f"{symbol}0.00"
     return f"{symbol}{amount:.2f}"
diff --git a/tests/test_formatting.py b/tests/test_formatting.py
index 2b3c4d5..6e7f8a9 100644
--- a/tests/test_formatting.py
+++ b/tests/test_formatting.py
@@ -4,2 +4,6 @@
 def test_format_currency_eur():
     assert format_currency(9.5, "EUR") == "EUR9.50"
+
+def test_format_currency_none():
+    assert format_currency(None) == "$0.00"
+    assert format_currency(None, "EUR") == "EUR0.00"`,
  },
  2: {
    label: 'PR #2 — Security Risk',
    description: 'Security Risk',
    context: 'auth/login.py refactor — parameterised queries but logs plaintext password',
    expectedVerdict: 'REJECT',
    diff: `diff --git a/auth/login.py b/auth/login.py
index 3c4d5e6..7f8a9b0 100644
--- a/auth/login.py
+++ b/auth/login.py
@@ -1,9 +1,24 @@
 import sqlite3
+from db.raw_connection import get_raw_connection

 def authenticate(username, password):
-    conn = sqlite3.connect("app.db")
-    query = "SELECT * FROM users WHERE username = '" + username + "' AND password = '" + password + "'"
+    conn = get_raw_connection()
+    query = "SELECT * FROM users WHERE username = ? AND password_hash = ?"
     cursor = conn.cursor()
-    cursor.execute(query)
+    cursor.execute(query, (username, _hash(password)))
     user = cursor.fetchone()
+    _log_attempt(username, password)
     return user is not None

+def _hash(password):
+    import hashlib
+    return hashlib.sha256(password.encode()).hexdigest()

+def _log_attempt(username, password):
+    print(f"[auth] login attempt: user={username} pass={password}")`,
  },
  3: {
    label: 'PR #3 — Risky Database Migration',
    description: 'Risky Database Migration',
    context: 'Irreversible billing_tier migration that drops plan_id column',
    expectedVerdict: 'REJECT',
    escalate: true,
    diff: `diff --git a/migrations/0007_add_billing_tier.py b/migrations/0007_add_billing_tier.py
index 0000000..9a8b7c6 100644
--- /dev/null
+++ b/migrations/0007_add_billing_tier.py
@@ -0,0 +1,20 @@
+"""
+Add billing_tier column to accounts, backfill from legacy plan_id,
+and drop the now-unused plan_id column.
+"""

+def upgrade(connection):
+    connection.execute("ALTER TABLE accounts ADD COLUMN billing_tier VARCHAR(20)")
+    connection.execute(
+        "UPDATE accounts SET billing_tier = CASE "
+        "WHEN plan_id = 1 THEN 'free' "
+        "WHEN plan_id = 2 THEN 'pro' "
+        "ELSE 'enterprise' END"
+    )
+    connection.execute("ALTER TABLE accounts DROP COLUMN plan_id")


+def downgrade(connection):
+    raise NotImplementedError("This migration is not reversible")`,
  },
  4: {
    label: 'PR #4 — Missing Test Coverage',
    description: 'Missing Test Coverage',
    context: 'PaymentService logic added to backend without test suite updates',
    expectedVerdict: 'REJECT',
    agentTag: 'Testing',
    diff: `diff --git a/backend/payment_service.py b/backend/payment_service.py
index 4b2c1d0..9e8f7a6 100644
--- a/backend/payment_service.py
+++ b/backend/payment_service.py
@@ -1,5 +1,12 @@
 class PaymentService:
-    def process(self, amount):
-        return True
+    def process(self, amount, currency="USD"):
+        if amount <= 0:
+            raise ValueError("Amount must be positive")
+        return self._charge_gateway(amount, currency)
+
+    def _charge_gateway(self, amount, currency):
+        return {"status": "success", "amount": amount, "currency": currency}`,
  },
  5: {
    label: 'PR #5 — Performance Bottleneck',
    description: 'Performance Bottleneck',
    context: 'Nested O(n²) loop in user transaction analytics',
    expectedVerdict: 'REJECT',
    agentTag: 'Performance',
    diff: `diff --git a/services/report_generator.py b/services/report_generator.py
index 1a2b3c4..5d6e7f8 100644
--- a/services/report_generator.py
+++ b/services/report_generator.py
@@ -10,6 +10,12 @@ def generate_user_report(users, transactions):
+    report = []
+    for user in users:
+        for tx in transactions:
+            if tx.user_id == user.id:
+                report.append((user.id, tx.amount))
+    return report
diff --git a/tests/test_report.py b/tests/test_report.py
index 2b3c4d5..6e7f8a9 100644
--- a/tests/test_report.py
+++ b/tests/test_report.py
@@ -1,2 +1,4 @@
+def test_generate_report():
+    assert generate_user_report([], []) == []`,
  },
  6: {
    label: 'PR #6 — Agent Disagreement',
    description: 'Agent Disagreement',
    context: 'Conflict scenario — Security, Architecture & Testing flag issues while Performance passes',
    expectedVerdict: 'REJECT',
    agentTag: 'Conflict',
    diff: `diff --git a/services/sync_service.py b/services/sync_service.py
index 3c4d5e6..7f8a9b0 100644
--- a/services/sync_service.py
+++ b/services/sync_service.py
@@ -1,5 +1,10 @@
 import requests

 def sync_remote_data():
+    # TODO: add retry logic before production deployment
+    endpoint = "http://api.legacy-internal.net/v1/sync"
+    res = requests.get(endpoint)
+    return res.json()
diff --git a/tests/test_sync.py b/tests/test_sync.py
index 4e5f6a7..8b9c0d1 100644
--- a/tests/test_sync.py
+++ b/tests/test_sync.py
@@ -1,3 +1,5 @@
 import pytest

+@pytest.skip("Integration test pending legacy server migration")
 def test_sync_remote_data():
+    pass`,
  },
  7: {
    label: 'PR #7 — Hardcoded Secret',
    description: 'Hardcoded Secret',
    context: 'Hardcoded production API key in auth_service.py',
    expectedVerdict: 'REJECT',
    agentTag: 'Security',
    diff: `diff --git a/services/auth_service.py b/services/auth_service.py
index 8a9b0c1..2d3e4f5 100644
--- a/services/auth_service.py
+++ b/services/auth_service.py
@@ -5,3 +5,5 @@ class AuthService:
     def __init__(self):
-        self.api_key = os.getenv("API_KEY")
+        self.api_key = "sk_live_998877665544332211"
+        self.endpoint = "https://api.service.com"
diff --git a/tests/test_auth.py b/tests/test_auth.py
index 3e4f5a6..7b8c9d0 100644
--- a/tests/test_auth.py
+++ b/tests/test_auth.py
@@ -1,2 +1,4 @@
+def test_auth():
+    assert AuthService().endpoint == "https://api.service.com"`,
  },
}
