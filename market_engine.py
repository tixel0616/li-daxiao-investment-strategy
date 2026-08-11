#!/usr/bin/env python3
"""
市场温度计引擎 —— 基于《李大霄投资战略》八维框架
=================================================
纯数据层：拉取、评分、存储。供 CLI / Streamlit 共用。
"""

import json, ssl, time, urllib.request
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

INDEX_CODES = {
    "沪深300": "sh000300",
    "上证50":  "sh000016",
    "中证500": "sh000905",
    "创业板指": "sz399006",
    "上证指数": "sh000001",
}

WEIGHTS = {
    "估值": 0.20, "股债性价比": 0.15, "盈利与信用": 0.15,
    "货币流动性": 0.10, "政策与制度": 0.10, "市场供求": 0.10,
    "长期资金": 0.10, "情绪与结构": 0.10,
}

MANUAL_DIMS = ["盈利与信用", "货币流动性", "政策与制度", "长期资金"]

RECORDS_FILE = Path(__file__).parent / "temperature_records.json"

# ═══════════════════════════════════════════════════════════
# HTTP 工具
# ═══════════════════════════════════════════════════════════

def _get(url: str, timeout: int = 15, retries: int = 2, encoding: str = "utf-8") -> str:
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
# 数据抓取
# ═══════════════════════════════════════════════════════════

def fetch_index_quotes() -> dict[str, dict]:
    """腾讯财经 → 指数 PE/PB/涨跌幅"""
    codes = list(INDEX_CODES.values())
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    raw = _get(url, timeout=10, encoding="gbk")
    result = {}
    for line in raw.strip().splitlines():
        if '="' not in line:
            continue
        tag = line.split("=")[0]
        body = line.split('"')[1]
        fields = body.split("~")

        def _f(i):
            try: return float(fields[i])
            except: return None

        code = tag[2:]
        result[code] = {
            "name": fields[1],
            "price": _f(3),
            "pre_close": _f(4),
            "pe_ttm": _f(39),
            "pb": _f(43),
            "change_pct": _f(32),
            "change_amt": _f(31),
            "volume": _f(6),
            "amount_yi": _f(37),
            "mcap_yi": _f(45),
        }
    return result


def fetch_bond_etf() -> dict:
    """国债 ETF（511010）价格趋势"""
    url = "https://qt.gtimg.cn/q=sh511010"
    raw = _get(url, timeout=10, encoding="gbk")
    for line in raw.strip().splitlines():
        if '="' not in line:
            continue
        body = line.split('"')[1]
        f = body.split("~")
        try:
            return {
                "name": f[1], "price": float(f[3]),
                "change_pct": float(f[32]), "pre_close": float(f[4]),
            }
        except:
            pass
    return {}


def fetch_limit_up_stats(date: str | None = None) -> dict:
    """东财 push2ex → 涨停/炸板/跌停"""
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
# 评分函数
# ═══════════════════════════════════════════════════════════

def score_valuation(pe: float | None) -> int:
    """沪深300 PE → -2~+2"""
    if pe is None: return 0
    if pe < 10: return 2
    if pe < 13: return 1
    if pe <= 16: return 0
    if pe <= 20: return -1
    return -2


def score_bond(bond: dict) -> int:
    """国债 ETF 涨跌 → -2~+2（涨=收益率降=流动性松）"""
    if not bond or not bond.get("price"): return 0
    chg = bond.get("change_pct", 0)
    if chg > 0.5: return 2
    if chg > 0.2: return 1
    if chg > -0.2: return 0
    if chg > -0.5: return -1
    return -2


def derive_breadth(quotes: dict[str, dict]) -> dict[str, dict]:
    """从腾讯指数行情提取涨跌"""
    result = {}
    for code, q in quotes.items():
        chg = q.get("change_pct")
        if chg is not None:
            short = code.replace("sh", "").replace("sz", "")
            result[short] = {"name": q.get("name", ""), "change_pct": chg}
    return result


def score_breadth(indices: dict) -> int:
    """广度涨跌 → -2~+2"""
    if not indices: return 0
    ups = sum(1 for v in indices.values() if (v.get("change_pct") or 0) > 0)
    total = len(indices)
    if total == 0: return 0
    ratio = ups / total
    if ratio > 0.8: return 2
    if ratio > 0.6: return 1
    if ratio > 0.4: return 0
    if ratio > 0.2: return -1
    return -2


def sentiment_from_breadth(hs300_chg: float | None, ups: int, total: int) -> int:
    """广度+涨跌幅代理情绪 → -2~+2"""
    if total == 0: return 0
    ratio = ups / total
    chg = hs300_chg or 0
    s = 0
    if ratio <= 0.2: s -= 1
    elif ratio >= 0.8: s += 1
    if chg < -2: s += 1
    elif chg > 2: s -= 1
    elif chg > 0.5: s += 1
    return max(-2, min(2, s))


def score_sentiment(lu: dict) -> int:
    """涨停数据 → -2~+2"""
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
# 主分析
# ═══════════════════════════════════════════════════════════

def run_analysis(manual_scores: dict[str, int] | None = None) -> dict:
    """执行完整市场温度分析，返回结果 dict"""
    if manual_scores is None:
        manual_scores = {k: 0 for k in MANUAL_DIMS}

    date = datetime.today()

    # 抓数据
    quotes = fetch_index_quotes()
    hs300 = quotes.get("sh000300", {})
    pe_300, pb_300 = hs300.get("pe_ttm"), hs300.get("pb")
    hs300_chg = hs300.get("change_pct")

    bond = fetch_bond_etf()
    lu = fetch_limit_up_stats()
    breadth = derive_breadth(quotes)

    # 评分
    val_score = score_valuation(pe_300)
    bond_score = score_bond(bond)
    br_score = score_breadth(breadth)
    ups = sum(1 for v in breadth.values() if (v.get("change_pct") or 0) > 0)

    # 情绪
    if lu["zt"] == 0 and lu["zb"] == 0:
        se_score = sentiment_from_breadth(hs300_chg, ups, len(breadth))
        sentiment_source = "breadth_proxy"
    else:
        se_score = score_sentiment(lu)
        sentiment_source = "push2ex"

    scores = {
        "估值":       (val_score, "auto"),
        "股债性价比": (bond_score, "auto"),
        "盈利与信用": (manual_scores.get("盈利与信用", 0), "manual"),
        "货币流动性": (manual_scores.get("货币流动性", 0), "manual"),
        "政策与制度": (manual_scores.get("政策与制度", 0), "manual"),
        "市场供求":   (br_score, "auto"),
        "长期资金":   (manual_scores.get("长期资金", 0), "manual"),
        "情绪与结构": (se_score, "auto"),
    }

    total = sum(v[0] * WEIGHTS[k] for k, v in scores.items())
    M = round(total * 50, 1)

    if M >= 50:      state = "低温/修复区"
    elif M >= 15:    state = "偏有利"
    elif M >= -14:   state = "中性/证据冲突"
    elif M >= -49:   state = "偏热/风险上升"
    else:            state = "过热/脆弱区"

    return {
        "date": date.strftime("%Y-%m-%d"),
        "datetime": date.isoformat(),
        "M": M,
        "state": state,
        "scores": {k: {"score": v[0], "source": v[1]} for k, v in scores.items()},
        "details": {
            "hs300_pe": pe_300, "hs300_pb": pb_300, "hs300_chg": hs300_chg,
            "limit_up": lu,
            "bond_etf": bond,
            "breadth": breadth,
            "ups": ups,
            "total_indices": len(breadth),
            "sentiment_source": sentiment_source,
            "index_quotes": {
                INDEX_CODES[name]: {
                    "name": name,
                    "price": q.get("price"),
                    "change_pct": q.get("change_pct"),
                    "pe_ttm": q.get("pe_ttm"),
                    "pb": q.get("pb"),
                }
                for name, code in INDEX_CODES.items()
                if (q := quotes.get(code))
            },
        }
    }

# ═══════════════════════════════════════════════════════════
# 历史记录
# ═══════════════════════════════════════════════════════════

def save_record(result: dict) -> None:
    """追加一条分析记录到 JSON 文件"""
    records = load_records()
    records.append({
        "date": result["date"],
        "M": result["M"],
        "state": result["state"],
        "scores": result["scores"],
    })
    RECORDS_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2))


def load_records() -> list[dict]:
    """加载历史记录"""
    if RECORDS_FILE.exists():
        try:
            return json.loads(RECORDS_FILE.read_text())
        except:
            pass
    return []

# ═══════════════════════════════════════════════════════════
# CLI 入口（兼容旧用法）
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    interactive = "--batch" not in sys.argv
    manual = {}
    if interactive:
        print("\n── 手动评分（-2 ~ +2，直接回车=0）──")
        hints = {
            "盈利与信用": "盈利增速/信用利差/社融（正=改善）",
            "货币流动性": "利率/LPR/降准降息（正=偏松）",
            "政策与制度": "政策落地 vs 价格反映（正=积极）",
            "长期资金": "北向/两融/险资动向（正=流入）",
        }
        for dim in MANUAL_DIMS:
            while True:
                raw = input(f"  {dim} [{hints[dim]}]: ").strip()
                if raw == "":
                    manual[dim] = 0; break
                try:
                    v = int(raw)
                    if -2 <= v <= 2:
                        manual[dim] = v; break
                    print("    -2 ~ +2")
                except ValueError:
                    print("    整数")

    result = run_analysis(manual)
    # 简洁终端输出
    print(f"\n{'═'*52}")
    print(f"  市场温度计 · {result['date']}")
    print(f"{'═'*52}")
    for k, v in result["scores"].items():
        bar = "█" * abs(v["score"])
        sign = "+" if v["score"] > 0 else ("-" if v["score"] < 0 else " ")
        print(f"  {k:　<6s} {sign}{bar:<4s} {v['score']:+d} [{v['source']}]")
    print(f"\n  市场总分 M = {result['M']}  ({result['state']})")
    d = result["details"]
    print(f"  沪深300 PE={d['hs300_pe']} PB={d['hs300_pb']} 涨跌={d['hs300_chg']}%")
    print(f"  广度 {d['ups']}/{d['total_indices']} 上涨 | 情绪源: {d['sentiment_source']}")
    print(f"  国债ETF {d['bond_etf'].get('price','N/A')} 涨跌 {d['bond_etf'].get('change_pct','N/A')}%")
