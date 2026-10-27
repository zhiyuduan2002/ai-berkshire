#!/usr/bin/env python3
"""港股股息率重算 — 按"完整年度周期"口径，修正 TTM 滚动窗口的重复计息

问题：以除净日滚动12个月求和，会在中报除净日前后把两个"中期"派息同时纳入
（例：申洲 2025中期1.38 + 2025末期1.20 + 2026中期0.88 = 3.46，虚高34%）。

口径：
  - 季度派息公司 -> 最近4个不同季度
  - 半年派息公司 -> 最近1个"中期" + 最近1个"末期"
  - 年度派息公司 -> 最近1个"末期"
  - "特别/特别分配"单列，不计入经常性股息
并额外给出中期派息同比，用于判断分红是在增还是在减。

用法: python3 hk_yield.py < codes.json   (读 hkstock_scan.py 的输出)
"""
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

WINDOW_DAYS = 400

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
REFERER = "https://emweb.securities.eastmoney.com/"
HKD = [re.compile(r"港币\s*([\d.]+)\s*元"), re.compile(r"([\d.]+)\s*港元"),
       re.compile(r"港元\s*([\d.]+)")]


def parse_hkd(plan):
    for pat in HKD:
        m = pat.findall(plan or "")
        if m:
            try:
                return float(m[-1])
            except ValueError:
                pass
    return None


def fetch_div(code):
    url = ("https://datacenter.eastmoney.com/securities/api/data/v1/get?"
           "reportName=RPT_HKF10_INFO_DIVIDEND&columns=ALL"
           f"&filter=(SECUCODE%3D%22{code}.HK%22)&pageNumber=1&pageSize=40"
           "&sortColumns=EX_DIVIDEND_DATE&sortTypes=-1")
    out = subprocess.run(
        ["/usr/bin/curl", "-s", "--noproxy", "*", "--max-time", "25",
         "-H", f"User-Agent: {UA}", "-H", f"Referer: {REFERER}", url],
        capture_output=True, text=True).stdout
    try:
        return json.loads(out)["result"]["data"] or []
    except Exception:
        return []


PERIOD = re.compile(r"(\d{4})\s*(中期|末期|一季|二季|三季|四季|年度)")


def recurring_dps(recs, today):
    """返回 (经常性年度每股港元, 口径, 特别派息, 中期同比%)

    先按除净日截取最近 WINDOW_DAYS，再按期间类型去重取最新一笔。
    时效约束不可省：建发国际 2022 年起停发中期息，若不加窗口会把 2021 中期息
    与 2025 末期息相加，股息率虚报一倍以上。
    """
    cutoff = (today - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    rows = []
    for r in recs:
        if r.get("IS_DIVIDEND") != "1":
            continue
        amt = parse_hkd(r.get("PLAN_EXPLAIN"))
        if amt is None or not r.get("EX_DIVIDEND_DATE"):
            continue
        p = (r.get("ASSIGN_PERIOD") or "").strip()
        ex = r["EX_DIVIDEND_DATE"][:10]
        m = PERIOD.search(p)
        if m:
            rows.append(dict(year=int(m.group(1)), kind=m.group(2), amt=amt, ex=ex))
        elif "特别" in p:
            rows.append(dict(year=None, kind="特别", amt=amt, ex=ex))
    rows.sort(key=lambda x: x["ex"], reverse=True)
    recent = [r for r in rows if r["ex"] >= cutoff]

    special = sum(r["amt"] for r in recent if r["kind"] == "特别")
    reg = [r for r in recent if r["kind"] != "特别"]
    quarters = [r for r in reg if r["kind"].endswith("季")]

    if len(quarters) >= 4:
        seen, tot = set(), 0.0
        for r in quarters:
            key = (r["year"], r["kind"])
            if key in seen:
                continue
            seen.add(key)
            tot += r["amt"]
            if len(seen) == 4:
                break
        dps, basis = tot, "季×4"
    else:
        mid = next((r for r in reg if r["kind"] == "中期"), None)
        fin = next((r for r in reg if r["kind"] in ("末期", "年度")), None)
        dps = (mid["amt"] if mid else 0) + (fin["amt"] if fin else 0)
        basis = "中期+末期" if mid and fin else ("仅末期" if fin else ("仅中期" if mid else "无"))

    # 中期同比用全历史，不受窗口限制
    mids = [r for r in rows if r["kind"] == "中期"]
    yoy = None
    if len(mids) >= 2 and mids[1]["amt"]:
        yoy = (mids[0]["amt"] / mids[1]["amt"] - 1) * 100
    return dps, basis, special, yoy


def main():
    data = json.load(sys.stdin)

    today = datetime.now()

    def work(c):
        dps, basis, sp, yoy = recurring_dps(fetch_div(c["code"]), today)
        c["dps_reg"] = dps
        c["basis"] = basis
        c["special"] = sp
        c["mid_yoy"] = yoy
        c["y_reg"] = dps / c["price"] * 100 if c["price"] else 0
        c["y_reg_net"] = c["y_reg"] * (1 - c["tax"])
        c["payout_reg"] = c["y_reg"] * c["pe"] / 100
        return c

    with ThreadPoolExecutor(max_workers=6) as ex:
        out = list(ex.map(work, data))
    json.dump(out, sys.stdout, ensure_ascii=False, default=str)


if __name__ == "__main__":
    main()
