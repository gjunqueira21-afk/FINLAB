"""
EPS VALUE TERMINAL v2
Tema: Midnight Blue — Alta legibilidade, profissional (sem laranja)

Baseado em pesquisa de UX: TradingView dark mode, Bloomberg acessível,
WCAG 2.2 contrast ratios. Fonte: Inter/Segoe UI com figuras tabulares.

Abas:
  VISÃO GERAL · HISTÓRICO · DEMONSTRATIVOS · SAÚDE FINANCEIRA · VALUATION · MACRO BRASIL

Uso:
    cd valuation_cvm
    streamlit run dashboard.py
"""

import re
import sys
import unicodedata
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.brapi_client import BrapiClient
from src.company_mapper import filter_company_by_name_or_cvm, load_company_registry
from src.config import DEMONSTRATIVOS, TIPOS_DOC, get_processed_path
from src.financial_statements import build_company_snapshot, load_processed_statement
from src.valuation_dcf import calculate_dcf
from src.valuation_epv import calculate_epv
from src.valuation_metrics import calculate_basic_metrics

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="EPS Value Terminal",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Paleta Midnight Blue
# Referência: TradingView dark + Bloomberg acessível + WCAG AA 4.5:1
# ─────────────────────────────────────────────────────────────────────────────

C = {
    # Fundos
    "bg":      "#111827",   # fundo principal — dark navy, não preto puro
    "surf":    "#1F2937",   # cards e painéis
    "surf2":   "#273244",   # hover / destaque sutil
    "sidebar": "#0F172A",   # sidebar ligeiramente mais escura

    # Bordas
    "brd":     "#374151",   # borda sutil
    "brd2":    "#4B5563",   # borda visível

    # Texto — progressão clara → muted
    "t1":      "#F0F4F8",   # texto principal (branco suave, não puro — reduz halação)
    "t2":      "#9CA3AF",   # texto secundário
    "t3":      "#6B7280",   # texto desabilitado / rótulos

    # Cores semânticas
    "green":   "#10B981",   # positivo (Emerald 500 — CVD-friendly)
    "green_l": "#34D399",   # positivo claro
    "red":     "#EF4444",   # negativo
    "red_l":   "#FCA5A5",   # negativo suave
    "yellow":  "#FBBF24",   # atenção / neutral
    "yellow_l":"#FDE68A",   # atenção suave

    # Acento principal — azul (confiança, profissional)
    "blue":    "#3B82F6",   # Blue 500
    "blue_l":  "#93C5FD",   # Blue 300 — labels sobre fundo escuro
    "blue_d":  "#1D4ED8",   # Blue 700

    # Acentos secundários
    "cyan":    "#22D3EE",   # destaque de dados
    "purple":  "#A78BFA",   # destaque alternativo
    "teal":    "#2DD4BF",   # EV / valuation
}


def rgba(hex_c: str, alpha: float) -> str:
    h = hex_c.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {{
    background-color: {C['bg']} !important;
    color: {C['t1']} !important;
    font-family: 'Inter', 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif !important;
    font-feature-settings: "tnum" on, "lnum" on;  /* figuras tabulares para números */
}}
.stApp {{
    background:
        radial-gradient(1100px 480px at 85% -10%, {rgba(C['blue'], 0.09)} 0%, transparent 60%),
        radial-gradient(900px 420px at -5% 110%, {rgba(C['cyan'], 0.06)} 0%, transparent 55%),
        linear-gradient(180deg, #0B1120 0%, {C['bg']} 45%) !important;
}}
/* grade técnica sutil ao fundo */
.stApp::before {{
    content: "";
    position: fixed; inset: 0;
    background-image:
        linear-gradient({rgba(C['blue'], 0.028)} 1px, transparent 1px),
        linear-gradient(90deg, {rgba(C['blue'], 0.028)} 1px, transparent 1px);
    background-size: 44px 44px;
    pointer-events: none;
    z-index: 0;
}}
.main .block-container {{ padding-top: 0.5rem; padding-bottom: 2rem; max-width: 100%; }}

/* ── Scrollbar ──────────────────────────────────────────────────────────── */
::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-track {{ background: {C['bg']}; }}
::-webkit-scrollbar-thumb {{ background: {C['brd2']}; border-radius: 6px; }}
::-webkit-scrollbar-thumb:hover {{ background: {C['blue']}; }}

/* ── Animações ──────────────────────────────────────────────────────────── */
@keyframes pulse-dot {{
    0%, 100% {{ opacity: 1; box-shadow: 0 0 0 0 {rgba(C['green'], 0.55)}; }}
    50%      {{ opacity: 0.55; box-shadow: 0 0 0 6px {rgba(C['green'], 0)}; }}
}}
@keyframes scan-line {{
    0%   {{ background-position: -300% 0; }}
    100% {{ background-position: 300% 0; }}
}}
.live-dot {{
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: {C['green']};
    animation: pulse-dot 2s ease-in-out infinite;
}}

/* ── Sidebar ────────────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {{
    background-color: {C['sidebar']} !important;
    border-right: 1px solid {C['brd']} !important;
}}
section[data-testid="stSidebar"] * {{ color: {C['t2']} !important; }}
section[data-testid="stSidebar"] input {{
    background: {C['surf']} !important;
    border: 1px solid {C['brd2']} !important;
    color: {C['t1']} !important;
    border-radius: 6px !important;
    font-size: 13px !important;
}}
section[data-testid="stSidebar"] input:focus {{
    border-color: {C['blue']} !important;
    box-shadow: 0 0 0 3px {rgba(C['blue'], 0.18)} !important;
    outline: none !important;
}}

/* ── Header ─────────────────────────────────────────────────────────────── */
.trm-header {{
    position: relative;
    background: linear-gradient(135deg, rgba(11,17,32,0.92) 0%, {rgba(C['bg'], 0.85)} 100%);
    backdrop-filter: blur(8px);
    border: 1px solid {C['brd']};
    border-radius: 12px;
    padding: 14px 24px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 14px;
    overflow: hidden;
}}
/* linha de energia varrendo o topo do header */
.trm-header::after {{
    content: "";
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg,
        transparent 0%, {rgba(C['cyan'], 0.0)} 30%,
        {rgba(C['cyan'], 0.9)} 50%, {rgba(C['blue'], 0.0)} 70%, transparent 100%);
    background-size: 300% 100%;
    animation: scan-line 6s linear infinite;
}}
.trm-badge {{
    background: linear-gradient(135deg, {C['blue']} 0%, {C['blue_d']} 100%);
    color: #fff;
    font-size: 13px;
    font-weight: 800;
    padding: 6px 15px;
    border-radius: 7px;
    letter-spacing: 2px;
    text-transform: uppercase;
    white-space: nowrap;
    box-shadow: 0 0 18px {rgba(C['blue'], 0.45)}, inset 0 1px 0 {rgba('#FFFFFF', 0.18)};
}}
.trm-title {{ color: {C['t1']}; font-size: 16px; font-weight: 700; margin: 0; letter-spacing: 0.5px; }}
.trm-sub   {{ color: {C['t3']}; font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase; margin: 0; }}

/* ── Company strip ──────────────────────────────────────────────────────── */
.co-strip {{
    background: linear-gradient(135deg, {rgba(C['surf2'], 0.7)} 0%, {rgba(C['surf'], 0.9)} 100%);
    backdrop-filter: blur(8px);
    border: 1px solid {rgba(C['blue'], 0.25)};
    border-left: 4px solid {C['blue']};
    border-radius: 0 12px 12px 0;
    padding: 12px 20px;
    margin-bottom: 18px;
    display: flex;
    align-items: center;
    gap: 20px;
    box-shadow: 0 4px 24px {rgba(C['blue'], 0.08)}, inset 0 1px 0 {rgba('#FFFFFF', 0.04)};
}}
.co-name {{ color: {C['t1']}; font-size: 18px; font-weight: 800; letter-spacing: 0.3px; }}
.co-tag  {{
    background: {rgba(C['blue'], 0.12)};
    color: {C['blue_l']};
    font-size: 11px;
    font-weight: 500;
    padding: 3px 10px;
    border-radius: 99px;
    border: 1px solid {rgba(C['blue'], 0.3)};
}}

/* ── Metric cards — glass + glow ────────────────────────────────────────── */
.mc {{
    position: relative;
    background: linear-gradient(180deg, {rgba(C['surf2'], 0.55)} 0%, {rgba(C['surf'], 0.85)} 100%);
    backdrop-filter: blur(6px);
    border: 1px solid {C['brd']};
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 12px;
    min-height: 76px;
    overflow: hidden;
    transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.25s ease;
}}
/* ── Variante "hero" — cards de veredito, maiores e mais espaçados ───────── */
.mc.hero {{ padding: 18px 20px; min-height: 92px; }}
.mc.hero .mc-lbl {{ font-size: 11px; margin-bottom: 9px; }}
.mc.hero .mc-val {{ font-size: 25px; }}
.mc.hero .mc-val.nd {{ font-size: 15px; }}
/* filete de energia no topo de cada card */
.mc::before {{
    content: "";
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, transparent, {rgba(C['blue'], 0.65)}, transparent);
    opacity: 0.5;
    transition: opacity 0.25s ease;
}}
.mc:hover {{
    transform: translateY(-2px);
    border-color: {rgba(C['blue'], 0.5)};
    box-shadow: 0 8px 28px {rgba(C['blue'], 0.16)}, 0 0 0 1px {rgba(C['blue'], 0.12)};
}}
.mc:hover::before {{ opacity: 1; }}
.mc-lbl {{
    color: {C['t3']};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    margin-bottom: 7px;
}}
.mc-val {{
    font-family: 'JetBrains Mono', 'Inter', monospace;
    font-size: 19px; font-weight: 700; color: {C['t1']}; line-height: 1;
}}
.mc-val.pos  {{ color: {C['green']};  text-shadow: 0 0 16px {rgba(C['green'], 0.35)}; }}
.mc-val.neg  {{ color: {C['red']};    text-shadow: 0 0 16px {rgba(C['red'], 0.35)}; }}
.mc-val.blu  {{ color: {C['blue_l']}; text-shadow: 0 0 16px {rgba(C['blue'], 0.35)}; }}
.mc-val.yel  {{ color: {C['yellow']}; text-shadow: 0 0 16px {rgba(C['yellow'], 0.3)}; }}
.mc-val.cyan {{ color: {C['cyan']};   text-shadow: 0 0 16px {rgba(C['cyan'], 0.35)}; }}
.mc-val.neu  {{ color: {C['t2']}; }}
.mc-val.nd   {{ color: {C['t3']}; font-size: 14px; font-weight: 400; font-family: 'Inter', sans-serif; }}
.mc-sub {{ color: {C['t3']}; font-size: 11px; margin-top: 4px; }}

/* ── Section titles ─────────────────────────────────────────────────────── */
.sec {{
    position: relative;
    color: {C['t2']};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.8px;
    text-transform: uppercase;
    border-bottom: 1px solid {C['brd']};
    padding-bottom: 8px;
    padding-left: 12px;
    margin-top: 32px;
    margin-bottom: 16px;
}}
/* marcador neon à esquerda do título */
.sec::before {{
    content: "";
    position: absolute; left: 0; top: 1px; bottom: 9px;
    width: 3px; border-radius: 2px;
    background: linear-gradient(180deg, {C['cyan']}, {C['blue']});
    box-shadow: 0 0 8px {rgba(C['cyan'], 0.6)};
}}
/* selo qualitativo (Barato / Justo / Caro) ao lado de um título .sec */
.verdict-badge {{
    display: inline-block;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
    padding: 3px 12px;
    border-radius: 99px;
    margin-left: 10px;
    vertical-align: middle;
    text-transform: uppercase;
}}
.verdict-badge.pos {{ background: {rgba(C['green'], 0.15)};  color: {C['green_l']}; border: 1px solid {rgba(C['green'], 0.4)}; }}
.verdict-badge.neg {{ background: {rgba(C['red'], 0.15)};    color: {C['red_l']};   border: 1px solid {rgba(C['red'], 0.4)}; }}
.verdict-badge.yel {{ background: {rgba(C['yellow'], 0.15)}; color: {C['yellow_l']};border: 1px solid {rgba(C['yellow'], 0.4)}; }}
.verdict-badge.nd  {{ background: {rgba(C['t3'], 0.15)};     color: {C['t2']};      border: 1px solid {C['brd2']}; }}

/* ── Alert boxes ────────────────────────────────────────────────────────── */
.box-info {{
    background: {rgba(C['blue'], 0.07)};
    border: 1px solid {rgba(C['blue'], 0.25)};
    border-radius: 8px;
    padding: 11px 16px;
    margin: 8px 0;
    font-size: 13px;
    color: {C['t2']};
    line-height: 1.7;
}}
.box-warn {{
    background: {rgba(C['yellow'], 0.07)};
    border: 1px solid {rgba(C['yellow'], 0.3)};
    border-radius: 8px;
    padding: 11px 16px;
    margin: 8px 0;
    font-size: 13px;
    color: {C['t2']};
    line-height: 1.7;
}}
.box-ok {{
    background: {rgba(C['green'], 0.07)};
    border: 1px solid {rgba(C['green'], 0.3)};
    border-radius: 8px;
    padding: 11px 16px;
    margin: 8px 0;
    font-size: 13px;
    color: {C['t2']};
    line-height: 1.7;
}}
.box-err {{
    background: {rgba(C['red'], 0.07)};
    border: 1px solid {rgba(C['red'], 0.3)};
    border-radius: 8px;
    padding: 11px 16px;
    margin: 8px 0;
    font-size: 13px;
    color: {C['t2']};
    line-height: 1.7;
}}

/* ── Tabs ───────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
    background: {C['bg']} !important;
    border-bottom: 1px solid {C['brd']} !important;
    gap: 0 !important;
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent !important;
    color: {C['t3']} !important;
    font-size: 10px !important;
    font-weight: 600 !important;
    letter-spacing: 1.2px !important;
    text-transform: uppercase !important;
    padding: 10px 18px !important;
    border-bottom: 2px solid transparent !important;
    transition: color 0.15s !important;
}}
.stTabs [data-baseweb="tab"]:hover {{
    color: {C['t2']} !important;
    background: {rgba(C['blue'], 0.04)} !important;
}}
.stTabs [aria-selected="true"] {{
    color: {C['cyan']} !important;
    border-bottom: 2px solid {C['cyan']} !important;
    background: linear-gradient(180deg, {rgba(C['cyan'], 0.10)} 0%, transparent 100%) !important;
    text-shadow: 0 0 14px {rgba(C['cyan'], 0.55)};
}}

/* ── DataFrames ─────────────────────────────────────────────────────────── */
.stDataFrame {{ background: {C['surf']} !important; border-radius: 8px; overflow: hidden; }}
.stDataFrame [data-testid="stDataFrameGlideDataEditor"] {{ background: {C['surf']} !important; }}
thead tr th {{
    background: {C['surf2']} !important;
    color: {C['t2']} !important;
    font-size: 10px !important;
    font-weight: 600 !important;
    letter-spacing: 1px !important;
    text-transform: uppercase !important;
    border-bottom: 1px solid {C['brd2']} !important;
    padding: 10px 12px !important;
}}
tbody tr td {{
    background: {C['surf']} !important;
    color: {C['t1']} !important;
    font-size: 12px !important;
    border-bottom: 1px solid {C['brd']} !important;
    padding: 9px 12px !important;
}}
tbody tr:hover td {{ background: {C['surf2']} !important; }}

/* ── Inputs ─────────────────────────────────────────────────────────────── */
.stTextInput input, .stNumberInput input {{
    background: {C['surf']} !important;
    border: 1px solid {C['brd2']} !important;
    color: {C['t1']} !important;
    border-radius: 6px !important;
    font-size: 13px !important;
}}
.stTextInput input:focus, .stNumberInput input:focus {{
    border-color: {C['blue']} !important;
    box-shadow: 0 0 0 3px {rgba(C['blue'], 0.15)} !important;
}}
.stSelectbox > div > div {{
    background: {C['surf']} !important;
    border: 1px solid {C['brd2']} !important;
    color: {C['t1']} !important;
    border-radius: 6px !important;
}}

/* ── Sliders ────────────────────────────────────────────────────────────── */
.stSlider [data-baseweb="slider"] > div:first-child {{
    background: {C['brd2']} !important;
}}
[data-testid="stThumbValue"] {{ color: {C['t2']} !important; font-size: 11px !important; }}

/* ── Buttons ────────────────────────────────────────────────────────────── */
.stButton > button {{
    background: {C['blue']} !important;
    color: #fff !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    font-size: 12px !important;
    letter-spacing: 0.5px !important;
    padding: 8px 22px !important;
    transition: background 0.15s !important;
}}
.stButton > button:hover {{ background: {C['blue_l']} !important; color: {C['bg']} !important; }}

/* ── Radio / Checkbox ───────────────────────────────────────────────────── */
[data-testid="stRadio"] label, [data-testid="stCheckbox"] label {{
    color: {C['t2']} !important;
    font-size: 13px !important;
}}

/* ── Expander ───────────────────────────────────────────────────────────── */
.streamlit-expanderHeader {{
    background: {C['surf']} !important;
    color: {C['t2']} !important;
    border: 1px solid {C['brd']} !important;
    border-radius: 6px !important;
    font-size: 12px !important;
    font-weight: 600 !important;
}}
[data-testid="stExpander"] {{ margin: 14px 0 20px 0 !important; }}

/* ── Sub-abas internas (ex.: Valuation) — leve recuo visual ───────────────── */
.stTabs .stTabs [data-baseweb="tab-list"] {{
    border-bottom: 1px solid {C['brd']} !important;
    margin-top: 4px !important;
}}
.stTabs .stTabs [data-baseweb="tab-panel"] {{ padding-top: 18px !important; }}

/* ── Health score bars ──────────────────────────────────────────────────── */
.score-row {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
    padding: 8px 12px;
    background: {C['surf']};
    border-radius: 6px;
    border: 1px solid {C['brd']};
}}
.score-lbl {{ color: {C['t3']}; font-size: 11px; width: 180px; flex-shrink: 0; }}
.score-bar-bg {{
    flex: 1;
    background: {C['brd2']};
    border-radius: 4px;
    height: 7px;
    overflow: hidden;
}}
.score-bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.4s; }}
.score-val {{ color: {C['t1']}; font-size: 13px; font-weight: 600; width: 70px; text-align: right; }}
.score-status {{ font-size: 11px; width: 60px; text-align: right; }}
.s-ok   {{ color: {C['green']}; }}
.s-warn {{ color: {C['yellow']}; }}
.s-err  {{ color: {C['red']}; }}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Plotly layout base
# ─────────────────────────────────────────────────────────────────────────────

_PL = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor=rgba(C["surf"], 0.55),
    font=dict(family="Inter, Segoe UI, sans-serif", color=C["t2"], size=11),
    title_font=dict(color=C["t1"], size=13, family="Inter, Segoe UI, sans-serif"),
    xaxis=dict(gridcolor=C["brd"], linecolor=C["brd2"],
               tickfont=dict(color=C["t3"], size=10), showgrid=True, zeroline=False),
    yaxis=dict(gridcolor=C["brd"], linecolor=C["brd2"],
               tickfont=dict(color=C["t3"], size=10), showgrid=True, zeroline=False),
    legend=dict(bgcolor=C["surf2"], bordercolor=C["brd"], borderwidth=1,
                font=dict(color=C["t2"], size=10)),
    margin=dict(l=55, r=20, t=45, b=45),
    hovermode="x unified",
    hoverlabel=dict(bgcolor=C["surf2"], font=dict(color=C["t1"], size=12), bordercolor=C["brd2"]),
)

_SER = [C["blue"], C["green"], C["red"], C["cyan"], C["purple"], C["yellow"], C["teal"]]


def _bar(years, values, name="", color=None, title="", sfx="B"):
    color = color or C["blue"]
    vals = [v if v is not None else 0 for v in values]
    bar_c = [C["red"] if v < 0 else color for v in vals]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=years, y=vals, name=name, marker_color=bar_c,
        text=[f"{v:.1f}{sfx}" for v in vals],
        textposition="outside", textfont=dict(color=C["t3"], size=9),
    ))
    fig.update_layout(**_PL, title=title, showlegend=False)
    return fig


def _lines(years, series, title=""):
    """series: [(name, values, color), ...]"""
    fig = go.Figure()
    for name, vals, col in series:
        fig.add_trace(go.Scatter(
            x=years, y=[v if v is not None else None for v in vals],
            name=name, mode="lines+markers",
            line=dict(color=col, width=2.5),
            marker=dict(color=col, size=5, symbol="circle"),
            connectgaps=False,
        ))
    fig.update_layout(**_PL, title=title)
    return fig


def _gauge(value, max_val, title, invert=False, show_number=True):
    """Gauge: invert=True → baixo é bom (dívida), False → alto é bom (liquidez).

    show_number=False oculta o número embutido do Plotly (que tende a ficar
    descentralizado); nesse caso o valor é renderizado via _trend_block logo
    abaixo, perfeitamente centralizado.
    """
    val = min(max(value or 0, 0), max_val)
    thirds = max_val / 3

    if invert:
        # baixo é verde, alto é vermelho
        steps = [
            dict(range=[0, thirds],       color=rgba(C["green"], 0.15)),
            dict(range=[thirds, 2*thirds], color=rgba(C["yellow"], 0.12)),
            dict(range=[2*thirds, max_val],color=rgba(C["red"], 0.15)),
        ]
    else:
        # alto é verde, baixo é vermelho
        steps = [
            dict(range=[0, thirds],        color=rgba(C["red"], 0.15)),
            dict(range=[thirds, 2*thirds],  color=rgba(C["yellow"], 0.12)),
            dict(range=[2*thirds, max_val], color=rgba(C["green"], 0.15)),
        ]

    bar_color = C["green"] if (val < thirds and invert) or (val > 2*thirds and not invert) \
               else C["yellow"] if val < 2*thirds \
               else C["red"]

    ind = dict(
        mode="gauge+number" if show_number else "gauge",
        value=val,
        title={"text": title, "font": {"color": C["t2"], "size": 11, "family": "Inter"},
               "align": "center"},
        gauge={
            "axis": {"range": [0, max_val], "tickcolor": C["t3"],
                     "tickfont": {"color": C["t3"], "size": 9}},
            "bar": {"color": bar_color, "thickness": 0.28},
            "bgcolor": C["surf2"],
            "borderwidth": 1,
            "bordercolor": C["brd"],
            "steps": steps,
        },
    )
    if show_number:
        ind["number"] = {"font": {"color": C["t1"], "size": 22}, "suffix": "x"}
    fig = go.Figure(go.Indicator(**ind))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=185 if not show_number else 200,
        margin=dict(l=15, r=15, t=40, b=10),
        font=dict(color=C["t2"]),
    )
    return fig


def _trend_block(value_str, color, values, lower_is_better, periods=None):
    """
    Renderiza, centralizado abaixo do gauge:
      • o valor do múltiplo em destaque (grande, mono, centralizado)
      • até 5 bolinhas de tendência período-a-período
        verde = melhorou · amarelo = estável (±2%) · vermelho = piorou

    `lower_is_better=True` → cair é bom (alavancagem).
    """
    pairs = [(p, v) for p, v in zip(periods or list(range(len(values))), values)
             if v is not None]
    dots_html = ""
    legenda = ""
    if len(pairs) >= 2:
        pairs = pairs[-6:]  # 6 pontos → até 5 comparações
        chips = []
        for i in range(1, len(pairs)):
            per, cur = pairs[i]
            prev = pairs[i - 1][1]
            if prev == 0:
                col, tip = C["t3"], "n/d"
            else:
                chg = (cur - prev) / abs(prev)
                if abs(chg) < 0.02:
                    col, tip = C["yellow"], "estável"
                elif (chg < 0) == lower_is_better:
                    col, tip = C["green"], "melhorou"
                else:
                    col, tip = C["red"], "piorou"
            chips.append(
                f'<span title="{per}: {cur:.2f}× · {tip}" '
                f'style="color:{col};font-size:17px;margin:0 4px;'
                f'text-shadow:0 0 7px {col}99">●</span>'
            )
        dots_html = "".join(chips)
        legenda = (f'<div style="font-size:9px;color:{C["t3"]};letter-spacing:1.4px;'
                   f'margin-top:3px">TENDÊNCIA · ÚLTIMOS {len(chips)} PERÍODOS</div>')
    else:
        dots_html = f'<span style="color:{C["t3"]};font-size:11px">histórico insuficiente</span>'

    return (
        f'<div style="text-align:center;margin-top:-26px">'
        f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:30px;'
        f'font-weight:700;color:{color};line-height:1;'
        f'text-shadow:0 0 14px {color}66">{value_str}</div>'
        f'{legenda}'
        f'<div style="margin-top:4px">{dots_html}</div>'
        f'</div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Formatação
# ─────────────────────────────────────────────────────────────────────────────

def _f(v):
    if v is None: return None
    try:
        x = float(v); return None if x != x else x
    except: return None


def fbrl(v, scale=1e6, sfx="M"):
    x = _f(v)
    return "–" if x is None else f"R$ {x/scale:,.0f}{sfx}"


def fpct(v, d=2):
    x = _f(v)
    return "–" if x is None else f"{x*100:.{d}f}%"


def fmult(v, d=1):
    x = _f(v)
    return "–" if x is None else f"{x:.{d}f}×"


def fnum(v, d=2, sfx=""):
    x = _f(v)
    return "–" if x is None else f"{x:,.{d}f}{sfx}"


def _cls(v, pos_good=True):
    x = _f(v)
    if x is None: return "nd"
    if x > 0: return "pos" if pos_good else "neg"
    if x < 0: return "neg" if pos_good else "pos"
    return "blu"


def _mult_cls(v, good, warn):
    """Classe de cor p/ múltiplos de valuation (menor = mais barato = verde).
    v < good → pos | v < warn → yel | senão neg | None/≤0 → nd."""
    x = _f(v)
    if x is None or x <= 0: return "nd"
    return "pos" if x < good else "yel" if x < warn else "neg"


def _selo_valuation(upside_pct):
    """Selo qualitativo Barato/Justo/Caro a partir do upside (%) vs. preço de mercado."""
    if upside_pct is None:
        return "–", "nd"
    if upside_pct > 15:
        return "BARATO", "pos"
    if upside_pct < -15:
        return "CARO", "neg"
    return "JUSTO", "yel"


# ─────────────────────────────────────────────────────────────────────────────
# UI helpers
# ─────────────────────────────────────────────────────────────────────────────

def mc(label, val, cls="", sub=""):
    tokens = cls.split()
    card_cls = "mc hero" if "hero" in tokens else "mc"
    val_cls = " ".join(t for t in tokens if t != "hero")
    sub_html = f'<div class="mc-sub">{sub}</div>' if sub else ""
    return f"""<div class="{card_cls}">
  <div class="mc-lbl">{label}</div>
  <div class="mc-val {val_cls}">{val}</div>
  {sub_html}
</div>"""


def sec(title):
    st.markdown(f'<div class="sec">{title}</div>', unsafe_allow_html=True)


def box(text, kind="info"):
    st.markdown(f'<div class="box-{kind}">{text}</div>', unsafe_allow_html=True)


def score_row(label, value_str, pct_fill, color, status_str):
    """Linha de saúde financeira com barra de progresso."""
    st.markdown(f"""
<div class="score-row">
  <div class="score-lbl">{label}</div>
  <div class="score-bar-bg">
    <div class="score-bar-fill" style="width:{min(pct_fill,100):.0f}%;background:{color}"></div>
  </div>
  <div class="score-val">{value_str}</div>
  <div class="score-status s-{'ok' if color==C['green'] else 'warn' if color==C['yellow'] else 'err'}">{status_str}</div>
</div>""", unsafe_allow_html=True)


def header():
    st.markdown(f"""
<div class="trm-header">
  <div class="trm-badge">EPS</div>
  <div>
    <div class="trm-title">Value Terminal</div>
    <div class="trm-sub">Análise Fundamentalista · CVM Open Data · B3 · Brasil · {datetime.now().strftime('%d/%m/%Y')}</div>
  </div>
  <div style="margin-left:auto;display:flex;align-items:center;gap:8px">
    <span class="live-dot"></span>
    <span style="color:{C['t3']};font-size:10px;letter-spacing:2px;font-weight:600">LIVE</span>
  </div>
</div>""", unsafe_allow_html=True)


def co_strip(name, cd_cvm, tipo_doc, setor="", brapi_data=None, ticker=""):
    tags = "".join([
        f'<span class="co-tag">CD_CVM {cd_cvm}</span>',
        f'<span class="co-tag">{tipo_doc}</span>',
        f'<span class="co-tag">{setor}</span>' if setor else "",
    ])
    price_html = ""
    if brapi_data:
        preco = brapi_data.get("regularMarketPrice", 0)
        var_d = brapi_data.get("regularMarketChangePercent", 0)
        cor_v = C["green"] if var_d >= 0 else C["red"]
        sinal = "▲" if var_d >= 0 else "▼"
        price_html = (
            f'<div style="margin-left:auto;text-align:right;padding-left:24px">'
            f'<div style="color:{C["t3"]};font-size:10px;letter-spacing:1.5px;margin-bottom:2px">'
            f'<span class="live-dot" style="width:6px;height:6px;margin-right:6px"></span>'
            f'{ticker.upper()}</div>'
            f'<div style="color:{C["t1"]};font-size:26px;font-weight:700;line-height:1;'
            f'font-family:\'JetBrains Mono\',monospace;'
            f'text-shadow:0 0 22px {rgba(cor_v, 0.4)}">'
            f'R$ {preco:.2f}</div>'
            f'<div style="color:{cor_v};font-size:12px;margin-top:4px;font-family:\'JetBrains Mono\',monospace">'
            f'{sinal} {abs(var_d):.2f}% hoje</div>'
            f'</div>'
        )
    st.markdown(f"""
<div class="co-strip" style="display:flex;align-items:center;justify-content:space-between">
  <div>
    <div class="co-name">{name}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:4px">{tags}</div>
  </div>
  {price_html}
</div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Cache / data loading
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=180)
def _registry():
    return load_company_registry()


@st.cache_data(ttl=120)
def _avail():
    return {
        f"{t}_{s}": get_processed_path(s.lower(), t.lower(), "parquet").exists()
        for t in TIPOS_DOC for s in DEMONSTRATIVOS
    }


@st.cache_data(ttl=60)
def _snap(cd, tipo):
    return build_company_snapshot(cd, tipo_doc=tipo)


@st.cache_data(ttl=3600, show_spinner=False)
def _capital_social() -> pd.DataFrame:
    """Carrega capital_social.csv — total de ações por empresa (Capital Emitido)."""
    p = Path(__file__).resolve().parent / "data" / "processed" / "capital_social.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, sep=";", encoding="latin1")
    df = df[df["Tipo_Capital"] == "Capital Emitido"].copy()
    return df[["CNPJ_Companhia", "Quantidade_Total_Acoes",
               "Quantidade_Acoes_Ordinarias", "Quantidade_Acoes_Preferenciais"]].reset_index(drop=True)


def _shares_for_cvm(cd_cvm: str) -> Optional[float]:
    """Retorna total de ações em milhões para um CD_CVM (via capital_social.csv)."""
    try:
        cad = _registry()
        if cad.empty:
            return None
        row = cad[cad["CD_CVM"].astype(str).str.strip() == str(cd_cvm).strip()]
        if row.empty:
            return None
        cnpj = row.iloc[0]["CNPJ_CIA"]
        cap = _capital_social()
        if cap.empty:
            return None
        match = cap[cap["CNPJ_Companhia"] == cnpj]
        if match.empty:
            return None
        total = float(match.iloc[0]["Quantidade_Total_Acoes"])
        return total / 1e6
    except Exception:
        return None


@st.cache_data(ttl=60)
def _stmt(stmt, tipo):
    return load_processed_statement(stmt, tipo)


@st.cache_data(ttl=120)
def _is_financial(cd, tipo) -> bool:
    """Detecta empresa do setor financeiro (banco/seguradora) pela estrutura
    contábil — não pelo nome, pois holdings de seguro usam o plano padrão.

    Sinais: DRE 3.01 = 'Receitas de Intermediação Financeira' (bancos) ou
    ausência das contas de dívida padrão 2.01.04 e 2.02.01 no passivo.
    """
    dre = _stmt("DRE", tipo)
    if not dre.empty and "CD_CVM" in dre.columns:
        s = dre[dre["CD_CVM"].astype(str).str.strip() == str(cd).strip()]
        if not s.empty and "ANO_REFER" in s.columns:
            s = s[s["ANO_REFER"] == s["ANO_REFER"].max()]
            r301 = s[s["CD_CONTA"].astype(str).str.strip() == "3.01"]
            if not r301.empty:
                ds = str(r301["DS_CONTA"].iloc[0]).upper()
                if "INTERMEDIAÇÃO FINANCEIRA" in ds or "INTERMEDIACAO FINANCEIRA" in ds:
                    return True
                if "OPERAÇÕES DE SEGUROS" in ds or "PRÊMIOS" in ds:
                    return True
    return False


@st.cache_data(ttl=60)
def _ext_snap(cd, tipo):
    """Snapshot estendido com campos adicionais para saúde financeira."""
    snap = _snap(cd, tipo)

    # Preserva o EBIT original da CVM (3.05) ANTES de qualquer reconciliação
    # com a BRAPI poder sobrescrever snap_ext["ebit"]/m["ebit"]. É usado para
    # montar o EBITDA "EBIT(CVM) + D&A(CVM)" sem misturar fontes diferentes
    # (ver `_get_ebitda`).
    snap["ebit_cvm"] = snap.get("ebit")

    dre = _stmt("DRE", tipo)
    bpa = _stmt("BPA", tipo)
    bpp = _stmt("BPP", tipo)
    dfc = _stmt("DFC_MI", tipo)

    def pick(df, codes, *kws):
        """Extrai conta no exercício mais recente: CD_CONTA exato > keyword."""
        if df.empty or "CD_CVM" not in df.columns: return None
        s = df[df["CD_CVM"].astype(str).str.strip() == cd].copy()
        if s.empty: return None
        vc = "VL_CONTA_AJUSTADO" if "VL_CONTA_AJUSTADO" in s.columns else "VL_CONTA"
        # Filtra o exercício mais recente (os processados têm ANO_REFER, não DT_REFER)
        if "ANO_REFER" in s.columns and s["ANO_REFER"].notna().any():
            s = s[s["ANO_REFER"] == s["ANO_REFER"].max()]
        elif "DT_FIM_EXERC" in s.columns and s["DT_FIM_EXERC"].notna().any():
            s = s[s["DT_FIM_EXERC"] == s["DT_FIM_EXERC"].max()]
        if vc not in s.columns: return None
        # 1) CD_CONTA exato (Plano de Contas Padronizado CVM)
        if codes and "CD_CONTA" in s.columns:
            cc = s["CD_CONTA"].astype(str).str.strip()
            for code in codes:
                hit = s[cc == code]
                v = hit[vc].dropna()
                if not v.empty: return float(v.iloc[0])
        # 2) Fallback por palavra-chave
        if "DS_CONTA" in s.columns:
            ds = s["DS_CONTA"].fillna("").str.upper()
            for kw in kws:
                m = ds.str.contains(kw.upper(), regex=False, na=False)
                if m.any():
                    s2 = s[m]
                    if "CD_CONTA" in s2.columns:
                        s2 = s2.assign(_l=s2["CD_CONTA"].astype(str).str.count(r"\.")
                                       ).sort_values("_l")
                    v = s2[vc].dropna()
                    if not v.empty: return float(v.iloc[0])
        return None

    snap["ativo_circulante"]  = pick(bpa, ["1.01"], "ativo circulante")
    snap["passivo_circulante"]= pick(bpp, ["2.01"], "passivo circulante")
    snap["estoques"]          = pick(bpa, ["1.01.04"], "estoques", "inventário")
    snap["desp_financeiras"]  = pick(dre, ["3.06.02", "3.06"], "despesas financeiras",
                                     "resultado financeiro")
    # D&A: keyword "deprecia" evita casar "Amortizações de financiamentos" (6.03.xx)
    snap["depreciacao"]       = pick(dfc, [], "deprecia")
    snap["divida_cp"]         = pick(bpp, ["2.01.04"])
    snap["divida_lp"]         = pick(bpp, ["2.02.01"])
    return snap


@st.cache_data(ttl=60)
def _history(cd, tipo):
    """Série histórica anual de métricas principais."""
    dre = _stmt("DRE", tipo)
    bpa = _stmt("BPA", tipo)
    bpp = _stmt("BPP", tipo)
    dfc = _stmt("DFC_MI", tipo)

    def flt(df):
        if df.empty or "CD_CVM" not in df.columns: return pd.DataFrame()
        s = df[df["CD_CVM"].astype(str).str.strip() == cd].copy()
        if not s.empty and "ANO_REFER" not in s.columns and "DT_FIM_EXERC" in s.columns:
            s["ANO_REFER"] = pd.to_datetime(s["DT_FIM_EXERC"], errors="coerce").dt.year
        return s

    d, b, p, f = flt(dre), flt(bpa), flt(bpp), flt(dfc)
    if d.empty or "ANO_REFER" not in d.columns: return pd.DataFrame()
    years = sorted(d["ANO_REFER"].dropna().unique())

    def pick(df, yr, codes, *kws):
        """Extrai conta de um ano: CD_CONTA exato > keyword."""
        if df.empty or "ANO_REFER" not in df.columns: return None
        s = df[df["ANO_REFER"] == yr]
        if s.empty: return None
        vc = "VL_CONTA_AJUSTADO" if "VL_CONTA_AJUSTADO" in s.columns else "VL_CONTA"
        if vc not in s.columns: return None
        # 1) CD_CONTA exato
        if codes and "CD_CONTA" in s.columns:
            cc = s["CD_CONTA"].astype(str).str.strip()
            for code in codes:
                hit = s[cc == code]
                v = hit[vc].dropna()
                if not v.empty: return float(v.iloc[0])
        # 2) Fallback por palavra-chave
        if "DS_CONTA" in s.columns:
            ds = s["DS_CONTA"].fillna("").str.upper()
            for kw in kws:
                m = ds.str.contains(kw.upper(), regex=False, na=False)
                if m.any():
                    s2 = s[m]
                    if "CD_CONTA" in s2.columns:
                        s2 = s2.assign(_l=s2["CD_CONTA"].astype(str).str.count(r"\.")
                                       ).sort_values("_l")
                    v = s2[vc].dropna()
                    if not v.empty: return float(v.iloc[0])
        return None

    rows = []
    for y in years:
        da = pick(f, y, [], "deprecia")
        eb = pick(d, y, ["3.05"], "resultado antes do resultado financeiro", "resultado operacional")
        ebitda = (eb + abs(da)) if eb is not None and da is not None else None
        rows.append({
            "ano":         int(y),
            "receita":     pick(d, y, ["3.01"], "receita de venda de bens", "receita líquida"),
            "lucro_bruto": pick(d, y, ["3.03"], "resultado bruto", "lucro bruto"),
            "ebit":        eb,
            "ebitda":      ebitda,
            "lucro_liq":   pick(d, y, ["3.11", "3.09"], "lucro/prejuízo consolidado do período", "lucro/prejuízo do período", "lucro líquido"),
            "fcop":        pick(f, y, ["6.01"], "caixa líquido atividades operacionais", "caixa líquido nas atividades operacionais"),
            "capex":       pick(f, y, ["6.02.01"], "aquisições de ativos imobilizados e intangíveis"),
            "depamort":    da,
            "ativo":       pick(b, y, ["1"], "ativo total"),
            "ativo_circ":  pick(b, y, ["1.01"], "ativo circulante"),
            "passivo_circ":pick(p, y, ["2.01"], "passivo circulante"),
            "caixa":       pick(b, y, ["1.01.01"], "caixa e equivalentes de caixa", "caixa e equivalentes"),
            "pl":          pick(p, y, None, "patrimônio líquido consolidado", "patrimônio líquido"),
            "divida_cp":   pick(p, y, ["2.01.04"]),
            "divida_lp":   pick(p, y, ["2.02.01"]),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=60, show_spinner=False)
def _brapi_quote(ticker: str) -> Optional[Dict]:
    """Cotação BRAPI em tempo real (cache curto de 60s)."""
    client = BrapiClient()
    return client.get_quote(ticker)


@st.cache_data(ttl=900, show_spinner=False)
def _brapi_fundamentals(ticker: str) -> Optional[Dict]:
    """Fundamentos completos BRAPI (módulos) — cache de 15 min."""
    if not ticker:
        return None
    try:
        return BrapiClient().get_fundamentals(ticker)
    except Exception:
        return None


def _brapi_beta(fund: Optional[Dict]) -> Optional[float]:
    """Extrai o beta dos módulos defaultKeyStatistics / financialData."""
    if not fund:
        return None
    for mod in ("defaultKeyStatistics", "financialData"):
        d = fund.get(mod) or {}
        b = _f(d.get("beta"))
        if b is not None:
            return b
    return None


def _brapi_trailing_dy(fund: Optional[Dict], preco: Optional[float]) -> Optional[float]:
    """Dividend Yield 12m (%) calculado dos proventos pagos (dividendsData).

    O quote básico da BRAPI não traz DY pronto — calculamos a partir dos
    proventos em dinheiro efetivamente pagos nos últimos 12 meses ÷ preço.
    """
    if not fund or not preco or preco <= 0:
        return None
    divs = ((fund.get("dividendsData") or {}).get("cashDividends")) or []
    if not isinstance(divs, list):
        return None
    now = pd.Timestamp.now()
    cutoff = now - pd.Timedelta(days=365)
    total, found = 0.0, False
    for d in divs:
        if not isinstance(d, dict):
            continue
        dt = pd.to_datetime(d.get("paymentDate"), errors="coerce")
        r = _f(d.get("rate"))
        if dt is None or pd.isna(dt) or not r:
            continue
        if dt.tzinfo is not None:
            dt = dt.tz_localize(None)
        if cutoff <= dt <= now:
            total += r
            found = True
    return (total / preco) * 100 if found else None


def _brapi_consensus(fund: Optional[Dict]) -> Dict:
    """Preço-alvo e recomendação de analistas (módulo financialData)."""
    fd = (fund or {}).get("financialData") or {}
    return {
        "target_mean": _f(fd.get("targetMeanPrice")),
        "target_high": _f(fd.get("targetHighPrice")),
        "target_low":  _f(fd.get("targetLowPrice")),
        "rec":         fd.get("recommendationKey"),
        "n":           _f(fd.get("numberOfAnalystOpinions")),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Reconciliação CVM × BRAPI
#
# Política (definida pelo usuário): a BRAPI.dev é a fonte de verdade.
#   • Campo CVM ausente  → preenche com o valor da BRAPI.
#   • Campos divergem    → usa o valor da BRAPI ("se não bater, usa o deles").
#   • Campos conferem    → mantém (origem registrada como "confere").
# Toda substituição/preenchimento fica VISÍVEL (filosofia do projeto: sem dados
# ocultos), exibida num painel auditável na aba Visão Geral.
# ─────────────────────────────────────────────────────────────────────────────

# Tolerância relativa para considerar que CVM e BRAPI "batem".
_RECON_TOL = 0.01


def _bnum(d: Optional[Dict], *keys) -> Optional[float]:
    """Extrai número de um dict BRAPI, tolerando formato Yahoo {'raw': x}."""
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = d.get(k)
        if isinstance(v, dict):
            v = v.get("raw", v.get("value"))
        v = _f(v)
        if v is not None:
            return v
    return None


def _brapi_stmt_latest(fund: Optional[Dict], module: str) -> Dict:
    """Demonstração anual mais recente de um módulo *History da BRAPI."""
    if not fund:
        return {}
    block = fund.get(module) or {}
    # BRAPI/Yahoo aninham a lista em chaves como 'incomeStatementHistory'
    rows = None
    if isinstance(block, dict):
        for v in block.values():
            if isinstance(v, list):
                rows = v
                break
    elif isinstance(block, list):
        rows = block
    if not rows:
        return {}

    def _end(r):
        e = r.get("endDate")
        if isinstance(e, dict):
            e = e.get("raw") or e.get("fmt")
        return str(e or "")

    try:
        rows = sorted(rows, key=_end, reverse=True)
    except Exception:
        pass
    return rows[0] if isinstance(rows[0], dict) else {}


def _brapi_figures(fund: Optional[Dict]) -> Dict[str, Optional[float]]:
    """Mapeia os números da BRAPI para os mesmos campos usados a partir da CVM.

    Prioriza `financialData` (dados consolidados/TTM) e usa o histórico de DRE
    como complemento. Todos em reais absolutos (mesma escala da CVM ajustada).
    """
    fd  = (fund or {}).get("financialData") or {}
    inc = _brapi_stmt_latest(fund, "incomeStatementHistory")
    bal = _brapi_stmt_latest(fund, "balanceSheetHistory")
    cfs = _brapi_stmt_latest(fund, "cashflowHistory")

    receita = _bnum(fd, "totalRevenue") or _bnum(inc, "totalRevenue")
    lucro_b = _bnum(fd, "grossProfits") or _bnum(inc, "grossProfit")
    ebit    = _bnum(inc, "ebit", "operatingIncome")
    lucro_l = _bnum(inc, "netIncome") or _bnum(cfs, "netIncome")
    ebitda  = _bnum(fd, "ebitda")
    div_br  = _bnum(fd, "totalDebt") or _bnum(bal, "totalDebt")
    caixa   = _bnum(fd, "totalCash") or _bnum(bal, "cash", "cashAndCashEquivalents")
    pl      = _bnum(bal, "totalStockholderEquity", "stockholdersEquity")
    ativo   = _bnum(bal, "totalAssets")
    fcop    = _bnum(fd, "operatingCashflow") or _bnum(cfs, "totalCashFromOperatingActivities")
    fcl     = _bnum(fd, "freeCashflow")

    nd = (div_br - caixa) if (div_br is not None and caixa is not None) else None

    return {
        "receita_liquida":        receita,
        "lucro_bruto":            lucro_b,
        "ebit":                   ebit,
        "lucro_liquido":          lucro_l,
        "ebitda":                 ebitda,
        "divida_bruta":           div_br,
        "caixa_total":            caixa,
        "divida_liquida":         nd,
        "patrimonio_liquido":     pl,
        "ativo_total":            ativo,
        "fluxo_caixa_operacional": fcop,
        "fcl_aprox":              fcl,
    }


# Rótulos legíveis para o painel de reconciliação.
_RECON_LABELS = {
    "receita_liquida":         "Receita Líquida",
    "lucro_bruto":             "Lucro Bruto",
    "ebit":                    "EBIT",
    "lucro_liquido":           "Lucro Líquido",
    "ebitda":                  "EBITDA",
    "divida_bruta":            "Dívida Bruta",
    "caixa_total":             "Caixa + Aplicações",
    "divida_liquida":          "Dívida Líquida",
    "patrimonio_liquido":      "Patrimônio Líquido",
    "ativo_total":             "Ativo Total",
    "fluxo_caixa_operacional": "Fluxo de Caixa Operacional",
    "fcl_aprox":               "Fluxo de Caixa Livre",
}


def _reconcile_cvm_brapi(m: Dict, snap_ext: Dict, fund: Optional[Dict]) -> List[Dict]:
    """Confronta os números da CVM com os da BRAPI e aplica a política do usuário.

    Trust = BRAPI: preenche ausências e sobrepõe divergências com o valor da
    BRAPI. Muta `m` e `snap_ext` in-place e devolve as notas de auditoria.
    """
    if not fund:
        return []

    bvals = _brapi_figures(fund)
    notes: List[Dict] = []

    for key, bval in bvals.items():
        if bval is None:
            continue
        cval = _f(m.get(key))

        if cval is None:
            origem, div_pct = "preenchido", None
        else:
            denom = max(abs(bval), abs(cval), 1.0)
            div_pct = (cval - bval) / denom * 100.0
            origem = "confere" if abs(div_pct) <= _RECON_TOL * 100 else "divergente"

        # Política: BRAPI é a fonte de verdade → grava o valor da BRAPI
        # (em "confere" o valor é praticamente o mesmo).
        m[key] = bval
        if key in snap_ext or key in (
            "divida_bruta", "divida_liquida", "patrimonio_liquido",
            "ativo_total", "fluxo_caixa_operacional",
        ):
            snap_ext[key] = bval

        notes.append({
            "campo":  _RECON_LABELS.get(key, key),
            "cvm":    cval,
            "brapi":  bval,
            "origem": origem,
            "div":    div_pct,
        })

    # Recalcula derivados coerentes com os valores adotados.
    if bvals.get("caixa_total") is not None:
        snap_ext["caixa_equivalentes"] = bvals["caixa_total"]
        snap_ext["aplicacoes_financeiras"] = 0.0
    if bvals.get("divida_liquida") is not None:
        m["divida_liquida"] = bvals["divida_liquida"]
        snap_ext["divida_liquida"] = bvals["divida_liquida"]

    return notes


def _render_reconciliation(notes: List[Dict]) -> None:
    """Painel auditável: o que a BRAPI preencheu / sobrepôs sobre a CVM."""
    if not notes:
        return
    n_div  = sum(1 for n in notes if n["origem"] == "divergente")
    n_fill = sum(1 for n in notes if n["origem"] == "preenchido")
    n_ok   = sum(1 for n in notes if n["origem"] == "confere")

    resumo = (f"BRAPI conferiu {n_ok} · sobrepôs {n_div} divergente(s) · "
              f"preencheu {n_fill} ausência(s)")
    with st.expander(f"🔄 Reconciliação CVM × BRAPI — {resumo}", expanded=n_div > 0):
        st.caption("Política: a BRAPI.dev é a fonte de verdade. Onde a CVM diverge "
                   "ou está ausente, o valor da BRAPI é adotado. Tudo auditável abaixo.")
        rows = []
        for n in notes:
            badge = {"confere": "✓ confere", "divergente": "⚠ BRAPI (divergia)",
                     "preenchido": "＋ BRAPI (CVM ausente)"}[n["origem"]]
            rows.append({
                "Campo":     n["campo"],
                "CVM":       fbrl(n["cvm"]) if n["cvm"] is not None else "–",
                "BRAPI":     fbrl(n["brapi"]),
                "Δ":         f"{n['div']:+.1f}%" if n["div"] is not None else "–",
                "Adotado":   badge,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _get_ebitda(m: Dict, snap_ext: Dict) -> Optional[float]:
    """EBITDA consolidado e auditável — uma única base, sem misturar fontes.

    Prioriza o EBITDA da BRAPI (`financialData.ebitda`, já líquido — ver
    `_reconcile_cvm_brapi`), pois é uma cifra internamente consistente.

    Na ausência, calcula a partir da CVM: EBIT original (3.05, capturado em
    `snap_ext["ebit_cvm"]" antes de qualquer sobreposição da BRAPI) + D&A do
    DFC. Não usa `m["ebit"]` aqui porque, após a reconciliação, esse campo
    pode já ter sido sobrescrito pelo EBIT da BRAPI — somá-lo ao D&A da CVM
    misturaria duas fontes/períodos diferentes e distorceria o índice
    Dívida Líquida/EBITDA.
    """
    ebd = _f(m.get("ebitda"))
    if ebd is not None:
        return ebd
    ebit_cvm = _f(snap_ext.get("ebit_cvm"))
    da = _f(snap_ext.get("depreciacao"))
    if ebit_cvm is not None and da is not None:
        return ebit_cvm + abs(da)
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def _brapi_search(query: str) -> List[Dict]:
    """Busca tickers pelo nome da empresa, com cache de 1 hora."""
    try:
        client = BrapiClient()
        return client.search_ticker(query)
    except Exception:
        return []


_STOP_WORDS = {"SA", "S.A", "S.A.", "DO", "DA", "DE", "DOS", "DAS", "E",
               "EM", "LTDA", "CIA", "COMPANHIA", "INDUSTRIAS", "INDUSTRIA",
               "GRUPO", "HOLDING", "PARTICIPACOES", "PARTICIPAÇÕES"}


def _no_accents(s: str) -> str:
    """Remove acentos para comparações tolerantes (ex.: 'ITAÚ' == 'ITAU')."""
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                    if not unicodedata.combining(c))


def _auto_ticker_from_name(company_name: str) -> str:
    """Tenta encontrar o ticker B3 mais relevante dado o nome da empresa CVM."""
    words = [w.rstrip(".,/") for w in company_name.upper().split()]
    search_words = [w for w in words if len(w) >= 3 and w not in _STOP_WORDS]
    search_term = search_words[0] if search_words else company_name[:20]

    results = _brapi_search(search_term)
    if not results:
        return ""

    # A BRAPI às vezes ignora o filtro `search` e devolve a lista padrão de
    # ativos (top do mercado) — sem este filtro, TODA empresa "herdaria" o
    # ticker do topo dessa lista (ex.: PETR4). Só aceita resultados cujo
    # nome realmente contenha o termo buscado.
    term = _no_accents(search_term)
    relevant = [r for r in results
                if term in _no_accents(str(r.get("name", "")).upper())]
    if not relevant:
        return ""
    results = relevant

    # Filtrar apenas ações (não FIIs/BDRs) e ordenar por volume
    stocks = [r for r in results
              if not str(r.get("stock", "")).endswith("11")   # exclui FIIs
              and not str(r.get("stock", "")).endswith("34")]  # exclui BDRs
    if not stocks:
        stocks = results

    # Preferir PN (terminam em 4) ou ON (terminam em 3)
    pn = [r for r in stocks if str(r.get("stock", "")).endswith("4")]
    on = [r for r in stocks if str(r.get("stock", "")).endswith("3")]
    best_list = pn or on or stocks

    return best_list[0].get("stock", "")


@st.cache_data(ttl=3600, show_spinner=False)
def _ticker_to_company_name(ticker: str) -> str:
    """Resolve ticker B3 → nome da empresa via BRAPI search.
    Usado para busca por ticker: ITUB4 → 'ITAU UNIBANCO HOLDING S.A.'
    """
    results = _brapi_search(ticker.upper())
    for r in results:
        if str(r.get("stock", "")).upper() == ticker.upper():
            return str(r.get("name", ""))
    # Sem correspondência exata: NÃO usa o primeiro resultado como fallback —
    # se `/quote/list?search=` ignorar o filtro e devolver a lista padrão de
    # ativos, qualquer ticker digitado "viraria" o #1 dessa lista (ex.: PETR4).
    return ""


def _is_ticker_like(s: str) -> bool:
    """Detecta se o input parece um ticker B3 (ex: ITUB4, PETR3, VALE3, CYRE3F)."""
    return bool(re.match(r'^[A-Za-z]{3,6}[0-9]{1,2}[FWf]?$', s.strip()))


@st.cache_data(ttl=1800, show_spinner=False)
def _bcb_serie(code: int, n: int = 36) -> pd.DataFrame:
    """Busca série temporal do Banco Central (api.bcb.gov.br)."""
    try:
        import requests as _req
        url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}"
               f"/dados/ultimos/{n}?formato=json")
        r = _req.get(url, timeout=10)
        if r.status_code == 200:
            df = pd.DataFrame(r.json())
            df["data"]  = pd.to_datetime(df["data"], format="%d/%m/%Y")
            df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
            return df.dropna()
    except Exception:
        pass
    return pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def _brapi_macro(kind: str) -> Optional[float]:
    """Fallback macro via BRAPI quando o BCB estiver indisponível.

    Usa apenas os endpoints DOCUMENTADOS da BRAPI:
      selic → /v2/prime-rate   ·   ipca → /v2/inflation
    (o antigo /v2/macro não existe na API e retornava 404).
    CDI não tem endpoint na BRAPI — retorna None.
    """
    try:
        cli = BrapiClient()
        if kind.lower() == "selic":
            return cli.get_prime_rate()
        if kind.lower() == "ipca":
            return cli.get_inflation()
    except Exception:
        pass
    return None


@st.cache_data(ttl=1800, show_spinner=False)
def _brapi_macro_hist(kind: str, months: int) -> pd.DataFrame:
    """Série histórica macro via BRAPI (fallback dos gráficos quando o BCB
    está fora do ar). Mesmo formato de `_bcb_serie`: colunas data/valor.

    kind ∈ {"selic", "ipca"} — únicos com endpoint documentado na BRAPI.
    """
    try:
        cli = BrapiClient()
        rows = (cli.get_prime_rate_history(months) if kind == "selic"
                else cli.get_inflation_history(months) if kind == "ipca"
                else [])
        if rows:
            df = pd.DataFrame(rows)
            df["data"]  = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
            df["valor"] = pd.to_numeric(
                df["value"].astype(str).str.replace(",", ".", regex=False),
                errors="coerce")
            return df[["data", "valor"]].dropna().sort_values("data")
    except Exception:
        pass
    return pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def _bcb_probe() -> Dict:
    """Diagnóstico do acesso à API do BCB (SGS): status HTTP / erro da chamada.

    A API do BCB costuma bloquear requisições de servidores fora do Brasil
    (ex.: Streamlit Cloud) — este probe torna o problema visível na aba Macro.
    """
    try:
        import requests as _req
        r = _req.get(
            "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json",
            timeout=10,
        )
        return {"status": r.status_code, "body": r.text[:300]}
    except Exception as exc:
        return {"status": None, "body": str(exc)}


@st.cache_data(ttl=60, show_spinner=False)
def _brapi_currency(pairs: str = "USD-BRL,EUR-BRL") -> List[Dict]:
    """Câmbio em tempo real via BRAPI /v2/currency (cache curto de 60s)."""
    try:
        return BrapiClient().get_currency(pairs)
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def _brapi_options_expirations(underlying: str) -> Tuple[List[str], Dict]:
    """Vencimentos de opções disponíveis para um ativo-objeto (cache de 5 min).

    Retorna `(vencimentos, debug)` — `debug` ajuda a diagnosticar respostas
    inesperadas da BRAPI (endpoint não documentado oficialmente).
    """
    if not underlying:
        return [], {}
    try:
        return BrapiClient().get_options_expirations(underlying)
    except Exception as exc:
        return [], {"body": str(exc)}


@st.cache_data(ttl=120, show_spinner=False)
def _brapi_options_chain(underlying: str, expiration: Optional[str] = None) -> Tuple[Optional[Dict], Dict]:
    """Cadeia de opções (calls/puts) para um ativo-objeto e vencimento (cache de 2 min).

    Retorna `(cadeia, debug)`.
    """
    if not underlying:
        return None, {}
    try:
        return BrapiClient().get_options(underlying, expiration)
    except Exception as exc:
        return None, {"body": str(exc)}


@st.cache_data(ttl=3600, show_spinner=False)
def _embi_brasil() -> Optional[float]:
    """
    Busca o EMBI+ Brasil (risco-país, série JPM366_EMBI366 do IPEA).

    O IPEA disponibiliza o valor em pontos-base; converte para % (pb / 100).
    Retorna None se a API estiver indisponível (sem mock — fallback fica a
    cargo do chamador).
    """
    try:
        import requests as _req
        url = ("http://www.ipeadata.gov.br/api/odata4/ValoresSerie"
               "(SERCODIGO='JPM366_EMBI366')")
        r = _req.get(url, timeout=10)
        if r.status_code == 200:
            registros = r.json().get("value", [])
            df = pd.DataFrame(registros)
            if df.empty or "VALVALOR" not in df.columns:
                return None
            df["VALVALOR"] = pd.to_numeric(df["VALVALOR"], errors="coerce")
            df["VALDATA"]  = pd.to_datetime(df["VALDATA"], errors="coerce")
            df = df.dropna(subset=["VALVALOR", "VALDATA"]).sort_values("VALDATA")
            if not df.empty:
                return float(df["VALVALOR"].iloc[-1]) / 100.0
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Tab renderers
# ─────────────────────────────────────────────────────────────────────────────

def _tab_overview(m, snap, brapi_data=None, ticker_input="", recon=None):
    if brapi_data and ticker_input:
        _render_brapi_panel(brapi_data, ticker_input.upper())
        st.markdown("---")
    if recon:
        _render_reconciliation(recon)
    sec("Resultado")
    c = st.columns(4, gap="medium")
    c[0].markdown(mc("Receita Líquida",  fbrl(m.get("receita_liquida")),  "blu"),  unsafe_allow_html=True)
    c[1].markdown(mc("Lucro Bruto",      fbrl(m.get("lucro_bruto")),      _cls(m.get("lucro_bruto"))),  unsafe_allow_html=True)
    c[2].markdown(mc("EBIT",             fbrl(m.get("ebit")),             _cls(m.get("ebit"))),  unsafe_allow_html=True)
    c[3].markdown(mc("Lucro Líquido",    fbrl(m.get("lucro_liquido")),    _cls(m.get("lucro_liquido"))), unsafe_allow_html=True)

    sec("Balanço")
    c2 = st.columns(4, gap="medium")
    c2[0].markdown(mc("Caixa + Aplicações", fbrl(m.get("caixa_total")),     "pos"),  unsafe_allow_html=True)
    c2[1].markdown(mc("Dívida Bruta",       fbrl(m.get("divida_bruta")),    _cls(m.get("divida_bruta"), False)), unsafe_allow_html=True)
    c2[2].markdown(mc("Dívida Líquida",     fbrl(m.get("divida_liquida")),  _cls(m.get("divida_liquida"), False)), unsafe_allow_html=True)
    c2[3].markdown(mc("Patrimônio Líquido", fbrl(m.get("patrimonio_liquido")), _cls(m.get("patrimonio_liquido"))), unsafe_allow_html=True)

    sec("Margens")
    c3 = st.columns(4, gap="medium")
    c3[0].markdown(mc("Margem Bruta",   fpct(m.get("margem_bruta")),   _cls(m.get("margem_bruta"))),  unsafe_allow_html=True)
    c3[1].markdown(mc("Margem EBIT",    fpct(m.get("margem_ebit")),    _cls(m.get("margem_ebit"))),   unsafe_allow_html=True)
    c3[2].markdown(mc("Margem Líquida", fpct(m.get("margem_liquida")), _cls(m.get("margem_liquida"))), unsafe_allow_html=True)
    c3[3].markdown(mc("Ativo Total",    fbrl(m.get("ativo_total")),    "blu"),  unsafe_allow_html=True)

    sec("Retornos & Fluxo de Caixa")
    c4 = st.columns(4, gap="medium")
    c4[0].markdown(mc("ROE",          fpct(m.get("roe")),       _cls(m.get("roe"))),  unsafe_allow_html=True)
    c4[1].markdown(mc("ROA",          fpct(m.get("roa")),       _cls(m.get("roa"))),  unsafe_allow_html=True)
    c4[2].markdown(mc("ROIC (aprox)", fpct(m.get("roic_aprox")),_cls(m.get("roic_aprox"))), unsafe_allow_html=True)
    fcop = m.get("fluxo_caixa_operacional"); fcl = m.get("fcl_aprox")
    c4[3].markdown(mc("FCOP / FCL",
                       f"{fbrl(fcop)}  /  {fbrl(fcl)}",
                       _cls(fcl)), unsafe_allow_html=True)


def _tab_history(cd, tipo, company):
    hist = _history(cd, tipo)
    if hist.empty:
        box("Dados históricos indisponíveis. Verifique se os arquivos parquet foram gerados.", "warn")
        return

    anos = hist["ano"].tolist()

    def b(col): return [(_f(v)/1e6 if _f(v) is not None else None) for v in hist[col]]

    # Resultado
    sec("Evolução do Resultado (R$ Milhões)")
    fig1 = _lines(anos, [
        ("Receita Líquida", b("receita"),    C["blue"]),
        ("EBITDA",          b("ebitda"),     C["cyan"]),
        ("EBIT",            b("ebit"),       C["green"]),
        ("Lucro Líquido",   b("lucro_liq"),  C["purple"]),
    ], title=f"{company} — Resultado")
    st.plotly_chart(fig1, use_container_width=True)

    # FCOP
    fcop_vals = b("fcop")
    if any(v is not None for v in fcop_vals):
        sec("Fluxo de Caixa Operacional (R$ Milhões)")
        fig2 = _bar(anos, fcop_vals, "FCOP", C["teal"],
                    f"{company} — FCOP", sfx="M")
        st.plotly_chart(fig2, use_container_width=True)

    # PL e Ativo
    pl_vals = b("pl"); at_vals = b("ativo")
    if any(v is not None for v in pl_vals):
        sec("Patrimônio e Ativo (R$ Milhões)")
        fig3 = _lines(anos, [
            ("Patrimônio Líquido", pl_vals, C["yellow"]),
            ("Ativo Total",        at_vals, C["t2"]),
        ], title=f"{company} — Balanço")
        st.plotly_chart(fig3, use_container_width=True)

    # Tabela
    sec("Dados Anuais")
    disp = hist[["ano", "receita", "ebitda", "ebit", "lucro_liq", "fcop", "pl", "ativo"]].copy()
    for col in ["receita", "ebitda", "ebit", "lucro_liq", "fcop", "pl", "ativo"]:
        disp[col] = disp[col].apply(
            lambda x: f"R$ {x/1e6:,.0f}M" if pd.notna(x) and x != 0 else "–"
        )
    disp.columns = ["Ano", "Receita", "EBITDA", "EBIT", "Lucro Líq.", "FCOP", "PL", "Ativo"]
    st.dataframe(disp, use_container_width=True, hide_index=True)


def _stmt_table(df, cd, title, date_key):
    sec(title)
    if df.empty:
        box("Demonstrativo não disponível.", "warn"); return

    co = df[df["CD_CVM"].astype(str).str.strip() == cd].copy() if "CD_CVM" in df.columns else pd.DataFrame()
    if co.empty:
        box("Empresa não encontrada neste demonstrativo.", "warn"); return

    vc = "VL_CONTA_AJUSTADO" if "VL_CONTA_AJUSTADO" in co.columns else "VL_CONTA"

    if "DT_FIM_EXERC" in co.columns:
        datas = sorted(co["DT_FIM_EXERC"].unique(), reverse=True)[:8]
        sel = st.selectbox("Período:", datas, key=date_key)
        co = co[co["DT_FIM_EXERC"] == sel]

    cols = [c for c in ["CD_CONTA", "DS_CONTA", vc] if c in co.columns]
    disp = co[cols].copy()
    if vc in disp.columns:
        disp[vc] = disp[vc].apply(lambda x: f"R$ {x/1e6:,.2f} M" if pd.notna(x) else "–")
        disp = disp.rename(columns={vc: "VALOR (R$ M)", "DS_CONTA": "CONTA"})

    st.dataframe(disp, use_container_width=True, hide_index=True, height=440)


def _tab_statements(cd, tipo):
    sub1, sub2, sub3, sub4 = st.tabs(["DRE", "ATIVO (BPA)", "PASSIVO + PL (BPP)", "FLUXO DE CAIXA"])
    with sub1: _stmt_table(_stmt("DRE",    tipo), cd, "Demonstração do Resultado do Exercício", "dt_dre")
    with sub2: _stmt_table(_stmt("BPA",    tipo), cd, "Balanço Patrimonial — Ativo",             "dt_bpa")
    with sub3: _stmt_table(_stmt("BPP",    tipo), cd, "Balanço Patrimonial — Passivo + PL",       "dt_bpp")
    with sub4: _stmt_table(_stmt("DFC_MI", tipo), cd, "Demonstração do Fluxo de Caixa",           "dt_dfc")


def _tab_health(snap_ext, m, hist):
    """Aba de Saúde Financeira."""

    if _is_financial(snap_ext.get("cd_cvm"), snap_ext.get("tipo_doc", "DFP")):
        box("🏦 <b>Empresa do setor financeiro.</b> Indicadores baseados em EBITDA "
            "(Dívida Líquida/EBITDA, cobertura de juros) e de liquidez corrente "
            "<b>não se aplicam a bancos</b> — a dívida é insumo operacional. "
            "Avalie o <b>Índice de Basileia</b>, a <b>inadimplência</b> e o <b>ROE</b> "
            "(disponíveis nas notas explicativas / release do banco).", "warn")

    # ── Extrair campos ──────────────────────────────────────────────────────
    ebit   = _f(m.get("ebit"))
    ebitda = _get_ebitda(m, snap_ext)
    nd     = _f(snap_ext.get("divida_liquida"))
    divbruta = _f(snap_ext.get("divida_bruta"))
    pl     = _f(m.get("patrimonio_liquido"))
    ac     = _f(snap_ext.get("ativo_circulante"))
    pc     = _f(snap_ext.get("passivo_circulante"))
    est    = _f(snap_ext.get("estoques"))
    caixa  = _f(snap_ext.get("caixa_equivalentes")) or 0
    aplic  = _f(snap_ext.get("aplicacoes_financeiras")) or 0
    caixa_t = caixa + aplic or None
    dfinanc = _f(snap_ext.get("desp_financeiras"))
    fcop   = _f(m.get("fluxo_caixa_operacional"))
    divcp  = _f(snap_ext.get("divida_cp"))
    divlp  = _f(snap_ext.get("divida_lp"))

    # ── Indicadores calculados ──────────────────────────────────────────────
    nd_ebitda    = (nd / ebitda) if nd is not None and ebitda and ebitda > 0 else None
    div_pl       = (divbruta / abs(pl)) if divbruta and pl and pl != 0 else None
    cob_juros    = (ebit / abs(dfinanc)) if ebit and dfinanc and dfinanc != 0 else None
    liq_corrente = (ac / pc) if ac and pc and pc > 0 else None
    liq_seca     = ((ac - abs(est or 0)) / pc) if ac and pc and pc > 0 else None
    liq_imediata = ((caixa_t or 0) / pc) if pc and pc > 0 else None
    anos_pagar   = (nd / fcop) if nd and nd > 0 and fcop and fcop > 0 else None
    duration_ap  = None
    if divcp is not None and divlp is not None and (divcp + divlp) > 0:
        duration_ap = (divcp * 0.5 + divlp * 3.0) / (divcp + divlp)

    # ── Séries de tendência (período-a-período) para as bolinhas dos gauges ──
    # Alavancagem: Dívida Líquida (CP+LP−Caixa) / EBITDA, por período da CVM
    # Liquidez Corrente: Ativo Circulante / Passivo Circulante, por período
    lev_series, lev_periods, liq_series, liq_periods = [], [], [], []
    if hist is not None and not hist.empty and "ano" in hist.columns:
        for _, r in hist.sort_values("ano").iterrows():
            ebd = _f(r.get("ebitda"))
            dcp = abs(_f(r.get("divida_cp")) or 0)
            dlp = abs(_f(r.get("divida_lp")) or 0)
            cx  = _f(r.get("caixa")) or 0
            nd_r = (dcp + dlp) - cx
            if ebd and ebd > 0:
                lev_series.append(max(nd_r, 0.0) / ebd)
            else:
                lev_series.append(None)
            lev_periods.append(int(r["ano"]))

            acc = _f(r.get("ativo_circ")); pcc = _f(r.get("passivo_circ"))
            liq_series.append((acc / pcc) if acc and pcc and pcc > 0 else None)
            liq_periods.append(int(r["ano"]))

    # ── Layout ──────────────────────────────────────────────────────────────
    col_lev, col_liq = st.columns(2, gap="medium")

    with col_lev:
        sec("Alavancagem e Cobertura")

        # Gauge ND/EBITDA (número centralizado + bolinhas de tendência abaixo)
        g1_val = nd_ebitda if nd_ebitda is not None and nd_ebitda > 0 else 0
        st.plotly_chart(_gauge(g1_val, 10, "Dívida Líquida / EBITDA",
                               invert=True, show_number=False),
                        use_container_width=True)
        if nd_ebitda is None:
            _lev_col, _lev_str = C["t3"], "N/D"
        elif nd_ebitda <= 0:
            _lev_col, _lev_str = C["green"], "Caixa líq."
        else:
            _lev_col = C["green"] if nd_ebitda < 2 else C["yellow"] if nd_ebitda < 4 else C["red"]
            _lev_str = fmult(nd_ebitda)
        st.markdown(_trend_block(_lev_str, _lev_col, lev_series, True, lev_periods),
                    unsafe_allow_html=True)

        if ebitda is not None:
            _eb_src = ("BRAPI (financialData.ebitda)" if _f(m.get("ebitda")) is not None
                       else "CVM: EBIT (3.05) + D&A (DFC)")
            st.caption(
                f"EBITDA usado: {fbrl(ebitda)}  ·  fonte: {_eb_src}. "
                "Pode divergir do \"EBITDA ajustado\" de releases (que costuma "
                "excluir itens não recorrentes/impairment e somar efeitos de "
                "IFRS16 ou ajustes pro-forma de M&A — vide nota da empresa)."
            )

        def _lev_bar(lbl, val, low_good, thr_ok, thr_warn, val_str, sfx="×"):
            if val is None:
                score_row(lbl, "N/D", 0, C["t3"], "–"); return
            if low_good:
                pct  = min(val / max(thr_warn * 1.5, 0.01) * 100, 100)
                col  = C["green"] if val < thr_ok else C["yellow"] if val < thr_warn else C["red"]
                stat = "✓ OK" if val < thr_ok else "△ Alt" if val < thr_warn else "✗ Alto"
            else:
                pct  = min(val / max(thr_warn * 1.5, 0.01) * 100, 100)
                col  = C["green"] if val > thr_ok else C["yellow"] if val > thr_warn else C["red"]
                stat = "✓ OK" if val > thr_ok else "△ Baixo" if val > thr_warn else "✗ Baixo"
            score_row(lbl, val_str, pct, col, stat)

        _lev_bar("Dívida Líquida / EBITDA", nd_ebitda, True,  2.0, 4.0,
                 fmult(nd_ebitda))
        _lev_bar("Dívida Bruta / PL",       div_pl,    True,  1.0, 2.5,
                 fmult(div_pl))
        _lev_bar("Cobertura de Juros (×)",  cob_juros, False, 3.0, 1.5,
                 fmult(cob_juros))

        sec("Métricas de Dívida")
        dm1, dm2, dm3 = st.columns(3, gap="medium")
        dm1.markdown(mc("Dívida Líq./EBITDA", fmult(nd_ebitda),   _cls(nd_ebitda, False) if nd_ebitda else "nd"), unsafe_allow_html=True)
        dm2.markdown(mc("Duration (aprox)",   f"{duration_ap:.1f} anos" if duration_ap else "–", "blu"), unsafe_allow_html=True)
        dm3.markdown(mc("Anos p/ Quitar¹",    f"{anos_pagar:.1f} anos" if anos_pagar else "–",
                        "pos" if anos_pagar and anos_pagar < 5 else "yel" if anos_pagar and anos_pagar < 10 else "neg"), unsafe_allow_html=True)

        st.caption("¹ Net Debt / FCOP — à taxa atual de geração de caixa operacional")

    with col_liq:
        sec("Liquidez")

        g2_val = liq_corrente if liq_corrente is not None else 0
        st.plotly_chart(_gauge(min(g2_val, 4), 4, "Liquidez Corrente",
                               invert=False, show_number=False),
                        use_container_width=True)
        if liq_corrente is None:
            _liq_col, _liq_str = C["t3"], "N/D"
        else:
            _liq_col = C["green"] if liq_corrente >= 2 else C["yellow"] if liq_corrente >= 1 else C["red"]
            _liq_str = fmult(liq_corrente, 2)
        st.markdown(_trend_block(_liq_str, _liq_col, liq_series, False, liq_periods),
                    unsafe_allow_html=True)

        def _liq_bar(lbl, val, thr_ok, thr_warn, val_str):
            if val is None:
                score_row(lbl, "N/D", 0, C["t3"], "–"); return
            pct  = min(val / (thr_ok * 1.5) * 100, 100)
            col  = C["green"] if val >= thr_ok else C["yellow"] if val >= thr_warn else C["red"]
            stat = "✓ OK" if val >= thr_ok else "△ Baixa" if val >= thr_warn else "✗ Baixa"
            score_row(lbl, val_str, pct, col, stat)

        _liq_bar("Liquidez Corrente  (AC/PC)",       liq_corrente, 2.0, 1.0, fmult(liq_corrente, 2))
        _liq_bar("Liquidez Seca  (AC-Est)/PC",        liq_seca,     1.5, 0.8, fmult(liq_seca, 2))
        _liq_bar("Liquidez Imediata  Caixa/PC",       liq_imediata, 0.5, 0.2, fmult(liq_imediata, 2))

        sec("Capital de Giro & Dados")
        cg1, cg2, cg3 = st.columns(3, gap="medium")
        ncg = (ac - pc) if ac and pc else None
        cg1.markdown(mc("Ativo Circulante",  fbrl(ac), "blu"), unsafe_allow_html=True)
        cg2.markdown(mc("Passivo Circulante",fbrl(pc), _cls(pc, False) if pc else "nd"), unsafe_allow_html=True)
        cg3.markdown(mc("Capital de Giro",   fbrl(ncg), _cls(ncg)), unsafe_allow_html=True)

    # ── Estrutura da dívida ─────────────────────────────────────────────────
    sec("Estrutura da Dívida")
    col_struct, col_idx = st.columns(2, gap="medium")

    with col_struct:
        if divcp is not None or divlp is not None:
            cp_val = abs(divcp or 0)
            lp_val = abs(divlp or 0)
            total  = cp_val + lp_val
            if total > 0:
                fig_pie = go.Figure(go.Pie(
                    labels=["Curto Prazo (< 1 ano)", "Longo Prazo (> 1 ano)"],
                    values=[cp_val, lp_val],
                    marker_colors=[C["yellow"], C["blue"]],
                    hole=0.45,
                    textfont=dict(color=C["t1"], size=11),
                    insidetextfont=dict(color=C["t1"]),
                ))
                fig_pie.update_layout(
                    **{k: v for k, v in _PL.items() if k not in ["xaxis", "yaxis", "legend", "margin", "hovermode"]},
                    title="CP vs LP",
                    height=260,
                    showlegend=True,
                    legend=dict(font=dict(color=C["t2"], size=11),
                                bgcolor=C["surf2"], bordercolor=C["brd"]),
                    margin=dict(l=10, r=10, t=40, b=10),
                )
                st.plotly_chart(fig_pie, use_container_width=True)

                cp_pct = cp_val / total * 100
                lp_pct = lp_val / total * 100
                st.caption(f"CP: **{fbrl(cp_val)}** ({cp_pct:.0f}%) | "
                           f"LP: **{fbrl(lp_val)}** ({lp_pct:.0f}%) | "
                           f"Duration aprox: **{f'{duration_ap:.1f} anos' if duration_ap else '–'}**")
        else:
            box("Estrutura de dívida CP/LP não encontrada nos dados processados.", "warn")

    with col_idx:
        sec("Indexadores da Dívida (entrada manual)")
        box("Os indexadores (CDI, IPCA, prefixado, USD) constam nas notas explicativas. "
            "Informe abaixo para gerar o gráfico de composição.", "info")

        pct_cdi   = st.number_input("% CDI",        0.0, 100.0, 50.0, 5.0, key="idx_cdi")
        pct_ipca  = st.number_input("% IPCA",       0.0, 100.0, 20.0, 5.0, key="idx_ipca")
        pct_pre   = st.number_input("% Prefixado",  0.0, 100.0, 15.0, 5.0, key="idx_pre")
        pct_usd   = st.number_input("% USD/FX",     0.0, 100.0, 10.0, 5.0, key="idx_usd")
        pct_outro = max(0, 100 - pct_cdi - pct_ipca - pct_pre - pct_usd)
        st.caption(f"Outros: {pct_outro:.0f}%")

        if sum([pct_cdi, pct_ipca, pct_pre, pct_usd, pct_outro]) > 0:
            fig_idx = go.Figure(go.Pie(
                labels=["CDI", "IPCA", "Prefixado", "USD/FX", "Outros"],
                values=[pct_cdi, pct_ipca, pct_pre, pct_usd, pct_outro],
                marker_colors=[C["blue"], C["green"], C["cyan"], C["purple"], C["t3"]],
                hole=0.45,
                textfont=dict(color=C["t1"], size=11),
            ))
            fig_idx.update_layout(
                **{k: v for k, v in _PL.items() if k not in ["xaxis", "yaxis", "legend", "margin", "hovermode"]},
                title="Composição dos Indexadores",
                height=260,
                showlegend=True,
                legend=dict(font=dict(color=C["t2"], size=11),
                            bgcolor=C["surf2"], bordercolor=C["brd"]),
                margin=dict(l=10, r=10, t=40, b=10),
            )
            st.plotly_chart(fig_idx, use_container_width=True)

    # ── Histórico de alavancagem ────────────────────────────────────────────
    if not hist.empty and "ebitda" in hist.columns and "divida_cp" in hist.columns:
        sec("Histórico de Alavancagem")

        def _nd_hist(row):
            divcp = abs(_f(row.get("divida_cp")) or 0)
            divlp = abs(_f(row.get("divida_lp")) or 0)
            return divcp + divlp

        anos_h = hist["ano"].tolist()
        nd_vals  = [_nd_hist(r) / 1e6 for _, r in hist.iterrows()]
        ebd_vals = [(_f(r.get("ebitda")) or 0) / 1e6 for _, r in hist.iterrows()]

        fig_lev = _lines(anos_h, [
            ("Dívida Bruta Aprox.", nd_vals,  C["red"]),
            ("EBITDA",             ebd_vals, C["green"]),
        ], title="Evolução: Dívida vs EBITDA (R$ Milhões)")
        st.plotly_chart(fig_lev, use_container_width=True)


def _tab_valuation(m, snap_ext, cd, hist, brapi_data=None):
    """Aba de Valuation: WACC + Múltiplos + EPV + DCF."""

    ebit   = _f(m.get("ebit"))
    ebitda = _get_ebitda(m, snap_ext)
    nd     = _f(snap_ext.get("divida_liquida"))
    pl     = _f(m.get("patrimonio_liquido"))
    receita= _f(m.get("receita_liquida"))
    lucro  = _f(m.get("lucro_liquido"))
    fcl    = _f(m.get("fcl_aprox"))

    tipo   = snap_ext.get("tipo_doc", "DFP")
    is_fin = _is_financial(cd, tipo)

    # ── Premissas pré-calculadas a partir de dados reais ────────────────────
    # EBIT normalizado (Greenwald): média dos últimos 3 EBITs anuais
    ebit_norm = None
    ebit_norm_detail = ""
    if not hist.empty and "ebit" in hist.columns:
        eh = hist.dropna(subset=["ebit"]).sort_values("ano").tail(3)
        if len(eh) > 0:
            ebit_norm = float(eh["ebit"].mean())
            ebit_norm_detail = "  ·  ".join(
                f"{int(r.ano)}: R$ {r.ebit/1e6:,.0f}M" for r in eh.itertuples()
            )
    if ebit_norm is None:
        ebit_norm = ebit

    # FCL normalizado: média 3 anos de (FCOP − |CAPEX|) — suaviza anos atípicos
    fcl_norm = None
    fcl_norm_detail = ""
    if not hist.empty and "fcop" in hist.columns:
        fh = hist.dropna(subset=["fcop"]).sort_values("ano").tail(3)
        if len(fh) > 0:
            _fcls = [((_f(r.fcop) or 0) - abs(_f(getattr(r, "capex", None)) or 0))
                     for r in fh.itertuples()]
            fcl_norm = float(np.mean(_fcls))
            fcl_norm_detail = "  ·  ".join(
                f"{int(r.ano)}: R$ {v/1e6:,.0f}M" for r, v in zip(fh.itertuples(), _fcls)
            )

    # Crescimento: CAGR da receita histórica, amortecido para projeção
    # (empresas não sustentam o CAGR passado indefinidamente — fade até g terminal)
    cagr_rev = None
    if not hist.empty and "receita" in hist.columns:
        # janela recente (CAGR ~5 anos): ciclos antigos distorcem o cenário-base
        rh = hist.dropna(subset=["receita"]).sort_values("ano").tail(6)
        if len(rh) >= 3:
            r_ini, r_fim = float(rh["receita"].iloc[0]), float(rh["receita"].iloc[-1])
            n_anos_c = int(rh["ano"].iloc[-1] - rh["ano"].iloc[0])
            if r_ini > 0 and r_fim > 0 and n_anos_c > 0:
                cagr_rev = (r_fim / r_ini) ** (1 / n_anos_c) - 1

    def _half_step(x):  # arredonda para o passo 0.5 dos sliders
        return float(round(x * 2) / 2)

    # Piso = 4.5% (g terminal): em termos nominais o fade converge para a
    # perpetuidade, nunca abaixo dela (evita rampa em "V" sem sentido econômico)
    if cagr_rev is not None:
        g12_def = _half_step(float(np.clip(cagr_rev * 100 * 0.80, 4.5, 15.0)))
        g34_def = _half_step(float(np.clip(cagr_rev * 100 * 0.55, 4.5, 10.0)))
        g5_def  = _half_step(float(np.clip(cagr_rev * 100 * 0.40, 4.5,  8.0)))
        g34_def = min(g34_def, g12_def)
        g5_def  = min(g5_def, g34_def)
        g_src   = f"CAGR receita {cagr_rev:.1%} a.a. com fade de 80%/55%/40% até o g terminal"
    else:
        g12_def, g34_def, g5_def = 8.0, 6.0, 5.0
        g_src = "histórico insuficiente — perfil conservador padrão"

    # Risk-free: SELIC Meta atual (BCB SGS 432)
    _selic_df = _bcb_serie(432, 1)
    rf_def = 10.5
    if not _selic_df.empty:
        rf_def = float(np.clip(round(_selic_df["valor"].iloc[-1] * 4) / 4, 5.0, 18.0))

    # Kd: CDI atual (BCB SGS 4392) + spread de crédito típico de dívida corporativa
    _cdi_df = _bcb_serie(4392, 1)
    _kd_spread = 3.0
    kd_def = 14.0
    if not _cdi_df.empty:
        kd_def = float(np.clip(round((_cdi_df["valor"].iloc[-1] + _kd_spread) * 4) / 4, 5.0, 22.0))

    # CRP: EMBI+ Brasil (risco-país, IPEA) — fallback para 2.5% se indisponível
    _embi_pct = _embi_brasil()
    crp_def = float(np.clip(round((_embi_pct or 2.5) * 4) / 4, 0.0, 6.0))

    # Beta: defaultKeyStatistics da BRAPI (fallback 1.0) — completa o CAPM
    _wacc_tkr = (brapi_data or {}).get("symbol")
    _fund     = _brapi_fundamentals(_wacc_tkr) if _wacc_tkr else None
    _beta_raw = _brapi_beta(_fund)
    beta_def  = float(np.clip(round((_beta_raw if _beta_raw else 1.0) / 0.05) * 0.05, 0.3, 2.5))

    # Placeholder para a faixa de veredito no topo (preenchida após os cálculos)
    _verdict = st.empty()

    if is_fin:
        box("🏦 <b>Empresa do setor financeiro (banco/seguradora).</b> "
            "Bancos <b>não têm EBITDA</b> — a dívida é insumo operacional, não estrutura "
            "de capital. EV, EV/EBITDA, Dív.Líq/EBITDA, EPV e DCF (FCOP−Capex) "
            "<b>não se aplicam</b> e foram substituídos pelo múltiplo padrão do setor: "
            "<b>P/VP (Preço/Valor Patrimonial)</b>, complementado por P/L, ROE e "
            "Dividend Yield.", "warn")

    sub_tabs = st.tabs(["💰 DCF", "⚖️ EPV", "🧮 WACC & Premissas", "📋 Múltiplos completos"])

    # ── SUB-ABA: WACC & Premissas ────────────────────────────────────────────
    # Calculado primeiro pois EPV e DCF usam wacc_final como premissa.
    with sub_tabs[2]:
        box("O WACC é a taxa de desconto usada no DCF e no EPV. Os valores abaixo já "
            "vêm pré-preenchidos com dados de mercado (SELIC, CDI, EMBI+, beta) — "
            "abra o detalhamento para ajustar.", "info")

        with st.expander("🧮  Detalhamento do cálculo — CAPM, custo da dívida e estrutura de capital", expanded=False):
            w1, w2 = st.columns(2, gap="medium")

            with w1:
                st.markdown("**Custo do Capital Próprio (Ke) — CAPM**")
                rf     = st.slider("Rf — Risk-free (SELIC/CDI) %", 5.0, 18.0, rf_def, 0.25,
                                   key="w_rf", help="Pré-preenchido com a SELIC Meta atual (BCB SGS 432)")
                if not _selic_df.empty:
                    st.caption(f"⚡ Rf pré-preenchido com SELIC Meta vigente: **{_selic_df['valor'].iloc[-1]:.2f}% a.a.** (BCB)")
                beta   = st.slider("Beta (β)",  0.3, 2.5, beta_def, 0.05, key="w_beta",
                                   help="Pré-preenchido com o beta da BRAPI (defaultKeyStatistics)")
                if _beta_raw is not None:
                    st.caption(f"⚡ Beta pré-preenchido com BRAPI: **{_beta_raw:.2f}** (vs. Ibovespa)")
                erp    = st.slider("ERP — Prêmio de Risco de Mercado %", 3.0, 9.0, 5.5, 0.25,
                                   key="w_erp", help="Damodaran: ~5.5% para Brasil")
                crp    = st.slider("CRP — Risco País %", 0.0, 6.0, crp_def, 0.25,
                                   key="w_crp", help="Pré-preenchido com EMBI+ Brasil (IPEA, em pb / 100)")
                if _embi_pct is not None:
                    st.caption(f"⚡ CRP pré-preenchido com EMBI+ Brasil vigente: **{_embi_pct*100:,.0f} pb** ≈ **{_embi_pct:.2f}%** (IPEA)")
                else:
                    st.caption("ℹ️ EMBI+ Brasil indisponível — CRP usando padrão de **2,5%**.")
                ke_pct = rf + beta * (erp + crp)
                st.markdown(f"**Ke = {rf:.2f}% + {beta:.2f}×({erp:.2f}%+{crp:.2f}%) = `{ke_pct:.2f}%`**")

            with w2:
                st.markdown("**Custo da Dívida (Kd) e Estrutura de Capital**")
                kd_pct = st.slider("Kd — Custo da dívida bruta %", 5.0, 22.0, kd_def, 0.25, key="w_kd",
                                   help="Pré-preenchido com CDI atual + spread de crédito (BCB SGS 4392)")
                if not _cdi_df.empty:
                    st.caption(f"⚡ Kd pré-preenchido com CDI vigente (**{_cdi_df['valor'].iloc[-1]:.2f}% a.a.**) "
                               f"+ spread de crédito de **{_kd_spread:.1f}pp** (BCB)")
                t_rate = st.slider("Alíquota efetiva (IR + CSLL) %", 15.0, 40.0, 34.0, 1.0, key="w_t")
                e_pct  = st.slider("% Equity (E/(E+D))", 10.0, 95.0, 60.0, 5.0, key="w_e",
                                   help="Participação do capital próprio no capital total")
                d_pct  = 100.0 - e_pct
                kd_at  = kd_pct * (1 - t_rate / 100)
                wacc_pct = ke_pct * (e_pct / 100) + kd_at * (d_pct / 100)

                st.markdown(f"**Kd após IR = {kd_pct:.2f}%×(1−{t_rate:.0f}%) = `{kd_at:.2f}%`**")
                st.markdown(f"**WACC = {ke_pct:.2f}%×{e_pct:.0f}% + {kd_at:.2f}%×{d_pct:.0f}% = `{wacc_pct:.2f}%`**")

        wacc = wacc_pct / 100.0

        sec("WACC Resultante")
        w_cols = st.columns(4, gap="medium")
        w_cols[0].markdown(mc("Ke (Custo Equity)",   f"{ke_pct:.2f}%",   "blu"), unsafe_allow_html=True)
        w_cols[1].markdown(mc("Kd (após IR)",         f"{kd_at:.2f}%",   "yel"), unsafe_allow_html=True)
        w_cols[2].markdown(mc("WACC Calculado",       f"{wacc_pct:.2f}%","pos"), unsafe_allow_html=True)

        wacc_manual = st.number_input("Ou informe o WACC diretamente (%) — sobrescreve o calculado acima",
                                      0.0, 30.0, round(wacc_pct, 2), 0.25, key="w_manual") / 100.0
        wacc_final = wacc_manual if wacc_manual > 0 else wacc
        w_cols[3].markdown(mc("WACC Final (usado no DCF/EPV)", f"{wacc_final*100:.2f}%", "pos"), unsafe_allow_html=True)

    # ── SUB-ABA: Múltiplos completos (parte 1 — entrada de preço e tabela) ──
    with sub_tabs[3]:
        # Ações: prioridade CSV capital_social > BRAPI > 0
        cvm_shares  = _shares_for_cvm(cd)
        brapi_preco = _f(brapi_data.get("regularMarketPrice")) if brapi_data else 0.0
        brapi_acoes = (_f(brapi_data.get("sharesOutstanding")) or 0) / 1e6 if brapi_data else 0.0
        acoes_default = cvm_shares or brapi_acoes or 0.0

        fonte_acoes = ""
        if cvm_shares:
            fonte_acoes = f"FRE CVM 2026: {cvm_shares:,.0f}M ações"
        elif brapi_acoes:
            fonte_acoes = f"BRAPI: {brapi_acoes:,.0f}M ações"

        if brapi_preco or cvm_shares:
            msg = "✅ Preço e ações preenchidos automaticamente —"
            if brapi_preco:
                msg += f" Preço R$ {brapi_preco:.2f} (BRAPI)"
            if fonte_acoes:
                msg += f"  |  {fonte_acoes}"
            box(msg, "ok")
        else:
            box("Informe o preço atual da ação e o total de ações para calcular os múltiplos "
                "no expansor abaixo. Fonte: B3, brapi.dev ou Yahoo Finance.", "info")

        # Mantém os campos sincronizados com a cotação/ações ao vivo enquanto o
        # usuário não editar manualmente — sem isso, o widget (com key fixa)
        # trava no valor da primeira execução e nunca acompanha a cotação atual.
        if brapi_preco:
            if st.session_state.get("mult_preco") in (None, st.session_state.get("_mult_preco_auto")):
                st.session_state["mult_preco"] = brapi_preco
            st.session_state["_mult_preco_auto"] = brapi_preco
        if acoes_default:
            if st.session_state.get("mult_acoes") in (None, st.session_state.get("_mult_acoes_auto")):
                st.session_state["mult_acoes"] = acoes_default
            st.session_state["_mult_acoes_auto"] = acoes_default

        with st.expander("✏️  Ajustar preço da ação e ações em circulação", expanded=False):
            mv1, mv2 = st.columns(2, gap="medium")
            with mv1:
                preco  = st.number_input("Preço da ação (R$)", 0.0, 99999.0, brapi_preco, 0.01,
                                          key="mult_preco", format="%.2f")
                acoes  = st.number_input("Total de ações (milhões)", 0.0, 9999999.0, acoes_default, 10.0,
                                          key="mult_acoes")

            mktcap = preco * acoes * 1e6 if preco > 0 and acoes > 0 else None
            ev_mkt = (mktcap + (nd or 0)) if mktcap is not None else None

            with mv2:
                if mktcap:
                    st.markdown(mc("Market Cap", fbrl(mktcap), "blu"), unsafe_allow_html=True)
                    if is_fin:
                        st.markdown(mc("P/VP", fmult(_f(mktcap)/_f(pl) if pl and pl > 0 else None),
                                       "pos" if (pl and pl > 0 and mktcap/pl < 1.5) else "neu"), unsafe_allow_html=True)
                    else:
                        st.markdown(mc("EV", fbrl(ev_mkt), "cyan"), unsafe_allow_html=True)

        pvp = _f(mktcap)/_f(pl)     if mktcap and pl and pl > 0 else None
        ple = _f(mktcap)/_f(lucro)  if mktcap and lucro and lucro > 0 else None
        roe = _f(m.get("roe"))
        dy  = _f(brapi_data.get("dividendYield")) if brapi_data else None

        # ── Múltiplos de EV e forward (projeção cenário-base) ───────────────
        # Forward usa o g de anos 1–2 já pré-calculado (mesma premissa do DCF),
        # mantendo o múltiplo auditável. EBITDA/Lucro projetados 1 ano à frente.
        g_fwd      = (g12_def or 0) / 100.0
        ebitda_fwd = _f(ebitda) * (1 + g_fwd) if ebitda else None
        lucro_fwd  = _f(lucro)  * (1 + g_fwd) if lucro else None
        ev_ebitda_mult     = _f(ev_mkt)/_f(ebitda) if ev_mkt and ebitda and ebitda > 0 else None
        ev_ebitda_fwd_mult = _f(ev_mkt)/ebitda_fwd if ev_mkt and ebitda_fwd and ebitda_fwd > 0 else None
        ev_ebit_mult       = _f(ev_mkt)/_f(ebit)   if ev_mkt and ebit and ebit > 0 else None
        ev_fcl_mult        = _f(ev_mkt)/_f(fcl)    if ev_mkt and fcl and fcl > 0 else None
        ev_sales_mult      = _f(ev_mkt)/_f(receita) if ev_mkt and receita and receita > 0 else None
        ps_mult            = _f(mktcap)/_f(receita) if mktcap and receita and receita > 0 else None
        pfcl_mult          = _f(mktcap)/_f(fcl)    if mktcap and fcl and fcl > 0 else None
        ple_fwd_mult       = _f(mktcap)/lucro_fwd  if mktcap and lucro_fwd and lucro_fwd > 0 else None
        peg_mult           = (ple / g12_def) if ple and g12_def and g12_def > 0 else None
        nd_eb_mult         = _f(nd)/_f(ebitda) if nd is not None and ebitda and ebitda > 0 else None

        if is_fin:
            # Bancos/seguradoras: P/VP é o múltiplo central; sem EV/EBITDA
            mult_rows = [
                ("P / Valor Patrimonial (P/VP) ⭐", fmult(pvp),
                 "PRINCIPAL p/ bancos: < 1× desconto | 1,5–2,5× típico bancões"),
                ("P / Lucro (P/L)", fmult(ple),
                 "Bancos BR: ~5–10× histórico"),
                ("ROE", fpct(roe),
                 "Driver do P/VP justo: P/VP ≈ ROE / Custo de Capital"),
                ("Dividend Yield", f"{dy:.2f}%" if dy else "–",
                 "Bancos pagam JCP + dividendos"),
                ("P / Receita Interm. Financeira", fmult(_f(mktcap)/_f(receita) if mktcap and receita and receita>0 else None),
                 "Receita = intermediação financeira"),
                ("Market Cap", fbrl(mktcap), "Preço × ações"),
                ("Patrimônio Líquido (book)", fbrl(pl), "Valor patrimonial contábil"),
            ]
        else:
            mult_rows = [
                ("Market Cap",   fbrl(mktcap), "–"),
                ("Enterprise Value (EV)", fbrl(ev_mkt), "EV = Mkt Cap + Dívida Líquida"),
                ("EV / EBITDA",          fmult(ev_ebitda_mult),
                                         "< 8× value | 8-15× neutro | > 15× caro"),
                ("EV / EBITDA Forward",  fmult(ev_ebitda_fwd_mult),
                                         f"EV ÷ EBITDA projetado +{g12_def:.1f}% (cenário-base)"),
                ("P / Lucro (P/L)",      fmult(ple),
                                         "< 15× barato | 15-25× justo | > 25× caro"),
                ("P / Lucro Forward (P/L fwd)", fmult(ple_fwd_mult),
                                         f"P ÷ lucro projetado +{g12_def:.1f}% (cenário-base)"),
                ("PEG (P/L ÷ crescimento)", fmult(peg_mult, 2),
                                         "< 1 atrativo p/ o crescimento | > 2 caro"),
                ("Dívida Líquida / EBITDA", fmult(nd_eb_mult),
                                         "< 2× confortável | 2-3,5× atenção | > 3,5× alto"),
                ("EV / EBIT",            fmult(ev_ebit_mult), "EV ÷ EBIT (3.05 CVM)"),
                ("EV / FCL",             fmult(ev_fcl_mult), "EV ÷ (FCOP − Capex)"),
                ("EV / Receita (EV/Sales)", fmult(ev_sales_mult),
                                         "Útil p/ empresas sem lucro / margem baixa"),
                ("P / Valor Patrimonial (P/VP)", fmult(pvp),
                                                 "< 1× abaixo do book"),
                ("P / Receita (P/S)",    fmult(ps_mult), "Benchmarks por setor"),
                ("P / FCL",              fmult(pfcl_mult), "< 15× interessante"),
            ]

        # Cards de destaque: os múltiplos mais acompanhados (não-financeiras)
        if not is_fin and mktcap:
            sec("Leitura Rápida")
            hc = st.columns(4, gap="medium")
            hc[0].markdown(mc("EV / EBITDA", fmult(ev_ebitda_mult),
                              _mult_cls(ev_ebitda_mult, 8, 15),
                              f"fwd: {fmult(ev_ebitda_fwd_mult)}"), unsafe_allow_html=True)
            hc[1].markdown(mc("P / L", fmult(ple),
                              _mult_cls(ple, 15, 25),
                              f"fwd: {fmult(ple_fwd_mult)}"), unsafe_allow_html=True)
            hc[2].markdown(mc("Dív.Líq / EBITDA", fmult(nd_eb_mult),
                              _mult_cls(nd_eb_mult, 2, 3.5) if (nd_eb_mult and nd_eb_mult > 0) else "pos",
                              "alavancagem"), unsafe_allow_html=True)
            hc[3].markdown(mc("PEG", fmult(peg_mult, 2),
                              _mult_cls(peg_mult, 1, 2), "P/L ÷ crescimento"),
                           unsafe_allow_html=True)

        sec("Tabela Completa de Múltiplos")
        df_mult = pd.DataFrame(mult_rows, columns=["Múltiplo", "Valor", "Referência"])
        st.dataframe(df_mult, use_container_width=True, hide_index=True)

        # Histórico: P/VP para financeiras, EV/EBITDA para demais
        if mktcap and not hist.empty:
            if is_fin and "pl" in hist.columns:
                with st.expander("📈  Histórico P/VP Implícito (PL histórico × Market Cap atual)", expanded=False):
                    anos_h = hist["ano"].tolist()
                    pvp_hist = [
                        _f(mktcap) / _f(r.get("pl")) if _f(r.get("pl")) and _f(r.get("pl")) > 0 else None
                        for _, r in hist.iterrows()
                    ]
                    fig_mult = _lines(anos_h, [("P/VP implícito", pvp_hist, C["blue"])],
                                      title="P/VP usando PL histórico e Market Cap atual")
                    st.plotly_chart(fig_mult, use_container_width=True)
            elif not is_fin and "ebitda" in hist.columns:
                with st.expander("📈  Histórico EV/EBITDA Implícito (EBITDA real × EV atual)", expanded=False):
                    anos_h = hist["ano"].tolist()
                    ev_eb_hist = [
                        _f(ev_mkt) / _f(r.get("ebitda")) if _f(r.get("ebitda")) and _f(r.get("ebitda")) > 0 else None
                        for _, r in hist.iterrows()
                    ]
                    fig_mult = _lines(anos_h, [("EV/EBITDA implícito", ev_eb_hist, C["cyan"])],
                                      title="EV/EBITDA usando EBITDA histórico e EV atual")
                    st.plotly_chart(fig_mult, use_container_width=True)

    if is_fin:
        with sub_tabs[1]:
            box("⚠️ <b>EPV não se aplica a bancos/seguradoras.</b> O EPV usa EBIT, que não "
                "existe para bancos (a dívida é insumo operacional, não estrutura de capital). "
                "Para financeiras, use o <b>P/VP</b> e o <b>P/L</b> na aba Múltiplos, e avalie a "
                "sustentabilidade do <b>ROE</b>. A seção abaixo fica disponível apenas para "
                "entrada manual.", "warn")
        with sub_tabs[0]:
            box("⚠️ <b>DCF não se aplica a bancos/seguradoras.</b> O DCF usa FCOP−Capex, e o "
                "fluxo de caixa de bancos segue outra lógica. Para financeiras, use o "
                "<b>P/VP</b> e o <b>P/L</b> na aba Múltiplos. A seção abaixo fica disponível "
                "apenas para entrada manual.", "warn")

    # ── SUB-ABA: EPV ──────────────────────────────────────────────────────────
    with sub_tabs[1]:
        box("EPV = NOPAT / WACC  |  NOPAT = EBIT normalizado × (1 − alíquota)  |  "
            "EPV Equity = EPV − Dívida Líquida", "info")

        with st.expander("⚙️  Premissas — EBIT normalizado, alíquota, WACC e dívida", expanded=False):
            if ebit_norm_detail:
                box(f"⚡ <b>EBIT normalizado (média 3 anos):</b> {ebit_norm_detail}  "
                    f"→  <b>média = R$ {ebit_norm/1e6:,.0f}M</b>", "ok")

            epv_ebit  = st.number_input("EBIT normalizado (R$ M) — média 3 anos, auditável",
                                        value=round(_f(ebit_norm)/1e6, 1) if ebit_norm else 0.0,
                                        step=100.0, key="epv_ebit",
                                        help="Média dos últimos 3 EBITs anuais (CVM). Edite se quiser outra normalização.")
            epv_tax   = st.slider("Alíquota efetiva", 0.15, 0.45, t_rate/100, 0.01, key="epv_tax")
            epv_wacc  = st.number_input("WACC (%)", 0.0, 30.0, round(wacc_final*100, 2), 0.25, key="epv_wacc2") / 100
            epv_nd    = st.number_input("Dívida Líquida (R$ M)",
                                        value=round(_f(nd)/1e6, 1) if nd else 0.0,
                                        step=100.0, key="epv_nd")
            epv_shr   = st.number_input("Ações em circulação (M) — para EPV/ação",
                                        value=acoes, step=10.0, key="epv_shr",
                                        help="Deixe 0 para não calcular por ação")

        epv_res = calculate_epv(epv_ebit * 1e6, tax_rate=epv_tax,
                                wacc=epv_wacc or 0.01, net_debt=epv_nd * 1e6)
        if epv_shr > 0 and epv_res.get("epv_equity"):
            epv_res["epv_per_share"] = epv_res["epv_equity"] / (epv_shr * 1e6)

        sec("Resultado EPV")
        ec = st.columns(4, gap="medium")
        ec[0].markdown(mc("NOPAT",          fbrl(epv_res.get("nopat")),          _cls(epv_res.get("nopat"))), unsafe_allow_html=True)
        ec[1].markdown(mc("EPV Enterprise", fbrl(epv_res.get("epv_enterprise")), _cls(epv_res.get("epv_enterprise"))), unsafe_allow_html=True)
        ec[2].markdown(mc("EPV Equity",     fbrl(epv_res.get("epv_equity")),     _cls(epv_res.get("epv_equity"))), unsafe_allow_html=True)
        if epv_res.get("epv_per_share"):
            ec[3].markdown(mc("EPV por Ação", f"R$ {epv_res['epv_per_share']:,.2f}",
                           _cls(epv_res.get("epv_per_share"))), unsafe_allow_html=True)
        else:
            ec[3].markdown(mc("EPV por Ação", "Informe ações ↑", "nd"), unsafe_allow_html=True)

        fl = "  ·  ".join(epv_res.get("flags", []))
        st.caption(f"Status: `{fl}`")

        epv_ev = _f(epv_res.get("epv_enterprise"))
        epv_nopat = _f(epv_res.get("nopat"))
        if epv_nopat and epv_ev:
            box(f"NOPAT = R$ {epv_nopat/1e6:,.0f}M  ÷  WACC {epv_wacc*100:.2f}%  =  "
                f"EPV Enterprise R$ {epv_ev/1e6:,.0f}M", "ok")

    # ── SUB-ABA: DCF ──────────────────────────────────────────────────────────
    eq_shr  = None  # preenchido abaixo
    dcf_res = None  # idem

    with sub_tabs[0]:
        box("EV = Σ FCL/(1+WACC)ᵗ + TV/(1+WACC)ⁿ  |  TV = FCL_n×(1+g)/(WACC−g)  |  "
            "Equity = EV − Dívida Líquida  |  "
            "FCL = Caixa Operacional − CAPEX (dados CVM)", "info")

        # FCL base: média 3 anos de FCOP−|CAPEX| (normalizado) > último ano > snapshot
        fcop_cvm  = _f(snap_ext.get("fluxo_caixa_operacional"))
        capex_cvm = _f(snap_ext.get("capex"))
        fcl_cvm   = None
        if fcop_cvm is not None:
            fcl_cvm = fcop_cvm - abs(capex_cvm or 0)
        fcl_base = fcl_norm if fcl_norm is not None else (fcl_cvm if fcl_cvm is not None else fcl)
        fcl_default = round(fcl_base / 1e6, 1) if fcl_base else 0.0

        with st.expander("⚙️  Premissas — FCL, crescimento e WACC", expanded=False):
            st.markdown("**FCL e Capital (dados CVM como base)**")
            if fcl_norm_detail:
                st.caption(
                    f"⚡ FCL normalizado (média 3 anos, FCOP−CAPEX): {fcl_norm_detail}  "
                    f"→  **média = {fbrl(fcl_norm)}**"
                )
            elif fcl_cvm is not None:
                st.caption(
                    f"CVM (último ano): FCOP = {fbrl(fcop_cvm)}  |  CAPEX = {fbrl(capex_cvm)}  "
                    f"→  **FCL = {fbrl(fcl_cvm)}**"
                )
            dcf_fcl = st.number_input("FCL Base (R$ M) — média 3 anos, auditável",
                                      value=fcl_default, step=100.0, key="dcf_fcl",
                                      help="Pré-preenchido com a média de 3 anos de FCOP−CAPEX da CVM. Edite se necessário.")
            dcf_nd  = st.number_input("Dívida Líquida (R$ M) — auditável",
                                      value=round(_f(nd)/1e6, 1) if nd else 0.0,
                                      step=100.0, key="dcf_nd2",
                                      help="Dívida Bruta − Caixa (dados CVM)")
            dcf_shr = st.number_input("Ações (M) — para Equity/ação",
                                      value=acoes, step=10.0, key="dcf_shr")

            st.markdown("**Premissas de Crescimento — auditáveis**")
            st.caption(f"⚡ Pré-preenchido pelo cenário-base: {g_src}. "
                       f"g terminal 4,5% ≈ inflação meta + crescimento real de longo prazo do PIB.")
            cg1, cg2 = st.columns(2, gap="medium")
            with cg1:
                g12 = st.slider("Anos 1–2 (%)",  0.0, 35.0, g12_def, 0.5, key="dg12") / 100
                g34 = st.slider("Anos 3–4 (%)",  0.0, 25.0, g34_def, 0.5, key="dg34") / 100
            with cg2:
                g5  = st.slider("Ano 5 (%)",      0.0, 20.0, g5_def, 0.5, key="dg5")  / 100
                g_t = st.slider("g terminal (%)", 0.0,  7.0,  4.5, 0.25, key="dgt") / 100

            dcf_wacc = st.number_input("WACC (%) — preenche com o calculado na aba WACC",
                                       0.0, 30.0, round(wacc_final*100, 2), 0.25, key="dcf_wacc2") / 100

            st.caption(
                f"Premissas: FCL R$ {dcf_fcl:,.0f}M | g12={g12:.1%} | g34={g34:.1%} | "
                f"g5={g5:.1%} | g_terminal={g_t:.2%} | WACC={dcf_wacc:.2%} | "
                f"Dívida Líq R$ {dcf_nd:,.0f}M | Ações {dcf_shr:,.0f}M"
            )

        growth_rates = [g12, g12, g34, g34, g5]

        sec("Resultado DCF")
        if dcf_wacc <= g_t:
            box(f"WACC ({dcf_wacc:.3f}) deve ser maior que g terminal ({g_t:.3f})!", "err")
        elif dcf_fcl == 0:
            box("FCL = 0. Verifique se os dados CVM estão carregados ou edite o FCL Base acima.", "warn")
        else:
            dcf_res = calculate_dcf(
                base_fcf=dcf_fcl * 1e6,
                growth_rates=growth_rates,
                terminal_growth=g_t,
                wacc=dcf_wacc,
                net_debt=dcf_nd * 1e6,
            )
            ev_dcf  = _f(dcf_res.get("enterprise_value"))
            eq_dcf  = _f(dcf_res.get("equity_value"))
            vp_tv   = _f(dcf_res.get("vp_valor_terminal"))
            pct_tv  = dcf_res.get("premissas", {}).get("pct_ev_de_valor_terminal")
            fl_dcf  = "  ·  ".join(dcf_res.get("flags", []))

            eq_shr = eq_dcf / (dcf_shr * 1e6) if dcf_shr > 0 and eq_dcf else None

            dc = st.columns(5, gap="medium")
            dc[0].markdown(mc("Enterprise Value (EV)",  fbrl(ev_dcf),  _cls(ev_dcf)),  unsafe_allow_html=True)
            dc[1].markdown(mc("Equity Value",           fbrl(eq_dcf),  _cls(eq_dcf)),  unsafe_allow_html=True)
            dc[2].markdown(mc("VP do Valor Terminal",   fbrl(vp_tv),   "blu"),          unsafe_allow_html=True)
            if pct_tv:
                cls_tv = "pos" if pct_tv < 75 else "neg"
                dc[3].markdown(mc("% EV do Valor Terminal", f"{pct_tv:.1f}%", cls_tv), unsafe_allow_html=True)
            if eq_shr:
                dc[4].markdown(mc("Equity por Ação", f"R$ {eq_shr:,.2f}", _cls(eq_shr)), unsafe_allow_html=True)
            else:
                dc[4].markdown(mc("Equity por Ação", "Informe ações ↑", "nd"), unsafe_allow_html=True)

            st.caption(f"Status: `{fl_dcf}`")

            fcfs = dcf_res.get("fcfs_projetados", [])
            vps  = dcf_res.get("vp_fcfs", [])
            if fcfs:
                with st.expander("📐  Projeção detalhada (ano a ano)", expanded=False):
                    df_proj = pd.DataFrame({
                        "Ano":          list(range(1, len(fcfs)+1)),
                        "g Aplicada":   [f"{r:.1%}" for r in growth_rates],
                        "FCL Projetado":  [f"R$ {v/1e6:,.1f}M" for v in fcfs],
                        "VP do FCL":      [f"R$ {v/1e6:,.1f}M" for v in vps],
                    })
                    st.dataframe(df_proj, use_container_width=True, hide_index=True)

            if dcf_fcl != 0 and dcf_wacc > g_t:
                waccs = [max(0.07, dcf_wacc + dw) for dw in [-0.02, -0.01, 0, +0.01, +0.02]]
                gs    = sorted({max(0.01, g_t - 0.01), g_t, min(0.07, g_t + 0.01)})
                gs    = [g for g in gs if g < dcf_wacc - 0.005]

                if gs:
                    with st.expander("📊  Análise de sensibilidade — EV por WACC × g", expanded=False):
                        sens = []
                        for w in waccs:
                            row = {"WACC \\ g": f"{w:.2%}"}
                            for g in gs:
                                if w > g + 0.005:
                                    d = calculate_dcf(dcf_fcl*1e6, growth_rates, g, w, dcf_nd*1e6)
                                    ev_s = _f(d.get("enterprise_value"))
                                    row[f"g={g:.1%}"] = f"R$ {ev_s/1e6:,.0f}M" if ev_s else "N/D"
                                else:
                                    row[f"g={g:.1%}"] = "—"
                            sens.append(row)
                        st.dataframe(pd.DataFrame(sens), use_container_width=True, hide_index=True)

    # ── Gráfico comparativo de valores — encerra a aba Múltiplos completos ──
    if not is_fin:
        with sub_tabs[3]:
            val_labels = []
            val_values = []

            if mktcap:
                val_labels.append("Market Cap (mercado)"); val_values.append(_f(mktcap) / 1e6)
            if pl:
                val_labels.append("Valor Patrimonial (PL)"); val_values.append(_f(pl) / 1e6)
            epv_ev2 = _f(epv_res.get("epv_enterprise"))
            if epv_ev2:
                val_labels.append("EPV Enterprise"); val_values.append(epv_ev2 / 1e6)
            if dcf_res and _f(dcf_res.get("enterprise_value")):
                val_labels.append("DCF Enterprise"); val_values.append(_f(dcf_res.get("enterprise_value")) / 1e6)

            if len(val_labels) >= 2:
                sec("Comparativo de Valores")
                bar_colors = [C["blue"], C["purple"], C["teal"], C["green"]][:len(val_labels)]
                fig_comp = go.Figure(go.Bar(
                    x=val_values, y=val_labels, orientation="h",
                    marker_color=bar_colors,
                    text=[f"R$ {v:,.0f}M" for v in val_values],
                    textposition="outside", textfont=dict(color=C["t2"], size=11),
                ))
                fig_comp.update_layout(**_PL, title="Comparativo de Valores (R$ Milhões)",
                                       showlegend=False)
                st.plotly_chart(fig_comp, use_container_width=True)

    # ── Faixa de veredito no topo (preenchida após todos os cálculos) ───────
    _preco    = preco   if preco  > 0  else None
    _epv_shr  = epv_res.get("epv_per_share") if epv_shr > 0 else None
    _epv_ev   = _f(epv_res.get("epv_enterprise"))
    _epv_eq   = _f(epv_res.get("epv_equity"))
    _dcf_ev   = _f(dcf_res.get("enterprise_value")) if dcf_res else None
    _dcf_eq   = _f(dcf_res.get("equity_value"))     if dcf_res else None
    _dcf_shr  = eq_shr

    with _verdict.container():
        if is_fin:
            # Veredito para bancos/seguradoras: P/VP, P/L, ROE, Dividend Yield
            sec("Veredito — Banco/Seguradora (P/VP é o múltiplo central)")
            _sc = st.columns(4, gap="medium")
            _sc[0].markdown(mc("P/VP ⭐", fmult(pvp) if pvp else "Informe preço ↓",
                               ("pos hero" if pvp and pvp < 1.0 else "neu hero" if pvp and pvp < 2.0 else "neg hero" if pvp else "nd hero")),
                            unsafe_allow_html=True)
            _sc[1].markdown(mc("P/L", fmult(ple) if ple else "–",
                               (_cls(ple) + " hero") if ple else "nd hero"), unsafe_allow_html=True)
            _sc[2].markdown(mc("ROE", fpct(roe) if roe is not None else "–",
                               ("pos hero" if roe and roe > 0.15 else "neu hero") if roe is not None else "nd hero"),
                            unsafe_allow_html=True)
            if dy:
                _sc[3].markdown(mc("Dividend Yield", f"{dy:.2f}%", "pos hero"), unsafe_allow_html=True)
            else:
                _sc[3].markdown(mc("Preço de Mercado",
                                   f"R$ {_preco:,.2f}" if _preco else "Informe ↓",
                                   "blu hero" if _preco else "nd hero"), unsafe_allow_html=True)
        else:
            # Valor Justo único: prioriza DCF/ação, depois EPV/ação, depois
            # totais de equity/EV — preserva os dois métodos completos nas
            # sub-abas, mas resume num só número no topo (5-second rule).
            _vj_val, _vj_lbl, _vj_src = None, "Preencha as premissas →", None
            if _dcf_shr:
                _vj_val, _vj_lbl, _vj_src = _dcf_shr, f"R$ {_dcf_shr:,.2f}", "DCF / ação"
            elif _epv_shr:
                _vj_val, _vj_lbl, _vj_src = _epv_shr, f"R$ {_epv_shr:,.2f}", "EPV / ação"
            elif _dcf_eq:
                _vj_lbl, _vj_src = fbrl(_dcf_eq), "DCF Equity (total)"
            elif _epv_eq:
                _vj_lbl, _vj_src = fbrl(_epv_eq), "EPV Equity (total)"
            elif _dcf_ev:
                _vj_lbl, _vj_src = fbrl(_dcf_ev), "DCF Enterprise (total)"
            elif _epv_ev:
                _vj_lbl, _vj_src = fbrl(_epv_ev), "EPV Enterprise (total)"

            _up = (_vj_val / _preco - 1) * 100 if (_vj_val and _preco) else None
            _selo_txt, _selo_cls = _selo_valuation(_up)

            sec(f"Veredito — Valuation  <span class='verdict-badge {_selo_cls}'>{_selo_txt}</span>")
            _sc = st.columns(4, gap="medium")
            _sc[0].markdown(mc("Preço de Mercado",
                               f"R$ {_preco:,.2f}" if _preco else "Informe em Múltiplos →",
                               "blu hero" if _preco else "nd hero"), unsafe_allow_html=True)
            _sc[1].markdown(mc("Valor Justo", _vj_lbl,
                               (_cls(_vj_val) + " hero") if _vj_val else "nd hero",
                               _vj_src or ""), unsafe_allow_html=True)
            if _up is not None:
                _sc[2].markdown(mc("Upside", f"{_up:+.1f}%", ("pos hero" if _up > 0 else "neg hero")), unsafe_allow_html=True)
            elif _dcf_ev and _epv_ev:
                _up_ev = (_dcf_ev / _epv_ev - 1) * 100
                _sc[2].markdown(mc("DCF vs EPV (EV)", f"{_up_ev:+.1f}%",
                                   "pos hero" if _up_ev > 0 else "neg hero"), unsafe_allow_html=True)
            else:
                _sc[2].markdown(mc("Upside", "Informe preço + ações →", "nd hero"), unsafe_allow_html=True)
            _sc[3].markdown(mc("Classificação", _selo_txt, f"{_selo_cls} hero",
                               "DCF/EPV vs. preço atual"), unsafe_allow_html=True)

            if mktcap:
                sec("5 Múltiplos-Chave")
                _mc5 = st.columns(5, gap="medium")
                _mc5[0].markdown(mc("P / L", fmult(ple), _mult_cls(ple, 15, 25)), unsafe_allow_html=True)
                _mc5[1].markdown(mc("P / VP", fmult(pvp), _mult_cls(pvp, 1, 2)), unsafe_allow_html=True)
                _mc5[2].markdown(mc("EV / EBITDA", fmult(ev_ebitda_mult), _mult_cls(ev_ebitda_mult, 8, 15)), unsafe_allow_html=True)
                _mc5[3].markdown(mc("Dividend Yield", f"{dy:.2f}%" if dy else "–",
                                    "pos" if dy and dy > 0 else "nd"), unsafe_allow_html=True)
                _mc5[4].markdown(mc("ROE", fpct(roe) if roe is not None else "–",
                                    "pos" if roe and roe > 0.15 else "neu" if roe is not None else "nd"), unsafe_allow_html=True)


def _tab_macro():
    """Aba de dados macroeconômicos — Banco Central do Brasil (SGS)."""

    # ── Definição das séries por categoria ───────────────────────────────────
    # (codigo_SGS, cor, unidade, n_obs, é_mensal)
    JUROS = {
        "SELIC Meta":    (432,  C["blue"],   "% a.a.",        40,  False),
        "SELIC Efetiva": (11,   C["cyan"],   "% a.a. diário", 756, False),
        "CDI":           (4392, C["teal"],   "% a.a. diário", 756, False),
    }
    INFLACAO = {
        "IPCA":  (433, C["red"],    "% mensal", 36, True),
        "INPC":  (188, C["purple"], "% mensal", 36, True),
        "IGP-M": (189, C["yellow"], "% mensal", 36, True),
    }
    CAMBIO = {
        "USD/BRL (PTAX)": (1, C["teal"], "R$/US$", 756, False),
    }

    # Fetch
    def _fetch(cat):
        return {k: (_bcb_serie(v[0], v[3]), v[1], v[2], v[4]) for k, v in cat.items()}

    juros_d  = _fetch(JUROS)
    inf_d    = _fetch(INFLACAO)
    cambio_d = _fetch(CAMBIO)

    # O BCB respondeu para alguma série? (a API do SGS costuma bloquear
    # requisições de servidores fora do Brasil — ex.: Streamlit Cloud)
    _bcb_ok = any(not v[0].empty for v in {**juros_d, **inf_d, **cambio_d}.values())

    # ── Fallback BRAPI (endpoints documentados) para SELIC e IPCA ────────────
    # Substitui a série vazia do BCB pela equivalente da BRAPI, marcando a
    # origem na unidade (transparência — sem dados ocultos).
    if juros_d["SELIC Meta"][0].empty:
        _df_fb = _brapi_macro_hist("selic", 24)
        if not _df_fb.empty:
            _, cor, unid, mensal = juros_d["SELIC Meta"]
            juros_d["SELIC Meta"] = (_df_fb, cor, f"{unid} · BRAPI", mensal)
    if inf_d["IPCA"][0].empty:
        _df_fb = _brapi_macro_hist("ipca", 36)
        if not _df_fb.empty:
            _, cor, unid, mensal = inf_d["IPCA"]
            inf_d["IPCA"] = (_df_fb, cor, f"{unid} · BRAPI", mensal)

    if not _bcb_ok:
        box("⚠️ <b>API do Banco Central (SGS) indisponível a partir deste servidor.</b> "
            "O BCB costuma bloquear requisições vindas de fora do Brasil — é o caso "
            "de servidores do Streamlit Cloud. Onde possível, as séries abaixo usam "
            "o fallback da BRAPI (SELIC via <code>/v2/prime-rate</code> e IPCA via "
            "<code>/v2/inflation</code>); as demais ficam offline.", "warn")
        with st.expander("🔍 Diagnóstico BCB (SGS)"):
            st.json(_bcb_probe())

    # ── Helper: card com último valor ─────────────────────────────────────────
    def _card(col, nome, df_s, unidade, is_cambio=False, fallback=None):
        with col:
            if not df_s.empty:
                last_val  = df_s["valor"].iloc[-1]
                last_date = df_s["data"].iloc[-1].strftime("%d/%m/%y")
                prev_val  = df_s["valor"].iloc[-2] if len(df_s) > 1 else None
                delta     = last_val - prev_val if prev_val is not None else None
                cls_d     = ("neg" if (delta or 0) > 0 else "pos") if is_cambio \
                            else ("pos" if (delta or 0) > 0 else "neg")
                sub = f"Δ {delta:+.3f}  |  {last_date}  ({unidade})" if delta is not None \
                      else f"{last_date}  ({unidade})"
                col.markdown(mc(nome, f"{last_val:.2f}", cls_d, sub), unsafe_allow_html=True)
            else:
                fb = fallback() if fallback else None
                if fb is not None:
                    col.markdown(mc(nome, f"{fb:.2f}", "blu",
                                    f"BRAPI (fallback)  ({unidade})"), unsafe_allow_html=True)
                else:
                    col.markdown(mc(nome, "Offline", "nd", "BCB API indisponível"),
                                 unsafe_allow_html=True)

    # ── Cards ────────────────────────────────────────────────────────────────
    sec("Juros — Banco Central do Brasil (SGS)")
    cj = st.columns(3, gap="medium")
    _juros_fb = {"SELIC Meta": "selic", "CDI": "cdi"}
    for i, (nome, (df_s, cor, unid, _)) in enumerate(juros_d.items()):
        _sym = _juros_fb.get(nome)
        fb = (lambda s=_sym: _brapi_macro(s)) if _sym else None
        _card(cj[i], nome, df_s, unid, fallback=fb)

    sec("Inflação")
    ci = st.columns(3, gap="medium")
    for i, (nome, (df_s, cor, unid, _)) in enumerate(inf_d.items()):
        fb = (lambda: _brapi_macro("ipca")) if nome == "IPCA" else None
        _card(ci[i], nome, df_s, unid, fallback=fb)

    sec("Câmbio")
    cc = st.columns(4, gap="medium")
    for i, (nome, (df_s, cor, unid, _)) in enumerate(cambio_d.items()):
        _card(cc[i], nome, df_s, unid, is_cambio=True)

    # Dólar em tempo real (BRAPI /v2/currency) — ao lado do PTAX do BCB
    fx = _brapi_currency("USD-BRL")
    slot = len(cambio_d)
    if slot < len(cc):
        info = fx[0] if fx else None
        if info:
            price = _f(info.get("bidPrice"))
            chg   = _f(info.get("percentageChange"))
            # dólar subindo = real desvalorizando → vermelho
            cls_d = "neg" if (chg or 0) > 0 else "pos"
            sub = (f"Δ {chg:+.2f}%  ·  BRAPI tempo real" if chg is not None
                   else "BRAPI tempo real")
            cc[slot].markdown(mc("USD/BRL (tempo real)", f"{price:.4f}" if price else "–",
                                 cls_d, sub), unsafe_allow_html=True)
        else:
            cc[slot].markdown(mc("USD/BRL (tempo real)", "–", "nd", "BRAPI indisponível"),
                              unsafe_allow_html=True)

    # ── Gráfico: Juros ────────────────────────────────────────────────────────
    sec("Gráficos Históricos")
    fig_j = go.Figure()
    for nome, (df_s, cor, unid, _) in juros_d.items():
        if not df_s.empty:
            fig_j.add_trace(go.Scatter(
                x=df_s["data"], y=df_s["valor"], name=nome, mode="lines",
                line=dict(color=cor, width=2.5 if "Meta" in nome else 1.5,
                          dash="solid" if "Meta" in nome else "dot"),
            ))
    fig_j.update_layout(**_PL, title="SELIC Meta / SELIC Efetiva / CDI  (% a.a.)")
    st.plotly_chart(fig_j, use_container_width=True)

    # ── Gráfico: Inflação ─────────────────────────────────────────────────────
    fig_inf = go.Figure()
    for nome, (df_s, cor, unid, _) in inf_d.items():
        if not df_s.empty:
            fig_inf.add_trace(go.Scatter(
                x=df_s["data"], y=df_s["valor"], name=nome, mode="lines+markers",
                line=dict(color=cor, width=2 if "IPCA" in nome else 1.5,
                          dash="solid" if "IPCA" in nome else "dot"),
                marker=dict(size=3),
            ))
    fig_inf.add_hline(y=0, line_width=1, line_dash="dot", line_color=C["brd2"])
    fig_inf.update_layout(**_PL, title="Inflação Mensal (%) — Últimos 36 meses")
    st.plotly_chart(fig_inf, use_container_width=True)

    # ── Gráfico: Câmbio ───────────────────────────────────────────────────────
    df_usd = cambio_d.get("USD/BRL (PTAX)", (pd.DataFrame(),))[0]
    if not df_usd.empty:
        fig_usd = go.Figure()
        fig_usd.add_trace(go.Scatter(
            x=df_usd["data"], y=df_usd["valor"], name="USD/BRL PTAX", mode="lines",
            line=dict(color=C["teal"], width=2),
            fill="tozeroy", fillcolor=rgba(C["teal"], 0.07),
        ))
        fig_usd.update_layout(**_PL, title="Dólar Comercial — PTAX Venda (R$/US$)")
        st.plotly_chart(fig_usd, use_container_width=True)

    # ── Tabela consolidada ────────────────────────────────────────────────────
    sec("Tabela de Referência — BCB / SGS")
    all_series = {**juros_d, **inf_d, **cambio_d}
    rows = []
    for nome, (df_s, cor, unid, is_mensal) in all_series.items():
        if not df_s.empty:
            last = df_s.iloc[-1]
            acum12 = None
            if is_mensal and len(df_s) >= 12:
                acum12 = df_s["valor"].tail(12).sum()
            rows.append({
                "Indicador":    nome,
                "Unidade":      unid,
                "Último Valor": f"{last['valor']:.4f}",
                "Data":         last["data"].strftime("%d/%m/%Y"),
                "Acum. 12m":    f"{acum12:.2f}%" if acum12 is not None else "–",
                "Fonte (SGS)":  str({"SELIC Meta": 432, "SELIC Efetiva": 11, "CDI": 4392,
                                     "IPCA": 433, "INPC": 188, "IGP-M": 189,
                                     "USD/BRL (PTAX)": 1}.get(nome, "–")),
            })
        else:
            rows.append({"Indicador": nome, "Unidade": unid,
                         "Último Valor": "Offline", "Data": "–",
                         "Acum. 12m": "–", "Fonte (SGS)": "–"})

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    box("Fonte: <b>api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json</b> "
        "(Banco Central do Brasil — Sistema Gerenciador de Séries Temporais). "
        "Cache 30 min. SELIC Efetiva e CDI: últimos 756 dias úteis (~3 anos).", "info")


# ─────────────────────────────────────────────────────────────────────────────
# Welcome & Demo screens
# ─────────────────────────────────────────────────────────────────────────────

def _welcome(avail):
    box("""<b>EPS Value Terminal</b> — Análise fundamentalista de empresas brasileiras.<br>
🔍 Busque uma empresa na barra lateral por <b>ticker B3</b> (ex: ITUB4, PETR4, VALE3), <b>nome</b>, <b>CD_CVM</b> ou <b>CNPJ</b>.<br>
📊 Veja DRE, Balanço, DFC, métricas e histórico gráfico.<br>
📋 Analise saúde financeira: alavancagem, liquidez, estrutura da dívida.<br>
💹 Calcule EPV e DCF com WACC breakdown completo.<br>
🌐 Monitore macro: SELIC, IPCA, CDI, USD/BRL em tempo real.""", "info")

    sec("Dados em Cache Local")
    for tipo in TIPOS_DOC:
        row = st.columns(len(DEMONSTRATIVOS), gap="medium")
        for i, stmt in enumerate(DEMONSTRATIVOS):
            ok = avail.get(f"{tipo}_{stmt}", False)
            with row[i]:
                if ok:
                    try:
                        df_t = pd.read_parquet(
                            get_processed_path(stmt.lower(), tipo.lower(), "parquet"),
                            columns=["CD_CVM"],
                        )
                        n_co = df_t["CD_CVM"].nunique()
                        n_rc = len(df_t)
                        st.markdown(mc(f"{tipo}/{stmt}",
                                       f"{n_rc:,} reg",
                                       "pos",
                                       f"{n_co:,} empresas"), unsafe_allow_html=True)
                    except Exception:
                        st.markdown(mc(f"{tipo}/{stmt}", "✓ OK", "pos"), unsafe_allow_html=True)
                else:
                    st.markdown(mc(f"{tipo}/{stmt}", "Não baixado", "nd"), unsafe_allow_html=True)


def _render_brapi_panel(q: Dict, ticker: str):
    """Painel completo de dados de mercado BRAPI (quote + módulos fundamentais).

    O quote básico da BRAPI traz preço/volume/52 semanas; múltiplos como P/L,
    P/VP, EV, EV/EBITDA e ações em circulação vêm dos módulos
    `defaultKeyStatistics`/`financialData` — sem eles os cards ficavam vazios.
    Quando nem o módulo traz o número pronto, calcula da forma padrão
    (ex.: P/L = preço ÷ LPA, EV = mktcap + dívida − caixa).
    """
    nome_c = q.get("shortName", ticker)
    sec(f"📈 Dados de Mercado — {nome_c} ({ticker})  (BRAPI.dev · cotação em tempo real)")

    fund  = _brapi_fundamentals(ticker)
    stats = (fund or {}).get("defaultKeyStatistics") or {}
    fd    = (fund or {}).get("financialData") or {}

    preco  = q.get("regularMarketPrice", 0)
    var_d  = q.get("regularMarketChangePercent", 0)
    var_r  = q.get("regularMarketChange", 0)
    mktcap = _bnum(q, "marketCap")
    vol    = q.get("regularMarketVolume")
    vol10d = _bnum(q, "averageDailyVolume10Day", "averageDailyVolume3Month")
    hi52   = q.get("fiftyTwoWeekHigh")
    lo52   = q.get("fiftyTwoWeekLow")

    # Múltiplos: quote (legado) → módulos → cálculo direto
    acoes = _bnum(q, "sharesOutstanding") or _bnum(stats, "sharesOutstanding")
    if not acoes and mktcap and preco:
        acoes = mktcap / preco

    eps = _bnum(q, "earningsPerShare") or _bnum(stats, "trailingEps")
    pl  = _bnum(q, "priceEarningsRatio", "priceEarnings")
    if pl is None and preco and eps and eps > 0:
        pl = preco / eps

    bvps = _bnum(stats, "bookValue")  # valor patrimonial por ação
    pvp  = _bnum(q, "priceToBook") or _bnum(stats, "priceToBook")
    if pvp is None and preco and bvps and bvps > 0:
        pvp = preco / bvps

    ev = _bnum(q, "enterpriseValue") or _bnum(stats, "enterpriseValue")
    if ev is None and mktcap is not None:
        _debt, _cash = _bnum(fd, "totalDebt"), _bnum(fd, "totalCash")
        if _debt is not None and _cash is not None:
            ev = mktcap + _debt - _cash

    ev_ebd = _bnum(q, "enterpriseValueEbitda") or _bnum(stats, "enterpriseToEbitda")
    _ebd   = _bnum(fd, "ebitda")
    if ev_ebd is None and ev and _ebd and _ebd > 0:
        ev_ebd = ev / _ebd

    dy = _bnum(q, "dividendYield")
    dy_sub = ""
    if dy is None:
        dy = _brapi_trailing_dy(fund, preco)
        if dy is not None:
            dy_sub = "12m (proventos pagos)"

    cor_v  = _cls(var_d)
    sinal  = "▲" if var_d >= 0 else "▼"

    # Row 1: preço e variação
    c = st.columns(5, gap="medium")
    c[0].markdown(mc("Preço Atual", f"R$ {preco:.2f}", cor_v,
                     f"{sinal} R$ {abs(var_r):.2f} ({var_d:+.2f}%)"), unsafe_allow_html=True)
    c[1].markdown(mc("Market Cap",  fbrl(mktcap), "blu"), unsafe_allow_html=True)
    c[2].markdown(mc("Ações (M)",   f"{acoes/1e6:,.0f}M" if acoes else "–", "neu"), unsafe_allow_html=True)
    c[3].markdown(mc("Volume Hoje", f"{vol/1e6:.1f}M" if vol else "–", "neu",
                     f"Média 10d: {vol10d/1e6:.1f}M" if vol10d else ""), unsafe_allow_html=True)
    c[4].markdown(mc("Dividend Yield", f"{dy:.2f}%" if dy else "–",
                     "pos" if dy and dy > 0 else "nd", dy_sub), unsafe_allow_html=True)

    # Row 2: múltiplos de mercado (BRAPI)
    c2 = st.columns(5, gap="medium")
    c2[0].markdown(mc("P/L (mercado)",      fmult(pl, 1)   if pl   else "–", "neu"), unsafe_allow_html=True)
    c2[1].markdown(mc("P/VP (mercado)",     fmult(pvp, 2)  if pvp  else "–", "neu"), unsafe_allow_html=True)
    c2[2].markdown(mc("EV/EBITDA (mercado)",fmult(ev_ebd,1)if ev_ebd else "–", "neu"), unsafe_allow_html=True)
    c2[3].markdown(mc("Enterprise Value",   fbrl(ev)  if ev   else "–", "cyan"), unsafe_allow_html=True)
    if hi52 and lo52:
        pos_pct = (preco - lo52) / (hi52 - lo52) * 100 if hi52 != lo52 else 50
        c2[4].markdown(mc("52 Semanas",
                          f"R$ {lo52:.2f} – R$ {hi52:.2f}",
                          "pos" if pos_pct > 50 else "neg",
                          f"Posição atual: {pos_pct:.0f}%"), unsafe_allow_html=True)

    if fund is None and (pl is None or pvp is None or ev is None):
        st.caption(
            "⚠️ Módulos fundamentais da BRAPI indisponíveis para este ticker "
            "(`defaultKeyStatistics`/`financialData` — verifique o plano/token). "
            "P/L, P/VP, EV e EV/EBITDA dependem deles."
        )

    # Row 3: consenso de analistas (módulo financialData da BRAPI)
    _cons = _brapi_consensus(fund)
    if _cons.get("target_mean"):
        tm = _cons["target_mean"]
        up = (tm / preco - 1) * 100 if preco else None
        _rec = (_cons.get("rec") or "").replace("_", " ").title() or "–"
        _n   = int(_cons["n"]) if _cons.get("n") else None
        c3 = st.columns(5, gap="medium")
        c3[0].markdown(mc("Preço-Alvo (consenso)", f"R$ {tm:.2f}",
                          "pos" if (up or 0) > 0 else "neg",
                          f"Upside: {up:+.1f}%" if up is not None else "analistas"),
                       unsafe_allow_html=True)
        if _cons.get("target_low") and _cons.get("target_high"):
            c3[1].markdown(mc("Faixa de Alvos",
                              f"R$ {_cons['target_low']:.2f} – R$ {_cons['target_high']:.2f}",
                              "neu"), unsafe_allow_html=True)
        c3[2].markdown(mc("Recomendação", _rec, "blu",
                          f"{_n} analistas" if _n else "consenso"),
                       unsafe_allow_html=True)


def _tab_options(ticker_input: str = ""):
    """Aba de Opções B3 (BRAPI /v2/options/expirations + /v2/options/chain)."""
    sec("📑 Opções — Ativo-Objeto")

    under = st.text_input(
        "Ativo-objeto (ticker)",
        value=(ticker_input or "").strip().upper(),
        placeholder="Ex: PETR4, VALE3, ITUB4",
        key="opt_underlying",
        help="Ticker do ativo-objeto na B3. Pode ser diferente da ação selecionada acima.",
    ).strip().upper()

    if not under:
        box("Informe um ticker (ex.: PETR4) para consultar a cadeia de opções via BRAPI.", "info")
        return

    with st.spinner(f"Buscando vencimentos de opções para {under}…"):
        expirations, exp_debug = _brapi_options_expirations(under)

    if not expirations:
        box(f"Nenhum vencimento de opções encontrado para <b>{under}</b> via BRAPI "
            f"(<code>/v2/options/expirations</code>). Pode ser que este ativo não "
            f"tenha opções listadas no momento, ou que o endpoint não esteja "
            f"disponível para o seu plano/token.", "warn")
        with st.expander("🔍 Diagnóstico BRAPI (/v2/options/expirations)"):
            st.json(exp_debug or {"info": "sem resposta"})
        return

    st.caption(f"{len(expirations)} vencimento(s) disponível(is) para {under} (BRAPI)")
    exp_sel = st.selectbox("Vencimento", expirations, key="opt_expiration")

    with st.spinner(f"Buscando cadeia de opções de {under} — {exp_sel}…"):
        chain, chain_debug = _brapi_options_chain(under, exp_sel)

    if not chain:
        box(f"BRAPI não retornou a cadeia de opções de <b>{under}</b> para o "
            f"vencimento <b>{exp_sel}</b> (<code>/v2/options/chain</code>). "
            f"Veja o status HTTP e a resposta no diagnóstico abaixo.", "warn")
        with st.expander("🔍 Diagnóstico BRAPI (/v2/options/chain)", expanded=True):
            st.json(chain_debug or {"info": "sem resposta"})
        return

    # Confere se a BRAPI de fato respondeu para o ativo solicitado.
    _ret_under = str(chain.get("underlying") or chain.get("symbol")
                     or chain.get("stock") or "").upper()
    if _ret_under and _ret_under != under:
        box(f"⚠ A BRAPI retornou dados para <b>{_ret_under}</b>, não para "
            f"<b>{under}</b> — verifique se o endpoint "
            f"<code>/v2/options/chain</code> suporta este ativo no seu plano.",
            "warn")

    # Parsing tolerante: {"calls":[...], "puts":[...]}, {"options":[...]},
    # {"series":[...]} ou a primeira lista de dicts encontrada no payload.
    calls = chain.get("calls") or []
    puts  = chain.get("puts") or []
    if not calls and not puts:
        rows = (chain.get("options") or chain.get("series")
                or chain.get("data") or [])
        if not rows:
            for v in chain.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    rows = v
                    break
        for o in rows:
            if not isinstance(o, dict):
                continue
            side = str(o.get("type") or o.get("side")
                       or o.get("category") or "").lower()
            (puts if "put" in side else calls).append(o)

    def _opt_row(o):
        return {
            "Ticker":    o.get("symbol") or o.get("ticker") or o.get("name") or "–",
            "Strike":    fnum(o.get("strike") or o.get("strikePrice")),
            "Último":    fnum(o.get("lastPrice") or o.get("regularMarketPrice") or o.get("close")),
            "Compra":    fnum(o.get("bid")),
            "Venda":     fnum(o.get("ask")),
            "Volume":    fnum(o.get("volume") or o.get("regularMarketVolume"), 0),
            "Em Aberto": fnum(o.get("openInterest"), 0),
        }

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        sec(f"📈 CALLs ({len(calls)})")
        if calls:
            st.dataframe(pd.DataFrame([_opt_row(o) for o in calls]),
                          use_container_width=True, hide_index=True)
        else:
            box("Sem calls para este vencimento.", "info")
    with c2:
        sec(f"📉 PUTs ({len(puts)})")
        if puts:
            st.dataframe(pd.DataFrame([_opt_row(o) for o in puts]),
                          use_container_width=True, hide_index=True)
        else:
            box("Sem puts para este vencimento.", "info")

    if not calls and not puts:
        box("BRAPI respondeu, mas o formato da cadeia de opções não é o esperado. "
            "Veja a resposta bruta abaixo para ajustar o parsing.", "warn")

    with st.expander("🔍 Diagnóstico BRAPI (resposta bruta)"):
        st.caption(f"Vencimentos: HTTP {exp_debug.get('status')} — {exp_debug.get('url')}")
        st.json(exp_debug.get("body") if exp_debug else None)
        st.caption(f"Cadeia: HTTP {chain_debug.get('status')} — {chain_debug.get('url')}")
        st.json(chain)


def _no_data():
    box("""<b>⚠ Nenhum dado processado encontrado</b><br><br>
Execute o pipeline CVM no seu computador para baixar os dados:<br><br>
<code>cd valuation_cvm</code><br>
<code>python -m src.main --start-year 2019 --end-year 2025</code><br><br>
O download pode levar 20–60 min dependendo da sua conexão. Após concluir, recarregue esta página.
""", "warn")

    sec("Prévia do Layout — Dados Hipotéticos")
    box("Os valores abaixo são <b>demonstrativos</b> apenas para ilustrar o painel. "
        "Dados reais aparecem após rodar o pipeline.", "info")

    demo = {
        "receita_liquida": 58e9, "lucro_bruto": 24e9, "ebit": 14e9,
        "lucro_liquido": 9e9, "caixa_total": 18e9, "divida_bruta": 35e9,
        "divida_liquida": 17e9, "patrimonio_liquido": 48e9, "ativo_total": 140e9,
        "margem_bruta": 0.414, "margem_ebit": 0.241, "margem_liquida": 0.155,
        "roe": 0.188, "roa": 0.064, "roic_aprox": 0.172,
        "fluxo_caixa_operacional": 12e9, "fcl_aprox": 8.5e9,
    }
    co_strip("EMPRESA DEMONSTRAÇÃO S.A.", "00000", "DFP")
    _tab_overview(demo, {})

    anos_d = [2019, 2020, 2021, 2022, 2023, 2024]
    fig_d = _lines(anos_d, [
        ("Receita",      [38, 35, 44, 53, 58, 58], C["blue"]),
        ("EBIT",         [9,  7,  11, 14, 15, 14], C["green"]),
        ("Lucro Líquido",[6,  4,  8,  10, 10, 9],  C["purple"]),
    ], title="Evolução Financeira (R$ Bilhões) — DEMONSTRAÇÃO")
    st.plotly_chart(fig_d, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    header()

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown('<div class="sec">🔍 Buscar Empresa</div>', unsafe_allow_html=True)
        query    = st.text_input("", placeholder="Nome, ticker (ITUB4), CD_CVM ou CNPJ…",
                                 key="q", label_visibility="collapsed")
        tipo_raw = st.selectbox("Tipo de relatório",
                                ["DFP — Demonstração Anual", "ITR — Informação Trimestral"],
                                key="tipo")
        tipo_doc = tipo_raw.split(" ")[0]

        st.markdown("---")
        avail    = _avail()
        has_data = any(avail.values())

        st.markdown('<div class="sec">Status dos Dados</div>', unsafe_allow_html=True)
        for tipo in TIPOS_DOC:
            ok_cnt = sum(v for k, v in avail.items() if k.startswith(tipo))
            total  = sum(1 for k in avail if k.startswith(tipo))
            icon   = "●" if ok_cnt == total else "◑" if ok_cnt > 0 else "○"
            color  = C["green"] if ok_cnt == total else C["yellow"] if ok_cnt > 0 else C["red"]
            st.markdown(
                f'<span style="color:{color}">{icon} {tipo}: {ok_cnt}/{total}</span>',
                unsafe_allow_html=True,
            )

        st.markdown("---")
        st.markdown(f"""
<div style="font-size:11px;color:{C['t3']};line-height:1.9">
Para baixar dados:<br>
<code style="color:{C['t2']}">python -m src.main</code><br>
<code style="color:{C['t2']}">  --start-year 2019</code><br>
<code style="color:{C['t2']}">  --end-year 2025</code>
</div>""", unsafe_allow_html=True)

    # ── Rota principal ────────────────────────────────────────────────────────
    if not has_data:
        _no_data()
        return

    # Busca
    selected_cd  = None
    selected_name = None
    selected_setor = ""

    if query:
        reg = _registry()
        if reg.empty:
            box("Cadastro de empresas não encontrado.", "warn")
        else:
            # ── Busca por ticker B3 (ex: ITUB4, PETR4) ───────────────────────
            ticker_override = ""
            if _is_ticker_like(query):
                t = query.strip().upper()
                with st.spinner(f"Resolvendo ticker {t} via BRAPI…"):
                    cname = _ticker_to_company_name(t)
                if cname:
                    ticker_override = t
                    matches = filter_company_by_name_or_cvm(cname, df=reg)
                    if matches.empty:
                        # Fallback: primeira palavra significativa do nome CVM
                        _stop = {"S.A.", "S.A", "SA", "HOLDING", "BANCO", "FUNDO",
                                 "PARTICIPACOES", "PARTICIPAÇÕES", "DO", "DA", "DE",
                                 "E", "DOS", "DAS", "LTDA"}
                        words = [w.rstrip(".,/") for w in cname.split()
                                 if len(w) >= 4 and w.upper().rstrip(".,/") not in _stop]
                        if words:
                            matches = filter_company_by_name_or_cvm(words[0], df=reg)
                    if not matches.empty:
                        box(f"✅ Ticker <b>{t}</b> → empresa encontrada: "
                            f"<b>{cname}</b>", "ok")
                    else:
                        box(f"Ticker <b>{t}</b> identificado como <b>{cname}</b> mas não "
                            f"encontrado no cadastro CVM. Tente buscar pelo nome.", "warn")
                else:
                    box(f"Ticker <b>{t}</b> não encontrado via BRAPI. "
                        f"Verifique o token ou tente buscar pelo nome da empresa.", "warn")
                    matches = filter_company_by_name_or_cvm(query, df=reg)
            else:
                matches = filter_company_by_name_or_cvm(query, df=reg)

            if matches.empty:
                box(f'Nenhuma empresa encontrada para <b>"{query}"</b>.', "warn")
            else:
                if len(matches) > 1:
                    sec("Resultados da Busca")
                    opts = [
                        f"{r.get('DENOM_CIA','N/D')}  (CD_CVM: {r.get('CD_CVM','?')})"
                        for _, r in matches.iterrows()
                    ]
                    idx  = st.selectbox("Selecione:", range(len(opts)),
                                        format_func=lambda i: opts[i], key="sel")
                    row  = matches.iloc[idx]
                else:
                    row  = matches.iloc[0]

                selected_cd    = str(row.get("CD_CVM", "")).strip()
                selected_name  = str(row.get("DENOM_CIA", "N/D")).strip()
                selected_setor = str(row.get("SETOR_ATIV", "")).strip()

                # Ticker search: define ticker agora para evitar auto-detect posterior
                if ticker_override:
                    st.session_state["ticker"] = ticker_override
                    st.session_state["_last_cd_ticker"] = selected_cd

    if not selected_cd:
        _welcome(avail)
        return

    # Dashboard da empresa
    with st.spinner(f"Carregando {selected_name}…"):
        snap_ext = _ext_snap(selected_cd, tipo_doc)
        m        = calculate_basic_metrics(snap_ext)
        m["caixa_total"]    = (snap_ext.get("caixa_equivalentes") or 0) + (snap_ext.get("aplicacoes_financeiras") or 0) or None
        m["divida_liquida"] = snap_ext.get("divida_liquida")
        hist = _history(selected_cd, tipo_doc)

    # Empresa mudou → limpa inputs de valuation para os defaults recalcularem
    # (widgets com key mantêm o valor da empresa anterior se não forem resetados)
    if st.session_state.get("_last_cd_val") != selected_cd:
        st.session_state["_last_cd_val"] = selected_cd
        for _k in ("epv_ebit", "epv_nd", "epv_shr", "epv_tax", "epv_wacc2",
                   "dcf_fcl", "dcf_nd2", "dcf_shr", "dg12", "dg34", "dg5", "dgt",
                   "dcf_wacc2", "mult_preco", "mult_acoes",
                   "_mult_preco_auto", "_mult_acoes_auto",
                   "w_rf", "w_beta", "w_kd", "w_crp", "w_manual"):
            st.session_state.pop(_k, None)

    # ── Auto-detect ticker quando empresa muda ───────────────────────────────
    # Sempre atribui (mesmo "" quando nada é detectado) — caso contrário o
    # ticker da empresa anterior ficaria "preso" no session_state e todo o
    # painel BRAPI continuaria mostrando o ativo antigo (ex.: PETR4).
    if selected_cd and st.session_state.get("_last_cd_ticker") != selected_cd:
        st.session_state["_last_cd_ticker"] = selected_cd
        st.session_state["ticker"] = _auto_ticker_from_name(selected_name or "")
        st.rerun()

    # ── Busca cotação BRAPI antes de renderizar o cabeçalho ──────────────────
    ticker_input = st.session_state.get("ticker", "").strip().upper()
    brapi_data = _brapi_quote(ticker_input) if ticker_input else None

    # ── Reconciliação CVM × BRAPI (BRAPI = fonte de verdade) ─────────────────
    # Preenche lacunas da CVM e sobrepõe divergências com os números da BRAPI.
    _fund  = _brapi_fundamentals(ticker_input) if ticker_input else None
    recon  = _reconcile_cvm_brapi(m, snap_ext, _fund)

    # ── Cabeçalho com nome + cotação ao lado ─────────────────────────────────
    co_strip(selected_name, selected_cd, tipo_doc, selected_setor,
             brapi_data=brapi_data, ticker=ticker_input)

    # ── Sidebar: ticker editável + detalhes ──────────────────────────────────
    with st.sidebar:
        st.markdown("---")
        st.markdown('<div class="sec">📈 Cotação B3 (BRAPI)</div>', unsafe_allow_html=True)
        ticker_input = st.text_input(
            "", placeholder="Ex: PETR4, VALE3, WEGE3",
            key="ticker", label_visibility="collapsed",
        )
        if brapi_data:
            preco = brapi_data.get("regularMarketPrice", 0)
            var_d = brapi_data.get("regularMarketChangePercent", 0)
            cor_v = C["green"] if var_d >= 0 else C["red"]
            sinal = "▲" if var_d >= 0 else "▼"
            st.markdown(
                f'<div style="background:{C["surf"]};border:1px solid {C["brd"]};'
                f'border-left:3px solid {C["blue"]};border-radius:6px;padding:10px 14px;margin-top:4px">'
                f'<div style="color:{C["t3"]};font-size:10px;letter-spacing:1px">{ticker_input.upper()}</div>'
                f'<div style="color:{C["t1"]};font-size:22px;font-weight:700">R$ {preco:.2f}</div>'
                f'<div style="color:{cor_v};font-size:12px">{sinal} {abs(var_d):.2f}% hoje</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            hi52 = brapi_data.get("fiftyTwoWeekHigh")
            lo52 = brapi_data.get("fiftyTwoWeekLow")
            if hi52 and lo52 and hi52 != lo52:
                pos_pct = (preco - lo52) / (hi52 - lo52) * 100
                st.markdown(
                    f'<div style="font-size:10px;color:{C["t3"]};margin-top:6px">'
                    f'52 sem: R$ {lo52:.2f} — R$ {hi52:.2f}<br>'
                    f'<div style="background:{C["brd2"]};border-radius:3px;height:5px;margin-top:4px">'
                    f'<div style="background:{C["blue"]};width:{pos_pct:.0f}%;height:100%;border-radius:3px"></div>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
            dy = brapi_data.get("dividendYield")
            if dy:
                st.markdown(f'<span style="color:{C["t3"]};font-size:10px">DY: <b style="color:{C["green"]}">{dy:.2f}%</b></span>',
                            unsafe_allow_html=True)
        elif ticker_input:
            st.markdown(f'<span style="color:{C["red"]};font-size:11px">Ticker não encontrado ou API offline.</span>',
                        unsafe_allow_html=True)

    tabs = st.tabs(["VISÃO GERAL", "HISTÓRICO", "DEMONSTRATIVOS",
                    "SAÚDE FINANCEIRA", "VALUATION", "OPÇÕES", "MACRO BRASIL"])

    with tabs[0]: _tab_overview(m, snap_ext, brapi_data=brapi_data,
                                ticker_input=ticker_input, recon=recon)
    with tabs[1]: _tab_history(selected_cd, tipo_doc, selected_name)
    with tabs[2]: _tab_statements(selected_cd, tipo_doc)
    with tabs[3]: _tab_health(snap_ext, m, hist)
    with tabs[4]: _tab_valuation(m, snap_ext, selected_cd, hist, brapi_data=brapi_data)
    with tabs[5]: _tab_options(ticker_input)
    with tabs[6]: _tab_macro()


if __name__ == "__main__":
    main()
