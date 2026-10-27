#!/usr/bin/env python3
"""港股「非周期 + 股东回报大方」扫描 — 东财数据

在 hkstock_scan.py 的股票池基础上，补三类信息：
  1) F10 行业 / ISIN（税制）
  2) 派息历史（经常性口径 dps + 5年连续性 + 派息率）
  3) 股本变动史（回购导致的股本收缩）

用法: python3 hk_defensive_scan.py [min_cap亿] [out.json]
"""
import json
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from hkstock_scan import fetch_universe, fetch_profile, fetch_dividends, num, tax_class
from hk_yield import recurring_dps

NON_CYCLIC = {
    "食物饮品", "消费者主要零售商", "药品及生物科技", "电讯", "公用事业",
    "保险", "银行", "软件服务", "专业零售", "家庭电器及用品", "综合企业",
    "资讯科技器材", "半导体", "媒体及娱乐", "纺织及服饰", "汽车",
}
EXCLUDE_NAME = ("-R", "-S", "-W")


def fetch_equity(code, size=200):
    url = ("https://datacenter.eastmoney.com/securities/api/data/v1/get?"
           "reportName=RPT_HKF10_INFO_EQUITY&columns=SECUCODE,CHANGE_DATE,TOTAL_SHARES,CHANGE_REASON"
           f"&filter={urllib.parse.quote(f'(SECUCODE="{code}.HK")')}"
           f"&pageNumber=1&pageSize={size}")
    from hkstock_scan import curl
    d = curl(url, referer=True)
    try:
        return d["result"]["data"] or []
    except Exception:
        return []


def buyback_stats(recs):
    """从股本变动史推回购：累计净变动 + 是否有回购/注销记录"""
    rows = []
    for r in recs:
        ts, cd = r.get("TOTAL_SHARES"), (r.get("CHANGE_DATE") or "")[:10]
        if not ts or not cd:
            continue
        rows.append((cd, ts, r.get("CHANGE_REASON") or ""))
    rows.sort(key=lambda x: x[0])
    if len(rows) < 2:
        return None
    cur = rows[-1][1]
    # 最早可比窗口：优先取 5 年前，否则取首条
    target = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    base = next((r for r in rows if r[0] >= target), rows[0])[1]
    if base <= 0:
        return None
    cancel = sum(1 for _, _, rs in rows if "注销" in rs or "回购" in rs)
    return dict(now=cur, base5y=base, delta_pct=(cur / base - 1) * 100, events=len(rows), bb_events=cancel)


def main():
    min_cap = float(sys.argv[1]) * 1e8 if len(sys.argv) > 1 else 200e8
    out_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/hk_defensive.json"
    uni = fetch_universe()
    today = datetime.now()

    cand = []
    for r in uni:
        name = r["f14"]
        cap, pe, pb = num(r.get("f20")), num(r.get("f115")), num(r.get("f23"))
        if cap is None or cap < min_cap or pe is None or pe <= 0 or pe > 40:
            continue
        if any(x in name for x in EXCLUDE_NAME):
            continue
        cand.append(dict(code=r["f12"], name=name, price=num(r.get("f2")),
                         cap=cap, pe=pe, pb=pb))
    print(f"[1] 市值>={min_cap/1e8:.0f}亿 & 0<PE<=40: {len(cand)}", file=sys.stderr)

    def enrich(c):
        p = fetch_profile(c["code"]) or {}
        c["ind"] = p.get("BELONG_INDUSTRY")
        c["isin"] = p.get("ISIN_CODE")
        c["reg"] = p.get("REG_PLACE")
        c["cls"], c["tax"] = tax_class(c.get("isin"), c.get("reg"))
        divs = fetch_dividends(c["code"])
        dps, basis, special, yoy = recurring_dps(divs, today)
        c.update(dps_reg=dps, basis=basis, special=special, mid_yoy=yoy)
        c["y_reg"] = dps / c["price"] * 100 if c["price"] else 0.0
        c["y_net"] = c["y_reg"] * (1 - c["tax"])
        c["payout"] = c["y_reg"] * c["pe"] / 100
        c["bb"] = buyback_stats(fetch_equity(c["code"]))
        return c

    with ThreadPoolExecutor(max_workers=8) as ex:
        cand = list(ex.map(enrich, cand))
    print(f"[2] enriched {len(cand)}", file=sys.stderr)
    json.dump(cand, open(out_path, "w"), ensure_ascii=False)
    print(out_path, file=sys.stderr)


if __name__ == "__main__":
    main()
