"""Teste dos gráficos em SVG (charts.js), executados no navegador.

Gráfico não se testa por pixel — se testa pelo que ele afirma: posição
proporcional ao valor e redesenho só quando a geometria muda.

Rodar: python -m pytest finlab/tests/test_charts.py -q
Requer playwright + chromium; é pulado automaticamente se não houver.
"""

from __future__ import annotations

from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api", reason="playwright não instalado")

CHARTS = Path(__file__).resolve().parents[1] / "web" / "assets" / "js" / "charts.js"


def _chromium_alternativo() -> str | None:
    import os

    raiz = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    if not raiz.is_dir():
        return None
    for padrao in ("chromium-*/chrome-linux/chrome", "chromium*/chrome-linux/chrome"):
        for caminho in sorted(raiz.glob(padrao), reverse=True):
            if caminho.is_file():
                return str(caminho)
    return None


@pytest.fixture(scope="module")
def pagina():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # pragma: no cover
            alt = _chromium_alternativo()
            if not alt:
                pytest.skip(f"chromium indisponível: {exc}")
            browser = pw.chromium.launch(executable_path=alt, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 900, "height": 600})
        page.set_content(
            "<html><body><div id='box' style='width:800px;height:300px'></div></body></html>")
        page.add_script_tag(content=CHARTS.read_text(encoding="utf-8"))

        def avaliar(expr: str, args: dict | None = None):
            return page.evaluate(f"(args) => {{ {expr} }}", args or {})

        yield avaliar
        browser.close()


# ---------------------------------------------------------------------------
# Linha / área e anel
# ---------------------------------------------------------------------------

def test_linha_posiciona_os_pontos_na_escala(pagina):
    """O ponto mais alto da série fica no topo da área de plotagem e o mais
    baixo embaixo: a escala tem de conter os dois, sem cortar nenhum."""
    saida = pagina("""
        const box = document.getElementById('box');
        box.innerHTML = '';
        const r = FLChart.line(box, {height: 200, padding: {t: 10, r: 10, b: 20, l: 40},
          series: [{name: 's', points: [{x: 0, y: 10}, {x: 1, y: 30}, {x: 2, y: 20}]}]});
        const ys = [10, 30, 20].map(r.sy);
        return {ys, topo: 10, base: 200 - 20,
                caminhos: box.querySelectorAll('path').length};
    """)
    alto, baixo = min(saida["ys"]), max(saida["ys"])
    assert saida["topo"] <= alto < baixo <= saida["base"]
    assert saida["ys"][1] == alto and saida["ys"][0] == baixo
    assert saida["caminhos"] == 1


def test_linha_sem_dado_avisa_e_nao_desenha(pagina):
    saida = pagina("""
        const box = document.getElementById('box');
        box.innerHTML = '';
        const r = FLChart.line(box, {series: [{name: 's', points: []}]});
        return {r, texto: box.textContent};
    """)
    assert saida["r"] is None
    assert "sem dados" in saida["texto"]


def test_anel_mostra_a_nota(pagina):
    saida = pagina("""
        const box = document.getElementById('box');
        box.innerHTML = '';
        FLChart.ring(box, {size: 118, value: 72.4, caption: 'SAÚDE'});
        return box.textContent;
    """)
    assert "72" in saida and "SAÚDE" in saida


# ---------------------------------------------------------------------------
# Redesenho
# ---------------------------------------------------------------------------

def test_observador_redesenha_so_quando_a_largura_muda_de_fato(pagina):
    """O SVG tem viewBox fixo e preserveAspectRatio "none": ele estica junto
    com a caixa. Sem redesenhar, arrastar a janela de 1366 para 626 mantinha o
    desenho de 1366 esmagado. Mas redesenhar a cada pixel seria caro — o
    gatilho é a largura ter mudado além do limiar, com espera."""
    saida = pagina("""
        const box = document.getElementById('box');
        const alvo = document.createElement('div');
        alvo.style.width = '800px';
        document.body.appendChild(alvo);
        let chamadas = 0;
        FLChart.observarLargura(() => { chamadas++; }, {alvo, espera: 20, limiar: 12});
        const esperar = ms => new Promise(r => setTimeout(r, ms));
        return (async () => {
          await esperar(60);
          const inicial = chamadas;              // observar não dispara sozinho
          alvo.style.width = '805px';            // 5px: ruído, abaixo do limiar
          await esperar(80);
          const ruido = chamadas;
          alvo.style.width = '400px';            // mudança real
          await esperar(120);
          const real = chamadas;
          alvo.remove();
          return {inicial, ruido, real};
        })();
    """)
    assert saida["inicial"] == 0, "montar o observador não pode redesenhar nada"
    assert saida["ruido"] == 0, "variação menor que o limiar não pode redesenhar"
    assert saida["real"] == 1, saida
