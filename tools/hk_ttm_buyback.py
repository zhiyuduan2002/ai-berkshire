#!/usr/bin/env python3
"""港股回购 TTM 测算 — 东财 RPT_HK_BUYBACK

三个必须处理的口径问题（不处理会得出翻倍甚至三倍的错误结论）：

  1) 同一笔回购会返回港元和美元两条记录（港股柜台 + 美股 ADS 两个口径）。
     直接求和会翻倍：百胜中国 09987 实测虚高 54%，汇丰 00005 虚高 219%。
     -> 按 TRADE_DATE 去重，每天只取金额最大的一条。
  2) 默认 pageSize=200 会截断高频回购公司（腾讯 754 条、百胜 1559 条）。
     -> pageSize=500 翻页至窗口边界。
  3) 不同公司用不同币种申报（HKD/USD/CNY/GBP）。
     -> 统一折算为港元再除以市值。

注意：回购收益率 ≠ 现金回报。只有注销式回购才增厚每股价值，港股不少公司
的回购是用于股权激励对冲（回购后转手发给员工），股本并未净减少。

用法:
  python3 hk_ttm_buyback.py 00700 09987 02057          # 直接指定代码
  python3 hk_ttm_buyback.py --json cand.json out.json  # 读候选池(含price/cap)批量算
"""
import json
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
REFERER = "https://emweb.securities.eastmoney.com/"
FX = {"HKD": 1.0, "USD": 7.80, "CNY": 1.10, "RMB": 1.10, "GBP": 9.80, "SGD": 5.85, "EUR": 8.40}
WINDOW_DAYS = 365


def curl(url):
    for _ in range(3):
        out = subprocess.run(
            ["/usr/bin/curl", "-s", "--noproxy", "*", "--max-time", "30",
             "-H", f"User-Agent: {UA}", "-H", f"Referer: {REFERER}", url],
            capture_output=True, text=True).stdout
        try:
            return json.loads(out)
        except Exception:
            continue
    return None


def to_hkd(r):
    return (r.get("REPO_AMT") or 0) * FX.get(r.get("CURRENCY") or "HKD", 1.0)


def buyback_ttm(code, today):
    """返回 TTM 回购金额(港元)、有回购的天数、涉及币种、被去重的天数"""
    cutoff = (today - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    byday = defaultdict(list)
    pn = 1
    while True:
        d = curl("https://datacenter.eastmoney.com/securities/api/data/v1/get?"
                 "reportName=RPT_HK_BUYBACK&columns=ALL"
                 f"&filter=(SECUCODE%3D%22{code}.HK%22)&pageNumber={pn}&pageSize=500"
                 "&sortColumns=TRADE_DATE&sortTypes=-1")
        try:
            res = d["result"]
            data = res["data"] or []
        except Exception:
            break
        stop = False
        for r in data:
            td = (r.get("TRADE_DATE") or "")[:10]
            if td < cutoff:
                stop = True
                break
            byday[td].append(r)
        if stop or not data or pn >= res.get("pages", 1):
            break
        pn += 1

    tot, ccys, dup_days = 0.0, set(), 0
    for recs in byday.values():
        cur = {r.get("CURRENCY") for r in recs}
        ccys |= cur
        if len(cur) > 1:
            dup_days += 1
        tot += max(to_hkd(r) for r in recs)
    return dict(bb_amt=tot, bb_days=len(byday),
                bb_ccy="/".join(sorted(str(c) for c in ccys)), dup_days=dup_days)


def main():
    today = datetime.now()

    if sys.argv[1] == "--json":
        data = json.load(open(sys.argv[2]))
        out_path = sys.argv[3] if len(sys.argv) > 3 else "/tmp/hk_bb.json"

        def work(c):
            c["bb"] = buyback_ttm(c["code"], today)
            if c.get("cap"):
                c["bb_yield"] = c["bb"]["bb_amt"] / c["cap"] * 100
                c["shareholder_yield"] = (c.get("y_net") or 0) + c["bb_yield"]
            return c

        with ThreadPoolExecutor(max_workers=8) as ex:
            data = list(ex.map(work, data))
        json.dump(data, open(out_path, "w"), ensure_ascii=False, default=str)
        print(f"{len(data)} 只 -> {out_path}", file=sys.stderr)
        return

    codes = sys.argv[1:]
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(lambda c: buyback_ttm(c, today), codes))

    print(f"{'代码':<8}{'TTM回购额(亿HK$)':>16}{'天数':>7}{'币种':>12}{'去重天数':>10}")
    for c, r in zip(codes, res):
        print(f"{c:<8}{r['bb_amt']/1e8:>16.2f}{r['bb_days']:>7}{r['bb_ccy']:>12}{r['dup_days']:>10}")


if __name__ == "__main__":
    main()
