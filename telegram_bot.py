"""
Bot Telegram para envio de relatórios diários.

Para configurar:
1. Fale com @BotFather no Telegram e crie um bot
2. Copie o token do bot
3. Descubra seu chat_id enviando /start para @userinfobot
4. Configure as variáveis TELEGRAM_TOKEN e TELEGRAM_CHAT_ID
"""

import os
import requests
import time
import threading
from datetime import datetime
from scanner import escanear_mercado, selecionar_backtest
from backtest import gerar_relatorio_backtest, atualizar_backtest

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def enviar_mensagem(texto: str, chat_id: str = None, token: str = None) -> bool:
    """Envia mensagem via Telegram Bot API."""
    tk = token or TELEGRAM_TOKEN
    cid = chat_id or TELEGRAM_CHAT_ID

    if not tk or not cid:
        print("TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não configurados.")
        return False

    url = f"https://api.telegram.org/bot{tk}/sendMessage"

    # Telegram tem limite de 4096 caracteres por mensagem
    partes = [texto[i:i+4000] for i in range(0, len(texto), 4000)]

    for parte in partes:
        payload = {
            "chat_id": cid,
            "text": parte,
            "parse_mode": "Markdown",
        }
        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code != 200:
                print(f"Erro ao enviar Telegram: {r.text}")
                return False
        except Exception as e:
            print(f"Erro Telegram: {e}")
            return False

    return True


def gerar_relatorio_scanner(tickers: list = None, dias_min: int = 180, top: int = 20) -> str:
    """Gera relatório do scanner para envio."""
    df = escanear_mercado(tickers=tickers, dias_min=dias_min, top_n=top)

    if df.empty:
        return "Nenhuma oportunidade encontrada com os filtros atuais."

    linhas = [
        "🔍 *SCANNER DE OPÇÕES — RELATÓRIO DIÁRIO*",
        f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"🎯 Filtro: ≥{dias_min} dias | Liquidez ≥ R$ 1.000/dia",
        f"📊 Top {len(df)} oportunidades",
        "",
    ]

    for i, (_, row) in enumerate(df.iterrows(), 1):
        emoji = "🟢" if row["distorcao_media_pct"] >= 20 else "🟡" if row["distorcao_media_pct"] >= 10 else "⚪"
        linhas.append(f"{emoji} *{i}. {row['simbolo']}* ({row['ativo']})")
        linhas.append(f"  {row['tipo']} | Strike {row['strike']:.2f} | Spot {row['spot']:.2f}")
        linhas.append(f"  Venc: {row['vencimento']} ({row['dias_vencimento']}d)")
        linhas.append(f"  Preço mkt: R$ {row['preco_mercado']:.2f}")
        linhas.append(f"  BS: {row['bs_preco']:.4f} | Binom: {row['binomial_preco']:.4f} | MC: {row['monte_carlo_preco']:.4f}")
        linhas.append(f"  📐 Distorção média: {row['distorcao_media_pct']:.2f}%")
        linhas.append("")

        if i >= 10:
            break

    return "\n".join(linhas)


def enviar_relatorio_diario(tickers: list = None, token: str = None, chat_id: str = None):
    """Envia relatório completo: scanner + backtest."""
    # 1. Relatório do scanner
    relatorio_scanner = gerar_relatorio_scanner(tickers=tickers)
    enviar_mensagem(relatorio_scanner, chat_id=chat_id, token=token)

    # 2. Relatório do backtest
    relatorio_bt = gerar_relatorio_backtest()
    enviar_mensagem(relatorio_bt, chat_id=chat_id, token=token)

    print(f"[{datetime.now()}] Relatórios enviados com sucesso.")


def agendar_diario(hora: int = 18, minuto: int = 0, tickers: list = None, token: str = None, chat_id: str = None):
    """Agenda envio diário em horário específico (roda em thread separada)."""
    def loop():
        while True:
            agora = datetime.now()
            if agora.hour == hora and agora.minute == minuto:
                enviar_relatorio_diario(tickers=tickers, token=token, chat_id=chat_id)
                time.sleep(61)
            time.sleep(30)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    print(f"Relatório diário agendado para {hora:02d}:{minuto:02d}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "enviar":
        tickers = sys.argv[2:] if len(sys.argv) > 2 else None
        enviar_relatorio_diario(tickers=tickers)
    else:
        print("Uso: python telegram_bot.py enviar [PETR4 VALE3 ...]")
