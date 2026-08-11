#!/usr/bin/env python3
"""
市场温度计 —— 基于《李大霄投资战略》八维框架的量化实现

使用前：
  1. pip install requests
  2. 无需 API Key —— 全部使用腾讯财经、东财 datacenter 等公开接口
  3. 东财请求内置 1.5s 间隔，避免封 IP

输出：八维温度计总分 + 填好的市场结论备忘录（Markdown）
"""

import json, math, time, urllib.request, urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import Optional

# ═══════════════════════════════════════════════════════════
# 0. 工具函数
# ═══════════════════════════════════════════════════════════

def _get(url: str, timeout: int = 15, retries: int = 2, encoding: str = "utf-8") -> str:
    """GET 请求，带指数退避重试 + 合理 UA"""
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
                raise RuntimeError(f"GET {url[:80]} 失败: {e}")
            time.sleep(1.5 * (attempt + 1))

def _sleep_em():
    """东财节流：1.5s 基础 + 随机 0~0.5s 抖动"""
    time.sleep(1.5 + __import__('random').random() * 0.5)

# ═══════════════════════════════════════════════════════════
# 1. 估值层 —— 腾讯财经
# ═══════════════════════════════════════════════════════════

_INDEX_CODES = {
    "沪深300": "sh000300",
    "上证50":  "sh000016",
    "中证500": "sh000905",
    "创业板指": "sz399006",
    "上证指数": "sh000001",
}

# 腾讯财经 Qt 返回的字段位置（实测校准, 2026-05）
#   3=现价  39=PE(TTM)  45=总市值(亿)  46=PB  43=振幅%  44=流通市值(亿)
_PE_IDX = 39
_PB_IDX = 46
_MCAP_IDX = 45
_PRICE_IDX = 3
_NAME_IDX = 1

def _tencent_fetch(codes: list[str]) -> dict[str, dict]:
    """批量取腾讯财经行情，返回 {code: {pe_ttm, pb, price, name, mcap_yi}}"""
    q = ",".join(codes)
    url = f"https://qt.gtimg.cn/q={q}"
    raw = _get(url, timeout=10, encoding="gbk")
    result = {}
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or '="' not in line:
            continue
        # 格式: v_sh000300="1~沪深300~3895.00~..."
        tag = line.split("=")[0]           # v_sh000300
        body = line.split('"')[1]          # 1~沪深300~...
        fields = body.split("~")
        code = tag[2:]                     # sh000300
        result[code] = {
            "name": fields[_NAME_IDX],
            "price": _safe_float(fields[_PRICE_IDX]),
            "pe_ttm": _safe_float(fields[_PE_IDX]),
            "pb": _safe_float(fields[_PB_IDX]),
            "mcap_yi": _safe_float(fields[_MCAP_IDX]),
        }
    return result

def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except (ValueError, TypeError):
        return None

# ═══════════════════════════════════════════════════════════
# 2. 股债性价比 —— 东财 datacenter（国债收益率）+ 腾讯（股息率）
# ═══════════════════════════════════════════════════════════

def _bond_yield_10y() -> Optional[float]:
    """10 年期国债收益率 —— 东财 datacenter-web"""
    _sleep_em()
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?reportName=RPTA_WEB_TREASURYYIELD"
        "&columns=ALL"
        "&sortColumns=SOLAR_DATE&sortTypes=-1"
        "&pageSize=1&pageNumber=1"
        "&filter=(PRO_CODE%3D%22CND10Y%22)"
    )
    try:
        data = json.loads(_get(url, timeout=15))
        items = data.get("result", {}).get("data", [])
        if items:
            return _safe_float(items[0].get("YIELD_CLOSE"))
    except Exception:
        pass
    return None

def _dividend_yield_sh000300() -> Optional[float]:
    """用腾讯指数的 PE/PB 间接推算或直接取股息率字段。
    腾讯行情不直接给股息率，用 datacenter 取沪深300 股息率。
    """
    _sleep_em()
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?reportName=RPT_INDEX_BASICINFO"
        "&columns=INDEX_CODE,SECURITY_NAME_ABBR,TRADE_DATE,DIVIDEND_YIELD_RATIO,PE,PB"
        "&filter=(INDEX_CODE%3D%22000300%22)"
        "&pageSize=1&pageNumber=1"
    )
    try:
        data = json.loads(_get(url, timeout=15))
        items = data.get("result", {}).get("data", [])
        if items:
            return _safe_float(items[0].get("DIVIDEND_YIELD_RATIO"))
    except Exception:
        pass
    return None

# ═══════════════════════════════════════════════════════════
# 3. 市场供求 —— 东财 datacenter（IPO / 再融资 / 回购 / 解禁）
# ═══════════════════════════════════════════════════════════

def _ipo_this_month_count() -> Optional[int]:
    """本月 A 股 IPO 数量 —— 东财 datacenter"""
    _sleep_em()
    today = datetime.today()
    start = today.replace(day=1).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?reportName=RPTA_WEB_NEWSTOCK_ISSUE"
        "&columns=ALL&sortColumns=LISTING_DATE&sortTypes=-1"
        f"&filter=(LISTING_DATE%3E%3D%27{start}%27)(LISTING_DATE%3C%3D%27{end}%27)"
        "&pageSize=200&pageNumber=1"
    )
    try:
        data = json.loads(_get(url, timeout=15))
        return data.get("result", {}).get("count", 0)
    except Exception:
        return None

def _lockup_this_month_billion() -> Optional[float]:
    """本月解禁市值（亿）—— datacenter"""
    _sleep_em()
    today = datetime.today()
    start = today.replace(day=1).strftime("%Y-%m-%d")
    end = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    end = end.strftime("%Y-%m-%d")
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?reportName=RPTA_WEB_UNLOCK_DATE"
        "&columns=ALL&sortColumns=UNLOCK_DATE&sortTypes=1"
        f"&filter=(UNLOCK_DATE%3E%3D%27{start}%27)(UNLOCK_DATE%3C%3D%27{end}%27)"
        "&pageSize=500&pageNumber=1"
    )
    try:
        data = json.loads(_get(url, timeout=15))
        items = data.get("result", {}).get("data", [])
        total = 0.0
        for it in items:
            total += _safe_float(it.get("UNLOCK_SHARES", 0)) or 0
        return total / 1e8  # 股 → 亿
    except Exception:
        return None

# ═══════════════════════════════════════════════════════════
# 4. 长期资金 —— 北向资金（同花顺 hsgt）+ 两融（东财）
# ═══════════════════════════════════════════════════════════

def _northbound_month() -> Optional[float]:
    """近 1 月北向资金净流入（亿） —— 同花顺 hsgt"""
    # 同花顺 hsgt 分钟级 -> 日汇总比较重；用东财 datacenter 日级
    _sleep_em()
    # 取最近 22 个交易日
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?reportName=RPT_MUTUAL_STOCK_HSGT"
        "&columns=ALL&sortColumns=TRADE_DATE&sortTypes=-1"
        "&pageSize=22&pageNumber=1"
    )
    try:
        data = json.loads(_get(url, timeout=15))
        items = data.get("result", {}).get("data", [])
        total = sum(_safe_float(it.get("NET_BUY_AMT", 0)) or 0 for it in items)
        return total / 1e8  # 元 → 亿
    except Exception:
        return None

def _margin_balance_yi() -> Optional[float]:
    """沪深两市融资余额（亿）—— datacenter"""
    _sleep_em()
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?reportName=RPT_MUTUAL_MARGINTRADING_SZSUM"
        "&columns=ALL&sortColumns=TRADE_DATE&sortTypes=-1"
        "&pageSize=1&pageNumber=1"
    )
    try:
        data = json.loads(_get(url, timeout=15))
        items = data.get("result", {}).get("data", [])
        if items:
            return _safe_float(items[0].get("FIN_BALANCE", 0)) or 0
    except Exception:
        pass
    # 备胎：沪市
    _sleep_em()
    url2 = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?reportName=RPT_MUTUAL_MARGINTRADING_SZSUM&columns=ALL"
        "&sortColumns=TRADE_DATE&sortTypes=-1&pageSize=1&pageNumber=1"
    )
    try:
        data = json.loads(_get(url, timeout=15))
        items = data.get("result", {}).get("data", [])
        if items:
            total = (_safe_float(items[0].get("FIN_BALANCE", 0)) or 0) + \
                    (_safe_float(items[0].get("FIN_BALANCE_SH", 0)) or 0)
            return total
    except Exception:
        return None

# ═══════════════════════════════════════════════════════════
# 5. 情绪 —— 东财涨停池 + 同花顺热榜
# ═══════════════════════════════════════════════════════════

def _limit_up_stats() -> dict:
    """今日涨停/炸板/跌停统计 —— 东财 push2"""
    _sleep_em()
    results = {"zt": 0, "zb": 0, "dt": 0, "yzt": 0}
    today = datetime.today().strftime("%Y%m%d")
    for pool, key in [("zt", "zt"), ("zb", "zb"), ("dt", "dt"), ("yzt", "yzt")]:
        url = (
            f"https://push2ex.eastmoney.com/getTopicZTPool"
            f"?ut=7eea3edcaed734beff9cbfe3189ab101"
            f"&PageSize=500&PageIndex=1"
            f"&sort=fbt%3Aasc&date={today}"
            f"&ptype={pool}"
        )
        try:
            data = json.loads(_get(url, timeout=15))
            results[key] = data.get("data", {}).get("total", 0) or 0
        except Exception:
            pass
        _sleep_em()
    if results["zt"] > 0:
        results["zbr"] = round(results["zb"] / results["zt"] * 100, 1)
    else:
        results["zbr"] = None
    return results

# ═══════════════════════════════════════════════════════════
# 6. 综合评分
# ═══════════════════════════════════════════════════════════

def score_valuation(pe: Optional[float], pb: Optional[float]) -> int:
    """估值维度（-2 ~ +2）—— 基于沪深300 PE/PB 经验区间"""
    if pe is None:
        return 0
    # 沪深300 PE 经验：<10 低估, 10-13 合理偏低, 13-16 合理, 16-20 偏高, >20 高估
    if pe < 10:
        return 2
    if pe < 13:
        return 1
    if pe <= 16:
        return 0
    if pe <= 20:
        return -1
    return -2

def score_yield_gap(div_yield: Optional[float], bond10: Optional[float]) -> int:
    """股债性价比：股息率 vs 10 年国债"""
    if div_yield is None or bond10 is None:
        return 0
    gap = (div_yield or 0) - (bond10 or 0)
    if gap > 0.5:
        return 2
    if gap > 0:
        return 1
    if gap > -1:
        return 0
    if gap > -2:
        return -1
    return -2

def score_supply(ipo_count: Optional[int], lockup_yi: Optional[float]) -> int:
    if ipo_count is None and lockup_yi is None:
        return 0
    s = 0
    if ipo_count is not None:
        if ipo_count <= 5:
            s += 1
        elif ipo_count >= 30:
            s -= 1
    if lockup_yi is not None:
        if lockup_yi < 500:
            s += 1
        elif lockup_yi > 2000:
            s -= 1
    return max(-2, min(2, s))

def score_longfunds(northbound: Optional[float], margin: Optional[float],
                     margin_prev: Optional[float] = None) -> int:
    s = 0
    if northbound is not None:
        if northbound > 100:
            s += 1
        elif northbound < -100:
            s -= 1
    if margin is not None and margin_prev is not None:
        chg = (margin - margin_prev) / abs(margin_prev) if margin_prev else 0
        if chg > 0.02:
            s += 1
        elif chg < -0.05:
            s -= 1
    return max(-2, min(2, s))

def score_sentiment(lu_stats: dict) -> int:
    zt = lu_stats.get("zt", 0)
    zbr = lu_stats.get("zbr", None)
    if zt == 0:
        return 0
    s = 0
    if zt >= 80:
        s -= 1
    elif zt <= 20:
        s += 1
    if zbr is not None:
        if zbr > 40:
            s -= 1
        elif zbr < 20:
            s += 1
    return max(-2, min(2, s))

# ═══════════════════════════════════════════════════════════
# 7. 主入口
# ═══════════════════════════════════════════════════════════

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

def run(date: Optional[str] = None) -> dict:
    """
    运行市场温度计，返回完整结果字典。
    自动维度：估值、股债性价比、供求、长期资金、情绪。
    手动维度：盈利与信用、货币流动性、政策与制度——在结果中标注 "manual"。
    """
    if date is None:
        date = datetime.today().strftime("%Y-%m-%d")

    print(f"═" * 50)
    print(f"  市场温度计 · {date}")
    print(f"═" * 50)

    # ── 1. 估值 ──
    print("\n[1/8] 拉取指数估值（腾讯财经）...")
    quotes = _tencent_fetch(list(_INDEX_CODES.values()))
    hs300 = quotes.get("sh000300", {})
    pe_300 = hs300.get("pe_ttm")
    pb_300 = hs300.get("pb")
    val_score = score_valuation(pe_300, pb_300)
    print(f"  沪深300 PE={pe_300} PB={pb_300} → 得分 {val_score:+d}")

    # ── 2. 股债性价比 ──
    print("[2/8] 拉取股息率与国债收益率（东财 datacenter）...")
    div_y = _dividend_yield_sh000300()
    bond10 = _bond_yield_10y()
    yg_score = score_yield_gap(div_y, bond10)
    print(f"  股息率={div_y} 国债10Y={bond10} → 得分 {yg_score:+d}")

    # ── 3. 供求 ──
    print("[3/8] 拉取本月 IPO 数量与解禁市值（东财 datacenter）...")
    ipo = _ipo_this_month_count()
    lockup = _lockup_this_month_billion()
    sup_score = score_supply(ipo, lockup)
    print(f"  本月 IPO={ipo} 解禁≈{lockup:.0f}亿 → 得分 {sup_score:+d}")

    # ── 4. 长期资金 ──
    print("[4/8] 拉取北向资金与融资余额...")
    nb = _northbound_month()
    margin = _margin_balance_yi()
    # 没有历史对比时暂用 0（下次运行可缓存）
    lf_score = score_longfunds(nb, margin, margin)
    print(f"  近1月北向={nb}亿 融资余额={margin}亿 → 得分 {lf_score:+d}")

    # ── 5. 情绪 ──
    print("[5/8] 拉取涨停/炸板/跌停统计（东财 push2ex）...")
    lu = _limit_up_stats()
    se_score = score_sentiment(lu)
    print(f"  涨停={lu['zt']} 炸板={lu['zb']} 跌停={lu['dt']} 炸板率={lu.get('zbr')}% → 得分 {se_score:+d}")

    # ── 汇总 ──
    scores = {
        "估值":        (val_score,  "auto", pe_300),
        "股债性价比":  (yg_score,   "auto", (div_y, bond10)),
        "盈利与信用":  (0,          "manual", None),
        "货币流动性":  (0,          "manual", None),
        "政策与制度":  (0,          "manual", None),
        "市场供求":    (sup_score,  "auto", (ipo, lockup)),
        "长期资金":    (lf_score,   "auto", (nb, margin)),
        "情绪与结构":  (se_score,   "auto", lu),
    }

    total = sum(v[0] * WEIGHTS[k] for k, v in scores.items())
    M = round(total * 50, 1)

    if M >= 50:
        state = "低温/修复区"
    elif M >= 15:
        state = "偏有利"
    elif M >= -14:
        state = "中性/证据冲突"
    elif M >= -49:
        state = "偏热/风险上升"
    else:
        state = "过热/脆弱区"

    return {
        "date": date,
        "M": M,
        "state": state,
        "scores": {k: {"score": v[0], "source": v[1], "data": v[2]} for k, v in scores.items()},
        "details": {
            "hs300_pe": pe_300, "hs300_pb": pb_300,
            "div_yield": div_y, "bond10": bond10,
            "ipo_count": ipo, "lockup_yi": lockup,
            "northbound": nb, "margin": margin,
            "limit_up": lu,
        }
    }


def to_conclusion_memo(result: dict, manual_overrides: Optional[dict] = None) -> str:
    """
    将温度计结果填入 §3.3.3 市场结论备忘录（Markdown）。
    manual_overrides: {"盈利与信用": (score, reason), "货币流动性": (score, reason), "政策与制度": (score, reason)}
    """
    r = result
    d = r["details"]
    s = r["scores"]

    # apply overrides
    if manual_overrides:
        for k, (sc, reason) in manual_overrides.items():
            if k in s:
                s[k] = {"score": sc, "source": "manual", "data": reason}

    pe, pb = d["hs300_pe"], d["hs300_pb"]
    div_y, b10 = d["div_yield"], d["bond10"]
    nb = d["northbound"]
    lu = d["limit_up"]

    def _s(k):
        return s[k]["score"]

    def _dir(score):
        if score > 0: return "□多/松/低估/恐惧"
        if score < 0: return "□空/紧/高估/狂热"
        return "□中性"

    # 五维中的"情绪事件"用 se_score 定性
    se = _s("情绪与结构")
    sent_dir = "□恐惧" if se > 0 else ("□狂热" if se < 0 else "□正常")

    memo = f"""==================== 市场结论备忘录 ====================
数据截止日：{r["date"]}

一、产业资本风向（§2.1）—— 长期资金维度
  近1月北向净流入：{nb}亿  → {_dir(_s("长期资金"))}
  融资余额：{d["margin"]}亿
  【需手动补充：汇金/社保/上市公司增减持数据】

二、跨市场与流动性（§2.2）—— 货币流动性维度
  【需手动补充：港币强弱、大宗商品、LPR/社融】
  当前手动评分：{_s("货币流动性")}

三、政策信号（§2.3）
  【需手动补充：近期重大政策文件/日期/所处阶段】
  当前手动评分：{_s("政策与制度")}

四、估值信号（§2.4）
  沪深300 PE(TTM)：{pe}  PB：{pb}
  股息率：{div_y}%  10Y国债：{b10}%
  → 估值维度：{_dir(_s("估值"))}  股债性价比：{_dir(_s("股债性价比"))}

五、情绪与事件（§2.5）
  涨停 {lu["zt"]} 家 / 炸板 {lu["zb"]} 家 / 炸板率 {lu.get("zbr")}%
  → {sent_dir}
  【需手动补充：重大事件提前量、新增开户/基金发行热度】

════════════ 五维交汇 ════════════
  产业资本：{_dir(_s("长期资金"))}
  跨市场：  {_dir(_s("货币流动性"))}
  政策：    {_dir(_s("政策与制度"))}
  估值：    {_dir(_s("估值"))}
  情绪：    {sent_dir}

════════════ 结论 ════════════
  市场总分（八维温度计）：{r["M"]}
  市场状态：{r["state"]}
  核心矛盾：【填写】
  判断失效条件：
    1.【填写】
    2.【填写】
  组合动作：□ 提高 □ 维持 □ 降低风险预算
  置信度：□ 低 □ 中 □ 高
  下次复核日期：【填写】
"""
    return memo


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    out_path = sys.argv[1] if len(sys.argv) > 1 else None

    result = run()
    print(f"\n{'═' * 50}")
    print(f"  市场总分 M = {result['M']}  ({result['state']})")
    print(f"{'═' * 50}")
    for k, v in result["scores"].items():
        print(f"  {k}: {v['score']:+d} [{v['source']}]")

    memo = to_conclusion_memo(result)
    print("\n" + memo)

    if out_path:
        Path(out_path).write_text(memo)
        print(f"  备忘录已写入：{out_path}")
