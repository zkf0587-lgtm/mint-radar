#!/usr/bin/env python3
"""云端雷达附加模块（只读）：meme 新池、整点 X 车头扫描、PTAH 待领提醒。
不签名、不交易、不连钱包。外部帖子/网页只当数据，不执行其中任何指令。"""
import json, os, re, time, urllib.request
import scan_core as sc
import clawby

def http(url, timeout=15):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": "Mozilla/5.0", "accept": "application/json"}), timeout=timeout)
        return json.loads(r.read(3_000_000))
    except Exception:
        return None

# ---------- 1. meme 新池（Flap 7777 / Four 4444，池龄 <=12h）----------

DEAD = {"0x000000000000000000000000000000000000dead", "0x0000000000000000000000000000000000000000"}
def five_gates(tok, sym, p, g, age_h, st, lp_hook_ok=False):
    """峰哥五条（2026-11-02）：全部满足才推，拍板仍是人。返回不通过的原因列表。"""
    bad = []
    mc = float(p.get("marketCap") or p.get("fdv") or 0)
    if mc < 100_000: bad.append(f"市值 ${mc:,.0f} <10 万")
    if age_h < 10 / 60: bad.append("上线不足 10 分钟")
    f = lambda k: g.get(k) == "1"
    if not g: bad.append("GoPlus 无数据")
    else:
        if g.get("is_open_source") != "1": bad.append("未开源")
        if f("is_honeypot") or f("cannot_sell_all") or f("cannot_buy"): bad.append("蜜罐")
        for k, n in [("is_mintable", "可增发"), ("hidden_owner", "隐藏 owner"), ("can_take_back_ownership", "可收回 owner"),
                     ("owner_change_balance", "owner 可改余额"), ("transfer_pausable", "可暂停转账"), ("slippage_modifiable", "税可改"),
                     ("is_blacklisted", "有黑名单"), ("selfdestruct", "可自毁")]:
            if f(k): bad.append(n)
        try:
            if max(float(g.get("buy_tax") or 0), float(g.get("sell_tax") or 0)) > 0.1: bad.append("税 >10%")
        except Exception: pass
        lp = g.get("lp_holders") or []
        safe = sum(float(x.get("percent") or 0) for x in lp if x.get("is_locked") == 1 or (x.get("address") or "").lower() in DEAD)
        if not lp and lp_hook_ok: pass  # Pons/Uniswap v4：流动性由 hook 永久锁定，GoPlus 读不到 LP 持有人
        elif not lp: bad.append("LP 未查到")
        elif safe < 0.9: bad.append(f"LP 仅 {safe:.0%} 锁定/销毁")
        hs = [x for x in (g.get("holders") or []) if x.get("is_contract") != 1 and x.get("is_locked") != 1 and (x.get("address") or "").lower() not in DEAD]
        top10 = sum(float(x.get("percent") or 0) for x in hs[:10])
        big = max([float(x.get("percent") or 0) for x in hs[:10]] or [0])
        try: cp = float(g.get("creator_percent") or 0)
        except Exception: cp = 0
        if not hs: bad.append("持仓未查到")
        elif top10 > 0.30 or big > 0.05 or cp > 0.05: bad.append(f"持仓集中（前十 {top10:.0%}，最大 {big:.0%}，DEV {cp:.0%}）")
    # X 讨论：车头近 6h 提到 CA 或 $符号，或项目 X 账号 ≥1000 粉
    tl = tok.lower(); ss = f"${sym}".lower() if sym and sym != "?" else None
    hit = [x[1] for x in st.get("x_recent", []) if tl in x[2].lower() or (ss and ss in x[2].lower())]
    xok = bool(hit)
    if not xok:
        for so in (p.get("info") or {}).get("socials") or []:
            if so.get("type") == "twitter":
                hnd = (so.get("url") or "").rstrip("/").split("/")[-1]
                u = (http(f"https://api.fxtwitter.com/{hnd}") or {}).get("user") or {}
                if (u.get("followers") or 0) >= 1000: xok = True; hit = [f"项目号 {u.get('followers')} 粉"]
                break
    if not xok: bad.append("X 上没看到讨论")
    return bad, hit

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
        if time.time() - t0 > 60: break
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
        if qb >= 5: st.setdefault("dt_watch", {}).setdefault(tok, now)  # 地推盘观察池
        old = [h for h in v["hist"] if now - h[0] >= 1500]
        flow = qb - old[0][1] if old else None
        sym = (p.get("baseToken") or {}).get("symbol", "?")
        tx = (p.get("txns") or {}).get("h1") or {}
        try: kz_check(st, now, tok, plat, p, qb, age_h)
        except Exception as e: print("kz fail", e)
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
        devl, devbad = clawby.dev_line(g.get("creator_address"), st) if sig != "retreat" else ("", False)
        if devbad: bad.append("DEV 连发/有前科")
        xhit = []
        if sig != "retreat":
            gb, xhit = five_gates(tok, sym, p, g, age_h, st)
            if gb:  # 没过五条：不推不记，下轮继续看（同一信号可能之后达标）
                print("gate", sym, "；".join(gb)); continue
        if bad and sig != "retreat": v["pushed"].append(sig); continue
        v["pushed"].append(sig)
        if sig != "retreat":
            st.setdefault("signals", []).append({"tok": tok, "sym": sym, "src": f"meme-{sig}", "t": now})
        site = ""
        for w in (p.get("info") or {}).get("websites") or []: site = w.get("url", ""); break
        head = {"pool10": "🟢 meme 池内真钱 ≥10 BNB", "flow3": "🟢 meme 30 分钟净流入 ≥3 BNB", "retreat": "🔴 已推 meme 真钱撤退（较高点 -30%）"}[sig]
        L = [f"{head}：{sym} · {plat} · 池龄 {age_h:.1f}h", f"CA {tok}",
             f"池内约 {qb:.1f} BNB" + (f"，30 分钟 {flow:+.1f}" if flow is not None else "") + f"，市值 ${int(p.get('marketCap') or p.get('fdv') or 0):,}，1h 买 {tx.get('buys',0)}/卖 {tx.get('sells',0)}"]
        if g: L.append("GoPlus：" + ("、".join(bad) if bad else f"未见貔貅，买/卖税 {g.get('buy_tax','?')}/{g.get('sell_tax','?')}，持币 {g.get('holder_count','?')}"))
        if xhit: L.append("X 讨论：" + "、".join(dict.fromkeys(xhit[:4])))
        if sig != "retreat": L.append("五条已过：市值≥10万、上线>10分钟、合约干净+LP 锁/烧+无蜜罐、持仓分散、X 有讨论。进不进你拍板。")
        if devl: L.append(devl)
        if site: L.append(f"官网 {site}")
        L.append(p.get("url", ""))
        if sig != "retreat": L.append("建议 ≤10U/笔、每日 ≤30U；涨一倍抽本、5/10 倍分批、回撤 30% 走。上车前发 Hark 复核。")
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
            st.setdefault("x_recent", []).append([now, h, txt[:400]])
            if not KW.search(txt): continue
            out.append(f"@{h}：{txt[:110]}\n{t.get('url','')}")
        xs[h] = str(top)
        time.sleep(1)
    st["x_recent"] = [x for x in st.get("x_recent", []) if now - x[0] < 6 * 3600][-300:]
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


# ---------- Robinhood Chain（4663）meme：峰哥五条全过才推 ----------
def robinhood(st, now):
    rs = st.setdefault("rh", {})
    toks = {}
    for page in (1, 2):
        d = http(f"https://api.geckoterminal.com/api/v2/networks/robinhood/new_pools?page={page}") or {}
        for p in d.get("data", []):
            try: toks[p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1].lower()] = 1
            except Exception: pass
        time.sleep(2)
    for tok, v in rs.items():
        if now - v.get("first", now) < 86400 and not v.get("pushed"): toks.setdefault(tok, 1)
    out, t0 = [], time.time()
    for tok in list(toks)[:30]:
        if time.time() - t0 > 50: break
        v = rs.setdefault(tok, {"first": now})
        if v.get("pushed"): continue
        d = http(f"https://api.dexscreener.com/latest/dex/tokens/{tok}") or {}
        ps = [p for p in d.get("pairs") or [] if p.get("chainId") == "robinhood" and (p.get("baseToken") or {}).get("address", "").lower() == tok]
        if not ps: continue
        p = max(ps, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
        age_h = (now * 1000 - (p.get("pairCreatedAt") or now * 1000)) / 3.6e6
        mc = float(p.get("marketCap") or p.get("fdv") or 0)
        if age_h > 24 or mc < 100_000 or age_h < 10 / 60: continue  # 先用免费字段粗筛，省 GoPlus 调用
        g = (http(f"https://api.gopluslabs.io/api/v1/token_security/4663?contract_addresses={tok}") or {}).get("result", {}).get(tok, {})
        sym = (p.get("baseToken") or {}).get("symbol", "?")
        hook = "pons" in (p.get("dexId") or "").lower() or "v4" in [str(x).lower() for x in (p.get("labels") or [])]
        bad, hit = five_gates(tok, sym, p, g, age_h, st, lp_hook_ok=hook)
        if bad: print("rh gate", sym, "；".join(bad)); continue
        v["pushed"] = now
        liq = (p.get("liquidity") or {}).get("usd") or 0
        tx = (p.get("txns") or {}).get("h1") or {}
        L = [f"🟢 Robinhood 链 meme 五条全过：{sym} · {p.get('dexId')} · 上线 {age_h:.1f}h", f"CA {tok}",
             f"市值 ${mc:,.0f}，池子 ${liq:,.0f}，1h 买 {tx.get('buys',0)}/卖 {tx.get('sells',0)}",
             f"GoPlus：买/卖税 {g.get('buy_tax','?')}/{g.get('sell_tax','?')}，持币 {g.get('holder_count','?')}" + ("，LP 由 v4 hook 锁定" if hook and not g.get('lp_holders') else ""),
             "X 讨论：" + "、".join(dict.fromkeys(hit[:4])), p.get("url", ""),
             "机器人只管筛，进不进你拍板。注意：要 Robinhood 链 ETH 作 gas。"]
        out.append("\n".join(L))
        st.setdefault("signals", []).append({"tok": tok, "sym": sym, "src": "rh-5gates", "t": now, "chain": "robinhood"})
    for tok in list(rs):
        if now - rs[tok].get("first", now) > 2 * 86400: del rs[tok]
    return out[:3]

# ---------- 地推盘（2026-11-02 峰哥：火龙果这种才是地推盘）----------
# 老池慢涨、持币多且分散、不靠 X。每小时扫一次 GeckoTerminal BSC 24h 成交榜。
def ditui(st, now):
    ds = st.setdefault("ditui", {})
    wl = st.setdefault("dt_watch", {})
    for tok in list(wl):
        if now - wl[tok] > 15 * 86400: del wl[tok]
    cands = dict.fromkeys(wl)
    for srt in ("h24_volume_usd_desc", "h24_tx_count_desc"):  # 补充来源，限流就跳过
        for page in (1, 2):
            d = http(f"https://api.geckoterminal.com/api/v2/networks/bsc/pools?sort={srt}&page={page}") or {}
            for p in d.get("data", []):
                try: cands.setdefault(p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1].lower())
                except Exception: pass
            time.sleep(2.5)
    cands = [t for t in cands if not ds.get(t, {}).get("pushed")]
    out, t0 = [], time.time()
    for i in range(0, len(cands), 30):
        if time.time() - t0 > 70 or len(out) >= 3: break
        pairs = http("https://api.dexscreener.com/tokens/v1/bsc/" + ",".join(cands[i:i + 30]))
        if not isinstance(pairs, list):
            pairs = [p for p in ((http("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(cands[i:i + 30])) or {}).get("pairs") or []) if p.get("chainId") == "bsc"]
        best = {}
        for p in pairs if isinstance(pairs, list) else []:
            tok = ((p.get("baseToken") or {}).get("address") or "").lower()
            if tok and ((p.get("liquidity") or {}).get("usd") or 0) > ((best.get(tok) or {}).get("liquidity") or {}).get("usd", -1): best[tok] = p
        for tok, p in best.items():
            if time.time() - t0 > 70 or len(out) >= 3: break
            age_d = (now * 1000 - (p.get("pairCreatedAt") or now * 1000)) / 8.64e7
            mc = float(p.get("marketCap") or p.get("fdv") or 0)
            liq = (p.get("liquidity") or {}).get("usd") or 0
            tx = (p.get("txns") or {}).get("h24") or {}
            b, s = tx.get("buys") or 0, tx.get("sells") or 0
            pc24 = float((p.get("priceChange") or {}).get("h24") or 0)
            if 2 <= age_d <= 14 and 1e6 <= mc <= 2e7 and liq >= 50_000: tier, hmin = "mature", 3000
            elif 0.25 <= age_d < 2 and 1e5 <= mc <= 2e7 and liq >= 15_000 and -10 <= pc24 <= 300: tier, hmin = "early", 500
            else: continue
            if b < 1.5 * max(s, 1) or (tier == "early" and b < 300): continue
            v = ds.setdefault(tok, {})
            if v.get("t") and now - v["t"] < 3000: continue        # 每币约 1 小时查一次 GoPlus
            g = (http(f"https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses={tok}") or {}).get("result", {}).get(tok, {})
            if not g: continue
            f = lambda k: g.get(k) == "1"
            if g.get("is_open_source") != "1" or f("is_honeypot") or f("cannot_sell_all") or f("is_mintable") or f("hidden_owner") \
               or f("owner_change_balance") or f("transfer_pausable") or f("slippage_modifiable") or f("is_blacklisted"): continue
            if (g.get("owner_address") or "0x0000000000000000000000000000000000000000").lower() not in DEAD: continue
            try:
                if max(float(g.get("buy_tax") or 0), float(g.get("sell_tax") or 0)) > 0.03: continue
            except Exception: continue
            lp = g.get("lp_holders") or []
            if sum(float(x.get("percent") or 0) for x in lp if x.get("is_locked") == 1 or (x.get("address") or "").lower() in DEAD) < 0.9: continue
            hs = [x for x in (g.get("holders") or []) if x.get("is_contract") != 1 and (x.get("address") or "").lower() not in DEAD]
            if max([float(x.get("percent") or 0) for x in hs[:10]] or [1]) > 0.05: continue
            h = int(g.get("holder_count") or 0)
            if h < hmin: continue
            hh = v.setdefault("hh", []); hh.append([now, h]); v["hh"] = hh = hh[-6:]; v["t"] = now
            if v.get("h") is None: v["h"] = h
            need = 2 if tier == "mature" else 4                    # 早期要连续 3 小时持币数都在涨
            if len(hh) < need or any(hh[k + 1][1] <= hh[k][1] for k in range(len(hh) - need, len(hh) - 1)): continue
            prev = hh[-need][1]; v["t0"] = hh[-need][0]
            v["pushed"] = now
            sym = (p.get("baseToken") or {}).get("symbol", "?")
            pc = p.get("priceChange") or {}
            out.append("\n".join([f"🟠 地推盘候选{'（早期，风险更高）' if tier == 'early' else ''}：{sym} · 池龄 {age_d:.1f} 天", f"CA {tok}",
                f"市值 ${mc:,.0f}，池子 ${liq:,.0f}，24h {pc.get('h24','?')}%，24h 买 {b}/卖 {s}",
                f"持币 {prev}→{h}（{(now - v['t0'])/3600:.1f}h 连涨），LP 已锁/销毁，税 {g.get('buy_tax')}/{g.get('sell_tax')}，无 owner",
                p.get("url", f"https://dexscreener.com/bsc/{tok}"), "机器人只管筛，进不进你拍板。"]))
            st.setdefault("signals", []).append({"tok": tok, "sym": sym, "src": "ditui", "tier": tier, "t": now, "chain": "bsc"})
    for tok in list(ds):
        if now - ds[tok].get("t", ds[tok].get("pushed", now)) > 15 * 86400: del ds[tok]
    return out


# ---------- 扣字眼（2026-11-02 峰哥：扣何一 / CZ 字眼的币，例如「我靠」）----------
KZ_HANDLES = ["cz_binance", "heyibinance"]
KZ_SKIP = {"bnb", "binance", "币安", "cz", "heyi", "一姐", "the", "and", "for", "you", "this", "that", "with", "btc", "eth",
           "usdt", "usdc", "sol", "meme", "coin", "token", "crypto", "web3", "build", "ai", "bsc", "new", "big", "good", "yes", "lol"}
_kz_out = []
def kz_feed(st, now):
    """每轮拉 CZ / 何一 最近推文（只读）。"""
    kt = st.setdefault("kz_tw", [])
    have = {x[3] for x in kt}
    for h in KZ_HANDLES:
        d = http(f"https://api.fxtwitter.com/2/profile/{h}/statuses?count=15") or {}
        for t in d.get("results") or []:
            u = t.get("url") or ""
            ts = int(t.get("created_timestamp") or 0)
            if u in have or now - ts > 86400: continue
            txt = t.get("text") or ""
            q = t.get("quote") or {}
            if q.get("text"): txt += " " + q["text"]
            kt.append([ts, h, txt[:600], u]); have.add(u)
        time.sleep(1)
    st["kz_tw"] = [x for x in kt if now - x[0] < 86400][-100:]
def _kz_hit(name, txt):
    n = (name or "").strip().lower().lstrip("$")
    if len(n) < 2 or n in KZ_SKIP: return False
    if re.fullmatch(r"[a-z0-9 ]+", n):
        return len(n) >= 3 and re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", txt.lower()) is not None
    return n in txt.lower()
def kz_check(st, now, tok, plat, p, qb, age_h):
    ks = st.setdefault("kz", {})
    if tok in ks: return
    bt = p.get("baseToken") or {}
    name, sym = bt.get("name") or "", bt.get("symbol") or ""
    for ts, h, txt, url in st.get("kz_tw", []):
        if not (_kz_hit(name, txt) or _kz_hit(sym, txt)): continue
        word = name if _kz_hit(name, txt) else sym
        same = sum(1 for v in ks.values() if v.get("w") == word.lower())
        ks[tok] = {"t": now, "w": word.lower()}
        if same >= 3: return  # 同一字眼已推 3 个，后面的仿盘不推
        g = ((http(f"https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses={tok}") or {}).get("result") or {}).get(tok, {})
        bad = [n for k, n in [("is_honeypot", "貔貅"), ("cannot_sell_all", "不能全卖"), ("is_mintable", "可增发"), ("hidden_owner", "隐藏 owner"), ("owner_change_balance", "owner 可改余额")] if g.get(k) == "1"]
        mc = float(p.get("marketCap") or p.get("fdv") or 0)
        tx = (p.get("txns") or {}).get("h1") or {}
        snip = txt.replace("\n", " ")
        i = snip.lower().find(word.lower()); snip = snip[max(0, i - 40): i + 60]
        _kz_out.append("\n".join([f"🔵 扣字眼：{name}（{sym}）· {plat} · 上线 {age_h*60:.0f} 分钟" + (f" · 同字眼第 {same+1} 个" if same else ""),
            f"CA {tok}", f"@{h} {time.strftime('%H:%M', time.gmtime(ts + 8*3600))}：…{snip}…", url,
            f"池内约 {qb:.1f} BNB，市值 ${mc:,.0f}，1h 买 {tx.get('buys',0)}/卖 {tx.get('sells',0)}",
            "GoPlus：" + ("⚠️" + "、".join(bad) if bad else (f"未见貔貅，税 {g.get('buy_tax','?')}/{g.get('sell_tax','?')}" if g else "暂无数据")),
            p.get("url", ""), "只是字眼匹配，没过五条，进不进你拍板。"]))
        return
def kouzi(st, now):
    for tok in list(st.get("kz", {})):
        if now - st["kz"][tok]["t"] > 2 * 86400: del st["kz"][tok]
    out = _kz_out[:5]; _kz_out.clear()
    return out

# ---------- 观察名单（峰哥说「观察」的币，条件触发各推一次）----------
WATCH = [{"tok": "0x6511c233790ec10f7d673c64dc82c3f941d57828", "chain": "robinhood", "sym": "OAK", "x": "OakAgentKit", "since": "2026-11-02"}]
def watch(st, now):
    ws = st.setdefault("watch", {})
    out = []
    for w in WATCH:
        v = ws.setdefault(w["tok"], {"hit": []})
        d = http(f"https://api.dexscreener.com/latest/dex/tokens/{w['tok']}") or {}
        ps = [p for p in d.get("pairs") or [] if p.get("chainId") == w["chain"]]
        if not ps: continue
        p = max(ps, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
        mc = float(p.get("marketCap") or p.get("fdv") or 0); liq = (p.get("liquidity") or {}).get("usd") or 0
        v["low"] = min(v.get("low", mc), mc)
        fol = None
        if w.get("x") and time.gmtime(now).tm_min < 10:
            fol = ((http(f"https://api.fxtwitter.com/{w['x']}") or {}).get("user") or {}).get("followers")
        conds = [("mc150", mc >= 150_000, f"市值站上 $150K（${mc:,.0f}）"),
                 ("hold100", v["low"] < 80_000 and mc >= 100_000, f"回调到 ${v['low']:,.0f} 后重回 $100K 以上（${mc:,.0f}）"),
                 ("liq50", liq >= 50_000, f"池子涨到 ${liq:,.0f}"),
                 ("x1000", (fol or 0) >= 1000, f"X 粉丝到 {fol}"),
                 ("dump", mc <= 40_000, f"跌破 $40K（${mc:,.0f}），观察结束建议放弃")]
        for k, ok, txt in conds:
            if ok and k not in v["hit"]:
                v["hit"].append(k)
                out.append("\n".join([f"👀 观察币 {w['sym']}（{w['chain']}）：{txt}", f"CA {w['tok']}",
                    f"市值 ${mc:,.0f}，池子 ${liq:,.0f}，1h {(p.get('priceChange') or {}).get('h1','?')}%", p.get("url", ""),
                    "只是提醒，进不进你拍板，上车前发 Hark 复核。"]))
        time.sleep(1)
    return out
