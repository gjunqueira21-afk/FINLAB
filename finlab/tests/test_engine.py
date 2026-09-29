"""Teste do motor de valuation (JavaScript) contra uma referência em Python.

O motor roda no navegador para que os sliders respondam sem round-trip ao
servidor. Para garantir que a matemática está certa, este teste executa o
mesmo cenário nos dois lados e compara casa decimal a casa decimal.

Rodar: python -m pytest finlab/tests/test_engine.py -q
Requer playwright + chromium; é pulado automaticamente se não houver.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api", reason="playwright não instalado")

ENGINE = Path(__file__).resolve().parents[1] / "web" / "assets" / "js" / "engine.js"

PREMISSAS = {
    "rf": 0.14, "beta": 1.0, "erp": 0.05, "premio_extra": 0.0,
    "cdi": 0.1415, "spread_credito": 0.025, "tax": 0.34, "wd": 0.30,
    "anos": 5, "growth": [0.10] * 5, "g_terminal": 0.04,
    "fcf_base": 100.0, "divida_liquida": 250.0, "shares": 10.0,
    "preco": 40.0, "ebit_normalizado": 180.0, "inflacao": 0.045,
}


def referencia(p: dict) -> dict:
    """DCF/EPV calculados de forma independente, em Python."""
    ke = p["rf"] + p["beta"] * p["erp"] + p["premio_extra"]
    kd = p["cdi"] + p["spread_credito"]
    kd_liquido = kd * (1 - p["tax"])
    wacc = (1 - p["wd"]) * ke + p["wd"] * kd_liquido

    fluxos, soma_vp, fcf = [], 0.0, p["fcf_base"]
    for t in range(1, p["anos"] + 1):
        fcf *= 1 + p["growth"][min(t - 1, len(p["growth"]) - 1)]
        fluxos.append(fcf)
        soma_vp += fcf / (1 + wacc) ** t

    tv = fluxos[-1] * (1 + p["g_terminal"]) / (wacc - p["g_terminal"])
    vp_tv = tv / (1 + wacc) ** p["anos"]
    ev = soma_vp + vp_tv
    equity = ev - p["divida_liquida"]
    epv = p["ebit_normalizado"] * (1 - p["tax"]) / wacc

    return {
        "ke": ke, "kd": kd, "kdLiquido": kd_liquido, "wacc": wacc,
        "soma_vp": soma_vp, "valor_terminal": tv, "vp_terminal": vp_tv,
        "ev": ev, "equity_value": equity, "preco_justo": equity / p["shares"],
        "peso_perpetuidade": vp_tv / ev,
        "upside": equity / p["shares"] / p["preco"] - 1,
        "epv_por_acao": (epv - p["divida_liquida"]) / p["shares"],
    }


def _chromium_alternativo() -> str | None:
    """Procura um Chromium já instalado quando o build esperado não existe.

    Útil em ambientes que trazem o navegador pré-instalado numa versão
    diferente da que o pacote playwright espera.
    """
    import os

    raiz = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    if not raiz.is_dir():
        return None
    for padrao in ("chromium-*/chrome-linux/chrome",
                   "chromium*/chrome-linux/chrome",
                   "chromium*/chrome-headless-shell-linux64/chrome-headless-shell"):
        for caminho in sorted(raiz.glob(padrao), reverse=True):
            if caminho.is_file():
                return str(caminho)
    return None


@pytest.fixture(scope="module")
def engine():
    from playwright.sync_api import sync_playwright

    codigo = ENGINE.read_text(encoding="utf-8")
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # pragma: no cover - ambiente sem chromium
            alternativo = _chromium_alternativo()
            if not alternativo:
                pytest.skip(f"chromium indisponível: {exc}")
            browser = pw.chromium.launch(executable_path=alternativo, args=["--no-sandbox"])
        page = browser.new_page()
        page.set_content("<html><body></body></html>")
        page.add_script_tag(content=codigo)

        def avaliar(expr: str, args: dict | None = None):
            return page.evaluate(f"(args) => {{ {expr} }}", args or {})

        yield avaliar
        browser.close()


def test_dcf_bate_com_a_referencia_em_python(engine):
    alvo = referencia(PREMISSAS)
    obtido = engine(
        "const d = FLEngine.dcf(args.p); const e = FLEngine.epv(args.p);"
        "return {ke:d.ke, kd:d.kd, kdLiquido:d.kdLiquido, wacc:d.wacc, soma_vp:d.soma_vp,"
        " valor_terminal:d.valor_terminal, vp_terminal:d.vp_terminal, ev:d.ev,"
        " equity_value:d.equity_value, preco_justo:d.preco_justo, upside:d.upside,"
        " peso_perpetuidade:d.peso_perpetuidade, epv_por_acao:e.por_acao};",
        {"p": PREMISSAS},
    )
    for chave, esperado in alvo.items():
        assert obtido[chave] == pytest.approx(esperado, rel=1e-9), chave


def test_gordon_invalido_quando_wacc_nao_supera_a_perpetuidade(engine):
    saida = engine(
        "const d = FLEngine.dcf(args.p, {g_terminal: 0.30});"
        "return {preco: d.preco_justo, ev: d.ev, alertas: d.alertas};",
        {"p": PREMISSAS},
    )
    assert saida["preco"] is None
    assert saida["ev"] is None
    assert "WACC_MENOR_QUE_G" in saida["alertas"]


def test_dcf_reverso_reproduz_o_preco_de_tela(engine):
    saida = engine(
        "const g = FLEngine.crescimentoImplicito(args.p);"
        "const d = FLEngine.dcf(args.p, {growth: FLEngine.rampaCom(args.p, g)});"
        "return {g, preco: d.preco_justo};",
        {"p": PREMISSAS},
    )
    assert saida["g"] is not None
    assert saida["preco"] == pytest.approx(PREMISSAS["preco"], abs=1e-6)


def test_regua_e_kpi_contam_a_mesma_historia(engine):
    """O achado nº 1 do diagnóstico: a curva rodava crescimento constante
    enquanto o KPI usava a rampa. Com uma rampa decrescente de verdade, o
    ponto da curva em x = g[0] tem de ser EXATAMENTE o preço justo do KPI."""
    p = dict(PREMISSAS, growth=[0.12, 0.10, 0.08, 0.06, 0.05])
    saida = engine(
        "const kpi = FLEngine.dcf(args.p).preco_justo;"
        "const g0 = args.p.growth[0];"
        "const pts = FLEngine.curva(args.p, 'growth', g0 - 0.01, g0 + 0.01, 2);"
        "return {kpi, meio: pts[1].y, x: pts[1].x};",
        {"p": p},
    )
    assert saida["x"] == pytest.approx(0.12, abs=1e-12)
    assert saida["meio"] == pytest.approx(saida["kpi"], rel=1e-9)


def test_rampa_deslocada_preserva_o_formato(engine):
    p = dict(PREMISSAS, growth=[0.12, 0.10, 0.08, 0.06, 0.05])
    rampa = engine("return FLEngine.rampaCom(args.p, 0.02);", {"p": p})
    assert rampa == pytest.approx([0.02, 0.00, -0.02, -0.04, -0.05], abs=1e-12)


def test_cenario_reverso_precifica_a_tela_com_a_rampa(engine):
    p = dict(PREMISSAS, growth=[0.12, 0.10, 0.08, 0.06, 0.05])
    saida = engine(
        "const c = FLEngine.cenario(args.p, 'implicito');"
        "const d = FLEngine.dcf(c);"
        "const passo = c.growth.map((v, i) => i ? +(v - c.growth[i-1]).toFixed(10) : null);"
        "return {preco: d.preco_justo, passo: passo.slice(1)};",
        {"p": p},
    )
    assert saida["preco"] == pytest.approx(PREMISSAS["preco"], abs=1e-6)
    # o formato da rampa original (-2, -2, -2, -1 pontos) sobrevive ao reverso
    assert saida["passo"] == pytest.approx([-0.02, -0.02, -0.02, -0.01], abs=1e-9)


def test_fluxo_base_negativo_e_recusado(engine):
    saida = engine(
        "const d = FLEngine.dcf(Object.assign({}, args.p, {fcf_base: -50}));"
        "const z = FLEngine.dcf(Object.assign({}, args.p, {fcf_base: 0}));"
        "return {preco: d.preco_justo, ev: d.ev, alertas: d.alertas, precoZero: z.preco_justo};",
        {"p": PREMISSAS},
    )
    assert saida["preco"] is None and saida["ev"] is None
    assert "FCL_BASE_NAO_POSITIVO" in saida["alertas"]
    assert saida["precoZero"] is None


def test_wacc_breakeven_zera_o_upside(engine):
    saida = engine(
        "const p = args.p;"
        "const w = FLEngine.waccBreakeven(p);"
        # Inverte a fórmula do WACC para recuperar o prêmio adicional exato.
        "const cc = FLEngine.wacc(p);"
        "const extra = (w - cc.wd * cc.kdLiquido) / cc.we - p.rf - p.beta * p.erp;"
        "return {wacc: w, upside: FLEngine.dcf(p, {premio_extra: extra}).upside};",
        {"p": PREMISSAS},
    )
    assert saida["wacc"] is not None
    assert saida["upside"] == pytest.approx(0.0, abs=1e-6)


def test_preco_justo_cresce_com_o_crescimento(engine):
    pontos = engine(
        "return FLEngine.curva(args.p, 'growth', -0.10, 0.20, 30);", {"p": PREMISSAS}
    )
    valores = [p["y"] for p in pontos]
    assert all(b >= a for a, b in zip(valores, valores[1:])), "curva deve ser monótona"


def test_preco_justo_cai_quando_o_custo_de_capital_sobe(engine):
    valores = engine(
        "return [0, 0.02, 0.04].map(x => FLEngine.dcf(args.p, {premio_extra:x}).preco_justo);",
        {"p": PREMISSAS},
    )
    assert valores[0] > valores[1] > valores[2]


def test_sem_fluxo_base_nao_inventa_preco(engine):
    saida = engine(
        "const d = FLEngine.dcf(Object.assign({}, args.p, {fcf_base: null}));"
        "return {preco: d.preco_justo, alertas: d.alertas};",
        {"p": PREMISSAS},
    )
    assert saida["preco"] is None
    assert "SEM_FCL_BASE" in saida["alertas"]


def test_sem_acoes_calcula_equity_mas_nao_preco(engine):
    saida = engine(
        "const d = FLEngine.dcf(Object.assign({}, args.p, {shares: null}));"
        "return {preco: d.preco_justo, equity: d.equity_value, alertas: d.alertas};",
        {"p": PREMISSAS},
    )
    assert saida["preco"] is None
    assert saida["equity"] is not None
    assert "SEM_ACOES" in saida["alertas"]


def test_alerta_de_perpetuidade_dominante(engine):
    alertas = engine(
        "return FLEngine.dcf(args.p).alertas;", {"p": PREMISSAS}
    )
    # No cenário-base, a perpetuidade responde por ~59% do EV: sem alerta.
    assert "PERPETUIDADE_ACIMA_75PCT" not in alertas
    saida = engine(
        "const d = FLEngine.dcf(args.p, {g_terminal: 0.13});"
        "return {peso: d.peso_perpetuidade, alertas: d.alertas};", {"p": PREMISSAS}
    )
    assert saida["peso"] > 0.75
    assert "PERPETUIDADE_ACIMA_75PCT" in saida["alertas"]


def test_cenarios_mantem_gordon_valido(engine):
    saida = engine(
        "return ['otimista','pessimista','inflacao','sem_crescimento','implicito'].map(t => {"
        "  const c = FLEngine.cenario(args.p, t);"
        "  const d = FLEngine.dcf(c);"
        "  return {tipo: t, wacc: d.wacc, g: c.g_terminal, preco: d.preco_justo};"
        "});",
        {"p": PREMISSAS},
    )
    for cen in saida:
        assert cen["g"] < cen["wacc"], cen["tipo"]
        assert cen["preco"] is not None, cen["tipo"]


def test_otimista_vale_mais_que_pessimista(engine):
    saida = engine(
        "const o = FLEngine.dcf(FLEngine.cenario(args.p,'otimista')).preco_justo;"
        "const p = FLEngine.dcf(FLEngine.cenario(args.p,'pessimista')).preco_justo;"
        "return {o, p};",
        {"p": PREMISSAS},
    )
    assert saida["o"] > saida["p"]


def test_matriz_de_sensibilidade_tem_todas_as_celulas(engine):
    celulas = engine(
        "return FLEngine.matriz(args.p, [-0.03,0,0.03], [0.02,0.03,0.04]);", {"p": PREMISSAS}
    )
    assert len(celulas) == 9
    # Mais custo de capital com o mesmo g sempre reduz o upside.
    assert celulas["-0.03|0.03"] > celulas["0|0.03"] > celulas["0.03|0.03"]


def test_growth_series_repete_a_ultima_taxa(engine):
    assert engine("return FLEngine.growthSeries([0.1, 0.05], 5);") == [0.1, 0.05, 0.05, 0.05, 0.05]
    assert engine("return FLEngine.growthSeries([], 3);") == [0, 0, 0]


def test_resumo_para_os_agentes_tem_os_campos_esperados(engine):
    resumo = engine("return FLEngine.resumo(args.p);", {"p": PREMISSAS})
    for campo in ("wacc", "preco_justo", "upside", "ev", "equity_value",
                  "peso_perpetuidade", "epv_por_acao", "g_implicito", "alertas"):
        assert campo in resumo, campo
    assert json.dumps(resumo)  # precisa ser serializável para ir ao backend
