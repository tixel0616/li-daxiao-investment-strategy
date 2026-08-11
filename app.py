"""
市场温度计 · Streamlit UI
==========================
基于《李大霄投资战略》八维框架的量化分析仪表盘
运行：streamlit run app.py
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime
from market_engine import (
    run_analysis, save_record, load_records,
    MANUAL_DIMS, WEIGHTS, INDEX_CODES,
)

st.set_page_config(
    page_title="市场温度计 · 李大霄八维框架",
    page_icon="🌡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ═══════════════════════════════════════════════════════════
# 样式
# ═══════════════════════════════════════════════════════════

st.markdown("""
<style>
    .temp-gauge { text-align: center; padding: 1rem; }
    .temp-value { font-size: 4rem; font-weight: 900; line-height: 1; }
    .temp-label { font-size: 1.2rem; opacity: 0.7; margin-top: 0.3rem; }
    .dim-card {
        border: 1px solid rgba(128,128,128,0.2);
        border-radius: 12px; padding: 1rem; margin-bottom: 0.5rem;
        background: rgba(128,128,128,0.03);
    }
    .dim-name { font-size: 0.95rem; font-weight: 600; }
    .dim-score { font-size: 1.5rem; font-weight: 800; }
    .dim-source { font-size: 0.7rem; opacity: 0.5; }
    .score-pos { color: #22c55e; }
    .score-neg { color: #ef4444; }
    .score-zero { color: #6b7280; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════
# 标题
# ═══════════════════════════════════════════════════════════

col1, col2 = st.columns([3, 1])
with col1:
    st.title("🌡️ 市场温度计")
    st.caption("基于《李大霄投资战略》八维框架 · 量化投资分析仪表盘")
with col2:
    st.caption(f"📅 {datetime.today().strftime('%Y-%m-%d %H:%M')}")

st.divider()

# ═══════════════════════════════════════════════════════════
# 手动维度输入（侧边展开）
# ═══════════════════════════════════════════════════════════

with st.expander("⚙️ 手动维度评分（-2 ~ +2）", expanded=False):
    hints = {
        "盈利与信用": "盈利增速/信用利差/社融 → 正=改善",
        "货币流动性": "利率/LPR/降准降息/汇率 → 正=偏松",
        "政策与制度": "政策落地 vs 价格反映阶段 → 正=积极",
        "长期资金":   "北向/两融/险资/社保动向 → 正=持续流入",
    }
    manual_cols = st.columns(4)
    manual_inputs = {}
    for i, dim in enumerate(MANUAL_DIMS):
        with manual_cols[i]:
            manual_inputs[dim] = st.slider(
                dim, -2, 2, 0, 1,
                help=hints[dim],
                key=f"manual_{dim}"
            )

# ═══════════════════════════════════════════════════════════
# 分析按钮
# ═══════════════════════════════════════════════════════════

run_col1, run_col2, run_col3 = st.columns([1, 2, 1])
with run_col2:
    analyze = st.button("🔍 运行分析", type="primary", use_container_width=True)

if analyze:
    with st.spinner("正在拉取实时数据…"):
        result = run_analysis(manual_inputs if any(manual_inputs.values()) else None)
        save_record(result)

    # ── 温度计大卡 ──
    M = result["M"]
    if M >= 50:
        color, emoji = "#22c55e", "🧊"
    elif M >= 15:
        color, emoji = "#84cc16", "🟢"
    elif M >= -14:
        color, emoji = "#eab308", "🟡"
    elif M >= -49:
        color, emoji = "#f97316", "🟠"
    else:
        color, emoji = "#ef4444", "🔥"

    gcol1, gcol2 = st.columns([1, 2])
    with gcol1:
        st.markdown(f"""
        <div class="temp-gauge">
            <div class="temp-value" style="color:{color}">{emoji} {M:.0f}</div>
            <div class="temp-label">市场总分 · {result['state']}</div>
        </div>
        """, unsafe_allow_html=True)

        # 计分表
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+delta",
            value=M,
            domain={'x': [0, 1], 'y': [0, 1]},
            title={'text': "八维温度计", 'font': {'size': 14}},
            delta={'reference': 0},
            gauge={
                'axis': {'range': [-100, 100], 'tickwidth': 1},
                'bar': {'color': color},
                'steps': [
                    {'range': [-100, -50], 'color': "rgba(239,68,68,0.3)"},
                    {'range': [-50, -15], 'color': "rgba(249,115,22,0.2)"},
                    {'range': [-15, 15], 'color': "rgba(234,179,8,0.15)"},
                    {'range': [15, 50], 'color': "rgba(132,204,22,0.2)"},
                    {'range': [50, 100], 'color': "rgba(34,197,94,0.3)"},
                ],
                'threshold': {
                    'line': {'color': "white", 'width': 2},
                    'thickness': 0.8, 'value': M
                }
            }
        ))
        fig_gauge.update_layout(height=250, margin=dict(t=30, b=0, l=20, r=20))
        st.plotly_chart(fig_gauge, use_container_width=True)

    with gcol2:
        # 关键数据摘要
        d = result["details"]
        md = f"""
| 指标 | 数值 |
|---|---|
| 沪深300 PE | **{d['hs300_pe']}** |
| 沪深300 PB | **{d['hs300_pb']}** |
| 沪深300 涨跌 | **{d['hs300_chg']:+.2f}%** |
| 国债ETF (511010) | **{d['bond_etf'].get('price','N/A')}** |
| 广度 | **{d['ups']}/{d['total_indices']}** 上涨 |
| 情绪数据源 | **{d['sentiment_source']}** |
"""
        st.markdown(md)

    st.divider()

    # ── 八维得分卡 ──
    st.subheader("📊 八维得分")

    dim_cols = st.columns(4)
    for i, (dim, v) in enumerate(result["scores"].items()):
        score = v["score"]
        source = v["source"]
        w = WEIGHTS[dim]

        if score > 0:
            sc, bar_char = "score-pos", "🟩"
        elif score < 0:
            sc, bar_char = "score-neg", "🟥"
        else:
            sc, bar_char = "score-zero", "⬜"

        bar = bar_char * abs(score) + "⬜" * (2 - abs(score))

        with dim_cols[i % 4]:
            st.markdown(f"""
            <div class="dim-card">
                <div class="dim-name">{dim} <span style="font-size:0.7rem;opacity:0.4">({w:.0%})</span></div>
                <div class="dim-score {sc}">{score:+d} {bar}</div>
                <div class="dim-source">{source}</div>
            </div>
            """, unsafe_allow_html=True)

    st.divider()

    # ── 指数明细 ──
    with st.expander("📋 指数行情明细", expanded=False):
        idx_data = []
        for code, q in d["index_quotes"].items():
            idx_data.append({
                "指数": q["name"],
                "代码": code,
                "最新价": q["price"],
                "涨跌幅": f"{q['change_pct']:+.2f}%" if q["change_pct"] else "-",
                "PE(TTM)": q["pe_ttm"],
                "PB": q["pb"],
            })
        st.dataframe(pd.DataFrame(idx_data), use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════════
# 历史趋势
# ═══════════════════════════════════════════════════════════

st.divider()
st.subheader("📈 历史趋势")

records = load_records()
if records:
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    # M 值趋势
    fig_trend = go.Figure()
    fig_trend.add_trace(go.Scatter(
        x=df["date"], y=df["M"], mode="lines+markers",
        line=dict(color="#3b82f6", width=2),
        marker=dict(size=8, color=df["M"].apply(
            lambda m: "#22c55e" if m >= 15 else ("#ef4444" if m <= -15 else "#eab308")
        )),
        name="M 值",
        hovertemplate="%{x|%Y-%m-%d}<br>M=%{y:.1f}<extra></extra>"
    ))

    # 添加区域着色
    fig_trend.add_hrect(y0=50, y1=100, fillcolor="rgba(34,197,94,0.08)", line_width=0)
    fig_trend.add_hrect(y0=15, y1=50, fillcolor="rgba(132,204,22,0.05)", line_width=0)
    fig_trend.add_hrect(y0=-15, y1=15, fillcolor="rgba(234,179,8,0.05)", line_width=0)
    fig_trend.add_hrect(y0=-50, y1=-15, fillcolor="rgba(249,115,22,0.05)", line_width=0)
    fig_trend.add_hrect(y0=-100, y1=-50, fillcolor="rgba(239,68,68,0.08)", line_width=0)

    fig_trend.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.3)
    fig_trend.update_layout(
        height=350,
        margin=dict(t=20, b=10, l=20, r=20),
        yaxis=dict(range=[-100, 100], title="M 值"),
        xaxis=dict(title=""),
        hovermode="x unified",
    )
    st.plotly_chart(fig_trend, use_container_width=True)

    # 八维雷达
    if len(df) >= 1:
        latest = df.iloc[-1]
        dims = list(WEIGHTS.keys())
        dim_scores = [latest["scores"].get(d, {}).get("score", 0) for d in dims]

        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(
            r=dim_scores + [dim_scores[0]],
            theta=dims + [dims[0]],
            fill='toself',
            fillcolor='rgba(59,130,246,0.2)',
            line=dict(color='#3b82f6', width=2),
            name='当前得分',
        ))
        fig_radar.update_layout(
            polar=dict(
                radialaxis=dict(range=[-2, 2], tickvals=[-2, -1, 0, 1, 2]),
            ),
            height=350,
            margin=dict(t=30, b=10, l=40, r=40),
        )
        st.plotly_chart(fig_radar, use_container_width=True)

    # 历史表
    with st.expander("📜 历史记录明细", expanded=False):
        display_df = df[["date", "M", "state"]].copy()
        display_df["M"] = display_df["M"].round(1)
        for dim in MANUAL_DIMS:
            display_df[dim] = df["scores"].apply(
                lambda s, d=dim: s.get(d, {}).get("score", 0)
            )
        st.dataframe(
            display_df.sort_values("date", ascending=False),
            use_container_width=True, hide_index=True
        )
else:
    st.info("还没有历史记录，点击「运行分析」开始积累数据。")

# ═══════════════════════════════════════════════════════════
# 底部
# ═══════════════════════════════════════════════════════════

st.divider()
st.caption(
    "数据来源：腾讯财经、东方财富  |  "
    "基于《李大霄投资战略》八维框架  |  "
    "仅用于研究，不构成投资建议"
)
