import base64
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from jsonl_rescue.core import process


class RescueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "data.jsonl"

    def run_data(self, data, **kwargs):
        self.source.write_bytes(data)
        return process(self.source, **kwargs)

    def test_valid_unicode(self):
        r = self.run_data('{"text":"你好"}\n{"id":2}\n'.encode())
        self.assertEqual((r["total"], r["accepted"], r["rejected"]), (2, 2, 0))

    def test_invalid_object_and_blank(self):
        r = self.run_data(b'{bad}\n[]\n\n{"x":1}\n')
        self.assertEqual(r["rejected"], 3)
        self.assertEqual(r["accepted"], 1)

    def test_key_order_duplicates(self):
        r = self.run_data(b'{"a":1,"b":2}\n{"b":2,"a":1}\n', dedupe=True)
        self.assertEqual(r["duplicates"], 1)
        self.assertEqual(r["accepted"], 1)

    def test_dedupe_is_opt_in(self):
        self.assertEqual(self.run_data(b'{"a":1}\n{"a":1}\n')["accepted"], 2)

    def test_required_keys(self):
        r = self.run_data(b'{"id":1}\n{"text":"x"}\n', required=["id"])
        self.assertEqual(r["rejected"], 1)
        self.assertEqual(r["issues"][0]["code"], "missing-keys")

    def test_nonfinite_and_duplicate_keys(self):
        r = self.run_data(b'{"v":NaN}\n{"v":Infinity}\n{"v":1,"v":2}\n')
        self.assertEqual(r["rejected"], 3)

    def test_rejects_preserve_exact_bytes(self):
        out = self.root / "clean.jsonl"
        rejected = self.root / "rejected.jsonl"
        original = b'{"a":1}\r\n\xffbroken\n{"a":1}\n'
        r = self.run_data(original, dedupe=True, output=out, rejects=rejected)
        rows = [json.loads(x) for x in rejected.read_text().splitlines()]
        self.assertEqual(base64.b64decode(rows[0]["raw_base64"]), b"\xffbroken\n")
        self.assertEqual(rows[1]["line"], 3)
        self.assertEqual(rows[1]["first_line"], 1)
        self.assertEqual(r["accepted"], 1)
        self.assertEqual(self.source.read_bytes(), original)

    def test_never_overwrites_existing_outputs(self):
        out = self.root / "clean.jsonl"
        out.write_text("keep")
        with self.assertRaises(ValueError):
            self.run_data(b"{}\n", output=out, rejects=self.root / "rejects.jsonl")
        self.assertEqual(out.read_text(), "keep")

    def test_output_cannot_alias_input(self):
        with self.assertRaises(ValueError):
            self.run_data(b"{}\n", output=self.source, rejects=self.root / "rejects.jsonl")

    def test_output_paths_distinct(self):
        out = self.root / "a.jsonl"
        with self.assertRaises(ValueError):
            self.run_data(b"{}\n", output=out, rejects=out)

    def test_gzip(self):
        p = self.root / "data.jsonl.gz"
        p.write_bytes(gzip.compress(b'{"a":1}\n'))
        self.assertEqual(process(p)["accepted"], 1)

    def test_issue_sampling_is_bounded(self):
        r = self.run_data(b"bad\n" * 50, max_issues=3)
        self.assertEqual(len(r["issues"]), 3)
        self.assertEqual(r["rejected"], 50)
        self.assertEqual(r["issue_counts"]["invalid-json"], 50)

    def test_bom_rejected(self):
        self.assertEqual(self.run_data(b"\xef\xbb\xbf{}\n")["rejected"], 1)

    def test_empty_file(self):
        self.assertEqual(self.run_data(b"")["total"], 0)

    def test_failed_write_setup_cleans_created_file(self):
        out = self.root / "clean.jsonl"
        with self.assertRaises(OSError):
            self.run_data(b"{}\n", output=out, rejects=self.root / "absent" / "rejects.jsonl")
        self.assertFalse(out.exists())

    def test_decimal_values_preserved_exactly(self):
        out, rejects = self.root / "clean.jsonl", self.root / "rejects.jsonl"
        data = b'{"x":1e-400}\n{"x":0.12345678901234567890123456789}\n{"x":0.12345678901234567890123456788}\n'
        r = self.run_data(data, dedupe=True, output=out, rejects=rejects)
        from decimal import Decimal

        values = [
            json.loads(line, parse_float=Decimal)["x"] for line in out.read_text().splitlines()
        ]
        self.assertEqual(
            values,
            [
                Decimal("1e-400"),
                Decimal("0.12345678901234567890123456789"),
                Decimal("0.12345678901234567890123456788"),
            ],
        )
        self.assertEqual(r["accepted"], 3)
