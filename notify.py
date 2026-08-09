#!/usr/bin/env python3
"""
Tell you when something happened, and stay silent otherwise.

The cost of a running project is not maintenance, it is having to check on it.
This runs after each deploy, works out whether anything is genuinely new, and
only then sends anything.

    python3 notify.py            # send
    python3 notify.py --dry-run  # print what would be sent

Telegram fires on every event. X only fires on milestones, because a post per
signature is noise. What has already been announced is recorded in
data/milestones.json so nothing is announced twice.

Environment (all optional; absent means that channel is skipped):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import pathlib
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
SIGDIR = ROOT / "data" / "signatures"
TREASURY = ROOT / "data" / "treasury.json"
STATE = ROOT / "data" / "milestones.json"
SITE = "https://agiasap.org"

# Signature counts worth a public post. Everything else goes to Telegram only.
SIG_MILESTONES = [1, 5, 10, 25, 50, 100, 250, 500, 1000]


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"announced_sigs": [], "announced_funding": [], "last_sig_count": 0, "last_usd": 0}


def post_json(url: str, payload: dict, headers: dict) -> tuple[int, str]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except urllib.error.URLError as e:
        return 0, str(e)


def telegram(text: str, dry: bool) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    # Show the message before checking configuration, otherwise a dry run on an
    # unconfigured machine prints nothing useful.
    if dry:
        print(f"--- telegram ---\n{text}\n")
        return
    if not token or not chat:
        print("telegram: not configured, skipping")
        return
    code, body = post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {"chat_id": chat, "text": text, "parse_mode": "HTML",
         "disable_web_page_preview": True}, {})
    print(f"telegram: {code} {body if code != 200 else 'sent'}")


# ------------------------------------------------------------- X / OAuth 1.0a

def _quote(s: str) -> str:
    return urllib.parse.quote(str(s), safe="~")


def oauth_header(method: str, url: str, creds: dict,
                 extra: dict | None = None, nonce: str | None = None,
                 timestamp: str | None = None) -> str:
    """
    OAuth 1.0a signature.

    `extra` carries query or form-encoded body parameters, which must be signed.
    For X's /2/tweets it stays empty: the body is JSON, and only form-encoded
    bodies enter the base string. The nonce and timestamp arguments exist so the
    implementation can be checked against a published test vector.
    """
    params = {
        "oauth_consumer_key": creds["key"],
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": creds["token"],
        "oauth_version": "1.0",
    }
    signed = {**params, **(extra or {})}
    joined = "&".join(f"{_quote(k)}={_quote(signed[k])}" for k in sorted(signed))
    base = f"{method.upper()}&{_quote(url)}&{_quote(joined)}"
    signing_key = f"{_quote(creds['secret'])}&{_quote(creds['token_secret'])}"
    sig = base64.b64encode(
        hmac.new(signing_key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    params["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{_quote(k)}="{_quote(v)}"' for k, v in sorted(params.items()))


def tweet(text: str, dry: bool) -> str | None:
    """Post to X. Returns an intent URL instead if credentials are absent."""
    creds = {
        "key": os.environ.get("X_API_KEY", ""),
        "secret": os.environ.get("X_API_SECRET", ""),
        "token": os.environ.get("X_ACCESS_TOKEN", ""),
        "token_secret": os.environ.get("X_ACCESS_SECRET", ""),
    }
    intent = "https://x.com/intent/post?text=" + urllib.parse.quote(text)

    if len(text) > 280:
        print(f"x: refusing to post, {len(text)} characters exceeds the limit")
        return None
    if dry:
        print(f"--- x ({len(text)} chars) ---\n{text}\n")
        return None
    if not all(creds.values()):
        print("x: not configured, returning a one-tap link instead")
        return intent

    url = "https://api.x.com/2/tweets"
    code, body = post_json(url, {"text": text},
                           {"authorization": oauth_header("POST", url, creds)})
    print(f"x: {code} {body if code >= 300 else 'posted'}")
    # A failed post should still be actionable rather than lost.
    return None if code < 300 else intent


# ------------------------------------------------------------------- events

def gather() -> tuple[dict, list[str], list[str]]:
    """Returns (facts, telegram lines, milestone posts)."""
    state = load_state()
    sigs = [json.loads(p.read_text()) for p in sorted(SIGDIR.glob("*.json"))]
    treasury = json.loads(TREASURY.read_text()) if TREASURY.exists() else {}
    usd = treasury.get("usd_total", 0)

    facts = {"sig_count": len(sigs), "usd": usd}
    tg, posts = [], []

    new_sigs = len(sigs) - state.get("last_sig_count", 0)
    if new_sigs > 0:
        newest = sigs[-new_sigs:]
        who = ", ".join(f"@{s['github']} ({s['lane']})" for s in newest)
        tg.append(f"🖋 <b>{new_sigs} new signator{'y' if new_sigs == 1 else 'ies'}</b>: {who}\n"
                  f"Total: {len(sigs)}")

    delta = usd - state.get("last_usd", 0)
    if delta > 0:
        tg.append(f"💰 <b>${delta:,.2f} received</b>\nTreasury now ${usd:,.2f}")

    # Milestones, announced once each.
    for m in SIG_MILESTONES:
        if len(sigs) >= m and m not in state.get("announced_sigs", []):
            state.setdefault("announced_sigs", []).append(m)
            if m == 1:
                continue  # the first signature is the author; not news
            posts.append(
                f"{m} people have now signed the AGI ASAP declaration.\n\n"
                f"Compute is capital gated. Attention is not. The open AI stack is held up by a "
                f"few thousand mostly unpaid people, and we fund them.\n\n{SITE}")

    for threshold in (100, 1000, 10000):
        if usd >= threshold and threshold not in state.get("announced_funding", []):
            state.setdefault("announced_funding", []).append(threshold)
            posts.append(
                f"AGI ASAP has passed ${threshold:,} in funding, all of it visible on chain.\n\n"
                f"Every figure on the site is read from a public RPC or the GitHub API. "
                f"None of it is typed in by hand.\n\n{SITE}")

    state["last_sig_count"] = len(sigs)
    state["last_usd"] = usd
    facts["state"] = state
    return facts, tg, posts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--failure", help="report a failed workflow instead of checking for news")
    args = ap.parse_args()

    if args.failure:
        telegram(f"⚠️ <b>agiasap: {args.failure} failed</b>\n"
                 f"https://github.com/pjdurden/agiasap/actions", args.dry_run)
        return

    facts, tg, posts = gather()

    if not tg and not posts:
        print(f"nothing new (signatories {facts['sig_count']}, ${facts['usd']:,.2f})")
        return

    for line in tg:
        telegram(line, args.dry_run)

    for p in posts:
        link = tweet(p, args.dry_run)
        if link:
            telegram(f"📣 <b>Milestone worth posting</b>\n\n{p}\n\n"
                     f'<a href="{link}">Tap to post on X</a>', args.dry_run)

    if not args.dry_run:
        STATE.write_text(json.dumps(facts["state"], indent=2) + "\n")
        print(f"state written: {STATE}")


if __name__ == "__main__":
    main()
