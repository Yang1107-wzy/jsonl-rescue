import base64
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "data.jsonl"
        self.source.write_bytes(b'{"id":1}\n{bad}\n{"id":1}\n')

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "jsonl_rescue", *args], capture_output=True, text=True
        )

    def test_scan_findings(self):
        r = self.cli("scan", str(self.source), "--dedupe", "--format", "json")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout)["rejected"], 2)

    def test_clean_succeeds_with_quarantine(self):
        out, rejects = self.root / "clean.jsonl", self.root / "rejects.jsonl"
        r = self.cli(
            "clean",
            str(self.source),
            "--dedupe",
            "--output",
            str(out),
            "--rejects",
            str(rejects),
            "--format",
            "json",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(out.read_text().splitlines()), 1)
        self.assertEqual(len(rejects.read_text().splitlines()), 2)
        self.assertEqual(
            base64.b64decode(json.loads(rejects.read_text().splitlines()[0])["raw_base64"]),
            b"{bad}\n",
        )

    def test_existing_file_fails_safely(self):
        r = self.cli(
            "clean",
            str(self.source),
            "--output",
            str(self.source),
            "--rejects",
            str(self.root / "r"),
        )
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.source.read_bytes(), b'{"id":1}\n{bad}\n{"id":1}\n')

    def test_missing_file_exit_two(self):
        self.assertEqual(self.cli("scan", str(self.root / "missing")).returncode, 2)

    def test_negative_limit_exit_two(self):
        self.assertEqual(self.cli("scan", str(self.source), "--max-issues", "-1").returncode, 2)

    def test_corrupt_gzip_exit_two_no_traceback(self):
        import gzip

        p = self.root / "bad.jsonl.gz"
        blob = bytearray(gzip.compress(b"{}\n"))
        blob[10] = 255
        p.write_bytes(blob)
        r = self.cli("scan", str(p))
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)
