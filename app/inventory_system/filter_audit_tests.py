"""
filter_audit_tests.py
=====================

Pytest wrapper that runs the data-driven Excel-vs-chatbot audit (Part 13) as an
isolated subprocess and asserts ZERO count mismatches and ZERO card violations
against the CURRENT Excel. The heavy logic lives in tests/excel_vs_chatbot_audit.py
(115+ questions, all expected counts computed from the workbook — never hardcoded).
"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
AUDIT = os.path.join(REPO, "tests", "excel_vs_chatbot_audit.py")


@unittest.skipUnless(os.path.exists(AUDIT), "audit harness not found")
class TestExcelVsChatbotAudit(unittest.TestCase):
    def test_zero_mismatches_against_excel(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        # Decode as utf-8 explicitly (the child writes utf-8 via -X utf8); the
        # default locale decoding on Windows would mangle ₹ / Devanagari output.
        p = subprocess.run([sys.executable, "-X", "utf8", AUDIT],
                           capture_output=True, encoding="utf-8", errors="replace",
                           env=env, timeout=900)
        tail = (p.stdout or "")[-3000:] + "\n--- stderr ---\n" + (p.stderr or "")[-1000:]
        # returncode is authoritative: the audit exits non-zero on ANY count
        # mismatch or card violation, and 0 only when every question matched the
        # Excel ground truth exactly.
        self.assertEqual(p.returncode, 0,
                         f"Excel-vs-chatbot audit found discrepancies:\n{tail}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
