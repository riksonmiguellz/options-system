import streamlit as st
from datetime import datetime
import csv
import os
import math
import pandas as pd
import altair as alt
from io import BytesIO

st.set_page_config(page_title="Sistema de Análise de Opções", layout="wide")

# -----------------------------
# AUTENTICAÇÃO
# -----------------------------
APP_USER = "admin"
APP_PASS = "admin123"

if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False
if "usuario" not in st.session_state:
    st.session_state["usuario"] = ""

if not st.session_state["autenticado"]:
    st.title("Login")
    usuario = st.text_input("Usuário")
    senha = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if usuario == APP_USER and senha == APP_PASS:
            st.session_state["autenticado"] = True
            st.session_state["usuario"] = usuario
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
    st.stop()

CSV_FILE = "trades_log.csv"

COLUNAS_CSV = [
    "data",
    "ativo",
    "tipo",
    "quantidade_contratos",
    "lote_por_contrato",
    "spot",
    "strike",
    "dias_vencimento",
    "vol_implicita_pct",
    "taxa_risco_pct",
    "preco_pago",
    "preco_teorico",
    "distorcao_pct",
    "prazo_score",
    "desconto_score",
    "liquidez_score",
    "probabilidade_score",
    "ativo_score",
    "assimetria_score",
    "media_final",
    "decisao",
    "tese",
    "risco_principal",
    "status_operacao",
    "data_saida",
    "observacao_pos_operacao",
    "resultado_real"
]

# -----------------------------
# ARQUIVOS
# -----------------------------
def garantir_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            writer.writerow(COLUNAS_CSV)

def salvar_csv(linha):
    with open(CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(linha)

def carregar_historico():
    if not os.path.exists(CSV_FILE):
        return pd.DataFrame(columns=COLUNAS_CSV)

    try:
        df = pd.read_csv(
            CSV_FILE,
            encoding="utf-8-sig",
            sep=",",
            engine="python",
            on_bad_lines="skip"
        )

        for col in COLUNAS_CSV:
            if col not in df.columns:
                df[col] = ""

        df = df[COLUNAS_CSV]
        return df
    except Exception:
        return pd.DataFrame(columns=COLUNAS_CSV)

def salvar_historico_df(df: pd.DataFrame):
    df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_ALL)

def dataframe_para_excel_bytes(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Historico")
    return output.getvalue()

# -----------------------------
# REGRAS / MODELO
# -----------------------------
def detectar_tipo_texto(texto: str) -> str:
    t = str(texto).lower()
    if any(p in t for p in ["transcrição", "call", "áudio", "reunião", "aula"]):
        return "Transcrição / fala"
    if any(p in t for p in ["dcf", "wacc", "valuation", "múltiplo", "preço-alvo"]):
        return "Valuation / fundamentos"
    if any(p in t for p in ["call", "put", "strike", "black-scholes", "theta", "delta", "itm", "otm", "volatilidade"]):
        return "Opções / derivativos"
    return "Tese / ideia geral"

def cdf_normal(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

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

def score_prazo(dias: int) -> int:
    if dias >= 180:
        return 5
    if dias >= 120:
        return 4
    if dias >= 60:
        return 3
    if dias >= 30:
        return 2
    return 1

def calcular_distorcao(preco_pago: float, preco_teorico: float) -> float:
    if preco_teorico <= 0:
        return 0.0
    return round(((preco_teorico - preco_pago) / preco_teorico) * 100, 2)

def score_desconto(preco_pago: float, preco_teorico: float) -> int:
    if preco_teorico <= 0:
        return 1

    desconto = (preco_teorico - preco_pago) / preco_teorico

    if desconto >= 0.60:
        return 5
    if desconto >= 0.40:
        return 4
    if desconto >= 0.25:
        return 3
    if desconto >= 0.10:
        return 2
    return 1

def score_liquidez(nivel: str) -> int:
    nivel = str(nivel).lower()
    if nivel == "alta":
        return 5
    if nivel == "média":
        return 3
    return 2

def score_probabilidade(texto: str, dias: int, spot: float, strike: float, tipo: str) -> int:
    t = str(texto).lower()
    pontos = 2

    if dias >= 120:
        pontos += 1

    if tipo.lower() == "call" and spot >= strike * 0.9:
        pontos += 1
    if tipo.lower() == "put" and spot <= strike * 1.1:
        pontos += 1

    palavras = ["probabilidade", "estatística", "cenário favorável", "tese forte", "validação"]
    for p in palavras:
        if p in t:
            pontos += 1

    return min(pontos, 5)

def score_ativo(texto: str) -> int:
    t = str(texto).lower()
    if any(p in t for p in ["empresa sólida", "bons resultados", "lucro", "crescimento", "fundamento forte", "ativo forte"]):
        return 4
    if any(p in t for p in ["empresa ruim", "risco de quebrar", "fundamento fraco", "ativo fraco"]):
        return 1
    return 3

def score_assimetria(texto: str, preco_pago: float, distorcao: float) -> int:
    t = str(texto).lower()
    pontos = 2

    if preco_pago <= 1:
        pontos += 1
    if distorcao >= 40:
        pontos += 1

    palavras = ["assimetria", "ganhar muito", "perder pouco", "explosão", "distorção"]
    for p in palavras:
        if p in t:
            pontos += 1

    return min(pontos, 5)

def decisao_final(media: float) -> str:
    if media >= 4.2:
        return "Executar forte"
    if media >= 3.4:
        return "Executar pequeno"
    if media >= 2.5:
        return "Observar"
    return "Evitar"

def risco_principal(liquidez: str, dias: int, texto: str, sigma_pct: float) -> str:
    t = str(texto).lower()
    if str(liquidez).lower() == "baixa":
        return "Liquidez ruim pode dificultar a entrada e a saída da operação."
    if dias < 30:
        return "Prazo curto aumenta a pressão do tempo contra a opção."
    if sigma_pct >= 60:
        return "Volatilidade muito alta pode inflar o preço e aumentar o risco de correção."
    if "valuation" in t and "premissa" in t:
        return "A tese pode depender demais de premissas frágeis."
    return "Risco de a tese não se confirmar ou de uma variável importante mudar."

def validacao() -> str:
    return "A tese melhora se o ativo andar na direção esperada, a distorção diminuir e o cenário principal continuar válido."

def invalidacao() -> str:
    return "A tese enfraquece se o ativo não evoluir, a liquidez piorar, o tempo apertar demais ou a premissa central falhar."

# -----------------------------
# PAYOFF E MÉTRICAS
# -----------------------------
def gerar_payoff(tipo: str, strike: float, premio: float, spot_ref: float, contratos: int, lote: int):
    if spot_ref <= 0:
        spot_ref = strike if strike > 0 else 1

    inicio = max(0.01, spot_ref * 0.5)
    fim = spot_ref * 1.5
    passos = 121

    precos = [inicio + (fim - inicio) * i / (passos - 1) for i in range(passos)]
    payoff_unitario = []
    payoff_total = []

    multiplicador = contratos * lote

    for s in precos:
        if tipo.lower() == "call":
            valor = max(0, s - strike) - premio
        else:
            valor = max(0, strike - s) - premio

        payoff_unitario.append(round(valor, 4))
        payoff_total.append(round(valor * multiplicador, 4))

    df = pd.DataFrame({
        "Preço do ativo no vencimento": precos,
        "Resultado por opção": payoff_unitario,
        "Resultado total": payoff_total
    })

    df["Zona"] = df["Resultado total"].apply(lambda x: "Lucro" if x >= 0 else "Prejuízo")
    return df

def calcular_break_even(tipo: str, strike: float, premio: float):
    if tipo.lower() == "call":
        return strike + premio
    return strike - premio

def perda_maxima_total(premio: float, contratos: int, lote: int):
    return round(premio * contratos * lote, 2)

def ganho_maximo_total(tipo: str, strike: float, premio: float, contratos: int, lote: int):
    if tipo.lower() == "call":
        return "Ilimitado"
    return round((strike - premio) * contratos * lote, 2)

def custo_total(premio: float, contratos: int, lote: int):
    return round(premio * contratos * lote, 2)

# -----------------------------
# APP
# -----------------------------
garantir_csv()

with st.sidebar:
    st.write(f"Usuário: **{st.session_state.get('usuario', '')}**")
    if st.button("Sair"):
        st.session_state["autenticado"] = False
        st.session_state["usuario"] = ""
        st.rerun()

tab1, tab2 = st.tabs(["Nova análise", "Histórico"])

with tab1:
    st.title("Sistema de Análise de Opções")
    st.caption("Leitura prática, linguagem simples e análise visual")

    col1, col2 = st.columns(2)

    with col1:
        ativo = st.text_input("Ativo", placeholder="Ex: PETR4")
        tipo = st.selectbox("Tipo da opção", ["Call", "Put"])
        quantidade_contratos = st.number_input("Quantidade de contratos", min_value=1, step=1, value=1)
        lote_por_contrato = st.number_input("Lote por contrato", min_value=1, step=1, value=100)
        spot = st.number_input("Preço atual do ativo", min_value=0.0, format="%.2f")
        strike = st.number_input("Strike", min_value=0.0, format="%.2f")
        dias_vencimento = st.number_input("Dias até o vencimento", min_value=1, step=1)
        vol_implicita_pct = st.number_input("Volatilidade implícita (%)", min_value=0.0, format="%.2f", value=30.00)
        taxa_risco_pct = st.number_input("Taxa livre de risco (%)", min_value=0.0, format="%.2f", value=10.50)
        preco_pago = st.number_input("Preço pago por opção", min_value=0.0, format="%.2f")

    with col2:
        liquidez = st.selectbox("Liquidez", ["Baixa", "Média", "Alta"])
        tese = st.text_area(
            "Tese / observações",
            height=160,
            placeholder="Explique a ideia com suas palavras."
        )
        status_operacao = st.selectbox("Status da operação", ["Aberta", "Encerrada", "Stopada", "Gain"])
        data_saida = st.text_input("Data de saída (opcional)", placeholder="Ex: 2026-04-07")
        observacao_pos_operacao = st.text_area(
            "Observação pós-operação",
            height=70,
            placeholder="Ex: entrei pequeno, mercado piorou, tese ficou mais forte..."
        )
        resultado_real = st.number_input(
            "Resultado real da operação (opcional)",
            value=0.0,
            format="%.2f"
        )

    if st.button("Analisar"):
        tipo_material = detectar_tipo_texto(tese)

        T = dias_vencimento / 365
        sigma = vol_implicita_pct / 100
        r = taxa_risco_pct / 100

        preco_teorico = black_scholes(tipo, spot, strike, T, r, sigma)
        distorcao = calcular_distorcao(preco_pago, preco_teorico)

        prazo_s = score_prazo(dias_vencimento)
        desconto_s = score_desconto(preco_pago, preco_teorico)
        liquidez_s = score_liquidez(liquidez)
        prob_s = score_probabilidade(tese, dias_vencimento, spot, strike, tipo)
        ativo_s = score_ativo(tese)
        assimetria_s = score_assimetria(tese, preco_pago, distorcao)

        media = round((prazo_s + desconto_s + liquidez_s + prob_s + ativo_s + assimetria_s) / 6, 2)
        decisao = decisao_final(media)
        risco = risco_principal(liquidez, dias_vencimento, tese, vol_implicita_pct)
        val = validacao()
        inval = invalidacao()
        data_analise = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        break_even = calcular_break_even(tipo, strike, preco_pago)
        custo_total_operacao = custo_total(preco_pago, quantidade_contratos, lote_por_contrato)
        perda_max = perda_maxima_total(preco_pago, quantidade_contratos, lote_por_contrato)
        ganho_max = ganho_maximo_total(tipo, strike, preco_pago, quantidade_contratos, lote_por_contrato)

        st.subheader("Resumo da análise")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Preço teórico", f"{preco_teorico:.4f}")
        c2.metric("Distorção", f"{distorcao}%")
        c3.metric("Nota média", f"{media}/5")
        c4.metric("Decisão", decisao)

        st.subheader("Operação em linguagem simples")
        st.write(f"**Ativo:** {ativo if ativo else '-'}")
        st.write(f"**Tipo:** {tipo}")
        st.write(f"**Quantidade de contratos:** {quantidade_contratos}")
        st.write(f"**Lote por contrato:** {lote_por_contrato}")
        st.write(f"**Preço atual do ativo:** {spot:.2f}")
        st.write(f"**Strike:** {strike:.2f}")
        st.write(f"**Dias até o vencimento:** {dias_vencimento}")
        st.write(f"**Preço pago por opção:** {preco_pago:.2f}")
        st.write(f"**Liquidez:** {liquidez}")
        st.write(f"**Status da operação:** {status_operacao}")
        st.write(f"**Data de saída:** {data_saida if data_saida else '-'}")
        st.write(f"**Tipo de material identificado:** {tipo_material}")

        st.subheader("Leitura rápida da operação")
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Preço de equilíbrio", f"{break_even:.2f}")
        c6.metric("Custo total", f"{custo_total_operacao:.2f}")
        c7.metric("Perda máxima total", f"{perda_max:.2f}")
        c8.metric("Ganho máximo total", str(ganho_max))

        if distorcao >= 0:
            st.success(f"A opção está {distorcao}% abaixo do preço teórico calculado.")
        else:
            st.error(f"A opção está {abs(distorcao)}% acima do preço teórico calculado.")

        st.subheader("Comparação entre preço pago e preço teórico")
        comparacao_df = pd.DataFrame({
            "Métrica": ["Preço pago", "Preço teórico"],
            "Valor": [preco_pago, preco_teorico]
        })

        graf_barra = alt.Chart(comparacao_df).mark_bar(size=60).encode(
            x=alt.X("Métrica:N", title=""),
            y=alt.Y("Valor:Q", title="Valor"),
            color=alt.Color(
                "Métrica:N",
                scale=alt.Scale(
                    domain=["Preço pago", "Preço teórico"],
                    range=["#dc2626", "#16a34a"]
                ),
                legend=None
            ),
            tooltip=["Métrica", alt.Tooltip("Valor:Q", format=".4f")]
        ).properties(height=320)

        st.altair_chart(graf_barra, use_container_width=True)

        st.subheader("Scorecard")
        st.write(f"**Prazo:** {prazo_s}/5")
        st.write(f"**Desconto:** {desconto_s}/5")
        st.write(f"**Liquidez:** {liquidez_s}/5")
        st.write(f"**Probabilidade:** {prob_s}/5")
        st.write(f"**Qualidade do ativo:** {ativo_s}/5")
        st.write(f"**Assimetria:** {assimetria_s}/5")

        st.subheader("O que fortalece a tese")
        st.write(val)

        st.subheader("O que enfraquece a tese")
        st.write(inval)

        st.subheader("Risco principal")
        st.write(risco)

        st.subheader("Gráfico de payoff no vencimento")
        payoff_df = gerar_payoff(tipo, strike, preco_pago, spot, quantidade_contratos, lote_por_contrato)

        base = alt.Chart(payoff_df).encode(
            x=alt.X("Preço do ativo no vencimento:Q", title="Preço do ativo no vencimento"),
            y=alt.Y("Resultado total:Q", title="Lucro / prejuízo total"),
            tooltip=[
                alt.Tooltip("Preço do ativo no vencimento:Q", format=".2f"),
                alt.Tooltip("Resultado total:Q", format=".2f"),
                alt.Tooltip("Zona:N")
            ]
        )

        area = base.mark_area(opacity=0.35).encode(
            color=alt.Color(
                "Zona:N",
                scale=alt.Scale(domain=["Lucro", "Prejuízo"], range=["#16a34a", "#dc2626"]),
                legend=None
            )
        )

        linha = base.mark_line(size=3, color="#2563eb")

        linha_zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#94a3b8").encode(y="y:Q")

        linha_break = alt.Chart(pd.DataFrame({
            "x": [break_even],
            "label": [f"Break-even: {break_even:.2f}"]
        })).mark_rule(color="#f59e0b", strokeDash=[6, 4]).encode(
            x="x:Q"
        )

        texto_break = alt.Chart(pd.DataFrame({
            "x": [break_even],
            "y": [0],
            "label": [f"Break-even: {break_even:.2f}"]
        })).mark_text(
            align="left",
            dx=8,
            dy=-10,
            color="#f59e0b"
        ).encode(
            x="x:Q",
            y="y:Q",
            text="label:N"
        )

        linha_strike = alt.Chart(pd.DataFrame({
            "x": [strike],
            "label": [f"Strike: {strike:.2f}"]
        })).mark_rule(color="#64748b", strokeDash=[2, 2]).encode(
            x="x:Q"
        )

        texto_strike = alt.Chart(pd.DataFrame({
            "x": [strike],
            "y": [0],
            "label": [f"Strike: {strike:.2f}"]
        })).mark_text(
            align="right",
            dx=-8,
            dy=14,
            color="#64748b"
        ).encode(
            x="x:Q",
            y="y:Q",
            text="label:N"
        )

        chart = (area + linha + linha_zero + linha_break + texto_break + linha_strike + texto_strike).properties(
            height=420
        ).interactive()

        st.altair_chart(chart, use_container_width=True)

        st.caption(
            "Área verde representa lucro. Área vermelha representa prejuízo. "
            "A linha amarela mostra o preço de equilíbrio e a cinza mostra o strike."
        )

        resultado = f"""# Sistema de Análise de Opções

## Resumo da operação
Ativo: {ativo}
Tipo: {tipo}
Quantidade de contratos: {quantidade_contratos}
Lote por contrato: {lote_por_contrato}
Preço atual do ativo: {spot:.2f}
Strike: {strike:.2f}
Dias até vencimento: {dias_vencimento}
Volatilidade implícita: {vol_implicita_pct:.2f}%
Taxa livre de risco: {taxa_risco_pct:.2f}%
Preço pago por opção: {preco_pago:.2f}
Preço teórico: {preco_teorico:.4f}
Liquidez: {liquidez}

## Tese
{tese}

## Leitura rápida
Preço de equilíbrio: {break_even:.2f}
Custo total: {custo_total_operacao:.2f}
Perda máxima total: {perda_max:.2f}
Ganho máximo total: {ganho_max}

## Distorção
{distorcao}%

## Scorecard
Prazo: {prazo_s}/5
Desconto: {desconto_s}/5
Liquidez: {liquidez_s}/5
Probabilidade: {prob_s}/5
Qualidade do ativo: {ativo_s}/5
Assimetria: {assimetria_s}/5
Média final: {media}/5

## O que fortalece a tese
{val}

## O que enfraquece a tese
{inval}

## Risco principal
{risco}

## Status da operação
{status_operacao}

## Data de saída
{data_saida}

## Observação pós-operação
{observacao_pos_operacao}

## Resultado real
{resultado_real}

## Decisão final
{decisao}

## Data
{data_analise}
"""

        nome_arquivo = f"output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(nome_arquivo, "w", encoding="utf-8") as f:
            f.write(resultado)

        salvar_csv([
            data_analise,
            ativo,
            tipo,
            quantidade_contratos,
            lote_por_contrato,
            spot,
            strike,
            dias_vencimento,
            vol_implicita_pct,
            taxa_risco_pct,
            preco_pago,
            preco_teorico,
            distorcao,
            prazo_s,
            desconto_s,
            liquidez_s,
            prob_s,
            ativo_s,
            assimetria_s,
            media,
            decisao,
            tese,
            risco,
            status_operacao,
            data_saida,
            observacao_pos_operacao,
            resultado_real
        ])

        st.info(f"Análise salva em: {nome_arquivo}")
        st.info(f"Registro adicionado em: {CSV_FILE}")

with tab2:
    st.title("Histórico das análises")

    df = carregar_historico()

    if df.empty:
        st.warning("Ainda não há histórico válido para mostrar.")
        st.caption("Se você tinha um CSV antigo bagunçado, esta versão ignora linhas ruins.")
    else:
        st.subheader("Dashboard de performance")

        df["media_final"] = pd.to_numeric(df["media_final"], errors="coerce")
        df["resultado_real"] = pd.to_numeric(df["resultado_real"], errors="coerce")

        total_operacoes = len(df)
        resultado_acumulado = df["resultado_real"].fillna(0).sum()

        encerradas = df[df["status_operacao"].astype(str).isin(["Encerrada", "Gain", "Stopada"])]
        ganhadoras = encerradas[encerradas["resultado_real"] > 0]
        taxa_acerto = 0.0
        if len(encerradas) > 0:
            taxa_acerto = round((len(ganhadoras) / len(encerradas)) * 100, 2)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total de operações", total_operacoes)
        c2.metric("Resultado acumulado", f"{resultado_acumulado:.2f}")
        c3.metric("Taxa de acerto", f"{taxa_acerto}%")
        c4.metric("Média das oportunidades", f"{df['media_final'].mean():.2f}" if not df["media_final"].dropna().empty else "-")

        st.subheader("Filtros")

        ativos = ["Todos"] + sorted([str(x) for x in df["ativo"].dropna().unique().tolist() if str(x).strip()])
        decisoes = ["Todas"] + sorted([str(x) for x in df["decisao"].dropna().unique().tolist() if str(x).strip()])
        status_lista = ["Todos"] + sorted([str(x) for x in df["status_operacao"].dropna().unique().tolist() if str(x).strip()])

        f1, f2, f3 = st.columns(3)
        with f1:
            ativo_filtro = st.selectbox("Filtrar por ativo", ativos)
        with f2:
            decisao_filtro = st.selectbox("Filtrar por decisão", decisoes)
        with f3:
            status_filtro = st.selectbox("Filtrar por status", status_lista)

        df_filtrado = df.copy()

        if ativo_filtro != "Todos":
            df_filtrado = df_filtrado[df_filtrado["ativo"].astype(str) == ativo_filtro]

        if decisao_filtro != "Todas":
            df_filtrado = df_filtrado[df_filtrado["decisao"].astype(str) == decisao_filtro]

        if status_filtro != "Todos":
            df_filtrado = df_filtrado[df_filtrado["status_operacao"].astype(str) == status_filtro]

        st.subheader("Tabela do histórico")
        st.dataframe(df_filtrado, use_container_width=True)

        excel_bytes = dataframe_para_excel_bytes(df_filtrado)
        st.download_button(
            label="Baixar histórico em Excel",
            data=excel_bytes,
            file_name="historico_analises.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        st.subheader("P&L por ativo")
        pnl_ativo = df.groupby("ativo", dropna=False)["resultado_real"].sum().reset_index()
        pnl_ativo.columns = ["Ativo", "Resultado real"]

        graf_pnl = alt.Chart(pnl_ativo).mark_bar().encode(
            x=alt.X("Ativo:N", sort="-y"),
            y=alt.Y("Resultado real:Q"),
            color=alt.condition(
                alt.datum["Resultado real"] >= 0,
                alt.value("#16a34a"),
                alt.value("#dc2626")
            ),
            tooltip=["Ativo", alt.Tooltip("Resultado real:Q", format=".2f")]
        ).properties(height=320)

        st.altair_chart(graf_pnl, use_container_width=True)

        st.subheader("Distribuição por status")
        resumo_status = df["status_operacao"].value_counts().reset_index()
        resumo_status.columns = ["Status", "Quantidade"]

        graf_status = alt.Chart(resumo_status).mark_bar().encode(
            x=alt.X("Status:N", sort="-y"),
            y=alt.Y("Quantidade:Q"),
            tooltip=["Status", "Quantidade"]
        ).properties(height=320)

        st.altair_chart(graf_status, use_container_width=True)

        st.subheader("Editar registro do histórico")

        opcoes_registro = [
            f"{idx} | {str(df_filtrado.iloc[idx]['data'])} | {str(df_filtrado.iloc[idx]['ativo'])} | {str(df_filtrado.iloc[idx]['tipo'])}"
            for idx in range(len(df_filtrado))
        ]

        if opcoes_registro:
            registro_escolhido = st.selectbox("Escolha um registro para editar", opcoes_registro)

            idx_local = int(registro_escolhido.split(" | ")[0])
            idx_real = df_filtrado.index[idx_local]

            observacao_atual = str(df.loc[idx_real, "observacao_pos_operacao"]) if "observacao_pos_operacao" in df.columns else ""
            resultado_atual = pd.to_numeric(df.loc[idx_real, "resultado_real"], errors="coerce") if "resultado_real" in df.columns else 0.0
            status_atual = str(df.loc[idx_real, "status_operacao"]) if "status_operacao" in df.columns else "Aberta"
            data_saida_atual = str(df.loc[idx_real, "data_saida"]) if "data_saida" in df.columns else ""

            if pd.isna(resultado_atual):
                resultado_atual = 0.0

            novo_status = st.selectbox(
                "Editar status da operação",
                ["Aberta", "Encerrada", "Stopada", "Gain"],
                index=["Aberta", "Encerrada", "Stopada", "Gain"].index(status_atual) if status_atual in ["Aberta", "Encerrada", "Stopada", "Gain"] else 0
            )

            nova_data_saida = st.text_input(
                "Editar data de saída",
                value=data_saida_atual
            )

            nova_observacao = st.text_area(
                "Editar observação pós-operação",
                value=observacao_atual,
                height=100
            )

            novo_resultado = st.number_input(
                "Editar resultado real",
                value=float(resultado_atual),
                format="%.2f"
            )

            if st.button("Salvar edição do registro"):
                df.loc[idx_real, "status_operacao"] = novo_status
                df.loc[idx_real, "data_saida"] = nova_data_saida
                df.loc[idx_real, "observacao_pos_operacao"] = nova_observacao
                df.loc[idx_real, "resultado_real"] = novo_resultado
                salvar_historico_df(df)
                st.success("Registro atualizado com sucesso. Recarregue a página para ver os dados atualizados.")
        else:
            st.info("Nenhum registro disponível para edição com os filtros atuais.")