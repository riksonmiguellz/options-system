"""
Scanner de opções: busca oportunidades descorrelacionadas com os modelos de precificação.
"""

import pandas as pd
from datetime import datetime
from oplab_api import get_ativos_com_opcoes_br, get_opcoes, get_ativo, filtrar_opcoes, preco_mercado
from modelos import comparar_modelos, calcular_distorcao

TAXA_SELIC = 0.1050  # 10.50% a.a.


def escanear_ativo(ticker: str, dados_ativo: dict, dias_min: int = 180, liquidez_min: float = 1000) -> list:
    """Escaneia todas as opções de um ativo e retorna oportunidades."""
    opcoes = get_opcoes(ticker)
    if not opcoes:
        return []

    filtradas = filtrar_opcoes(opcoes, dias_min=dias_min, liquidez_min_reais=liquidez_min)
    resultados = []

    spot = dados_ativo.get("close", 0)
    iv = dados_ativo.get("iv_current", 30) / 100
    if spot <= 0:
        return []

    for o in filtradas:
        strike = o.get("strike", 0)
        dias = o.get("days_to_maturity", 0)
        tipo = o.get("category", o.get("type", "CALL"))
        preco_mkt = preco_mercado(o)

        if strike <= 0 or preco_mkt <= 0:
            continue

        T = dias / 365
        tipo_modelo = tipo.lower() if tipo.lower() in ["call", "put"] else "call"

        modelos = comparar_modelos(tipo_modelo, spot, strike, T, TAXA_SELIC, iv)

        distorcao_bs = calcular_distorcao(preco_mkt, modelos["black_scholes"])
        distorcao_binom = calcular_distorcao(preco_mkt, modelos["binomial"])
        distorcao_mc = calcular_distorcao(preco_mkt, modelos["monte_carlo"])
        distorcao_media = calcular_distorcao(preco_mkt, modelos["media_modelos"])

        resultados.append({
            "ativo": ticker,
            "simbolo": o.get("symbol", ""),
            "nome": o.get("name", ""),
            "tipo": tipo,
            "strike": strike,
            "spot": spot,
            "vencimento": o.get("due_date", ""),
            "dias_vencimento": dias,
            "preco_mercado": preco_mkt,
            "bid": o.get("bid", 0),
            "ask": o.get("ask", 0),
            "close": o.get("close", 0),
            "volume": o.get("volume", 0),
            "volume_financeiro": o.get("financial_volume", 0),
            "market_maker": o.get("market_maker", False),
            "tipo_exercicio": o.get("maturity_type", ""),
            "lote": o.get("contract_size", 100),
            "variacao": o.get("variation", 0),
            "bs_preco": modelos["black_scholes"],
            "binomial_preco": modelos["binomial"],
            "monte_carlo_preco": modelos["monte_carlo"],
            "media_modelos": modelos["media_modelos"],
            "distorcao_bs_pct": distorcao_bs,
            "distorcao_binomial_pct": distorcao_binom,
            "distorcao_mc_pct": distorcao_mc,
            "distorcao_media_pct": distorcao_media,
            "iv_ativo_pct": iv * 100,
            "setor": dados_ativo.get("sector", ""),
            "score_oplab": dados_ativo.get("oplab_score", {}).get("value", 0),
            "data_analise": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

    return resultados


def escanear_mercado(tickers: list = None, dias_min: int = 180, liquidez_min: float = 1000, top_n: int = 50) -> pd.DataFrame:
    """Escaneia múltiplos ativos e retorna DataFrame com oportunidades ordenadas."""
    if tickers is None:
        ativos = get_ativos_com_opcoes_br()
        tickers_info = {a["symbol"]: a for a in ativos}
    else:
        tickers_info = {}
        for t in tickers:
            dados = get_ativo(t)
            if dados:
                tickers_info[t] = dados

    todos = []
    for ticker, dados in tickers_info.items():
        resultados = escanear_ativo(ticker, dados, dias_min=dias_min, liquidez_min=liquidez_min)
        todos.extend(resultados)

    if not todos:
        return pd.DataFrame()

    df = pd.DataFrame(todos)
    # Ordenar por maior distorção positiva (opção mais barata vs modelo)
    df = df.sort_values("distorcao_media_pct", ascending=False)

    if top_n > 0:
        df = df.head(top_n)

    return df.reset_index(drop=True)


def selecionar_backtest(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Seleciona as N melhores opções para backtest."""
    if df.empty:
        return df

    # Critérios: maior distorção + maior prazo + liquidez razoável
    df_copia = df.copy()
    df_copia["score_oportunidade"] = (
        df_copia["distorcao_media_pct"] * 0.5 +
        df_copia["dias_vencimento"].clip(upper=365) / 365 * 30 +
        df_copia["volume_financeiro"].clip(upper=1000000).apply(lambda x: min(x / 100000 * 10, 20))
    )

    return df_copia.nlargest(n, "score_oportunidade").reset_index(drop=True)
