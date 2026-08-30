/**
 * Fixture diffs embedded in the frontend so no /demo/* endpoints are needed.
 * These match the exact diffs used in the original static dashboard.
 */

export const DEMO_DIFFS = {
  1: {
    label: 'PR #1 Safe Change — Null Guard & Tests',
    description: 'Null guard for format_currency + matching test',
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
    label: 'PR #2 Security Risk — Authentication Query',
    description: 'Parameterised query but logs plaintext password',
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
+
+def _hash(password):
+    import hashlib
+    return hashlib.sha256(password.encode()).hexdigest()
+
+def _log_attempt(username, password):
+    print(f"[auth] login attempt: user={username} pass={password}")`,
  },
  3: {
    label: 'PR #3 Risky Database Migration',
    description: 'Irreversible schema change — drops plan_id, no rollback',
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
+
+def upgrade(connection):
+    connection.execute("ALTER TABLE accounts ADD COLUMN billing_tier VARCHAR(20)")
+    connection.execute(
+        "UPDATE accounts SET billing_tier = CASE "
+        "WHEN plan_id = 1 THEN 'free' "
+        "WHEN plan_id = 2 THEN 'pro' "
+        "ELSE 'enterprise' END"
+    )
+    connection.execute("ALTER TABLE accounts DROP COLUMN plan_id")
+
+
+def downgrade(connection):
+    raise NotImplementedError("This migration is not reversible")`,
  },
}
