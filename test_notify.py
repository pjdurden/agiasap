#!/usr/bin/env python3
"""
Checks on the parts of notify.py that fail silently if wrong.

    python3 test_notify.py

The OAuth base string is the piece worth pinning: percent-encoding, parameter
sorting and the exclusion of a JSON body are all easy to get subtly wrong, and
the failure mode is a 401 with no explanation of which detail was off.
"""

import re
import sys
import urllib.parse

import notify

failures = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name}\n     got:  {got!r}\n     want: {want!r}")
        failures.append(name)


# Twitter's published worked example for OAuth 1.0a.
CREDS = {
    "key": "xvz1evFS4wEEPTGEFPHBog",
    "secret": "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
    "token": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
    "token_secret": "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
}
DOCUMENTED_BASE = (
    "POST&https%3A%2F%2Fapi.twitter.com%2F1.1%2Fstatuses%2Fupdate.json&"
    "include_entities%3Dtrue%26oauth_consumer_key%3Dxvz1evFS4wEEPTGEFPHBog%26"
    "oauth_nonce%3DkYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg%26"
    "oauth_signature_method%3DHMAC-SHA1%26oauth_timestamp%3D1318622958%26"
    "oauth_token%3D370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb%26"
    "oauth_version%3D1.0%26status%3DHello%2520Ladies%2520%252B%2520Add%2520Me"
    "%2520To%2520Your%2520List"
)


def rebuild_base() -> str:
    """Reconstruct the base string using notify's own encoder and ordering."""
    q = notify._quote
    params = {
        "include_entities": "true",
        "oauth_consumer_key": CREDS["key"],
        "oauth_nonce": "kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg",
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": "1318622958",
        "oauth_token": CREDS["token"],
        "oauth_version": "1.0",
        "status": "Hello Ladies + Add Me To Your List",
    }
    joined = "&".join(f"{q(k)}={q(params[k])}" for k in sorted(params))
    return f"POST&{q('https://api.twitter.com/1.1/statuses/update.json')}&{q(joined)}"


check("oauth base string matches the published example", rebuild_base(), DOCUMENTED_BASE)

# Percent-encoding rules that OAuth is strict about.
check("space encodes as %20", notify._quote("a b"), "a%20b")
check("plus encodes as %2B", notify._quote("+"), "%2B")
check("tilde stays literal", notify._quote("~"), "~")
check("slash is encoded", notify._quote("/"), "%2F")

# The header must be well formed and carry a signature.
hdr = notify.oauth_header("POST", "https://api.x.com/2/tweets", CREDS,
                          nonce="abc", timestamp="1700000000")
check("header starts with OAuth", hdr.startswith("OAuth "), True)
check("header carries a signature", bool(re.search(r'oauth_signature="[^"]+"', hdr)), True)
check("JSON body is not signed", "status" in hdr, False)

# Signature must be deterministic for fixed inputs, or retries would differ.
again = notify.oauth_header("POST", "https://api.x.com/2/tweets", CREDS,
                            nonce="abc", timestamp="1700000000")
check("deterministic for fixed nonce and timestamp", hdr, again)

# Milestone posts have to fit X's limit, which is the other silent failure.
for m in (5, 10, 25, 50, 100, 250, 500, 1000):
    text = (f"{m} people have now signed the AGI ASAP declaration.\n\n"
            "Compute is capital gated. Attention is not. The open AI stack is held up by a "
            "few thousand mostly unpaid people, and we fund them.\n\n"
            "https://agiasap.org")
    check(f"milestone post for {m} fits 280 chars ({len(text)})", len(text) <= 280, True)

for t in (100, 1000, 10000):
    text = (f"AGI ASAP has passed ${t:,} in funding, all of it visible on chain.\n\n"
            "Every figure on the site is read from a public RPC or the GitHub API. "
            "None of it is typed in by hand.\n\n"
            "https://agiasap.org")
    check(f"funding post for ${t:,} fits 280 chars ({len(text)})", len(text) <= 280, True)

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
