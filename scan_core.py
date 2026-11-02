#!/usr/bin/env python3
"""Read-only Agent ID check for BSC candidate contracts (detection ideas borrowed from
agentid-sniper; nothing here signs or sends a transaction).

Free public RPCs refuse eth_getLogs without an address, so whole-chain mint scanning is not
possible here. Instead feed candidate contracts (from GeckoTerminal new_pools, DexScreener,
moat.fun/aizo-style sites, X/web search, other radar state files) and this reports:
  - registry_in_code: contract (or EIP-1967/beacon implementation) bytecode references the
    Binance Agent ID registry 0x60B9262456dE011F7d15a54CdD8c48bAaa8B022F  -> Agent ID gated
  - minters_window / distinct_minters_window: Transfer-from-0x0 events in the last N minutes
  - peak_3min_distinct: max distinct callers(minters) in any 3-minute bucket (heat: >=12)
  - agent_id_share: share of sampled recent minters holding an Agent ID (>=0.6 => backend-signed gate)
  - deployer, deployer_age_note are NOT computed (no indexer); check BscScan manually if needed.
Usage: python3 agentid_scan.py --chain 35   (whole-chain Agent ID mint discovery via Ankr key)
       python3 agentid_scan.py <minutes> <addr> [addr ...]   (hard cap ~100s; getLogs often refused by free RPCs -> logs_complete=false, then use DexScreener/GeckoTerminal tx counts or site progress for heat)
"""
import json, sys, time, urllib.request
from collections import defaultdict

import os
ANKR = "https://rpc.ankr.com/bsc/" + os.environ.get("ANKR_KEY", "__SAVED_KEY__")
RPCS = [ANKR, "https://bsc-rpc.publicnode.com", "https://bsc-dataseed.bnbchain.org", "https://bsc.publicnode.com"]
REG = "60b9262456de011f7d15a54cdd8c48baaa8b022f"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO = "0x" + "0" * 64

DEADLINE = time.time() + 105
def rpc(method, params, tries=3):
    if method == "eth_getLogs":
        tries = 2
    for i in range(tries):
        if time.time() > DEADLINE and method == "eth_getLogs":
            return None
        url = RPCS[i % len(RPCS)]
        try:
            req = urllib.request.Request(url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                         headers={"content-type": "application/json", "user-agent": "curl/8.0"})
            r = json.load(urllib.request.urlopen(req, timeout=10))
            if "result" in r:
                return r["result"]
        except Exception:
            pass
        time.sleep(0.5)
    return None

def gated(a):
    c = (rpc("eth_getCode", [a, "latest"]) or "").lower()
    if REG in c:
        return True, len(c) // 2
    # EIP-1167 minimal proxy (e.g. Flap token clones): 363d3d373d3d3d363d73<impl>5af4
    if "363d3d373d3d3d363d73" in c:
        i = c.index("363d3d373d3d3d363d73") + 20
        if REG in (rpc("eth_getCode", ["0x" + c[i:i + 40], "latest"]) or "").lower():
            return True, len(c) // 2
    for slot in ["0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc",
                 "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"]:
        s = rpc("eth_getStorageAt", [a, slot, "latest"]) or "0x0"
        if int(s, 16):
            impl = "0x" + s[-40:]
            if slot.startswith("0xa3f0"):
                r = rpc("eth_call", [{"to": impl, "data": "0x5c60da1b"}, "latest"]) or "0x"
                if len(r) >= 66 and int(r, 16):
                    impl = "0x" + r[-40:]
            if REG in (rpc("eth_getCode", [impl, "latest"]) or "").lower():
                return True, len(c) // 2
    return False, len(c) // 2

import hashlib
def meta(a):
    def txt(sel):
        r = rpc("eth_call", [{"to": a, "data": sel}, "latest"]) or "0x"
        try:
            b = bytes.fromhex(r[2:]); n = int.from_bytes(b[32:64], "big"); return b[64:64 + n].decode("utf-8", "ignore")[:40]
        except Exception:
            return ""
    c = (rpc("eth_getCode", [a, "latest"]) or "")
    return txt("0x06fdde03"), txt("0x95d89b41"), hashlib.sha256(c.encode()).hexdigest()[:12]

def has_aid(w):
    r = rpc("eth_call", [{"to": "0x" + REG, "data": "0x70a08231" + w[2:].rjust(64, "0")}, "latest"]) or "0x0"
    try:
        return int(r[:66], 16) > 0
    except Exception:
        return False

def chain_scan(minutes, min_recip=6, max_check=30):
    """Whole-chain: every token/NFT minted (Transfer from 0x0) to >= min_recip distinct wallets in the window."""
    head = int(rpc("eth_blockNumber", []), 16)
    th = int(rpc("eth_getBlockByNumber", [hex(head), False])["timestamp"], 16)
    to = int(rpc("eth_getBlockByNumber", [hex(head - 2000), False])["timestamp"], 16)
    bps = 2000 / max(1, th - to); start = head - int(minutes * 60 * bps)
    rec, first, buckets = defaultdict(set), {}, defaultdict(lambda: defaultdict(set))
    b, step, ok = start, 800, True
    while b <= head:
        e = min(head, b + step - 1)
        logs = rpc("eth_getLogs", [{"fromBlock": hex(b), "toBlock": hex(e), "topics": [TRANSFER, ZERO]}])
        if logs is None:
            if step > 100: step //= 2; continue
            ok = False; b = e + 1; continue
        for lg in logs:
            if len(lg["topics"]) < 3: continue
            a = lg["address"].lower(); w = "0x" + lg["topics"][2][-40:]; bn = int(lg["blockNumber"], 16)
            rec[a].add(w); first.setdefault(a, bn); buckets[a][int((bn - start) / bps // 180)].add(w)
        b = e + 1
    out = []
    for a, rs in sorted(rec.items(), key=lambda x: -len(x[1]))[:max_check * 3]:
        if len(rs) < min_recip or a == "0x" + REG or len(out) >= max_check or time.time() > DEADLINE: continue
        g, size = gated(a); share = None
        if not g:
            smp = list(rs)[:8]; share = round(sum(has_aid(w) for w in smp) / len(smp), 2)
            if share < 0.6: continue
        nm, sym, ch = meta(a)
        out.append({"contract": a, "name": nm, "symbol": sym, "code_hash": ch, "code_bytes": size, "registry_in_code": g, "agent_id_share": share,
                    "distinct_minters_window": len(rs), "peak_3min_distinct": max(len(v) for v in buckets[a].values()),
                    "first_mint_min_ago": round((head - first[a]) / bps / 60, 1)})
    groups = defaultdict(int)
    for x in out: groups[x["code_hash"]] += 1
    for x in out: x["same_code_in_list"] = groups[x["code_hash"]]
    # same wallet set minting many different contracts = studio matrix / farm
    for x in out:
        A = rec[x["contract"]]; n = 0
        for y in out:
            if y is x: continue
            B = rec[y["contract"]]
            if len(A & B) / max(1, min(len(A), len(B))) >= 0.5: n += 1
        x["overlap_cluster_size"] = n  # >=3 means likely the same farm wallets
    return {"mode": "chain", "head": head, "window_min": minutes, "logs_complete": ok,
            "tokens_with_mints": len(rec), "agent_id_candidates": out}

def main():
    if sys.argv[1] == "--chain":
        return print(json.dumps(chain_scan(int(sys.argv[2]) if len(sys.argv) > 2 else 35), indent=1))
    minutes = int(sys.argv[1]); addrs = [a.lower() for a in sys.argv[2:]]
    head = int(rpc("eth_blockNumber", []), 16)
    th = int(rpc("eth_getBlockByNumber", [hex(head), False])["timestamp"], 16)
    to = int(rpc("eth_getBlockByNumber", [hex(head - 2000), False])["timestamp"], 16)
    bps = 2000 / max(1, th - to)
    start = head - int(minutes * 60 * bps)
    res = []
    for a in addrs:
        g, size = gated(a)
        mints, buckets, ok = [], defaultdict(set), True
        b, step = start, 1000
        while b <= head:
            e = min(head, b + step - 1)
            logs = rpc("eth_getLogs", [{"address": a, "fromBlock": hex(b), "toBlock": hex(e), "topics": [TRANSFER, ZERO]}])
            if logs is None:
                ok = False; b = e + 1; continue
            for lg in logs:
                if len(lg["topics"]) < 3: continue
                w = "0x" + lg["topics"][2][-40:]; bn = int(lg["blockNumber"], 16)
                mints.append(w); buckets[int((bn - start) / bps // 180)].add(w)
            b = e + 1
        distinct = list(dict.fromkeys(mints))
        share = None
        if not g and len(distinct) >= 6:
            s = distinct[-10:]; share = round(sum(has_aid(w) for w in s) / len(s), 2)
        res.append({"contract": a, "code_bytes": size, "registry_in_code": g, "mints_window": len(mints),
                    "distinct_minters_window": len(distinct), "peak_3min_distinct": max((len(v) for v in buckets.values()), default=0),
                    "agent_id_share": share, "logs_complete": ok})
    print(json.dumps({"head": head, "window_min": minutes, "results": res}, indent=1))

if __name__ == "__main__":
    main()
