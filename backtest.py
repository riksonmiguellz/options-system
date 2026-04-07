"""
Sistema de backtest: acompanha opções selecionadas e registra variações diárias.
"""

import os
import json
import pandas as pd
from datetime import datetime
from oplab_api import get_opcoes, get_ativo, preco_mercado
from modelos import comparar_modelos

BACKTEST_FILE = "backtest_carteira.json"
BACKTEST_HISTORICO = "backtest_historico.csv"
TAXA_SELIC = 0.1050


def carregar_carteira() -> list:
    if not os.path.exists(BACKTEST_FILE):
        return []
    with open(BACKTEST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_carteira(carteira: list):
    with open(BACKTEST_FILE, "w", encoding="utf-8") as f:
        json.dump(carteira, f, ensure_ascii=False, indent=2)


def adicionar_ao_backtest(opcoes_df: pd.DataFrame):
    """Adiciona opções selecionadas à carteira de backtest."""
    carteira = carregar_carteira()
    simbolos_existentes = {item["simbolo"] for item in carteira}

    for _, row in opcoes_df.iterrows():
        if row["simbolo"] not in simbolos_existentes:
            carteira.append({
                "simbolo": row["simbolo"],
                "ativo": row["ativo"],
                "tipo": row["tipo"],
                "strike": row["strike"],
                "vencimento": row["vencimento"],
                "preco_entrada": row["preco_mercado"],
                "data_entrada": datetime.now().strftime("%Y-%m-%d"),
                "dias_entrada": row["dias_vencimento"],
                "distorcao_entrada": row["distorcao_media_pct"],
                "ativo_spot_entrada": row["spot"],
                "status": "ativo",
            })

    salvar_carteira(carteira)
    return carteira


def atualizar_backtest() -> pd.DataFrame:
    """Atualiza preços de todas as opções na carteira de backtest."""
    carteira = carregar_carteira()
    if not carteira:
        return pd.DataFrame()

    registros = []
    ativos_cache = {}

    for item in carteira:
        if item["status"] != "ativo":
            continue

        ticker = item["ativo"]

        if ticker not in ativos_cache:
            dados_ativo = get_ativo(ticker)
            opcoes = get_opcoes(ticker)
            ativos_cache[ticker] = (dados_ativo, opcoes)
        else:
            dados_ativo, opcoes = ativos_cache[ticker]

        if not dados_ativo or not opcoes:
            continue

        opcao_atual = None
        for o in opcoes:
            if o.get("symbol") == item["simbolo"]:
                opcao_atual = o
                break

        if not opcao_atual:
            item["status"] = "vencida_ou_removida"
            continue

        spot = dados_ativo.get("close", 0)
        iv = dados_ativo.get("iv_current", 30) / 100
        preco_atual = preco_mercado(opcao_atual)
        dias_atual = opcao_atual.get("days_to_maturity", 0)

        if dias_atual <= 0:
            item["status"] = "vencida_ou_removida"
            continue

        T = dias_atual / 365
        tipo_modelo = item["tipo"].lower()
        modelos = comparar_modelos(tipo_modelo, spot, item["strike"], T, TAXA_SELIC, iv)

        variacao_preco = 0
        if item["preco_entrada"] > 0:
            variacao_preco = round(((preco_atual - item["preco_entrada"]) / item["preco_entrada"]) * 100, 2)

        pnl_unitario = preco_atual - item["preco_entrada"]
        pnl_zona = "LUCRO" if pnl_unitario >= 0 else "PREJUÍZO"

        registro = {
            "data": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "simbolo": item["simbolo"],
            "ativo": ticker,
            "tipo": item["tipo"],
            "strike": item["strike"],
            "vencimento": item["vencimento"],
            "dias_restantes": dias_atual,
            "spot_atual": spot,
            "preco_entrada": item["preco_entrada"],
            "preco_atual": preco_atual,
            "pnl_unitario": round(pnl_unitario, 4),
            "zona": pnl_zona,
            "variacao_pct": variacao_preco,
            "bs_preco": modelos["black_scholes"],
            "binomial_preco": modelos["binomial"],
            "mc_preco": modelos["monte_carlo"],
            "heston_preco": modelos["heston"],
            "media_modelos": modelos["media_modelos"],
            "distorcao_atual_pct": round(((modelos["media_modelos"] - preco_atual) / modelos["media_modelos"]) * 100, 2) if modelos["media_modelos"] > 0 else 0,
            "distorcao_entrada_pct": item["distorcao_entrada"],
            "status": item["status"],
        }
        registros.append(registro)

    salvar_carteira(carteira)

    if registros:
        df_novo = pd.DataFrame(registros)
        if os.path.exists(BACKTEST_HISTORICO):
            df_antigo = pd.read_csv(BACKTEST_HISTORICO, encoding="utf-8-sig")
            df_total = pd.concat([df_antigo, df_novo], ignore_index=True)
        else:
            df_total = df_novo
        df_total.to_csv(BACKTEST_HISTORICO, index=False, encoding="utf-8-sig")
        return df_novo

    return pd.DataFrame()


def carregar_historico_backtest() -> pd.DataFrame:
    if not os.path.exists(BACKTEST_HISTORICO):
        return pd.DataFrame()
    return pd.read_csv(BACKTEST_HISTORICO, encoding="utf-8-sig")


def gerar_relatorio_backtest() -> str:
    """Gera relatório em texto para envio (Telegram, etc)."""
    carteira = carregar_carteira()
    ativos_bt = [c for c in carteira if c["status"] == "ativo"]

    if not ativos_bt:
        return "Nenhuma opção ativa no backtest."

    df = atualizar_backtest()
    if df.empty:
        return "Não foi possível atualizar os dados do backtest."

    linhas = ["📊 *RELATÓRIO DIÁRIO DE BACKTEST*", f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}", ""]

    for _, row in df.iterrows():
        emoji = "🟢" if row["variacao_pct"] >= 0 else "🔴"
        dist_emoji = "✅" if row["distorcao_atual_pct"] > 0 else "⚠️"

        zona_emoji = "💰" if row.get("zona") == "LUCRO" else "💸"
        linhas.append(f"{emoji} *{row['simbolo']}* ({row['ativo']}) {zona_emoji} {row.get('zona', '')}")
        linhas.append(f"  Tipo: {row['tipo']} | Strike: {row['strike']:.2f}")
        linhas.append(f"  Venc: {row['vencimento']} ({row['dias_restantes']}d)")
        linhas.append(f"  Entrada: R$ {row['preco_entrada']:.2f} → Atual: R$ {row['preco_atual']:.2f} ({row['variacao_pct']:+.2f}%)")
        linhas.append(f"  P&L unitário: R$ {row.get('pnl_unitario', 0):+.4f}")
        linhas.append(f"  {dist_emoji} Distorção: {row['distorcao_atual_pct']:.2f}% (entrada: {row['distorcao_entrada_pct']:.2f}%)")
        linhas.append(f"  BS: {row['bs_preco']:.4f} | Binom: {row['binomial_preco']:.4f} | MC: {row['mc_preco']:.4f} | Heston: {row.get('heston_preco', 0):.4f}")
        linhas.append("")

    ganhadoras = len(df[df["variacao_pct"] > 0])
    perdedoras = len(df[df["variacao_pct"] <= 0])
    media_var = df["variacao_pct"].mean()

    linhas.append(f"📈 Ganhadoras: {ganhadoras} | 📉 Perdedoras: {perdedoras}")
    linhas.append(f"📊 Variação média: {media_var:+.2f}%")

    return "\n".join(linhas)
