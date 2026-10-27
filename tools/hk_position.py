#!/usr/bin/env python3
"""港股困境/位置核验 — 腾讯前复权月K + 东财52周高低

腾讯 hkfqkline 只提供复权序列（不复权接口已下线），高股息港股的早年复权价
会被历次派息压成负值，故只取最近 N 年且价格为正的样本。
复权口径下的"距高点"= 含息总回报回撤，对收息投资者比价格回撤更有意义。

用法: python3 hk_position.py 00288 02313 ...
"""
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
YEARS = 10


def curl(url):
    return subprocess.run(
        ["/usr/bin/curl", "-s", "--noproxy", "*", "--max-time", "20",
         "-H", f"User-Agent: {UA}", url],
        capture_output=True, text=True,
    ).stdout


def qfq_month(code):
    out = curl("https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?"
               f"_var=k&param=hk{code},month,,,240,qfq")
    m = re.search(r"=(\{.*\})", out.strip(), re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(1))["data"][f"hk{code}"]["qfqmonth"]
    except Exception:
        return None
    rows = [r for r in d if float(r[2]) > 0 and float(r[4]) > 0]
    return rows[-YEARS * 12:] if rows else None


def week52(code):
    """stock/get 里价格是 f43、52周高低是 f174/f175，港股统一 ×1000 缩放。"""
    out = curl("https://push2delay.eastmoney.com/api/qt/stock/get?"
               f"secid=116.{code}&fields=f43,f174,f175")
    try:
        d = json.loads(out)["data"]
        return d["f43"] / 1000, d["f174"] / 1000, d["f175"] / 1000
    except Exception:
        return None, None, None


def one(code):
    kl = qfq_month(code)
    price, hi52, lo52 = week52(code)
    r = dict(code=code, price=price, hi52=hi52, lo52=lo52)
    if hi52 and lo52 and hi52 > lo52 and price:
        r["pos52"] = (price - lo52) / (hi52 - lo52) * 100
        r["off52hi"] = (price / hi52 - 1) * 100
    if kl:
        closes = [float(x[2]) for x in kl]
        highs = [float(x[3]) for x in kl]
        cur, hi = closes[-1], max(highs)
        r["dd"] = (cur / hi - 1) * 100
        r["peak"] = kl[highs.index(hi)][0]
        r["pctile"] = sum(1 for v in closes if v <= cur) / len(closes) * 100
        r["start"] = kl[0][0]
    time.sleep(0.2)
    return r


def main():
    codes = sys.argv[1:]
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(one, codes))
    print(f"{'代码':<7}{'现价':>8}{'52周低':>9}{'52周高':>9}{'52周位置':>9}"
          f"{'距52高':>9}{'10年含息回撤':>13}{'10年分位':>9}  峰值月")
    for r in res:
        if r.get("pos52") is None:
            print(f"{r['code']:<7}  取数失败")
            continue
        dd = f"{r['dd']:.1f}%" if "dd" in r else "n/a"
        pc = f"{r['pctile']:.0f}%" if "pctile" in r else "n/a"
        print(f"{r['code']:<7}{r['price']:>8.2f}{r['lo52']:>9.2f}{r['hi52']:>9.2f}"
              f"{r['pos52']:>8.0f}%{r['off52hi']:>8.1f}%{dd:>13}{pc:>9}  "
              f"{r.get('peak','')}")


if __name__ == "__main__":
    main()
