"""模拟盘（2026-11-02 峰哥同意先练两周）：雷达每条「值得参与」信号虚拟买 10U，按纪律虚拟卖出。
只记账，不交易，不碰任何钱包。
规则：每笔 10U，每日最多 3 笔（30U）；买卖各扣 3%（手续费+滑点）。
卖出：2 倍卖一半回本；5 倍再卖剩余一半；10 倍清仓；从最高点回撤 30% 清仓（含买入后直接跌 30%）；池内 <1 BNB 视为归零。
铸造信号没开池的，等开池后第一笔读价入场；24 小时不开池作废。
每天北京时间 22 点后第一轮推一次日报。"""
import json, time, urllib.request

COST = 0.03

def pair(tok):
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"https://api.dexscreener.com/latest/dex/tokens/{tok}", headers={"user-agent": "Mozilla/5.0"}), timeout=15).read())
    except Exception:
        return None
    best = None
    for p in d.get("pairs") or []:
        if p.get("chainId") not in ("bsc", "robinhood") or not p.get("priceUsd"): continue
        liq = (p.get("liquidity") or {}).get("usd") or 0
        if best is None or liq > best[1]: best = (float(p["priceUsd"]), liq)
    return best  # (price, liquidity_usd)

def run(st, now):
    pp = st.setdefault("paper", {"open": {}, "closed": [], "pending": {}, "day": {}, "last_report": ""})
    out = []
    day = time.strftime("%Y-%m-%d", time.gmtime(now + 8 * 3600))
    for s in st.pop("signals", []):
        if s["tok"] in pp["open"] or s["tok"] in pp["pending"]: continue
        pp["pending"][s["tok"]] = s
    # 入场
    for tok, s in list(pp["pending"].items()):
        if now - s["t"] > 86400: del pp["pending"][tok]; continue
        if pp["day"].get(day, 0) >= 3: break
        q = pair(tok)
        if not q: continue
        price, liq = q
        if liq < 700: continue
        pp["open"][tok] = {"sym": s["sym"], "src": s["src"], "t": now, "entry": price, "peak": price,
                           "qty": 10 * (1 - COST) / price, "cash": 0.0, "steps": []}
        pp["day"][day] = pp["day"].get(day, 0) + 1
        del pp["pending"][tok]
    # 持仓管理
    for tok, o in list(pp["open"].items()):
        q = pair(tok)
        if not q: continue
        price, liq = q
        o["peak"] = max(o["peak"], price)
        m = price / o["entry"]
        def sell(frac, why):
            n = o["qty"] * frac
            o["qty"] -= n
            o["cash"] += n * price * (1 - COST)
            o["steps"].append(f"{why}@{m:.2f}x")
        if liq < 700:
            o["steps"].append("池子归零"); o["qty"] = 0
        else:
            if m >= 2 and "2x" not in str(o["steps"]): sell(0.5, "2x")
            if m >= 5 and "5x" not in str(o["steps"]): sell(0.5, "5x")
            if m >= 10: sell(1, "10x")
            elif price <= o["peak"] * 0.7: sell(1, "回撤30%")
        if o["qty"] * price < 0.05 or now - o["t"] > 14 * 86400:
            if o["qty"] > 0: sell(1, "到期")
            pnl = o["cash"] - 10
            pp["closed"].append({"sym": o["sym"], "src": o["src"], "pnl": round(pnl, 2), "steps": o["steps"], "t": now})
            out.append(f"📒模拟盘平仓 {o['sym']}：{pnl:+.2f}U（{' → '.join(o['steps'])}）")
            del pp["open"][tok]
        else:
            o["last"] = price
    # 日报
    if time.gmtime(now).tm_hour >= 14 and pp["last_report"] != day:
        pp["last_report"] = day
        c = pp["closed"]
        win = sum(1 for x in c if x["pnl"] > 0)
        tot = sum(x["pnl"] for x in c)
        flo = sum(o["cash"] + o["qty"] * o.get("last", o["entry"]) - 10 for o in pp["open"].values())
        out.append(f"📒模拟盘日报 {day}：已平 {len(c)} 笔，胜 {win}，累计 {tot:+.2f}U；持仓 {len(pp['open'])} 笔，浮动 {flo:+.2f}U；今日入场 {pp['day'].get(day,0)}/3。")
    pp["day"] = {k: v for k, v in pp["day"].items() if k >= time.strftime("%Y-%m-%d", time.gmtime(now - 3 * 86400))}
    return out
