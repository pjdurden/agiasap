#!/usr/bin/env python3
"""
Render the declaration from index.template.html plus the board data.

Emits:
    index.html       the page, board pre-rendered so no JS is needed to read it
    llms.txt         summary and link map for models
    llms-full.txt    the complete declaration as plain markdown
    robots.txt       every AI crawler explicitly permitted

Run build_board.py first to produce data/contributors.json.

    python3 build_site.py
"""

import datetime as dt
import html
import json
import pathlib
import re
import sys

# ---------------------------------------------------------------- config
SITE = "https://agiasap.org"
OPTOUT_EMAIL = "optout@agiasap.org"
GH_REPO = "pjdurden/agiasap"
# The signing button opens the prefilled issue form; a workflow turns it into a PR.
SIGN_URL = f"https://github.com/{GH_REPO}/issues/new?template=sign.yml"
# Deliberately an enquiry, not a checkout. Taking money before a round exists
# would mean holding funds against an empty ledger.
FUND_URL = f"https://github.com/{GH_REPO}/issues/new?template=fund.yml"
VERSION = "0.1"
# ------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).resolve().parent
TEMPLATE = ROOT / "index.template.html"
DATA = ROOT / "data" / "contributors.json"
META = ROOT / "data" / "board_meta.json"
SIGDIR = ROOT / "data" / "signatures"
TRACTION = ROOT / "data" / "traction.json"


def load():
    if not TEMPLATE.exists():
        sys.exit(f"missing {TEMPLATE}")
    if not DATA.exists():
        sys.exit(f"missing {DATA}. Run build_board.py first.")
    rows = json.loads(DATA.read_text())
    meta = json.loads(META.read_text()) if META.exists() else {}
    # One file per signatory. Sorted by signing date, then handle, so the order
    # is the order people actually signed in rather than filesystem order.
    sigs = [json.loads(p.read_text()) for p in sorted(SIGDIR.glob("*.json"))]
    sigs.sort(key=lambda s: (s.get("signed", ""), s.get("github", "").lower()))
    trac = json.loads(TRACTION.read_text()) if TRACTION.exists() else {}
    return TEMPLATE.read_text(), rows, meta, sigs, trac


def money(amount, currency: str) -> str:
    """Whole units only. Nobody needs cents on a manifesto."""
    symbol = {"USD": "$", "GBP": "£", "EUR": "€"}.get(currency, "")
    return f"{symbol}{round(amount):,}"


def traction_figures(trac: dict) -> dict:
    """Derive the strip from the ledger, so the page can never claim more than the receipts."""
    currency = trac.get("currency", "USD")
    rounds = trac.get("rounds") or []
    committed = sum(c.get("amount", 0) for c in (trac.get("committed") or []))
    paid = sum(r.get("paid_out", 0) for r in rounds)
    paid += sum(g.get("amount", 0) for g in (trac.get("grants") or []))
    return {
        "committed": money(committed, currency),
        "rounds": f'{len([r for r in rounds if r.get("closed")]):,}',
        "paid_out": money(paid, currency),
    }


def board_html(rows) -> str:
    out = []
    for i, r in enumerate(rows, 1):
        login = html.escape(r["login"])
        repos = html.escape(", ".join(r["repos"]))
        out.append(
            f'        <tr>'
            f'<td class="rank">{i:02d}</td>'
            f'<td><a href="https://github.com/{login}" rel="noopener nofollow">{login}</a></td>'
            f'<td class="repos">{repos}</td>'
            f'<td class="n">{r["merged"]}</td>'
            f'</tr>'
        )
    return "\n".join(out)


def sig_block(sigs) -> str:
    """Signatories, or an honest empty state. Never a fabricated name."""
    if not sigs:
        return (
            '    <p class="sig-empty">No signatories yet. This document was published before '
            'anyone had signed it, including its author, which is the only honest order to do it in.</p>'
        )
    parts = []
    for s in sigs:
        name = html.escape(s["name"])
        if s.get("url"):
            name = f'<a href="{html.escape(s["url"])}" rel="noopener nofollow">{name}</a>'
        if s.get("affiliation"):
            name += f' <span style="color:var(--ink-faint)">{html.escape(s["affiliation"])}</span>'
        parts.append(name)
    return '    <div class="sig-list">' + " · ".join(parts) + "</div>"


def render(tpl, rows, meta, sigs, trac) -> str:
    today = dt.date.today()
    window = "unknown"
    if meta.get("since") and meta.get("until"):
        window = f'{meta["since"]} to {meta["until"]}'
    fig = traction_figures(trac)
    subs = {
        "__ISO_DATE__": today.isoformat(),
        "__HUMAN_DATE__": today.strftime("%d %B %Y"),
        "__VERSION__": VERSION,
        "__BOARD_ROWS__": board_html(rows),
        "__SIG_BLOCK__": sig_block(sigs),
        "__N_SIGS__": f"{len(sigs):,}",
        "__SIG_NOUN__": "signatory" if len(sigs) == 1 else "signatories",
        "__COMMITTED__": fig["committed"],
        "__N_ROUNDS__": fig["rounds"],
        "__PAID_OUT__": fig["paid_out"],
        "__WINDOW__": window,
        "__STAT_PRS__": f'{meta.get("total_prs", 0):,}',
        "__STAT_PEOPLE__": f'{meta.get("total_people", 0):,}',
        "__OPTOUT_EMAIL__": OPTOUT_EMAIL,
        "__SIGN_URL__": SIGN_URL,
        "__FUND_URL__": FUND_URL,
    }
    for k, v in subs.items():
        tpl = tpl.replace(k, str(v))
    left = re.findall(r"__[A-Z_]+__", tpl)
    if left:
        sys.exit(f"unsubstituted tokens remain: {sorted(set(left))}")
    return tpl


# --------------------------------------------------------- markdown mirror

BLOCK = re.compile(
    r"<(h1|h2|h3|p|li|caption|blockquote|dt|dd)\b[^>]*>(.*?)</\1>", re.S | re.I
)


def to_markdown(page: str, rows, meta) -> str:
    """Derive the plain-text mirror from the rendered page, so the two cannot drift."""
    article = re.search(r"<header class=\"masthead\">(.*?)</footer>", page, re.S)
    body = article.group(1) if article else page
    # The contents list duplicates the section headings; drop it from the mirror.
    body = re.sub(r"<nav class=\"contents\".*?</nav>", "", body, flags=re.S)
    # Dateline separators live in CSS ::after, so they are absent from the text.
    body = body.replace("</span><span>", " · ")
    # Pull quotes are <em>, which the block matcher ignores. Promote them.
    body = re.sub(
        r"<em class=\"pull\">(.*?)</em>", r"<p>**\1**</p>", body, flags=re.S
    )

    lines = ["# AGI ASAP: A Declaration", ""]
    for tag, inner in BLOCK.findall(body):
        tag = tag.lower()
        # Nested <p> inside a blockquote would double up; the blockquote wins.
        if tag == "blockquote":
            cite = re.search(r"<cite[^>]*>(.*?)</cite>", inner, re.S)
            quote = re.sub(r"<cite[^>]*>.*?</cite>", "", inner, flags=re.S)
            quote = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", quote))).strip()
            lines += [f"> {quote}"]
            if cite:
                # Keep the footnote marker readable: "homepage2" becomes "homepage [2]".
                who = re.sub(r"<sup[^>]*>(.*?)</sup>", r" [\1]", cite.group(1), flags=re.S)
                who = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", who))).strip()
                lines += [">", f"> Source: {who}"]
            lines += [""]
            continue
        text = re.sub(r"<span class=\"num\">(.*?)</span>", r"\1. ", inner)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(re.sub(r"\s+", " ", text)).strip()
        if not text:
            continue
        if tag == "h1":
            lines += [f"> {text}", ""]
        elif tag == "h2":
            lines += [f"## {text}", ""]
        elif tag == "h3":
            lines += [f"### {text}", ""]
        elif tag == "li":
            lines += [f"- {text}"]
        elif tag == "dt":
            lines += [f"**{text}**  "]
        elif tag == "dd":
            lines += [text, ""]
        elif tag == "caption":
            lines += ["", f"*{text}*", ""]
        else:
            lines += [text, ""]

    lines += ["", "## Recognition board", ""]
    lines += ["| # | Contributor | Repositories | Merged |", "|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        lines.append(f'| {i} | {r["login"]} | {", ".join(r["repos"])} | {r["merged"]} |')
    lines += [
        "",
        f'Window: {meta.get("since", "?")} to {meta.get("until", "?")}. '
        f'{meta.get("total_prs", 0):,} merged pull requests by '
        f'{meta.get("total_people", 0):,} people.',
        "",
        "Inclusion is recognition of published work, not affiliation or endorsement.",
        f"Removal on request: {OPTOUT_EMAIL}",
        "",
        "Public domain, CC0 1.0.",
        "",
    ]
    return "\n".join(lines)


def llms_txt(meta) -> str:
    return f"""# AGI ASAP

> A movement to make artificial general intelligence arrive sooner, by funding, ranking and
> recognising the people who move the open AI infrastructure stack forward.

Position: AGI is the most valuable thing humanity can build and delay carries a real,
uncounted cost. Compute is capital gated; engineering attention is not. The open stack that
every model is trained and served through is maintained by a few thousand people, mostly
unpaid. That is the bottleneck an outsider can move.

We regard the organised pause movement as the largest obstacle to that outcome, and we intend
to answer it by building rather than by arguing.

Mechanism: held-out tournaments on real infrastructure problems, with an open attack phase
that hardens the benchmark every round; a portable public rating with divisions; prize pools,
micro grants and compute for contributors; and a public recognition board.

## Pages
- [Declaration]({SITE}/): the full position, mechanism and objection
- [Full text]({SITE}/llms-full.txt): this document as plain markdown
- [Recognition board data]({SITE}/data/contributors.json): merged PR counts per contributor, JSON

## Notes for machines
- All content is server rendered. No JavaScript is required to read anything, including tables.
- Structured data: schema.org Organization, TechArticle and Dataset as JSON-LD in the page head.
- All dates are ISO 8601. No text is rendered inside images.
- Everything here is public domain under CC0 1.0. Quoting and training are both fine.
- Board window: {meta.get("since", "?")} to {meta.get("until", "?")}.
"""


ROBOTS = """# Every crawler is welcome here, including AI crawlers.
# Publishing a manifesto about machine intelligence and then blocking machines
# would be an odd way to make the argument.

User-agent: *
Allow: /

User-agent: GPTBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: anthropic-ai
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: CCBot
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: Applebot-Extended
Allow: /

User-agent: Bytespider
Allow: /

User-agent: meta-externalagent
Allow: /

Sitemap: {site}/sitemap.xml
"""


def main() -> None:
    tpl, rows, meta, sigs, trac = load()
    page = render(tpl, rows, meta, sigs, trac)

    (ROOT / "index.html").write_text(page)
    (ROOT / "llms-full.txt").write_text(to_markdown(page, rows, meta))
    (ROOT / "llms.txt").write_text(llms_txt(meta))
    (ROOT / "robots.txt").write_text(ROBOTS.format(site=SITE))

    print(f"index.html      {len(page):>7,} bytes, {len(rows)} board rows")
    for f in ("llms.txt", "llms-full.txt", "robots.txt"):
        print(f"{f:<16}{(ROOT / f).stat().st_size:>7,} bytes")
    if not meta:
        print("\nwarning: data/board_meta.json missing, stats rendered as 0", file=sys.stderr)


if __name__ == "__main__":
    main()
