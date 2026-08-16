#!/usr/bin/env python3
"""
Generate data/contributors.json for the AGI ASAP recognition board.

Counts merged pull requests per author across the open AI infrastructure stack
over a trailing window, then writes a ranked list.

Usage:
    export GITHUB_TOKEN=ghp_...
    python3 build_board.py [--days 90] [--top 50]

Only public data is used. Anyone in optout.txt is excluded before the file is
written, so removals survive regeneration.
"""

import argparse
import collections
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REPOS = [
    "vllm-project/vllm",
    "sgl-project/sglang",
    # Undercounts badly: most PyTorch work lands via Meta's internal tooling and
    # shows as closed rather than merged. Kept for coverage, not for fair ranking.
    "pytorch/pytorch",
    "triton-lang/triton",
    "huggingface/transformers",
    "huggingface/tokenizers",
    "huggingface/accelerate",
    "ggml-org/llama.cpp",
    "NVIDIA/TensorRT-LLM",
    "deepspeedai/DeepSpeed",
    "ray-project/ray",
    "guidance-ai/llguidance",
    "dottxt-ai/outlines-core",
    "NVIDIA/kvpress",
    "linkedin/Liger-Kernel",
]

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "data" / "contributors.json"
META = ROOT / "data" / "board_meta.json"
OPTOUT = ROOT / "optout.txt"
API = "https://api.github.com/search/issues"

# Bots and automation accounts never belong on a recognition board.
BOT_MARKERS = (
    "[bot]", "-bot", "bot-", "dependabot", "renovate", "github-actions",
    "-agent", "-ci", "-automation", "copilot",
)


class RepoGone(Exception):
    """Repo is missing or renamed; skip it rather than aborting the run."""


def token() -> str:
    """A real GITHUB_TOKEN if one is exported, else "" meaning use the gh CLI."""
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    # "ghp_..." is the placeholder from the usage string, not a credential.
    if tok and not tok.endswith("..."):
        return tok
    return ""


def gh_api(path: str, attempt: int = 0) -> dict:
    """Call the API through the gh CLI, which owns the credential."""
    proc = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github+json", path],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        err = proc.stderr.strip()
        if ("rate limit" in err.lower() or "403" in err) and attempt < 5:
            wait = 2 ** attempt * 15
            print(f"  rate limited, sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            return gh_api(path, attempt + 1)
        # 422 means the repo does not exist under that name, usually a rename.
        # One dead entry in REPOS should not kill the whole run.
        if "422" in err:
            raise RepoGone(err)
        sys.exit(f"gh api failed for {path}\n{err}")
    return json.loads(proc.stdout)


def check_auth(tok: str) -> None:
    """Fail fast and legibly rather than tracebacking on the first search."""
    # /rate_limit, not /user: under Actions the GITHUB_TOKEN is an app
    # installation token with no user behind it, so /user is forbidden to it by
    # construction. /rate_limit answers for every credential type, and it also
    # reports the search quota, which is the budget this script actually spends.
    try:
        limits = get("rate_limit", tok)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            sys.exit(
                f"GitHub rejected GITHUB_TOKEN ({e.code}: {e.reason}). "
                "It is expired, revoked, a placeholder, or lacks the scope.\n"
                "Unset it to fall back to the gh CLI: unset GITHUB_TOKEN"
            )
        raise
    quota = limits.get("resources", {}).get("search", {})
    print(
        f"authenticated; search quota {quota.get('remaining')}/{quota.get('limit')}",
        file=sys.stderr,
    )


def is_throttled(e: urllib.error.HTTPError) -> bool:
    """
    Tell a throttle apart from a refusal; GitHub returns 403 for both.

    A primary limit zeroes x-ratelimit-remaining, a secondary one sets
    retry-after. A permissions 403 carries neither, and retrying it just burns
    eight minutes of backoff before failing with the same error.
    """
    if e.code == 429:
        return True
    if e.headers.get("retry-after"):
        return True
    return e.headers.get("x-ratelimit-remaining") == "0"


def get(path: str, tok: str, attempt: int = 0) -> dict:
    """Fetch an API path. Uses GITHUB_TOKEN if set, otherwise the gh CLI."""
    if not tok:
        return gh_api(path)

    req = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "agi-asap-board",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if is_throttled(e) and attempt < 5:
            wait = 2 ** attempt * 15
            print(f"  rate limited, sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            return get(path, tok, attempt + 1)
        raise


def search(repo: str, lo: dt.date, hi: dt.date, page: int, tok: str, per_page: int = 100) -> dict:
    query = f"repo:{repo} is:pr is:merged merged:{lo.isoformat()}..{hi.isoformat()}"
    path = f"search/issues?q={urllib.parse.quote(query)}&per_page={per_page}&page={page}"
    return get(path, tok)


def merged_prs(repo: str, lo: dt.date, hi: dt.date, tok: str):
    """
    Yield (author, repo) for each PR merged in [lo, hi].

    The search API refuses to page past 1000 results, so any window holding more
    than that is split in half and recursed rather than silently truncated.
    """
    probe = search(repo, lo, hi, 1, tok, per_page=1)
    total = probe.get("total_count", 0)
    if total == 0:
        return

    if total > 1000 and (hi - lo).days >= 1:
        mid = lo + (hi - lo) / 2
        yield from merged_prs(repo, lo, mid, tok)
        yield from merged_prs(repo, mid + dt.timedelta(days=1), hi, tok)
        return

    if total > 1000:
        # A single day with >1000 merges. Nothing left to split; take what we can.
        print(f"  {repo}: >1000 merges on {lo}, truncating", file=sys.stderr)

    for page in range(1, min(total // 100 + 2, 11)):
        time.sleep(1)
        items = search(repo, lo, hi, page, tok).get("items", [])
        for it in items:
            user = (it.get("user") or {}).get("login")
            if user:
                yield user, repo
        if len(items) < 100:
            return


def is_bot(login: str) -> bool:
    low = login.lower()
    return any(m in low for m in BOT_MARKERS)


def load_optout() -> set:
    if not OPTOUT.exists():
        return set()
    return {
        line.strip().lower()
        for line in OPTOUT.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90, help="trailing window (default 90)")
    ap.add_argument("--top", type=int, default=50, help="entries to keep (default 50)")
    args = ap.parse_args()

    tok = token()
    check_auth(tok)
    today = dt.date.today()
    since = today - dt.timedelta(days=args.days)
    excluded = load_optout()

    counts = collections.Counter()
    repos_by_user = collections.defaultdict(set)

    skipped = []
    for repo in REPOS:
        print(f"{repo} ...", file=sys.stderr)
        found = 0
        try:
            for user, r in merged_prs(repo, since, today, tok):
                if is_bot(user) or user.lower() in excluded:
                    continue
                counts[user] += 1
                repos_by_user[user].add(r.split("/")[-1])
                found += 1
        except RepoGone:
            print("  skipped: not found (renamed or moved?)", file=sys.stderr)
            skipped.append(repo)
            continue
        print(f"  {found} merged", file=sys.stderr)
        time.sleep(1)

    rows = [
        {
            "login": user,
            "merged": n,
            "repos": sorted(repos_by_user[user])[:4],
        }
        for user, n in counts.most_common(args.top)
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=2) + "\n")

    # Totals cover every contributor found, not just the top N written above.
    META.write_text(json.dumps({
        "since": since.isoformat(),
        "until": today.isoformat(),
        "days": args.days,
        "total_prs": sum(counts.values()),
        "total_people": len(counts),
        "repos": [r for r in REPOS if r not in skipped],
        "skipped": skipped,
    }, indent=2) + "\n")
    print(f"\nwrote {len(rows)} contributors to {OUT}", file=sys.stderr)
    print(f"window: {since} to {today}, {sum(counts.values())} merged PRs, "
          f"{len(counts)} distinct people", file=sys.stderr)
    if excluded:
        print(f"excluded {len(excluded)} opted-out account(s)", file=sys.stderr)
    if skipped:
        print(f"skipped (not found): {', '.join(skipped)}", file=sys.stderr)


if __name__ == "__main__":
    main()
