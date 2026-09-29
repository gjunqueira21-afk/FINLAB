"""
Cliente BRAPI.dev — dados de mercado B3 em tempo real.

BRAPI.dev é uma API brasileira que fornece cotações e dados fundamentais
de ações negociadas na B3.

Configure o token em .env:
    BRAPI_TOKEN=seu_token_aqui

Ou passe diretamente: BrapiClient(token="seu_token")
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from .logger import logger


def _get_brapi_token() -> str:
    """Lê o token BRAPI do .env ou do st.secrets (Streamlit Cloud)."""
    token = os.getenv("BRAPI_TOKEN", "")
    if not token:
        try:
            import streamlit as st
            token = st.secrets.get("BRAPI_TOKEN", "")
        except Exception:
            pass
    return token

_BASE = "https://brapi.dev/api"
_TIMEOUT = 12


class BrapiClient:
    """Cliente para a API BRAPI.dev."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or _get_brapi_token()
        if not self.token:
            logger.warning("BrapiClient: BRAPI_TOKEN não configurado.")

    @property
    def _headers(self) -> Dict[str, str]:
        """Autenticação via Bearer (padrão recomendado pela BRAPI)."""
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    # ------------------------------------------------------------------
    # Cotação + dados fundamentais
    # ------------------------------------------------------------------

    def get_quote(self, ticker: str) -> Optional[Dict]:
        """
        Retorna cotação completa + dados fundamentais de um ticker B3.

        Campos principais retornados:
            regularMarketPrice          Preço atual
            regularMarketChangePercent  Variação do dia (%)
            regularMarketVolume         Volume
            marketCap                   Market Cap (R$)
            sharesOutstanding           Ações em circulação
            priceEarningsRatio          P/L
            priceToBook                 P/VP
            enterpriseValue             EV
            enterpriseValueEbitda       EV/EBITDA
            dividendYield               Dividend Yield (%)
            fiftyTwoWeekHigh / Low      Máx/mín 52 semanas
        """
        if not self.token:
            logger.error("BrapiClient.get_quote: token ausente.")
            return None

        ticker = ticker.upper().strip()
        try:
            resp = requests.get(
                f"{_BASE}/quote/{ticker}",
                params={"token": self.token, "fundamental": "true"},
                timeout=_TIMEOUT,
            )

            if resp.status_code == 401:
                logger.error("BrapiClient: token inválido ou expirado.")
                return None
            if resp.status_code == 404:
                logger.warning("BrapiClient: ticker '%s' não encontrado.", ticker)
                return None
            if resp.status_code != 200:
                logger.error("BrapiClient: HTTP %d para %s", resp.status_code, ticker)
                return None

            results = resp.json().get("results", [])
            if not results:
                logger.warning("BrapiClient: sem resultados para '%s'.", ticker)
                return None

            logger.info("BrapiClient: cotação obtida para %s @ R$ %.2f",
                        ticker, results[0].get("regularMarketPrice", 0))
            return results[0]

        except requests.Timeout:
            logger.error("BrapiClient: timeout ao buscar %s.", ticker)
            return None
        except Exception as exc:
            logger.error("BrapiClient: erro inesperado para %s: %s", ticker, exc)
            return None

    # ------------------------------------------------------------------
    # Fundamentos completos (módulos: statements, key stats, financialData)
    # ------------------------------------------------------------------

    def get_fundamentals(
        self,
        ticker: str,
        modules: Optional[str] = None,
        dividends: bool = True,
    ) -> Optional[Dict]:
        """
        Quote enriquecido com módulos fundamentais da BRAPI.

        Inclui defaultKeyStatistics (beta, forwardPE, EV/EBITDA),
        financialData (preço-alvo de analistas, recomendação, dívida, EBITDA),
        summaryProfile (setor/indústria) e o histórico de demonstrações
        (balanço, DRE, fluxo de caixa — anual e trimestral).
        """
        if not self.token:
            return None
        ticker = ticker.upper().strip()
        mods = modules or (
            "summaryProfile,defaultKeyStatistics,financialData,"
            "balanceSheetHistory,incomeStatementHistory,cashflowHistory,"
            "balanceSheetHistoryQuarterly,incomeStatementHistoryQuarterly,"
            "cashflowHistoryQuarterly"
        )
        try:
            resp = requests.get(
                f"{_BASE}/quote/{ticker}",
                params={"modules": mods, "dividends": str(dividends).lower()},
                headers=self._headers,
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    return results[0]
                logger.warning("BrapiClient.get_fundamentals: sem resultados para %s", ticker)
            else:
                logger.warning("BrapiClient.get_fundamentals: HTTP %d para %s",
                               resp.status_code, ticker)
        except Exception as exc:
            logger.warning("BrapiClient.get_fundamentals: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Dados macro (fallback quando BCB/IPEA estiverem indisponíveis)
    # ------------------------------------------------------------------

    def get_prime_rate(self) -> Optional[float]:
        """Retorna a taxa SELIC mais recente (% a.a.) via BRAPI /v2/prime-rate."""
        if not self.token:
            return None
        try:
            resp = requests.get(
                f"{_BASE}/v2/prime-rate",
                params={"token": self.token, "country": "brazil", "historical": "false"},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json().get("prime-rate", [])
                if data:
                    return float(data[0].get("value"))
        except Exception as exc:
            logger.warning("BrapiClient.get_prime_rate: %s", exc)
        return None

    def get_inflation(self) -> Optional[float]:
        """Retorna o IPCA mais recente (% no período) via BRAPI /v2/inflation."""
        if not self.token:
            return None
        try:
            resp = requests.get(
                f"{_BASE}/v2/inflation",
                params={"token": self.token, "country": "brazil", "historical": "false"},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json().get("inflation", [])
                if data:
                    return float(data[0].get("value"))
        except Exception as exc:
            logger.warning("BrapiClient.get_inflation: %s", exc)
        return None

    def _v2_macro_series(self, endpoint: str, key: str, months: int) -> List[Dict]:
        """
        Série histórica de um endpoint macro documentado da BRAPI
        (/v2/prime-rate ou /v2/inflation), com `historical=true`.

        Retorna lista de {date: 'dd/mm/aaaa', value: str} em ordem cronológica.
        """
        if not self.token:
            return []
        from datetime import date, timedelta
        end = date.today()
        start = end - timedelta(days=int(months * 30.5))
        try:
            resp = requests.get(
                f"{_BASE}/v2/{endpoint}",
                params={
                    "country": "brazil",
                    "historical": "true",
                    "start": start.strftime("%d/%m/%Y"),
                    "end": end.strftime("%d/%m/%Y"),
                    "sortBy": "date",
                    "sortOrder": "asc",
                },
                headers=self._headers,
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json().get(key, [])
                return data if isinstance(data, list) else []
            logger.warning("BrapiClient._v2_macro_series(%s): HTTP %d", endpoint, resp.status_code)
        except Exception as exc:
            logger.warning("BrapiClient._v2_macro_series(%s): %s", endpoint, exc)
        return []

    def get_prime_rate_history(self, months: int = 24) -> List[Dict]:
        """Histórico da SELIC (% a.a.) via BRAPI /v2/prime-rate (documentado)."""
        return self._v2_macro_series("prime-rate", "prime-rate", months)

    def get_inflation_history(self, months: int = 36) -> List[Dict]:
        """Histórico do IPCA (% mensal) via BRAPI /v2/inflation (documentado)."""
        return self._v2_macro_series("inflation", "inflation", months)

    def get_currency(self, pairs: str = "USD-BRL,EUR-BRL") -> List[Dict]:
        """
        Cotações de câmbio em tempo real via BRAPI /v2/currency.

        `pairs`: pares separados por vírgula (ex.: 'USD-BRL,EUR-BRL').
        Cada item retorna fromCurrency, toCurrency, name, bidPrice,
        askPrice, percentageChange, updatedAtDate, etc.
        """
        if not self.token:
            return []
        try:
            resp = requests.get(
                f"{_BASE}/v2/currency",
                params={"currency": pairs},
                headers=self._headers,
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.json().get("currency", [])
            logger.warning("BrapiClient.get_currency: HTTP %d", resp.status_code)
        except Exception as exc:
            logger.warning("BrapiClient.get_currency: %s", exc)
        return []

    # ------------------------------------------------------------------
    # Opções B3 (mercado de derivativos)
    # ------------------------------------------------------------------

    def get_options_expirations(
        self, underlying: str, include_expired: bool = False
    ) -> Tuple[List[str], Dict]:
        """
        Datas de vencimento de opções disponíveis para um ativo-objeto B3
        via BRAPI /v2/options/expirations.

        `underlying`: ticker do ativo-objeto (ex.: 'PETR4').

        Retorna `(vencimentos, debug)`. `debug` traz `url`, `status` e
        `body` (resposta crua/erro) para diagnóstico — este endpoint não
        consta na documentação pública da BRAPI, então o formato exato da
        resposta pode variar por plano/token.
        """
        debug: Dict = {"url": f"{_BASE}/v2/options/expirations", "status": None, "body": None}
        if not self.token:
            debug["body"] = "BRAPI_TOKEN não configurado."
            return [], debug
        underlying = underlying.upper().strip()
        try:
            resp = requests.get(
                f"{_BASE}/v2/options/expirations",
                params={"underlying": underlying, "includeExpired": str(include_expired).lower()},
                headers=self._headers,
                timeout=_TIMEOUT,
            )
            debug["url"] = resp.url
            debug["status"] = resp.status_code
            if resp.status_code == 200:
                data = resp.json()
                debug["body"] = data
                exp = data.get("expirations") or data.get("dates") or data.get("data") or []
                if isinstance(exp, dict):
                    exp = exp.get(underlying) or []
                return ([str(x) for x in exp] if isinstance(exp, list) else []), debug
            debug["body"] = resp.text[:500]
            logger.warning("BrapiClient.get_options_expirations: HTTP %d para %s",
                           resp.status_code, underlying)
        except Exception as exc:
            debug["body"] = str(exc)
            logger.warning("BrapiClient.get_options_expirations: %s", exc)
        return [], debug

    def get_options(
        self, underlying: str, expiration: Optional[str] = None
    ) -> Tuple[Optional[Dict], Dict]:
        """
        Cadeia de opções (calls/puts) de um ativo-objeto B3 via BRAPI
        /v2/options/chain.

        Rota confirmada por sondagem em produção (11/06/2026): o endpoint
        valida com Zod e exige o parâmetro `expirationDate` (não
        `expiration`); as rotas `/v2/options/{ticker}`, `/v2/options` e
        `/v2/options/series` retornam 404.

        `underlying`:  ticker do ativo-objeto (ex.: 'PETR4').
        `expiration`:  data de vencimento no formato retornado por
                       get_options_expirations (ex.: '2026-06-12').
                       Obrigatória na API — sem ela retorna 400.

        Retorna `(cadeia, debug)`. `debug` traz `url`, `status` e `body`
        (resposta crua/erro) para diagnóstico.
        """
        debug: Dict = {"url": f"{_BASE}/v2/options/chain", "status": None, "body": None}
        if not self.token:
            debug["body"] = "BRAPI_TOKEN não configurado."
            return None, debug
        underlying = underlying.upper().strip()
        params: Dict[str, str] = {"underlying": underlying}
        if expiration:
            params["expirationDate"] = expiration
        try:
            resp = requests.get(
                f"{_BASE}/v2/options/chain",
                params=params,
                headers=self._headers,
                timeout=_TIMEOUT,
            )
            debug["url"] = resp.url
            debug["status"] = resp.status_code
            if resp.status_code == 200:
                data = resp.json()
                debug["body"] = "200 OK"
                return data, debug
            debug["body"] = resp.text[:500]
            logger.warning("BrapiClient.get_options: HTTP %d para %s",
                           resp.status_code, underlying)
        except Exception as exc:
            debug["body"] = str(exc)
            logger.warning("BrapiClient.get_options: %s", exc)
        return None, debug

    # ------------------------------------------------------------------
    # Lista de tickers disponíveis
    # ------------------------------------------------------------------

    def list_tickers(self) -> List[str]:
        """Retorna lista de tickers de ações disponíveis na B3."""
        if not self.token:
            return []
        try:
            resp = requests.get(
                f"{_BASE}/quote/list",
                params={"token": self.token},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                return [s["stock"] for s in data.get("stocks", [])]
        except Exception:
            pass
        return []

    # ------------------------------------------------------------------
    # Busca de ticker pelo nome da empresa
    # ------------------------------------------------------------------

    def search_ticker(self, query: str) -> List[Dict]:
        """Busca tickers pelo nome da empresa (retorna lista de sugestões)."""
        if not self.token:
            return []
        try:
            resp = requests.get(
                f"{_BASE}/quote/list",
                params={"token": self.token, "search": query, "limit": 10},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.json().get("stocks", [])
        except Exception:
            pass
        return []


# Instância global (usa BRAPI_TOKEN do .env automaticamente)
brapi = BrapiClient()
