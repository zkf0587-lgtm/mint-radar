"""Clawby 只读复核：DEV 历史。需要 GitHub Secret CLAWBY_API_KEY；没有就跳过。
免费档约 5 次/分钟，每轮最多查 2 个，间隔 13 秒；429 立刻停。"""
import json, os, time, urllib.request

_calls = {"n": 0, "banned": False}

def relay(name, params):
    key = os.environ.get("CLAWBY_API_KEY")
    if not key or _calls["banned"] or _calls["n"] >= 2: return None
    if _calls["n"]: time.sleep(13)
    _calls["n"] += 1
    try:
        r = urllib.request.urlopen(urllib.request.Request("https://api.openclawby.com/api/relay",
            data=json.dumps({"name": name, "params": params}).encode(),
            headers={"X-API-Key": key, "Content-Type": "application/json", "user-agent": "Mozilla/5.0"}), timeout=25)
        d = json.loads(r.read())
    except Exception:
        return None
    if "429" in str(d.get("error", "")): _calls["banned"] = True; return None
    return d.get("data")

def _num(d, *ks):
    for k in ks:
        if isinstance(d, dict) and d.get(k) is not None: return d.get(k)
    return None

def dev_line(creator, st):
    """返回 (一行中文, 是否拉黑)。"""
    if not creator or len(creator) != 42: return ("DEV 地址未知", False)
    cache = st.setdefault("dev_cache", {})
    c = cache.get(creator.lower())
    if c and time.time() - c["t"] < 86400: return (c["line"], c["bad"])
    d = relay("dex_wallet_created_tokens", {"chain": "bsc", "wallet_address": creator})
    if d is None: return ("DEV 历史未核实（Clawby 未配置或限速）", False)
    toks = d.get("tokens") if isinstance(d, dict) else d
    n = len(toks) if isinstance(toks, list) else _num(d, "total", "token_count", "count")
    ratio = _num(d, "open_ratio", "opened_ratio")
    ath = _num(d.get("creator_ath_info") or {}, "ath_mc", "market_cap", "ath_market_cap") if isinstance(d, dict) else None
    rugs = 0
    if isinstance(toks, list):
        for t in toks:
            s = json.dumps(t).lower()
            if '"is_rug": true' in s or '"rug": true' in s or 'rugged' in s: rugs += 1
    try: n = int(n or 0)
    except Exception: n = 0
    bad = n >= 10 or rugs >= 2
    line = f"DEV 历史：发过 {n} 个币" + (f"，开盘率 {float(ratio):.0%}" if ratio is not None else "") + \
           (f"，疑似割人 {rugs} 个" if rugs else "") + (f"，最高市值 ${int(float(ath)):,}" if ath else "") + ("（⚠️连发/有前科，不碰）" if bad else "")
    cache[creator.lower()] = {"t": time.time(), "line": line, "bad": bad}
    return (line, bad)
