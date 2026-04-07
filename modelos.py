"""
Modelos de precificação de opções:
1. Black-Scholes
2. Binomial (Cox-Ross-Rubinstein)
3. Monte Carlo
4. Put-Call Parity (verificação de arbitragem)
"""

import math
import random

def cdf_normal(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

# -----------------------------------------------
# 1. BLACK-SCHOLES
# -----------------------------------------------
def black_scholes(tipo: str, S: float, K: float, T: float, r: float, sigma: float) -> float:
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        if tipo.lower() == "call":
            return max(0.0, S - K)
        return max(0.0, K - S)

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if tipo.lower() == "call":
        preco = S * cdf_normal(d1) - K * math.exp(-r * T) * cdf_normal(d2)
    else:
        preco = K * math.exp(-r * T) * cdf_normal(-d2) - S * cdf_normal(-d1)

    return max(0.0, round(preco, 4))

# -----------------------------------------------
# 2. BINOMIAL (Cox-Ross-Rubinstein)
# -----------------------------------------------
def binomial_crr(tipo: str, S: float, K: float, T: float, r: float, sigma: float, passos: int = 200) -> float:
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        if tipo.lower() == "call":
            return max(0.0, S - K)
        return max(0.0, K - S)

    dt = T / passos
    u = math.exp(sigma * math.sqrt(dt))
    d = 1.0 / u
    p = (math.exp(r * dt) - d) / (u - d)

    precos = [S * (u ** (passos - j)) * (d ** j) for j in range(passos + 1)]

    if tipo.lower() == "call":
        valores = [max(0.0, preco - K) for preco in precos]
    else:
        valores = [max(0.0, K - preco) for preco in precos]

    for i in range(passos - 1, -1, -1):
        for j in range(i + 1):
            valores[j] = math.exp(-r * dt) * (p * valores[j] + (1 - p) * valores[j + 1])

    return max(0.0, round(valores[0], 4))

# -----------------------------------------------
# 3. MONTE CARLO
# -----------------------------------------------
def monte_carlo(tipo: str, S: float, K: float, T: float, r: float, sigma: float, simulacoes: int = 50000) -> float:
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        if tipo.lower() == "call":
            return max(0.0, S - K)
        return max(0.0, K - S)

    random.seed(42)
    soma_payoff = 0.0

    for _ in range(simulacoes):
        z = random.gauss(0, 1)
        ST = S * math.exp((r - 0.5 * sigma**2) * T + sigma * math.sqrt(T) * z)

        if tipo.lower() == "call":
            payoff = max(0.0, ST - K)
        else:
            payoff = max(0.0, K - ST)

        soma_payoff += payoff

    preco = math.exp(-r * T) * (soma_payoff / simulacoes)
    return max(0.0, round(preco, 4))

# -----------------------------------------------
# 4. PUT-CALL PARITY (verificação)
# -----------------------------------------------
def put_call_parity_call(put_price: float, S: float, K: float, T: float, r: float) -> float:
    """Dado o preço da PUT, calcula o preço teórico da CALL via paridade."""
    if T <= 0:
        return max(0.0, S - K)
    call = put_price + S - K * math.exp(-r * T)
    return max(0.0, round(call, 4))

def put_call_parity_put(call_price: float, S: float, K: float, T: float, r: float) -> float:
    """Dado o preço da CALL, calcula o preço teórico da PUT via paridade."""
    if T <= 0:
        return max(0.0, K - S)
    put = call_price - S + K * math.exp(-r * T)
    return max(0.0, round(put, 4))

# -----------------------------------------------
# COMPARAR TODOS OS MODELOS
# -----------------------------------------------
def comparar_modelos(tipo: str, S: float, K: float, T: float, r: float, sigma: float) -> dict:
    bs = black_scholes(tipo, S, K, T, r, sigma)
    binom = binomial_crr(tipo, S, K, T, r, sigma)
    mc = monte_carlo(tipo, S, K, T, r, sigma)

    media = round((bs + binom + mc) / 3, 4)

    return {
        "black_scholes": bs,
        "binomial": binom,
        "monte_carlo": mc,
        "media_modelos": media,
    }

def calcular_distorcao(preco_mercado: float, preco_teorico: float) -> float:
    if preco_teorico <= 0:
        return 0.0
    return round(((preco_teorico - preco_mercado) / preco_teorico) * 100, 2)
