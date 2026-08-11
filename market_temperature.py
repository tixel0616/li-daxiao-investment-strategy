#!/usr/bin/env python3
"""
市场温度计 —— 基于《李大霄投资战略》八维框架
=============================================
自动数据源：腾讯财经 (PE/PB)、东财 push2ex (涨停/炸板/跌停)
其余维度：交互式手动输入（每次运行会提示填写）

使用：python3 market_temperature.py
输出：终端结果 + 可选备忘录文件
"""

import json, time, urllib.request
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# 0. 配置
# ═══════════════════════════════════════════════════════════

INDEX_CODES = {
    "沪深300": "sh000300",
    "上证50":  "sh000016",
    "中证500": "sh000905",
    "创业板指": "sz399006",
    "上证指数": "sh000001",
}

WEIGHTS = {
    "估值":          0.20,
    "股债性价比":    0.15,
    "盈利与信用":    0.15,
    "货币流动性":    0.10,
    "政策与制度":    0.10,
    "市场供求":      0.10,
    "长期资金":      0.10,
    "情绪与结构":    0.10,
}

# ═══════════════════════════════════════════════════════════
# 1. HTTP
# ═══════════════════════════════════════════════════════════

def _get(url: str, timeout: int = 15, retries: int = 2, encoding: str = "utf-8") -> str:
    import ssl
    ctx = ssl.create_default_context()
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            })
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read().decode(encoding, errors="replace")
        except Exception as e:
            if attempt == retries:
                raise
            time.sleep(1.5 * (attempt + 1))
    return ""

# ═══════════════════════════════════════════════════════════
# 2. 自动数据：腾讯财经 → 指数 PE/PB
# ═══════════════════════════════════════════════════════════

def fetch_index_quotes() -> dict[str, dict]:
    """返回 {code: {name, price, pe_ttm, pb, mcap_yi}}"""
    codes = list(INDEX_CODES.values())
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    raw = _get(url, timeout=10, encoding="gbk")
    result = {}
    for line in raw.strip().splitlines():
        if '="' not in line:
            continue
        tag = line.split("=")[0]          # v_sh000300
        body = line.split('"')[1]
        fields = body.split("~")
        code = tag[2:]
        def _f(i):
            try: return float(fields[i])
            except: return None
        result[code] = {
            "name": fields[1],
            "price": _f(3),
            "pe_ttm": _f(39),
            "pb": _f(43),
            "change_pct": _f(32),
            "mcap_yi": _f(45),
        }
    return result

# ═══════════════════════════════════════════════════════════
# 3. 自动数据：东财 push2ex → 涨停/炸板/跌停
# ═══════════════════════════════════════════════════════════

def fetch_limit_up_stats(date: str | None = None) -> dict:
    """返回 {zt, zb, dt, yzt, zbr}"""
    if date is None:
        date = datetime.today().strftime("%Y%m%d")
    result = {"zt": 0, "zb": 0, "dt": 0, "yzt": 0, "zbr": None}
    for ptype, key in [("zt", "zt"), ("zb", "zb"), ("dt", "dt"), ("yzt", "yzt")]:
        url = (
            f"https://push2ex.eastmoney.com/getTopicZTPool"
            f"?ut=7eea3edcaed734beff9cbfe3189ab101"
            f"&PageSize=500&PageIndex=1&sort=fbt%3Aasc"
            f"&date={date}&ptype={ptype}"
        )
        try:
            data = json.loads(_get(url, timeout=10))
            result[key] = data.get("data", {}).get("total", 0) or 0
        except Exception:
            pass
        time.sleep(1.5)
    if result["zt"] > 0:
        result["zbr"] = round(result["zb"] / result["zt"] * 100, 1)
    return result


# ═══════════════════════════════════════════════════════════
# 2.5 自动数据：腾讯财经 → 国债 ETF（511010）价格趋势
# ═══════════════════════════════════════════════════════════

def fetch_bond_etf() -> dict:
    """返回国债 ETF 价格、涨跌幅（proxy for 债券市场趋势）"""
    url = "https://qt.gtimg.cn/q=sh511010"
    raw = _get(url, timeout=10, encoding="gbk")
    for line in raw.strip().splitlines():
        if '="' not in line: continue
        body = line.split('"')[1]; f = body.split("~")
        try:
            return {
                "name": f[1], "price": float(f[3]),
                "change_pct": float(f[32]), "pre_close": float(f[4]),
            }
        except: pass
    return {}

# ═══════════════════════════════════════════════════════════
# 4. 评分函数
# ═══════════════════════════════════════════════════════════

def score_valuation(pe: float | None) -> int:
    """沪深300 PE 经验区间：<10=2, 10-13=1, 13-16=0, 16-20=-1, >20=-2"""
    if pe is None: return 0
    if pe < 10: return 2
    if pe < 13: return 1
    if pe <= 16: return 0
    if pe <= 20: return -1
    return -2

def score_bond(bond: dict) -> int:
    """国债 ETF 近5日趋势 → -2~+2（涨=收益率降=流动性松）"""
    if not bond or not bond.get("price"): return 0
    chg = bond.get("change_pct", 0)
    if chg > 0.5: return 2
    if chg > 0.2: return 1
    if chg > -0.2: return 0
    if chg > -0.5: return -1
    return -2

def sentiment_from_breadth(hs300_chg: float | None, ups: int, total: int) -> int:
    """用广度+指数涨跌幅代理情绪（替代已失效的东财 push2ex）→ -2~+2"""
    if total == 0:
        return 0
    ratio = ups / total
    chg = hs300_chg or 0
    s = 0
    # 广度: 多数涨→恐慌/见底, 多数跌→狂热/追高需要区分
    if ratio <= 0.2:
        s -= 1  # 普跌, 可能恐慌
    elif ratio >= 0.8:
        s += 1  # 普涨, 可能修复情绪
    # 幅度: 大跌→恐慌, 大涨→过热
    if chg < -2:
        s += 1  # 急跌后恐慌见底信号
    elif chg < -0.5:
        s += 0
    elif chg > 2:
        s -= 1  # 急涨→过热
    elif chg > 0.5:
        s += 1  # 温和上涨
    return max(-2, min(2, s))

def score_breadth(indices: dict) -> int:
    """大盘涨跌 → -2~+2（正=多数指数上涨）"""
    if not indices: return 0
    ups = sum(1 for v in indices.values() if v and (v.get("change_pct") or 0) > 0)
    total = len(indices)
    if total == 0: return 0
    ratio = ups / total
    if ratio > 0.8: return 2
    if ratio > 0.6: return 1
    if ratio > 0.4: return 0
    if ratio > 0.2: return -1
    return -2

def score_sentiment(lu: dict) -> int:
    """涨停家数 + 炸板率 → -2~+2"""
    if lu["zt"] == 0: return 0
    s = 0
    if lu["zt"] >= 80: s -= 1
    elif lu["zt"] <= 20: s += 1
    zbr = lu.get("zbr")
    if zbr is not None:
        if zbr > 40: s -= 1
        elif zbr < 20: s += 1
    return max(-2, min(2, s))


# ═══════════════════════════════════════════════════════════
# 2.6 自动数据：东财 push2 → 大盘涨跌
# ═══════════════════════════════════════════════════════════

def derive_breadth(quotes: dict[str, dict]) -> dict[str, dict]:
    """从腾讯指数行情提取涨跌 → {code: {name, change_pct}}"""
    result = {}
    for code, q in quotes.items():
        chg = q.get("change_pct")
        if chg is not None:
            short = code.replace("sh", "").replace("sz", "")
            result[short] = {
                "name": q.get("name", ""),
                "change_pct": chg,
            }
    return result

# ═══════════════════════════════════════════════════════════
# 5. 交互输入
# ═══════════════════════════════════════════════════════════

MANUAL_DIMS = {
    "盈利与信用": "盈利增速/信用利差/社融 → -2~+2（正=盈利改善/信用宽）",
    "货币流动性": "利率/LPR/降准降息/汇率 → -2~+2（正=流动性偏松）",
    "政策与制度": "政策落地 vs 价格反映阶段 → -2~+2（正=积极）",
    "长期资金":   "北向/两融/险资/社保动向 → -2~+2（正=持续流入）",
}

def manual_scores() -> dict[str, int]:
    scores = {}
    print("\n── 手动评分（-2 ~ +2，直接回车=0）──")
    for dim, hint in MANUAL_DIMS.items():
        while True:
            raw = input(f"  {dim}  [{hint}]: ").strip()
            if raw == "":
                scores[dim] = 0
                break
            try:
                v = int(raw)
                if -2 <= v <= 2:
                    scores[dim] = v
                    break
                print("    请输入 -2 ~ +2")
            except ValueError:
                print("    请输入整数")
    return scores

# ═══════════════════════════════════════════════════════════
# 6. 主入口
# ═══════════════════════════════════════════════════════════

def run(interactive: bool = True) -> dict:
    date = datetime.today().strftime("%Y-%m-%d")

    print(f"\n{'═' * 52}")
    print(f"  市场温度计 · {date}")
    print(f"{'═' * 52}")

    # ── 自动：估值 ──
    print("[auto] 拉取指数 PE/PB（腾讯财经）...")
    quotes = fetch_index_quotes()
    hs300 = quotes.get("sh000300", {})
    pe_300, pb_300 = hs300.get("pe_ttm"), hs300.get("pb")
    val_score = score_valuation(pe_300)
    print(f"  沪深300 PE={pe_300} PB={pb_300} → 得分 {val_score:+d}")

    # ── 自动：股债 ──
    print("[auto] 拉取国债 ETF（511010）趋势...") 
    bond = fetch_bond_etf()
    bond_score = score_bond(bond)
    print(f"  国债ETF={bond.get('price')} 涨跌={bond.get('change_pct')}% → 得分 {bond_score:+d}")

    # ── 自动：大盘涨跌 ──
    print("[auto] 计算大盘涨跌（腾讯指数行情）...")
    breadth = derive_breadth(quotes)
    br_score = score_breadth(breadth)
    ups_b = sum(1 for v in breadth.values() if (v.get("change_pct") or 0) > 0)
    print(f"  主要指数 {ups_b}/{len(breadth)} 上涨 → 得分 {br_score:+d}")

    # ── 自动：情绪 ──
    print("[auto] 拉取涨停/炸板统计（东财 push2ex）...")
    lu = fetch_limit_up_stats()
    if lu["zt"] == 0 and lu["zb"] == 0:
        # push2ex 不可用 → 用广度+涨跌幅代理
        hs300_chg = quotes.get("sh000300", {}).get("change_pct")
        se_score = sentiment_from_breadth(hs300_chg, ups_b, len(breadth))
        lu["_fallback"] = True
        print(f"  涨停 API 无数据，改用广度代理 → 得分 {se_score:+d}")
    else:
        se_score = score_sentiment(lu)
        lu["_fallback"] = False
        print(f"  涨停={lu['zt']} 炸板={lu['zb']} 跌停={lu['dt']} 炸板率={lu['zbr']}% → 得分 {se_score:+d}")

    # ── 手动：其余 ──
    manual = manual_scores() if interactive else {k: 0 for k in MANUAL_DIMS}

    scores = {
        "估值":        (val_score, "auto"),
        "股债性价比":  (bond_score, "auto"),
        "盈利与信用":  (manual["盈利与信用"], "manual"),
        "货币流动性":  (manual["货币流动性"], "manual"),
        "政策与制度":  (manual["政策与制度"], "manual"),
        "市场供求":    (br_score, "auto"),
        "长期资金":    (manual["长期资金"], "manual"),
        "情绪与结构":  (se_score, "auto"),
    }

    total = sum(v[0] * WEIGHTS[k] for k, v in scores.items())
    M = round(total * 50, 1)

    if M >= 50:      state = "低温/修复区"
    elif M >= 15:    state = "偏有利"
    elif M >= -14:   state = "中性/证据冲突"
    elif M >= -49:   state = "偏热/风险上升"
    else:            state = "过热/脆弱区"

    result = {
        "date": date,
        "M": M,
        "state": state,
        "scores": {k: {"score": v[0], "source": v[1]} for k, v in scores.items()},
        "details": {
            "hs300_pe": pe_300, "hs300_pb": pb_300,
            "limit_up": lu,
            "bond_etf": bond,
            "breadth": breadth,
            "index_quotes": {k: v.get("pe_ttm") for k, v in quotes.items() if "sh" in k or "sz" in k},
        }
    }

    return result


def print_report(result: dict) -> None:
    r = result
    d = r["details"]
    lu = d["limit_up"]

    print(f"\n{'═' * 52}")
    print(f"  结果汇总")
    print(f"{'═' * 52}")
    for k, v in r["scores"].items():
        bar = "█" * abs(v["score"])
        sign = "+" if v["score"] > 0 else ("-" if v["score"] < 0 else " ")
        print(f"  {k:　<6s} {sign}{bar:<4s} {v['score']:+d} [{v['source']}]")

    print(f"\n  市场总分 M = {r['M']}  ({r['state']})")

    # 五维汇总
    def _dir(s): return "多" if s > 0 else ("空" if s < 0 else "中")
    s = r["scores"]
    se_s = s["情绪与结构"]["score"]

    print(f"""
════════ 五维交汇 ════════
  产业资本：{'□多' if _dir(s['长期资金']['score'])=='多' else ('□空' if _dir(s['长期资金']['score'])=='空' else '□中')}
  跨市场：  {'□松' if _dir(s['货币流动性']['score'])=='多' else ('□紧' if _dir(s['货币流动性']['score'])=='空' else '□中')}
  政策：    {'□积极' if _dir(s['政策与制度']['score'])=='多' else ('□偏紧' if _dir(s['政策与制度']['score'])=='空' else '□中')}
  估值：    {'□低估' if _dir(s['估值']['score'])=='多' else ('□高估' if _dir(s['估值']['score'])=='空' else '□合理')}
  情绪：    {'□恐惧' if se_s>0 else ('□狂热' if se_s<0 else '□正常')}

  数据截止：{r['date']}
  沪深300 PE={d['hs300_pe']}  PB={d['hs300_pb']}
  国债ETF {d['bond_etf'].get('price')} 涨跌 {d['bond_etf'].get('change_pct')}%
  涨停 {lu['zt']} 家 / 炸板 {lu['zb']} / 跌停 {lu['dt']} / 炸板率 {lu['zbr']}%
  大盘上涨 {sum(1 for v in d['breadth'].values() if v.get('change_pct',0)>0)}/{len(d['breadth'])} 家
""")


if __name__ == "__main__":
    import sys
    batch = "--batch" in sys.argv
    result = run(interactive=not batch)
    print_report(result)
