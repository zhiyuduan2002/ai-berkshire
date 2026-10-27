#!/usr/bin/env python3
"""按财政年度归集的经常性每股股息（港元）—— 中期息与末期息归入同一财政年。

用途：判断分红是否持续、是否增长，避免 hk_yield 的 TTM 滚动口径
在除净日附近重复计入两个"中期"。

- 末期息（ASSIGN_PERIOD = "YYYY末期"）-> 归入 YYYY 财年
- 中期息（"YYYY中期"）-> 归入 YYYY 财年
- 特别息 -> 单列 TOTAL_SPECIAL
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from hkstock_scan import fetch_dividends
from hk_yield import parse_hkd, PERIOD


def fy_dps(code):
    agg = {}
    for r in fetch_dividends(code, size=80):
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
        b = agg.setdefault(y, dict(reg={}, sp=0.0))
        if kind == "特别":
            b["sp"] += amt
        else:
            b["reg"][kind] = b["reg"].get(kind, 0) + amt   # 同期同类型只取一次
    out = {}
    for y, v in agg.items():
        reg = sum(v["reg"].values())
        out[str(y)] = dict(reg=round(reg, 4), special=round(v["sp"], 4),
                           kinds={k: round(a, 4) for k, a in v["reg"].items()})
    return out


def main():
    codes = json.load(open(sys.argv[1]))
    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for c, v in zip(codes, ex.map(fy_dps, codes)):
            out[c] = v
    json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False)
    print("saved", sys.argv[2], file=sys.stderr)


if __name__ == "__main__":
    main()
