#!/usr/bin/env python3
"""峰哥打新铸造雷达（云端版，GitHub Actions 定时跑，不耗 Hark 额度）。
只读：只查链上和公开 API，不签名、不交易、不连钱包。命中才发 Telegram。
需要三个 GitHub Secrets：ANKR_KEY、TG_TOKEN、TG_CHAT_ID。
纪律（2026-11-01 峰哥定）：
- 真钱门槛：30 分钟合约 BNB 流入 >=3 BNB，或池内 BNB >=10 / 30 分钟净流入 >=3 BNB
- 矩阵农场（同一批钱包铸 >=3 个合约）不推；同一份字节码 24h 部署 >=3 次不推；DEV 黑名单永久不推
- 免费 NFT：进度 >=70%、>=150 个钱包、必须有每钱包上限、图片能打开且不重复，才推
- 推送带建议：付费 <=10U/笔、每日 <=30U，NFT <=10U/项目；2 倍回本、5/10 倍分批、回撤 30% 走
"""
import json, os, time, hashlib, urllib.request
import scan_core as sc

STATE = "state.json"
BLACKLIST = "blacklist.json"   # 手动维护：{"deployers": [...], "contracts": [...]}
WINDOW = int(os.environ.get("WINDOW_MIN", "15"))
now = int(time.time())

def load(p, d):
    try: return json.load(open(p))
    except Exception: return d

st = load(STATE, {"seen": {}, "code_hashes": {}, "pushed": {}, "img_hashes": {}})
bl = load(BLACKLIST, {"deployers": [], "contracts": []})
blk = set(x.lower() for x in bl.get("contracts", []) + bl.get("deployers", []))

def http(url, timeout=15, raw=False):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": "Mozilla/5.0"}), timeout=timeout)
        b = r.read(3_000_000)
        return (r.status, r.headers.get("content-type", ""), b) if raw else json.loads(b)
    except Exception:
        return None

def call_uint(a, sel):
    r = sc.rpc("eth_call", [{"to": a, "data": sel}, "latest"]) or "0x"
    try: return int(r[:66], 16) if len(r) >= 66 else None
    except Exception: return None

def balance_bnb(a):
    r = sc.rpc("eth_getBalance", [a, "latest"])
    return int(r, 16) / 1e18 if r else 0.0

def pool_bnb(a):
    d = http(f"https://api.dexscreener.com/latest/dex/tokens/{a}") or {}
    best = None
    for p in d.get("pairs") or []:
        if p.get("chainId") != "bsc": continue
        q = (p.get("quoteToken") or {}).get("symbol", "")
        if q in ("WBNB", "BNB"):
            v = (p.get("liquidity") or {}).get("quote") or 0
            if best is None or v > best[0]:
                best = (v, p.get("url"), (p.get("info") or {}).get("websites") or [])
    return best

def is_nft(a):
    r = sc.rpc("eth_call", [{"to": a, "data": "0x01ffc9a780ac58cd" + "0" * 56}, "latest"]) or "0x"
    try: return int(r[:66], 16) == 1
    except Exception: return False

def nft_checks(a, minters):
    out = {"ok": False, "why": []}
    total = call_uint(a, "0x18160ddd")
    cap = call_uint(a, "0xd5abeb01") or call_uint(a, "0x32cb6b0c")
    prog = (total / cap) if total and cap else None
    out["progress"] = prog
    per = None
    for sel in ["0x453c2310", "0x0f2cdd6c", "0xb228d925", "0x639814e0", "0x3c8463a1", "0xe0f9b479", "0xf516a2e6"]:
        v = call_uint(a, sel)
        if v: per = v; break
    out["per_wallet"] = per
    if prog is None or prog < 0.70: out["why"].append("进度<70%或读不到")
    if minters < 150: out["why"].append("钱包<150")
    if not per: out["why"].append("无每钱包上限")
    # 图片：tokenURI(1) -> json -> image
    img_ok, img_hash = False, None
    r = sc.rpc("eth_call", [{"to": a, "data": "0xc87b56dd" + "1".rjust(64, "0")}, "latest"]) or "0x"
    try:
        b = bytes.fromhex(r[2:]); n = int.from_bytes(b[32:64], "big"); uri = b[64:64 + n].decode()
        uri = uri.replace("ipfs://", "https://ipfs.io/ipfs/")
        meta = json.loads(uri.split(",", 1)[1]) if uri.startswith("data:application/json") and not "base64" in uri[:40] else http(uri)
        img = (meta or {}).get("image", "").replace("ipfs://", "https://ipfs.io/ipfs/")
        if img.startswith("http"):
            g = http(img, raw=True)
            if g and g[0] == 200 and len(g[2]) > 200:
                img_ok, img_hash = True, hashlib.sha256(g[2]).hexdigest()
        elif img.startswith("data:image"):
            img_ok, img_hash = True, hashlib.sha256(img.encode()).hexdigest()
    except Exception:
        pass
    if not img_ok: out["why"].append("图片打不开")
    elif img_hash in st["img_hashes"] and st["img_hashes"][img_hash] != a: out["why"].append("同图出现在别的合约")
    elif img_hash: st["img_hashes"][img_hash] = a
    out["ok"] = not out["why"]
    return out

def tg(text):
    tok, chat = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not tok or not chat:
        print("[no TG]\n" + text); return
    data = json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data,
                               headers={"content-type": "application/json"}), timeout=20)
    except Exception as e:
        print("TG fail", e)

res = sc.chain_scan(WINDOW)
msgs = []
STOP = time.time() + 150  # 单轮检查上限，防止超时
for c in res["agent_id_candidates"]:
    if time.time() > STOP: break
    a = c["contract"]
    if a in blk: continue
    # 批量发盘：同一份字节码 24h 内出现 >=3 个合约
    ch = st["code_hashes"].setdefault(c["code_hash"], {})
    ch[a] = ch.get(a, now)
    if sum(1 for t in ch.values() if now - t < 86400) >= 3: continue
    if c["overlap_cluster_size"] >= 3: continue  # 矩阵农场
    w = c["distinct_minters_window"]
    if not (c["peak_3min_distinct"] >= 12 or w >= 25): continue
    # 真钱
    bal = balance_bnb(a)
    hist = st["seen"].setdefault(a, [])
    hist.append([now, round(bal, 4)])
    hist[:] = [h for h in hist if now - h[0] < 7200]
    old = [h for h in hist if now - h[0] >= 1500]
    inflow = bal - old[0][1] if old else None
    pool = pool_bnb(a)
    pbnb = pool[0] if pool else 0
    real = (inflow is not None and inflow >= 3 and w >= 30) or pbnb >= 10
    kind, extra = "代币", ""
    if is_nft(a):
        kind = "NFT"
        if not real:
            n = nft_checks(a, w)
            if not n["ok"]: continue
            extra = f"进度 {n['progress']:.0%}，每钱包上限 {n['per_wallet']}，图片可打开且不重复"
    elif not real:
        continue
    level = "pool10" if pbnb >= 10 else "inflow"
    key = f"{a}:{level}"
    if key in st["pushed"]: continue
    st["pushed"][key] = now
    site = (pool[2][0].get("url") if pool and pool[2] else "") or ""
    lines = [f"🟢 {c['name'] or '?'} ({c['symbol'] or '?'}) · {kind} · Agent ID 专属",
             f"CA {a}",
             f"{WINDOW} 分钟 {w} 个钱包在铸，3 分钟峰值 {c['peak_3min_distinct']}，开铸约 {c['first_mint_min_ago']} 分钟前",
             f"合约 BNB {bal:.2f}" + (f"，30 分钟流入 {inflow:+.2f}" if inflow is not None else "") + (f"，池内 BNB {pbnb:.1f}" if pool else "，未开池")]
    if extra: lines.append(extra)
    if site: lines.append(f"官网 {site}")
    lines.append(f"建议：{'NFT ≤10U/项目' if kind == 'NFT' else '付费 ≤10U/笔，每日 ≤30U'}；2 倍回本，5/10 倍分批，回撤 30% 走。退款函数/DEV 历史未自动核实，上车前发给 Hark 复核。")
    msgs.append("\n".join(lines))

# 附加：meme 新池 / 整点 X / PTAH（各自独立，出错不影响主扫描）
import extras
for name, fn in [("meme", lambda: extras.meme(st, now, blk)),
                 ("x", lambda: extras.xscan(st, now) if time.gmtime(now).tm_min < 10 else []),
                 ("ptah", lambda: extras.ptah(st, now))]:
    try: msgs += fn()
    except Exception as e: print(name, "fail", e)

# 清理旧状态
for k in list(st["seen"]):
    if not st["seen"][k]: del st["seen"][k]
for h in list(st["code_hashes"]):
    st["code_hashes"][h] = {a: t for a, t in st["code_hashes"][h].items() if now - t < 86400}
    if not st["code_hashes"][h]: del st["code_hashes"][h]
st["pushed"] = {k: t for k, t in st["pushed"].items() if now - t < 3 * 86400}
json.dump(st, open(STATE, "w"))

if msgs:
    tg("\n\n".join(msgs))
print(f"candidates={len(res['agent_id_candidates'])} pushed={len(msgs)} logs_complete={res['logs_complete']}")
