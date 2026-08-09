#!/usr/bin/env python3
"""
Read what has actually arrived at the funding addresses and write data/treasury.json.

The point of publishing an address is that the figure stops being a claim. So the
number on the page is read from the chain rather than typed into a file, and it
can be reproduced by anyone with curl.

    python3 read_treasury.py

Public RPCs, no keys, no dependencies. Stablecoins are counted at face value;
native balances are converted using Coinbase spot, and if that call fails the
native holding is still recorded but excluded from the USD total, so the
published figure is never an overstatement.
"""

import json
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
FUNDING = ROOT / "data" / "funding.json"
OUT = ROOT / "data" / "treasury.json"

# chain -> (rpc, native symbol, {token symbol: (contract, decimals)})
CHAINS = {
    "Ethereum": (
        "https://ethereum-rpc.publicnode.com", "ETH",
        {"USDC": ("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6),
         "USDT": ("0xdAC17F958D2ee523a2206206994597C13D831ec7", 6)},
    ),
    "Base": (
        "https://mainnet.base.org", "ETH",
        {"USDC": ("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6)},
    ),
    "Arbitrum": (
        "https://arb1.arbitrum.io/rpc", "ETH",
        {"USDC": ("0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6),
         "USDT": ("0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", 6)},
    ),
    "Optimism": (
        "https://mainnet.optimism.io", "ETH",
        {"USDC": ("0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85", 6),
         "USDT": ("0x94b008aA00579c1307B0EF2c499aD98a8ce58e58", 6)},
    ),
    "Polygon": (
        "https://polygon-bor-rpc.publicnode.com", "POL",
        {"USDC": ("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", 6),
         "USDT": ("0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 6)},
    ),
}

BALANCE_OF = "0x70a08231"


def rpc(url: str, method: str, params: list):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "content-type": "application/json",
            # Several public RPCs reject the default Python user-agent with a 403.
            "user-agent": "Mozilla/5.0 (compatible; agiasap-treasury/1.0)",
            "accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        out = json.load(r)
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]


def native_price(symbol: str) -> float | None:
    """Coinbase spot. Returns None rather than guessing if it is unavailable."""
    try:
        with urllib.request.urlopen(
            f"https://api.coinbase.com/v2/prices/{symbol}-USD/spot", timeout=15
        ) as r:
            return float(json.load(r)["data"]["amount"])
    except (urllib.error.URLError, KeyError, ValueError, TimeoutError):
        return None


def main() -> None:
    fund = json.loads(FUNDING.read_text())
    wallets = [w for w in (fund.get("wallets") or []) if (w.get("type") or "evm") == "evm"]
    if not wallets:
        OUT.write_text(json.dumps({"usd_total": 0, "holdings": [], "priced": True}, indent=2) + "\n")
        print("no EVM wallets configured")
        return

    prices: dict[str, float | None] = {}
    holdings, usd_total = [], 0.0
    unpriced = False
    # A chain we could not read might hold funds we are not counting. That makes
    # the published total an understatement, which is the safe direction, but it
    # must be visible rather than silent.
    unreadable: set[str] = set()

    for w in wallets:
        addr = w["address"]
        arg = "0x" + BALANCE_OF[2:] + addr[2:].lower().rjust(64, "0")
        for chain, (url, native, tokens) in CHAINS.items():
            try:
                raw = int(rpc(url, "eth_getBalance", [addr, "latest"]), 16)
            except Exception as e:
                print(f"  {chain}: native read failed ({e})", file=sys.stderr)
                unreadable.add(chain)
                raw = 0
            if raw:
                amount = raw / 1e18
                if native not in prices:
                    prices[native] = native_price(native)
                px = prices[native]
                usd = amount * px if px else None
                if usd is None:
                    unpriced = True
                else:
                    usd_total += usd
                holdings.append({"chain": chain, "asset": native,
                                 "amount": round(amount, 8), "usd": round(usd, 2) if usd else None})

            for sym, (contract, dec) in tokens.items():
                try:
                    raw = int(rpc(url, "eth_call", [{"to": contract, "data": arg}, "latest"]), 16)
                except Exception as e:
                    print(f"  {chain}: {sym} read failed ({e})", file=sys.stderr)
                    unreadable.add(chain)
                    continue
                if raw:
                    amount = raw / (10 ** dec)
                    usd_total += amount  # stablecoin, face value
                    holdings.append({"chain": chain, "asset": sym,
                                     "amount": round(amount, 6), "usd": round(amount, 2)})

    result = {
        "usd_total": round(usd_total, 2),
        "holdings": sorted(holdings, key=lambda h: -(h["usd"] or 0)),
        "priced": not unpriced,
        "complete": not unreadable,
        "unreadable_chains": sorted(unreadable),
        "addresses": [w["address"] for w in wallets],
        "note": "Read from public RPCs. Stablecoins at face value, native assets at "
                "Coinbase spot. Anything unpriced is listed but excluded from the total.",
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")

    print(f"treasury: ${result['usd_total']:,.2f} across {len(holdings)} holding(s)")
    for h in holdings:
        print(f"  {h['chain']:<10} {h['amount']} {h['asset']}")
    if unreadable:
        print(f"\nWARNING: could not read {', '.join(sorted(unreadable))}. "
              "The total may be an understatement.", file=sys.stderr)


if __name__ == "__main__":
    main()
