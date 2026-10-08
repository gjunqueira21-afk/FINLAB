"""
Ponto de entrada do pipeline CVM.

Uso:
    python -m src.main --start-year 2019 --end-year 2026
    python -m src.main --start-year 2019 --end-year 2026 --force-download
    python -m src.main --start-year 2019 --end-year 2026 --company-query PETROBRAS
    python -m src.main --example
"""

import argparse
from typing import List

import pandas as pd

from .config import (
    DEMONSTRATIVOS,
    PROCESSED_DIR,
    TIPOS_DOC,
    create_directories,
    get_processed_path,
)
from .cvm_cleaner import clean_cadastro, clean_statement
from .cvm_downloader import download_all_cvm_data
from .cvm_parser import load_statement
from .company_mapper import (
    create_ticker_mapper_template,
    filter_company_by_name_or_cvm,
    load_company_registry,
)
from .financial_statements import build_company_snapshot
from .logger import logger
from .valuation_metrics import calculate_basic_metrics


# ---------------------------------------------------------------------------
# Processamento e persistência
# ---------------------------------------------------------------------------

def _save_df(df: pd.DataFrame, name: str, tipo_doc: str) -> None:
    """Salva DataFrame em parquet e CSV."""
    if df.empty:
        logger.warning("DataFrame vazio para %s %s — nada salvo.", name, tipo_doc)
        return

    parquet_path = get_processed_path(name.lower(), tipo_doc.lower(), "parquet")
    csv_path = get_processed_path(name.lower(), tipo_doc.lower(), "csv")

    parquet_path.parent.mkdir(parents=True, exist_ok=True)

    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)
    logger.info("Salvo: %s (%d linhas) | parquet + csv", parquet_path.name, len(df))


def process_and_save_statements(years: List[int]) -> None:
    """
    Para cada combinação de tipo_doc × demonstrativo, carrega, limpa e salva.
    """
    for tipo_doc in TIPOS_DOC:
        for stmt in DEMONSTRATIVOS:
            logger.info("[%s %s] Processando...", tipo_doc, stmt)
            df_raw = load_statement(tipo_doc, stmt, years, consolidated=True)

            if df_raw.empty:
                logger.warning("[%s %s] Nenhum dado disponível.", tipo_doc, stmt)
                continue

            df_clean = clean_statement(df_raw)
            _save_df(df_clean, stmt.lower(), tipo_doc.lower())


def process_and_save_ipe(years: List[int]) -> None:
    """Consolida o índice IPE dos anos pedidos num parquet único.

    O IPE não segue o formato dos demonstrativos: é um CSV por ano, uma linha
    por documento entregue à CVM, com Link_Download apontando para o PDF no
    RAD/ENET. Aqui só o índice é guardado — o texto dos PDFs é outra etapa,
    e o índice sozinho já responde "o que aconteceu nesta empresa desde o
    balanço", com data e link.
    """
    import io
    import zipfile

    from .config import CSV_ENCODING, CSV_SEP, RAW_DIR

    partes = []
    for ano in years:
        zip_path = RAW_DIR / f"ipe_cia_aberta_{ano}.zip"
        if not zip_path.exists():
            logger.debug("[IPE %d] ZIP ausente — pulando.", ano)
            continue
        try:
            with zipfile.ZipFile(zip_path) as zf:
                nomes = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not nomes:
                    logger.warning("[IPE %d] ZIP sem CSV dentro.", ano)
                    continue
                with zf.open(nomes[0]) as fh:
                    bruto = fh.read()
            df = pd.read_csv(io.BytesIO(bruto), sep=CSV_SEP, encoding=CSV_ENCODING,
                             dtype=str, low_memory=False)
            partes.append(df)
            logger.info("[IPE %d] %d documentos.", ano, len(df))
        except Exception as exc:
            logger.error("[IPE %d] Falha ao ler: %s", ano, exc)

    if not partes:
        logger.warning("IPE: nenhum ano disponível — o painel segue sem o índice.")
        return

    df = pd.concat(partes, ignore_index=True)
    if "Codigo_CVM" in df.columns:
        df["Codigo_CVM"] = df["Codigo_CVM"].astype(str).str.strip()
    for col in ("Data_Entrega", "Data_Referencia"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Reapresentação: a CVM republica o mesmo protocolo com Versao maior. Fica
    # a última — senão o painel mostra o mesmo fato relevante três vezes.
    if {"Protocolo_Entrega", "Versao"} <= set(df.columns):
        df["Versao"] = pd.to_numeric(df["Versao"], errors="coerce").fillna(0)
        df = (df.sort_values("Versao")
                .drop_duplicates(subset=["Protocolo_Entrega"], keep="last"))

    destino = PROCESSED_DIR / "ipe.parquet"
    destino.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(destino, index=False)
    logger.info("Salvo: ipe.parquet (%d documentos, %d companhias)",
                len(df), df["Codigo_CVM"].nunique() if "Codigo_CVM" in df.columns else 0)


def process_and_save_cadastro() -> pd.DataFrame:
    """Processa e salva o cadastro de empresas."""
    from .config import RAW_DIR
    cadastro_path = RAW_DIR / "cad_cia_aberta.csv"

    if not cadastro_path.exists():
        logger.error("Cadastro não encontrado: %s", cadastro_path)
        return pd.DataFrame()

    df_raw = pd.read_csv(cadastro_path, sep=";", encoding="latin1", dtype=str)
    df_clean = clean_cadastro(df_raw)

    parquet_path = PROCESSED_DIR / "cadastro_cvm.parquet"
    csv_path = PROCESSED_DIR / "cadastro_cvm.csv"
    df_clean.to_parquet(parquet_path, index=False)
    df_clean.to_csv(csv_path, index=False)
    logger.info("Cadastro salvo: %d empresas | parquet + csv", len(df_clean))

    return df_clean


# ---------------------------------------------------------------------------
# Comandos especiais
# ---------------------------------------------------------------------------

def run_company_query(query: str) -> None:
    """Busca empresa, mostra CD_CVM e gera snapshot financeiro."""
    logger.info("Buscando empresa: '%s'", query)
    df = load_company_registry()

    if df.empty:
        print("\nCadastro não encontrado. Execute o pipeline completo primeiro.")
        return

    matches = filter_company_by_name_or_cvm(query, df=df)

    if matches.empty:
        print(f"\nNenhuma empresa encontrada para '{query}'.")
        return

    print(f"\n{'='*60}")
    print(f"Resultados para '{query}':")
    print(f"{'='*60}")

    cols_show = [c for c in ["CD_CVM", "CNPJ_CIA", "DENOM_CIA", "SIT", "SETOR_ATIV"] if c in matches.columns]
    print(matches[cols_show].to_string(index=False))

    # Gerar snapshot da primeira empresa encontrada
    if "CD_CVM" in matches.columns:
        cd_cvm = str(matches.iloc[0]["CD_CVM"]).strip()
        denom = matches.iloc[0].get("DENOM_CIA", "N/A")
        print(f"\n{'='*60}")
        print(f"Snapshot financeiro: {denom} (CD_CVM={cd_cvm})")
        print(f"{'='*60}")

        snapshot = build_company_snapshot(cd_cvm)
        metrics = calculate_basic_metrics(snapshot)

        _print_snapshot(metrics)


def _print_snapshot(m: dict) -> None:
    """Formata e imprime o snapshot de métricas."""
    def fmt(val, scale=1e6, suffix="M"):
        if val is None or (isinstance(val, float) and __import__("math").isnan(val)):
            return "N/D"
        return f"R$ {val/scale:,.2f}{suffix}"

    def fmt_pct(val):
        if val is None or (isinstance(val, float) and __import__("math").isnan(val)):
            return "N/D"
        return f"{val*100:.2f}%"

    print(f"\n  {'Receita Líquida:':<30} {fmt(m.get('receita_liquida'))}")
    print(f"  {'Lucro Bruto:':<30} {fmt(m.get('lucro_bruto'))}")
    print(f"  {'EBIT:':<30} {fmt(m.get('ebit'))}")
    print(f"  {'Lucro Líquido:':<30} {fmt(m.get('lucro_liquido'))}")
    print(f"  {'Caixa (total):':<30} {fmt(m.get('caixa_total'))}")
    print(f"  {'Dívida Bruta:':<30} {fmt(m.get('divida_bruta'))}")
    print(f"  {'Dívida Líquida:':<30} {fmt(m.get('divida_liquida'))}")
    print(f"  {'Patrimônio Líquido:':<30} {fmt(m.get('patrimonio_liquido'))}")
    print(f"  {'Ativo Total:':<30} {fmt(m.get('ativo_total'))}")
    print(f"  {'FCOP:':<30} {fmt(m.get('fluxo_caixa_operacional'))}")
    print(f"  {'Capex:':<30} {fmt(m.get('capex'))}")
    print()
    print(f"  {'Margem Bruta:':<30} {fmt_pct(m.get('margem_bruta'))}")
    print(f"  {'Margem EBIT:':<30} {fmt_pct(m.get('margem_ebit'))}")
    print(f"  {'Margem Líquida:':<30} {fmt_pct(m.get('margem_liquida'))}")
    print(f"  {'ROE:':<30} {fmt_pct(m.get('roe'))}")
    print(f"  {'ROA:':<30} {fmt_pct(m.get('roa'))}")
    print(f"  {'ROIC (aprox):':<30} {fmt_pct(m.get('roic_aprox'))}")


def run_example() -> None:
    """Mostra exemplo de uso do módulo de valuation."""
    print("\n" + "="*60)
    print("EXEMPLO: Cálculo de EPV com dados hipotéticos")
    print("="*60)

    from .valuation_epv import epv_from_ebit_series
    from .valuation_dcf import calculate_dcf

    ebit_historico = [5_000_000, 5_500_000, 4_800_000, 6_000_000, 5_700_000]
    epv = epv_from_ebit_series(
        ebit_series=ebit_historico,
        tax_rate=0.34,
        wacc=0.12,
        net_debt=10_000_000,
        norm_method="median",
    )
    print(f"\nEPV Enterprise:  R$ {epv['epv_enterprise']:,.0f}" if epv["epv_enterprise"] else "\nEPV: N/D")
    print(f"EPV Equity:      R$ {epv['epv_equity']:,.0f}" if epv["epv_equity"] else "EPV Equity: N/D")
    print(f"Flags: {epv['flags']}")

    print("\n" + "="*60)
    print("EXEMPLO: DCF com premissas hipotéticas")
    print("="*60)

    dcf = calculate_dcf(
        base_fcf=4_000_000,
        growth_rates=[0.12, 0.10, 0.08, 0.06, 0.05],
        terminal_growth=0.03,
        wacc=0.12,
        net_debt=10_000_000,
    )
    print(f"\nEnterprise Value: R$ {dcf['enterprise_value']:,.0f}" if dcf["enterprise_value"] else "\nDCF: N/D")
    print(f"Equity Value:     R$ {dcf['equity_value']:,.0f}" if dcf["equity_value"] else "")
    print(f"Flags: {dcf['flags']}")


# ---------------------------------------------------------------------------
# Resumo do processamento
# ---------------------------------------------------------------------------

def print_processing_summary(years: List[int]) -> None:
    """Imprime resumo dos arquivos gerados."""
    print(f"\n{'='*60}")
    print("RESUMO DO PROCESSAMENTO")
    print(f"{'='*60}")
    print(f"Anos processados: {years[0]} - {years[-1]}")

    total_rows = 0
    for tipo_doc in TIPOS_DOC:
        for stmt in DEMONSTRATIVOS:
            path = get_processed_path(stmt.lower(), tipo_doc.lower(), "parquet")
            if path.exists():
                try:
                    df = pd.read_parquet(path, columns=["CD_CVM"])
                    empresas = df["CD_CVM"].nunique()
                    print(f"  {tipo_doc}/{stmt:<8}: {len(df):>8} linhas | {empresas:>5} empresas | {path.name}")
                    total_rows += len(df)
                except Exception:
                    print(f"  {tipo_doc}/{stmt:<8}: arquivo gerado (não pôde contar linhas)")

    print(f"\nTotal de registros processados: {total_rows:,}")
    print(f"Arquivos em: {PROCESSED_DIR}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# CLI principal
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pipeline de dados fundamentalistas CVM para valuation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python -m src.main --start-year 2019 --end-year 2026
  python -m src.main --start-year 2019 --end-year 2026 --force-download
  python -m src.main --start-year 2019 --end-year 2026 --company-query PETROBRAS
  python -m src.main --start-year 2019 --end-year 2026 --company-query VALE
  python -m src.main --example
        """,
    )
    parser.add_argument(
        "--start-year", type=int, default=2019, help="Ano inicial (padrão: 2019)"
    )
    parser.add_argument(
        "--end-year", type=int, default=2025, help="Ano final (padrão: 2025)"
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        default=False,
        help="Força novo download ignorando cache",
    )
    parser.add_argument(
        "--company-query",
        type=str,
        default=None,
        help="Busca empresa por nome, CD_CVM ou CNPJ",
    )
    parser.add_argument(
        "--example",
        action="store_true",
        default=False,
        help="Executa exemplo de cálculo de EPV e DCF",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        default=False,
        help="Pula etapa de download (usa cache existente)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.example:
        run_example()
        return

    years = list(range(args.start_year, args.end_year + 1))

    logger.info("Iniciando pipeline CVM | Anos: %d - %d", args.start_year, args.end_year)

    # 1. Criar diretórios
    create_directories()

    # 2. Download
    if not args.skip_download:
        download_all_cvm_data(
            start_year=args.start_year,
            end_year=args.end_year,
            force_download=args.force_download,
        )
    else:
        logger.info("Etapa de download ignorada (--skip-download).")

    # 3. Processar cadastro
    logger.info("Processando cadastro de empresas...")
    df_cadastro = process_and_save_cadastro()

    # 4. Processar demonstrativos
    logger.info("Processando demonstrativos financeiros...")
    process_and_save_statements(years)
    process_and_save_ipe(years)

    # 5. Criar template de ticker_mapper
    if not df_cadastro.empty:
        create_ticker_mapper_template(df_cadastro=df_cadastro)

    # 6. Resumo
    print_processing_summary(years)

    # 7. Busca de empresa (opcional)
    if args.company_query:
        run_company_query(args.company_query)

    logger.info("Pipeline concluído com sucesso.")


if __name__ == "__main__":
    main()
