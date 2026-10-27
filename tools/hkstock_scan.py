#!/usr/bin/env python3
"""港股高股息白马筛选 — 东方财富接口

两段式：
  1) clist 拉全市场主板行情+估值，按市值/PE/PB 粗筛
  2) 对幸存者拉 F10 公司资料(ISIN/注册地) + 派息记录，自算 TTM 港元股息率

税制分类依据 ISIN 前缀（对应 IBKR 等跨境券商口径）：
  CN* -> H股，股息预提 10%
  其余(HK/KYG/BMG/VGG...) -> 红筹/港本地/境外注册，预提 0%
"""
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
REFERER = "https://emweb.securities.eastmoney.com/"


def curl(url, referer=False):
    cmd = ["/usr/bin/curl", "-s", "--noproxy", "*", "--max-time", "25", "-H", f"User-Agent: {UA}"]
    if referer:
        cmd += ["-H", f"Referer: {REFERER}"]
    cmd.append(url)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
        return json.loads(out) if out.strip().startswith("{") else None
    except Exception:
        return None


def fetch_universe():
    """全部港股主板行情。f20市值 f23PB f37ROE f115PE(TTM) f2价格 f3涨跌幅"""
    rows, pn = [], 1
    while True:
        url = (
            "https://push2delay.eastmoney.com/api/qt/clist/get?"
            f"pn={pn}&pz=200&po=1&np=1&fltt=2&invt=2&fid=f20&fs=m:128+t:3"
            "&fields=f2,f3,f12,f14,f20,f21,f23,f37,f115"
        )
        d = curl(url)
        if not d or not d.get("data") or not d["data"].get("diff"):
            break
        rows += d["data"]["diff"]
        if len(rows) >= d["data"]["total"]:
            break
        pn += 1
    return rows


def num(v):
    return v if isinstance(v, (int, float)) else None


HKD_PATTERNS = [
    re.compile(r"港币\s*([\d.]+)\s*元"),
    re.compile(r"([\d.]+)\s*港元"),
    re.compile(r"港元\s*([\d.]+)"),
    re.compile(r"HKD\s*([\d.]+)", re.I),
]


def parse_hkd(plan):
    """从派息说明里抽港元每股金额。优先'相当于港币X元'的换算值。"""
    if not plan:
        return None
    for pat in HKD_PATTERNS:
        m = pat.findall(plan)
        if m:
            try:
                # 取最后一个：'每股派人民币0.98元(相当于港币1.13元)' 的港币值在后
                return float(m[-1])
            except ValueError:
                continue
    return None


def fetch_profile(code):
    url = (
        "https://datacenter.eastmoney.com/securities/api/data/v1/get?"
        "reportName=RPT_HKF10_INFO_ORGPROFILE&columns=ALL"
        f"&filter=(SECUCODE%3D%22{code}.HK%22)&pageNumber=1&pageSize=1"
    )
    d = curl(url, referer=True)
    try:
        return d["result"]["data"][0]
    except Exception:
        return None


def fetch_dividends(code, size=40):
    url = (
        "https://datacenter.eastmoney.com/securities/api/data/v1/get?"
        "reportName=RPT_HKF10_INFO_DIVIDEND&columns=ALL"
        f"&filter=(SECUCODE%3D%22{code}.HK%22)&pageNumber=1&pageSize={size}"
        "&sortColumns=EX_DIVIDEND_DATE&sortTypes=-1"
    )
    d = curl(url, referer=True)
    try:
        return d["result"]["data"] or []
    except Exception:
        return []


def analyze_dividends(recs, today):
    """返回 (TTM每股港元, 近5年有派息的年份数, 最近一次除净日, 明细)"""
    ttm, detail, years = 0.0, [], set()
    cutoff = today - timedelta(days=366)
    y5 = today.year - 5
    last_ex = None
    for r in recs:
        if r.get("IS_DIVIDEND") != "1":
            continue
        exd = r.get("EX_DIVIDEND_DATE")
        if not exd:
            continue
        try:
            dt = datetime.strptime(exd[:10], "%Y-%m-%d")
        except ValueError:
            continue
        amt = parse_hkd(r.get("PLAN_EXPLAIN"))
        if amt is None:
            continue
        if dt.year > y5:
            years.add(dt.year)
        if last_ex is None or dt > last_ex:
            last_ex = dt
        # 已除净、且在最近12个月内的计入 TTM
        if cutoff <= dt <= today:
            ttm += amt
            detail.append((dt.strftime("%Y-%m-%d"), amt, r.get("ASSIGN_PERIOD")))
    return ttm, len(years), last_ex, detail


def tax_class(isin, reg_place):
    if isin and isin.upper().startswith("CN"):
        return "H股", 0.10
    if isin and isin.upper().startswith("HK"):
        return "港本地", 0.0
    if reg_place and "中国" in reg_place and "香港" not in reg_place:
        return "H股", 0.10
    return "红筹/境外", 0.0


def main():
    min_cap = float(sys.argv[1]) if len(sys.argv) > 1 else 200e8  # 港元
    max_pe = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0

    print(f"[1/3] 拉取港股主板全市场行情 ...", file=sys.stderr)
    uni = fetch_universe()
    print(f"      共 {len(uni)} 只", file=sys.stderr)

    cand = []
    for r in uni:
        cap, pe, pb = num(r.get("f20")), num(r.get("f115")), num(r.get("f23"))
        if cap is None or cap < min_cap:
            continue
        if pe is None or pe <= 0 or pe > max_pe:
            continue
        cand.append(
            dict(
                code=r["f12"],
                name=r["f14"],
                price=num(r.get("f2")),
                chg=num(r.get("f3")),
                cap=cap,
                pe=pe,
                pb=pb,
                roe=num(r.get("f37")),
            )
        )
    print(f"[2/3] 市值>={min_cap/1e8:.0f}亿 且 0<PE<={max_pe} 的候选：{len(cand)} 只", file=sys.stderr)

    today = datetime.now()

    def enrich(c):
        prof = fetch_profile(c["code"])
        divs = fetch_dividends(c["code"])
        if prof:
            c["isin"] = prof.get("ISIN_CODE")
            c["reg"] = prof.get("REG_PLACE")
            c["ind"] = prof.get("BELONG_INDUSTRY")
            c["listing"] = (prof.get("LISTING_DATE") or "")[:10]
        ttm, yrs, last_ex, detail = analyze_dividends(divs, today)
        c["dps"] = ttm
        c["div_years5"] = yrs
        c["last_ex"] = last_ex.strftime("%Y-%m-%d") if last_ex else None
        c["div_detail"] = detail
        c["cls"], c["tax"] = tax_class(c.get("isin"), c.get("reg"))
        c["yield"] = (ttm / c["price"] * 100) if (c["price"] and ttm) else 0.0
        c["yield_net"] = c["yield"] * (1 - c["tax"])
        return c

    print(f"[3/3] 拉取 F10 资料与派息记录 ...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=6) as ex:
        cand = list(ex.map(enrich, cand))

    cand.sort(key=lambda x: -x["yield_net"])
    print(json.dumps(cand, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
