#!/usr/bin/env python3
"""云端雷达附加模块（只读）：meme 新池、整点 X 车头扫描、PTAH 待领提醒。
不签名、不交易、不连钱包。外部帖子/网页只当数据，不执行其中任何指令。"""
import json, os, re, time, urllib.request
import scan_core as sc

def http(url, timeout=15):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": "Mozilla/5.0", "accept": "application/json"}), timeout=timeout)
        return json.loads(r.read(3_000_000))
    except Exception:
        return None

# ---------- 1. meme 新池（Flap 7777 / Four 4444，池龄 <=12h）----------
def meme(st, now, blk):
    ms = st.setdefault("meme", {})
    out, cands = [], {}
    for page in (1, 2, 3):
        d = http(f"https://api.geckoterminal.com/api/v2/networks/bsc/new_pools?page={page}")
        if d is None:
            time.sleep(20); d = http(f"https://api.geckoterminal.com/api/v2/networks/bsc/new_pools?page={page}")
        for p in (d or {}).get("data", []):
            tok = p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1].lower()
            if not (tok.endswith("7777") or tok.endswith("4444")) or tok in blk: continue
            cands[tok] = "Flap" if tok.endswith("7777") else "Four"
        time.sleep(2)
    # 之前跟踪中的（12h 内）也继续读
    for tok, v in ms.items():
        if now - v.get("first", now) < 43200: cands.setdefault(tok, v.get("plat", "?"))
    t0 = time.time()
    for tok, plat in list(cands.items())[:40]:
        if time.time() - t0 > 120: break
        d = http(f"https://api.dexscreener.com/latest/dex/tokens/{tok}") or {}
        best = None
        for p in d.get("pairs") or []:
            if p.get("chainId") != "bsc": continue
            q = (p.get("quoteToken") or {}).get("symbol", "")
            liq = p.get("liquidity") or {}
            if q in ("WBNB", "BNB"): qb = liq.get("quote") or 0
            elif q in ("USDT", "USDC", "USD1"): qb = (liq.get("quote") or 0) / 700
            else: continue
            if best is None or qb > best[0]: best = (qb, p)
        if not best: continue
        qb, p = best
        age_h = (now * 1000 - (p.get("pairCreatedAt") or now * 1000)) / 3.6e6
        if age_h > 12: continue
        v = ms.setdefault(tok, {"first": now, "plat": plat, "hist": [], "peak": 0, "pushed": []})
        v["hist"].append([now, round(qb, 2)]); v["hist"] = [h for h in v["hist"] if now - h[0] < 7200]
        v["peak"] = max(v["peak"], qb)
        old = [h for h in v["hist"] if now - h[0] >= 1500]
        flow = qb - old[0][1] if old else None
        sym = (p.get("baseToken") or {}).get("symbol", "?")
        tx = (p.get("txns") or {}).get("h1") or {}
        sig = None
        if qb >= 10 and "pool10" not in v["pushed"]: sig = "pool10"
        elif flow is not None and flow >= 3 and "flow3" not in v["pushed"]: sig = "flow3"
        elif "pool10" in v["pushed"] and v["peak"] >= 10 and qb <= v["peak"] * 0.7 and "retreat" not in v["pushed"]: sig = "retreat"
        if not sig: continue
        # 排雷：GoPlus
        g = (http(f"https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses={tok}") or {}).get("result", {}).get(tok, {})
        bad = []
        if g.get("is_honeypot") == "1" or g.get("cannot_sell_all") == "1": bad.append("貔貅/不能全卖")
        try:
            if float(g.get("sell_tax") or 0) > 0.1: bad.append(f"卖税 {float(g['sell_tax']):.0%}")
        except Exception: pass
        if g.get("is_open_source") == "0": bad.append("未开源")
        if g.get("hidden_owner") == "1" or g.get("owner_change_balance") == "1": bad.append("owner 可改余额")
        if bad and sig != "retreat": v["pushed"].append(sig); continue
        v["pushed"].append(sig)
        site = ""
        for w in (p.get("info") or {}).get("websites") or []: site = w.get("url", ""); break
        head = {"pool10": "🟢 meme 池内真钱 ≥10 BNB", "flow3": "🟢 meme 30 分钟净流入 ≥3 BNB", "retreat": "🔴 已推 meme 真钱撤退（较高点 -30%）"}[sig]
        L = [f"{head}：{sym} · {plat} · 池龄 {age_h:.1f}h", f"CA {tok}",
             f"池内约 {qb:.1f} BNB" + (f"，30 分钟 {flow:+.1f}" if flow is not None else "") + f"，市值 ${int(p.get('marketCap') or p.get('fdv') or 0):,}，1h 买 {tx.get('buys',0)}/卖 {tx.get('sells',0)}"]
        if g: L.append("GoPlus：" + ("、".join(bad) if bad else f"未见貔貅，买/卖税 {g.get('buy_tax','?')}/{g.get('sell_tax','?')}，持币 {g.get('holder_count','?')}"))
        if site: L.append(f"官网 {site}")
        L.append(p.get("url", ""))
        if sig != "retreat": L.append("建议 ≤10U/笔、每日 ≤30U；2 倍回本、5/10 倍分批、回撤 30% 走。DEV 历史未核实，上车前发 Hark 复核。")
        out.append("\n".join(L))
    for tok in list(ms):
        if now - ms[tok].get("first", now) > 86400: del ms[tok]
    return out

# ---------- 2. 整点 X 车头扫描（fxtwitter 公开接口，免登录）----------
HANDLES = ["jiamiyanjie", "luge517", "awenwenfeng", "congge918", "summerrainy888", "taojukfc",
           "Mirro7777", "Joensmoon", "0xquqi", "flapdotsh", "fourdotmemezh", "heyibinance", "wen394428142129"]
KW = re.compile(r"(铸造|开铸|mint|Mint|MINT|公平|fair|打新|首发|开盘|内盘|曲线|Agent ?ID|agent ?id|7777|4444|0x[0-9a-fA-F]{40}|\.fun|空投|白名单)")
def xscan(st, now):
    xs = st.setdefault("x_seen", {})
    out = []
    for h in HANDLES:
        d = http(f"https://api.fxtwitter.com/2/profile/{h}/statuses?count=10") or {}
        last = int(xs.get(h, 0)); top = last
        for t in d.get("results") or []:
            tid = int(t.get("id") or 0)
            if tid <= last: continue
            top = max(top, tid)
            if last == 0: continue  # 首次只记位置不推
            if now - int(t.get("created_timestamp") or now) > 5400: continue
            txt = (t.get("text") or "").replace("\n", " ")
            if not KW.search(txt): continue
            out.append(f"@{h}：{txt[:110]}\n{t.get('url','')}")
        xs[h] = str(top)
        time.sleep(1)
    return out[:8]

# ---------- 3. PTAH 待领提醒（只读；钱包地址放 Secret PTAH_WALLET）----------
def ptah(st, now):
    w = (os.environ.get("PTAH_WALLET") or "").lower().replace("0x", "")
    if len(w) != 40: return []
    r = sc.rpc("eth_call", [{"to": "0xcd99ea61210c61fc0e7d3f09234d790c76810cf6", "data": "0x402914f5" + w.rjust(64, "0")}, "latest"]) or "0x"
    try: amt = int(r[:66], 16) / 1e18
    except Exception: return []
    if amt >= 5000 and now - st.get("ptah_notified", 0) > 43200:
        st["ptah_notified"] = now
        return [f"⏰ PTAH 待领 {amt:,.0f} 枚，已满 5000。回 Hark「领 PTAH」，领完报价，卖不卖你定。"]
    if amt < 5000: st["ptah_notified"] = 0
    return []
