#!/usr/bin/env python3
"""拉港股 F10 主要财务指标历史（年报口径），输出近 8 年 ROE/净利/毛利率/负债率轨迹。"""
import json
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from hkstock_scan import curl

COLS = ("REPORT_DATE,REPORT_TYPE,ROE_YEARLY,ROE_AVG,HOLDER_PROFIT,HOLDER_PROFIT_YOY,OPERATE_INCOME,"
        "OPERATE_INCOME_YOY,GROSS_PROFIT_RATIO,NET_PROFIT_RATIO,DEBT_ASSET_RATIO,NETCASH_OPERATE,"
        "ISSUED_COMMON_SHARES,BASIC_EPS,DIVIDEND_RATE,CURRENT_RATIO")


def fetch_annual(code, years=9):
    url = ("https://datacenter.eastmoney.com/securities/api/data/v1/get?"
           "reportName=RPT_HKF10_FN_MAININDICATOR&columns=" + COLS +
           f"&filter={urllib.parse.quote(f'(SECUCODE="{code}.HK")')}"
           f"&pageNumber=1&pageSize=120&sortColumns=REPORT_DATE&sortTypes=-1")
    d = curl(url, referer=True)
    rows = (d.get("result") or {}).get("data") or []
    out = []
    for r in rows:
        rd = (r.get("REPORT_DATE") or "")[:10]
        if rd.endswith("12-31") and (r.get("REPORT_TYPE") or "").endswith("年报"):
            out.append(dict(
                y=int(rd[:4]), roe=r.get("ROE_YEARLY"), np=r.get("HOLDER_PROFIT"),
                np_yoy=r.get("HOLDER_PROFIT_YOY"), rev=r.get("OPERATE_INCOME"),
                rev_yoy=r.get("OPERATE_INCOME_YOY"), gpm=r.get("GROSS_PROFIT_RATIO"),
                npm=r.get("NET_PROFIT_RATIO"), dar=r.get("DEBT_ASSET_RATIO"),
                ocf=r.get("NETCASH_OPERATE"), eps=r.get("BASIC_EPS"),
            ))
        if len(out) >= years:
            break
    return list(reversed(out))


def main():
    codes = json.load(open(sys.argv[1]))
    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for c, data in zip(codes, ex.map(fetch_annual, codes)):
            out[c] = data
    json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False)
    print("saved", sys.argv[2], file=sys.stderr)


if __name__ == "__main__":
    main()
