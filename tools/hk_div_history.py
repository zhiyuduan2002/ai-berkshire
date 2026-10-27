#!/usr/bin/env python3
"""港股派息历史 —— 逐年经常性 DPS（港元），用于判断分红是否稳定/增长。

按除净日归年到「财政期间年」，中期+末期（+季度）合计，特别息单列。
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from hkstock_scan import fetch_dividends
from hk_yield import parse_hkd, PERIOD


def by_year(code, years=9):
    recs = fetch_dividends(code, size=80)
    agg = {}
    for r in recs:
        if r.get("IS_DIVIDEND") != "1":
            continue
        amt = parse_hkd(r.get("PLAN_EXPLAIN"))
        p = (r.get("ASSIGN_PERIOD") or "").strip()
        if amt is None:
            continue
        m = PERIOD.search(p)
        if m:
            y, kind = int(m.group(1)), m.group(2)
        elif "特别" in p:
            y, kind = (r.get("EX_DIVIDEND_DATE") or "")[:4], "特别"
            y = int(y) if y.isdigit() else None
        else:
            continue
        if y is None:
            continue
        b = agg.setdefault(y, dict(reg=0.0, special=0.0, kinds=set()))
        if kind == "特别":
            b["special"] += amt
        else:
            if kind in b["kinds"]:
                continue
            b["kinds"].add(kind)
            b["reg"] += amt
    out = {y: dict(reg=round(v["reg"], 4), special=round(v["special"], 4), kinds=sorted(v["kinds"]))
           for y, v in agg.items()}
    return out


def main():
    codes = json.load(open(sys.argv[1]))
    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for c, v in zip(codes, ex.map(by_year, codes)):
            out[c] = v
    json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False)
    print("saved", sys.argv[2], file=sys.stderr)


if __name__ == "__main__":
    main()
