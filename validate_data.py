#!/usr/bin/env python3
"""
Validate data/signatories.json and data/traction.json.

Runs in CI on every pull request and is worth running locally before you push:

    python3 validate_data.py

Exits non-zero with a list of problems. The point is that a bad signature or an
unsupported number cannot reach the published page without someone overriding CI.
"""

import datetime as dt
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SIGDIR = ROOT / "data" / "signatures"
TRACTION = ROOT / "data" / "traction.json"

LANES = {"infra", "research", "compute", "evals", "signal", "capital"}
# GitHub's own rule: alphanumerics and single hyphens, no leading/trailing hyphen.
GH_USER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")

problems: list[str] = []


def fail(where: str, msg: str) -> None:
    problems.append(f"{where}: {msg}")


def is_iso_date(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def check_signatures() -> None:
    """One file per signatory, named for the handle. The filename is an identity check."""
    if not SIGDIR.exists():
        fail("data/signatures", "directory is missing")
        return

    today = dt.date.today()
    allowed = {"name", "github", "url", "affiliation", "lane", "signed"}
    count = 0

    for path in sorted(SIGDIR.glob("*.json")):
        at = f"signatures/{path.name}"
        count += 1
        try:
            s = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            fail(at, f"invalid JSON: {e}")
            continue
        if not isinstance(s, dict):
            fail(at, "must be a single JSON object")
            continue

        extra = set(s) - allowed
        if extra:
            fail(at, f"unknown field(s): {', '.join(sorted(extra))}")

        name = s.get("name")
        if not isinstance(name, str) or not (1 <= len(name.strip()) <= 80):
            fail(at, "name must be a string of 1 to 80 characters")

        gh = s.get("github")
        if not isinstance(gh, str) or not GH_USER.match(gh):
            fail(at, f"github must be a valid GitHub username, got {gh!r}")
        elif gh.lower() != path.stem.lower():
            # Duplicates are impossible by construction once this holds, since a
            # filesystem cannot hold two files of the same name.
            fail(at, f"filename must match the github field; expected {gh.lower()}.json")

        lane = s.get("lane")
        if lane not in LANES:
            fail(at, f"lane must be one of {', '.join(sorted(LANES))}, got {lane!r}")

        signed = s.get("signed")
        if not is_iso_date(signed):
            fail(at, f"signed must be an ISO date (YYYY-MM-DD), got {signed!r}")
        elif dt.date.fromisoformat(signed) > today:
            fail(at, f"signed is in the future: {signed}")

        url = s.get("url")
        if url is not None and (not isinstance(url, str) or not url.startswith("https://")):
            fail(at, "url must be an https:// address if present")

        aff = s.get("affiliation")
        if aff is not None and (not isinstance(aff, str) or len(aff) > 60):
            fail(at, "affiliation must be a string of at most 60 characters")

    print(f"data/signatures: {count} signature(s)")


def check_traction() -> None:
    if not TRACTION.exists():
        fail("traction.json", "file is missing")
        return
    try:
        data = json.loads(TRACTION.read_text())
    except json.JSONDecodeError as e:
        fail("traction.json", f"invalid JSON: {e}")
        return
    if not isinstance(data, dict):
        fail("traction.json", "top level must be an object")
        return

    for key in ("committed", "rounds", "grants"):
        if not isinstance(data.get(key), list):
            fail("traction.json", f"{key} must be a list")

    for i, c in enumerate(data.get("committed", []) or []):
        at = f"committed[{i}]"
        if not is_iso_date(c.get("date")):
            fail(at, "date must be an ISO date")
        if not isinstance(c.get("amount"), (int, float)) or c.get("amount", -1) < 0:
            fail(at, "amount must be a non-negative number")
        if not isinstance(c.get("source"), str) or not c["source"].strip():
            fail(at, "source is required")

    for i, r in enumerate(data.get("rounds", []) or []):
        at = f"rounds[{i}]"
        for field in ("id", "title"):
            if not isinstance(r.get(field), str) or not r[field].strip():
                fail(at, f"{field} is required")
        if not is_iso_date(r.get("opened")):
            fail(at, "opened must be an ISO date")
        if r.get("closed") is not None and not is_iso_date(r["closed"]):
            fail(at, "closed must be an ISO date or null")
        for field in ("purse", "paid_out"):
            if not isinstance(r.get(field), (int, float)) or r.get(field, -1) < 0:
                fail(at, f"{field} must be a non-negative number")
        if isinstance(r.get("paid_out"), (int, float)) and isinstance(r.get("purse"), (int, float)):
            if r["paid_out"] > r["purse"]:
                fail(at, f"paid_out ({r['paid_out']}) exceeds purse ({r['purse']})")
        # A closed round that paid nothing is possible but almost always a mistake.
        if r.get("closed") and r.get("paid_out") == 0:
            fail(at, "round is closed but paid_out is 0; add a note field if that is intentional")

    paid = sum(r.get("paid_out", 0) for r in data.get("rounds", []) or [])
    committed = sum(c.get("amount", 0) for c in data.get("committed", []) or [])
    if paid > committed:
        fail("traction.json", f"paid out ({paid}) exceeds committed ({committed})")

    print(f"traction.json: {committed} committed, {paid} paid out, "
          f"{len(data.get('rounds', []) or [])} round(s)")


def main() -> None:
    check_signatures()
    check_traction()
    if problems:
        print(f"\n{len(problems)} problem(s):\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)
    print("\nall data valid")


if __name__ == "__main__":
    main()
