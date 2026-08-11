# 数据接入指南：a-stock-data × 结构化投资分析框架

> 本指南把 `a-stock-data`（A 股全栈数据工具包，10 层架构、47 个端点）接入《结构化投资分析框架》，为框架的每个分析模块提供可直接调用的数据来源。
>
> 数据工具包仓库：https://github.com/tixel0616/a-stock-data（Apache 2.0，作者 Simon 林）
> 更新日期：2026-08-11

---

## 一、接入架构

```text
结构化投资分析框架（决策层）
        │  六问流程：适配性 → 市场阶段 → 公司质量 → 估值 → 组合执行 → 复盘
        ▼
数据接入层（本指南）
        │  八维市场温度计 · 公司评分卡 · 估值 · 风险排雷 · 跟踪监控
        ▼
a-stock-data（数据层，SKILL.md 内嵌 Python）
        │  10 层 · 47 端点 · 15 数据源 · 零鉴权（iwencai 除外）
        ▼
mootdx(通达信) · 腾讯 · 百度 · 东财 · 同花顺 · 新浪 · 巨潮 · 财联社
```

原则：**框架负责“怎么判断”，a-stock-data 负责“拿什么数据”**。所有数据结论必须回到框架的评分表和投资命题中验证，不能因为数据可得就直接下买卖结论。

---

## 二、环境准备（一次性）

### 2.1 安装

```bash
# 1. 获取 SKILL.md（二选一）
git clone https://github.com/tixel0616/a-stock-data.git
# 或
curl -O https://raw.githubusercontent.com/tixel0616/a-stock-data/main/SKILL.md

# 2. 安装 Python 依赖
pip install mootdx requests pandas stockstats

# 3.（可选）iwencai 语义搜索需要 API Key
export IWENCAI_API_KEY="your_key_here"
```

### 2.2 使用规则（来自 SKILL.md，必须遵守）

- **东财防封铁律**：所有 eastmoney.com 请求必须走 `em_get()`（内置串行限流 + 会话复用）；批量任务把 `EM_MIN_INTERVAL` 调大到 1.5~2 秒。
- **数据源优先级**：能用 mootdx/腾讯就拿到的数据，不要用东财；东财只用于它独有的数据（龙虎榜、解禁、两融、股东户数、资金流、研报等）。
- **ticker 归一化**：调用端点前先过 `norm_ticker(code)`；北交所 2024-10 后使用 920xxx 新号段，老号段会静默返回僵尸数据。
- **mootdx 客户端**：使用 SKILL.md 提供的 `tdx_client()` 替代 `Quotes.factory(market='std')`，规避 0.11.x BESTIP bug。
- **复权**：mootdx K 线为不复权，跨除权除息日的估值与回测需自行复权，或改用腾讯前复权 K 线。
- **数据日期**：所有数据必须记录获取日期；北向资金实时口径、东财资金流分钟级数据盘中可用，盘后口径不同。

---

## 三、八维市场温度计 × 数据映射

框架 §3.1 的每个维度，对应下列数据源（`SKILL.md` 中的函数名）：

| 温度计维度 | 权重 | a-stock-data 数据源 | 关键函数/端点 | 使用要点 |
|---|---|:---:|---|---|
| 市场估值 | 20% | 腾讯财经、东财研报 | `tencent_quote([指数代码])`、`full_valuation(code)` | 指数 PE/PB 用腾讯；个股估值用 `full_valuation()` 拿 PE(TTM)/PB/前向 PE/PEG/消化时间 |
| 股债性价比 | 15% | 腾讯 + 财联社/全球资讯 | `tencent_quote`、`cls_telegraph()`、`eastmoney_global_news()` | 股息率与国债收益率需另接债券源（a-stock-data 不含债券端）；新闻层用于捕捉利率/债市变化 |
| 盈利与信用周期 | 15% | 东财个股信息、新浪三表、mootdx 财务快照 | `eastmoney_stock_info()`、`sina_financial_report()`、mootdx 37 字段季报 | 全市场盈利周期需自建盈利扩散指标；单票用 `full_valuation()` 的一致预期 EPS 做边际跟踪 |
| 货币与流动性 | 10% | 财联社、全球资讯 | `cls_telegraph()`、`eastmoney_global_news()` | 跟踪降准降息、MLF/LPR、汇率与资金面变化 |
| 政策与制度 | 10% | 财联社、公告层、新闻层 | `cls_telegraph()`、`cninfo_announcements()` | 政策信号以正式文件/公告为准；区分“政策意图→落地→传导→价格反映” |
| 市场供求 | 10% | 东财 | `lockup_expiry()`（解禁）、`em_zt_pool()`（新股情绪）、`block_trade()`（大宗） | 解禁日历覆盖未来 90 天；回购/IPO 数据需另接（a-stock-data 无专项端点） |
| 长期资金行为 | 10% | 东财、同花顺 | `holder_num_change()`（股东户数）、`margin_trading()`（两融）、`hsgt_realtime()`（北向） | 股东户数下降=筹码集中；北向分钟级盘中可看，历史数据靠本地缓存积累 |
| 情绪与市场结构 | 10% | 打板层、舆情层、资金面 | `limit_up_sentiment()`（炸板率/连板高度）、`ths_hot_list()`、`em_hot_rank()`、`daily_dragon_tiger()` | 涨停家数、炸板率、连板高度构成情绪温度；人气榜/龙虎榜用于拥挤度交叉验证 |

> **注意**：a-stock-data 未覆盖的指标（债券收益率、回购金额、IPO 节奏等），需接入其他数据源后在框架的“观察项”列人工补充。

---

## 四、公司质量评分卡 × 数据映射

框架 §4.2 的六个模块，对应数据如下：

| 评分模块 | 分值 | 数据来源 | 关键函数 | 使用要点 |
|---|---|:---:|---|---|
| 真实价值创造 | 10 | 财报三表 + 互动易 + 公告 | `sina_financial_report()`、`cninfo_irm()`、`cninfo_announcements()` | 用互动易看公司如何回应市场关切；用公告验证业务真实性 |
| 行业空间与生命周期 | 15 | 研报层 + 板块 | `eastmoney_industry_reports()`、`eastmoney_concept_blocks()`、`iwencai_search()` | 行业研报用于判断渗透率/空间；概念板块用于确认公司所处的产业主题 |
| 商业模式与护城河 | 15 | 研报 + F10 | `eastmoney_reports()`、mootdx F10（9 大类）、`download_pdf()` | 研报 PDF 用于深度阅读；F10 提供公司文本资料 |
| 管理层与治理 | 15 | 公告 + 新闻 + 互动易 | `cninfo_announcements()`、`eastmoney_stock_news()`、`cninfo_irm()` | 重点看减持、质押、关联交易、资本运作类公告 |
| 财务质量与韧性 | 20 | 新浪三表 + mootdx 财务 | `sina_financial_report(code, "lrb" / "zcfz" / "xjll")`、mootdx 37 字段 | 三表分别取利润表/资产负债表/现金流量表，做 5-10 年趋势与现金转换率 |
| 股东回报 | 5 | 东财分红 | `dividend_history()` | 分红送转历史 + 进度状态，验证分红可持续性 |

---

## 五、估值层 × 数据映射

框架 §5 的三类估值方法与 `a-stock-data` 的结合方式：

| 框架方法 | 数据支持 | 关键函数 | 注意 |
|---|---|---|---|
| DCF/股利折现 | 一致预期 EPS + 历史三表 | `ths_eps_forecast()`、`sina_financial_report()` | 一致预期只反映卖方观点，需与自身 DCF 假设交叉验证 |
| 相对估值 | 实时估值 + 一致预期 | `tencent_quote()`、`full_valuation()` | PE(TTM)/PB 来自腾讯；前向 PE/PEG/消化时间由 `full_valuation()` 计算 |
| 资产/重置价值 | 资产负债表 | `sina_financial_report(code, "zcfz")` | 关注资产质量、负债结构、商誉与减值 |

**单票估值速查（流程 A）**：

```python
# SKILL.md 中的完整函数，返回 PE(TTM)/PB/前向PE/PEG/消化时间/机构覆盖数
r = full_valuation("688017")
print(r)
```

**批量估值对比（流程 B）**：

```python
stocks = ["600519", "000858", "601318", "300750"]
for code in stocks:
    r = full_valuation(code)
    print(f"{r['name']}({code}): PE_fwd={r['pe_fwd']}x PEG={r['peg']} 消化={r['digest_years']}年 覆盖={r['analyst_count']}家")
```

> **估值公式注意**：SKILL.md 的 `pe_digestion()` 把 30x 固定为成长股合理估值锚点、PEG 阈值 1/1.5 为“便宜/合理/贵”分界——这是数据工具包自带的简化口径。实际投决时，请以框架 §5.4 的估值评分（至少两种方法 + 三情景 + 安全边际）为准，**不要只凭 PEG 一个数字做买卖决策**。

---

## 六、风险排雷与投决前检查

把框架 §2.2 一票否决项与 §4.1 硬门槛转成可执行的数据检查：

| 检查项 | 数据端点 | 关键函数 | 排雷信号 |
|---|---|---|---|
| 治理/诚信 | 公告 + 互动易 | `cninfo_announcements()`、`cninfo_irm()` | 问询函、监管处罚、资金占用、关联交易 |
| 财务造假红旗 | 新浪三表 | `sina_financial_report()` | 利润增长但经营现金流长期落后 |
| 商誉/减值 | 资产负债表 | `sina_financial_report(code, "zcfz")` | 高商誉 + 业绩承诺到期 |
| 大股东质押/减持 | 公告 + 大宗交易 | `cninfo_announcements()`、`block_trade()` | 大宗折价率高、连续减持 |
| 解禁压力 | 东财解禁 | `lockup_expiry(code, trade_date, 90)` | 未来 90 天解禁批次/数量占比大 |
| 筹码集中度 | 东财股东户数 | `holder_num_change()` | 户数持续下降=筹码集中；上升需警惕 |
| 杠杆风险 | 东财两融 | `margin_trading()` | 融资余额快速上升且股价高位 |
| 舆情风险 | 财联社/热榜 | `cls_telegraph()`、`em_hot_rank()` | 负面快讯、异常高人气 |

---

## 七、标准调研流程（流程 D：新标的快速调研）

```python
code = "600519"

# 1. 机构覆盖与一致预期
forecast = ths_eps_forecast(code)
print(f"机构覆盖: {'有' if not forecast.empty else '无'}")

# 2. 实时估值
q = tencent_quote([code])[code]
print(f"PE={q['pe_ttm']} PB={q['pb']} 市值={q['mcap_yi']}亿")

# 3. 完整估值（前向PE/PEG/消化时间）
r = full_valuation(code)
print(r)

# 4. 概念板块归属
blocks = eastmoney_concept_blocks(code)
print(f"板块: {', '.join(blocks['concept_tags'][:10])}")

# 5. 资金流向（分钟级/120日）
flow = stock_fund_flow_120d(code)
total = sum(d["main_net"] for d in flow[-20:])
print(f"近20日主力累计净流入: {total/1e8:.2f}亿")

# 6. 龙虎榜 / 解禁 / 两融 / 股东户数 / 分红
dragon_tiger_board(code, "2026-08-11")
lockup_expiry(code, "2026-08-11", 90)
margin_trading(code, page_size=5)
holder_num_change(code)
dividend_history(code)
```

**完整调研流程**：`SKILL.md` 中「流程 D：新标的快速调研（V3.0 增强版）」共 11 步（机构覆盖 → 实时估值 → PE 消化 → PEG → 概念板块 → 分钟资金流 → 120 日资金流 → 龙虎榜 → 解禁 → 两融 → 股东户数），可直接作为框架 §9.1 十步流程的数据执行层。

---

## 八、跟踪监控（框架 §9.3 更新频率）

| 频率 | 框架要求 | a-stock-data 实现 |
|---|---|---|
| 每周 | 重大风险与失效信号 | `cninfo_announcements()`、`eastmoney_stock_news()`、`em_stock_monitor()`（重点监控池）、`em_price_anomaly()`（日内异动） |
| 每月 | 市场温度计 + 组合集中度 | `limit_up_sentiment()`、`board_fund_flow()`、`daily_dragon_tiger()`、`industry_comparison()` |
| 每季度 | 财务/行业/估值更新 | `sina_financial_report()`、`ths_eps_forecast()`、`eastmoney_industry_reports()` |
| 事件触发 | 财务预警/监管/并购 | `cls_telegraph()`、`eastmoney_global_news()`、`cninfo_irm()` |

---

## 九、暂未覆盖与扩展方向

a-stock-data 当前未提供的框架所需数据，建议另行补充：

1. **全市场估值分位数**：指数 PE/PB 历史分位需自建或接入其他估值数据库。
2. **债券收益率与股债性价比**：需接入国债收益率/信用利差数据源。
3. **回购与 IPO 节奏**：回购金额、IPO 批文/发行节奏无专项端点。
4. **汇率与商品**：汇率、原油、粮食等跨市场数据需单独接入。
5. **一致预期历史序列**：`ths_eps_forecast()` 仅提供当前一致预期，历史调仓数据需自建缓存。
6. **盈利扩散指标**：全市场盈利上修/下修家数占比需基于财报快照自建统计。

这些缺口不影响框架的决策质量——评分时在对应维度标记“数据缺失/人工补充”即可，不要因为缺数据就跳过该维度。

---

## 十、集成边界

- `a-stock-data` 是独立仓库（Apache 2.0），本指南不复制其代码，仅做映射与调用约定。
- 引用其数据时注明来源与获取日期；若修改其代码，遵守 Apache 2.0 许可。
- 本指南中的函数名以 a-stock-data SKILL.md V3.6.1 为准；上游更新后需同步核对。
- 所有数据仅用于研究，不构成投资建议。
