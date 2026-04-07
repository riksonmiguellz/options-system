"""
Wrapper completo da API OpLab v3.
"""

import requests
from datetime import datetime, date

OPLAB_TOKEN = "igLO7xOgvGN5C1bWhzmP7mGaIVh6lkddO7MdfP2WGQ2rcSg3uZsEJW012KXqAz5f--6nuuFsZFm9PUpBIqwMX0uQ==--ZDcwMThkZjIwYjI5NTA4ZmNhZTY2NGIxMTJhODE0Njg="
OPLAB_BASE = "https://api.oplab.com.br/v3"
HEADERS = {"Access-Token": OPLAB_TOKEN}
TIMEOUT = 15


def get_todos_ativos():
    """Retorna lista de todos os ativos com opções."""
    try:
        r = requests.get(f"{OPLAB_BASE}/market/stocks", headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def get_ativo(ticker: str):
    """Retorna dados completos de um ativo."""
    try:
        r = requests.get(f"{OPLAB_BASE}/market/stocks/{ticker.upper()}", headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def get_opcoes(ticker: str):
    """Retorna todas as opções de um ativo."""
    try:
        r = requests.get(f"{OPLAB_BASE}/market/options/{ticker.upper()}", headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def get_ativos_com_opcoes_br():
    """Retorna apenas ativos brasileiros com opções e volume > 0."""
    todos = get_todos_ativos()
    return [
        a for a in todos
        if a.get("has_options")
        and a.get("close", 0) > 0
    ]


def filtrar_opcoes(opcoes: list, dias_min: int = 180, liquidez_min_reais: float = 1000) -> list:
    """Filtra opções com critérios mínimos."""
    filtradas = []
    for o in opcoes:
        dias = o.get("days_to_maturity", 0)
        fin_vol = o.get("financial_volume", 0) or 0
        bid = o.get("bid", 0) or 0
        ask = o.get("ask", 0) or 0

        if dias >= dias_min and fin_vol >= liquidez_min_reais and (bid > 0 or ask > 0):
            filtradas.append(o)

    return filtradas


def preco_mercado(opcao: dict) -> float:
    """Retorna o melhor preço de mercado disponível."""
    ask = opcao.get("ask", 0) or 0
    bid = opcao.get("bid", 0) or 0
    close = opcao.get("close", 0) or 0

    if bid > 0 and ask > 0:
        return round((bid + ask) / 2, 4)
    if ask > 0:
        return ask
    if bid > 0:
        return bid
    return close
