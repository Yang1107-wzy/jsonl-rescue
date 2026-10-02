"""Streaming JSONL validation with disk-backed exact deduplication."""

import base64
import gzip
import hashlib
import json
import sqlite3
import tempfile
from collections import Counter
from contextlib import ExitStack
from decimal import Decimal, InvalidOperation
from pathlib import Path


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate-key")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("nonfinite-number")


def _canonical(value):
    """Serialize parsed decimals without passing through binary floats."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return (
            "{" + ",".join(json.dumps(k) + ":" + _canonical(value[k]) for k in sorted(value)) + "}"
        )
    if isinstance(value, list):
        return "[" + ",".join(_canonical(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def process(source, *, required=(), dedupe=False, output=None, rejects=None, max_issues=100):
    """Scan or clean object JSONL. Cleaning requires a separate rejection archive.

    Source is never modified; output paths must be new, distinct files. Rejected
    bytes, including line endings, are preserved in raw_base64. Deduplication
    uses canonical sorted-key JSON SHA-256 fingerprints in temporary SQLite.
    """
    source = Path(source)
    if max_issues < 0:
        raise ValueError("max_issues must be nonnegative.")
    if (output is None) != (rejects is None):
        raise ValueError("Cleaning requires both output and rejects paths.")
    paths = [Path(p) for p in (output, rejects) if p is not None]
    if len({p.resolve() for p in [source, *paths]}) != 1 + len(paths):
        raise ValueError("Input, output and rejects must be distinct paths.")
    if any(p.exists() or p.is_symlink() for p in paths):
        raise ValueError("Output files already exist; choose new paths.")
    report = {
        "schema_version": 1,
        "total": 0,
        "accepted": 0,
        "rejected": 0,
        "duplicates": 0,
        "issue_counts": {},
        "issues": [],
    }
    counts = Counter()
    created = []
    try:
        with ExitStack() as stack:
            reader = stack.enter_context(
                gzip.open(source, "rb") if source.suffix == ".gz" else source.open("rb")
            )
            writers = []
            for path in paths:
                writers.append(stack.enter_context(path.open("x", encoding="utf-8", newline="\n")))
                created.append(path)
            database = None
            if dedupe:
                temp = stack.enter_context(tempfile.TemporaryDirectory(prefix="jsonl-rescue-"))
                database = sqlite3.connect(str(Path(temp) / "seen.sqlite3"))
                stack.callback(database.close)
                database.execute("CREATE TABLE seen (digest TEXT PRIMARY KEY, first_line INTEGER)")
            for line, raw in enumerate(reader, 1):
                report["total"] += 1
                code, first_line = None, None
                value = None
                try:
                    text = raw.decode("utf-8")
                    if not text.strip():
                        code = "blank-line"
                    else:
                        value = json.loads(
                            text,
                            object_pairs_hook=_object,
                            parse_constant=_constant,
                            parse_float=Decimal,
                        )
                        if not isinstance(value, dict):
                            code = "not-object"
                        elif any(key not in value for key in required):
                            code = "missing-keys"
                except UnicodeError:
                    code = "invalid-utf8"
                except json.JSONDecodeError:
                    code = "invalid-json"
                except InvalidOperation:
                    code = "invalid-number"
                except ValueError as exc:
                    code = (
                        str(exc)
                        if str(exc) in ("duplicate-key", "nonfinite-number")
                        else "invalid-json"
                    )
                except RecursionError:
                    code = "nesting-too-deep"
                canonical = None
                if code is None:
                    try:
                        canonical = _canonical(value)
                    except (ValueError, RecursionError):
                        code = "nonfinite-number"
                if code is None and database is not None:
                    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                    found = database.execute(
                        "SELECT first_line FROM seen WHERE digest=?", (digest,)
                    ).fetchone()
                    if found:
                        code, first_line = "duplicate", found[0]
                        report["duplicates"] += 1
                    else:
                        database.execute("INSERT INTO seen VALUES (?,?)", (digest, line))
                if code:
                    report["rejected"] += 1
                    counts[code] += 1
                    issue = {"line": line, "code": code}
                    if first_line is not None:
                        issue["first_line"] = first_line
                    if len(report["issues"]) < max_issues:
                        report["issues"].append(issue)
                    if writers:
                        record = {**issue, "raw_base64": base64.b64encode(raw).decode("ascii")}
                        writers[1].write(json.dumps(record) + "\n")
                else:
                    report["accepted"] += 1
                    if writers:
                        writers[0].write(canonical + "\n")
        report["issue_counts"] = dict(sorted(counts.items()))
        return report
    except BaseException:
        # Delete only files created by this invocation, after handles close.
        for path in created:
            path.unlink(missing_ok=True)
        raise
