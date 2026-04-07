import streamlit as st
from datetime import datetime, date
import csv
import os
import math
import pandas as pd
import altair as alt
from io import BytesIO

from modelos import black_scholes, binomial_crr, monte_carlo, comparar_modelos, calcular_distorcao, cdf_normal
from oplab_api import get_ativo, get_opcoes, get_ativos_com_opcoes_br, filtrar_opcoes, preco_mercado
from scanner import escanear_mercado, selecionar_backtest, escanear_ativo
from backtest import (
    carregar_carteira, salvar_carteira, adicionar_ao_backtest,
    atualizar_backtest, carregar_historico_backtest, gerar_relatorio_backtest
)
from telegram_bot import enviar_mensagem, enviar_relatorio_diario

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

# -----------------------------
# ARQUIVOS
# -----------------------------
CSV_FILE = "trades_log.csv"

COLUNAS_CSV = [
    "data", "ativo", "tipo", "quantidade_contratos", "lote_por_contrato",
    "spot", "strike", "dias_vencimento", "vol_implicita_pct", "taxa_risco_pct",
    "preco_pago", "preco_teorico", "distorcao_pct", "prazo_score", "desconto_score",
    "liquidez_score", "probabilidade_score", "ativo_score", "assimetria_score",
    "media_final", "decisao", "tese", "risco_principal", "status_operacao",
    "data_saida", "observacao_pos_operacao", "resultado_real"
]

def garantir_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f, quoting=csv.QUOTE_ALL).writerow(COLUNAS_CSV)

def salvar_csv(linha):
    with open(CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f, quoting=csv.QUOTE_ALL).writerow(linha)

def carregar_historico():
    if not os.path.exists(CSV_FILE):
        return pd.DataFrame(columns=COLUNAS_CSV)
    try:
        df = pd.read_csv(CSV_FILE, encoding="utf-8-sig", sep=",", engine="python", on_bad_lines="skip")
        for col in COLUNAS_CSV:
            if col not in df.columns:
                df[col] = ""
        return df[COLUNAS_CSV]
    except Exception:
        return pd.DataFrame(columns=COLUNAS_CSV)

def salvar_historico_df(df):
    df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_ALL)

def dataframe_para_excel_bytes(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Dados")
    return output.getvalue()

# -----------------------------
# SCORES
# -----------------------------
def score_prazo(dias):
    if dias >= 180: return 5
    if dias >= 120: return 4
    if dias >= 60: return 3
    if dias >= 30: return 2
    return 1

def score_desconto(preco_pago, preco_teorico):
    if preco_teorico <= 0: return 1
    d = (preco_teorico - preco_pago) / preco_teorico
    if d >= 0.60: return 5
    if d >= 0.40: return 4
    if d >= 0.25: return 3
    if d >= 0.10: return 2
    return 1

def score_liquidez(nivel):
    n = str(nivel).lower()
    if n == "alta": return 5
    if n == "média": return 3
    return 2

def score_probabilidade(texto, dias, spot, strike, tipo):
    t = str(texto).lower()
    p = 2
    if dias >= 120: p += 1
    if tipo.lower() == "call" and spot >= strike * 0.9: p += 1
    if tipo.lower() == "put" and spot <= strike * 1.1: p += 1
    for w in ["probabilidade", "estatística", "cenário favorável", "tese forte", "validação"]:
        if w in t: p += 1
    return min(p, 5)

def score_ativo(texto):
    t = str(texto).lower()
    if any(w in t for w in ["empresa sólida", "bons resultados", "lucro", "crescimento", "fundamento forte", "ativo forte"]): return 4
    if any(w in t for w in ["empresa ruim", "risco de quebrar", "fundamento fraco", "ativo fraco"]): return 1
    return 3

def score_assimetria(texto, preco_pago, distorcao):
    t = str(texto).lower()
    p = 2
    if preco_pago <= 1: p += 1
    if distorcao >= 40: p += 1
    for w in ["assimetria", "ganhar muito", "perder pouco", "explosão", "distorção"]:
        if w in t: p += 1
    return min(p, 5)

def decisao_final(media):
    if media >= 4.2: return "Executar forte"
    if media >= 3.4: return "Executar pequeno"
    if media >= 2.5: return "Observar"
    return "Evitar"

def risco_principal(liquidez, dias, texto, sigma_pct):
    t = str(texto).lower()
    if str(liquidez).lower() == "baixa": return "Liquidez ruim pode dificultar a entrada e a saída da operação."
    if dias < 30: return "Prazo curto aumenta a pressão do tempo contra a opção."
    if sigma_pct >= 60: return "Volatilidade muito alta pode inflar o preço e aumentar o risco de correção."
    return "Risco de a tese não se confirmar ou de uma variável importante mudar."

def classificar_liquidez_volume(volume):
    if volume >= 50000: return "Alta"
    if volume >= 5000: return "Média"
    return "Baixa"

# -----------------------------
# PAYOFF
# -----------------------------
def gerar_payoff(tipo, strike, premio, spot_ref, contratos, lote):
    if spot_ref <= 0: spot_ref = strike if strike > 0 else 1
    inicio = max(0.01, spot_ref * 0.5)
    fim = spot_ref * 1.5
    passos = 121
    precos = [inicio + (fim - inicio) * i / (passos - 1) for i in range(passos)]
    mult = contratos * lote
    dados = []
    for s in precos:
        if tipo.lower() == "call":
            v = max(0, s - strike) - premio
        else:
            v = max(0, strike - s) - premio
        dados.append({"Preço do ativo no vencimento": s, "Resultado por opção": round(v, 4), "Resultado total": round(v * mult, 4)})
    df = pd.DataFrame(dados)
    df["Zona"] = df["Resultado total"].apply(lambda x: "Lucro" if x >= 0 else "Prejuízo")
    return df

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
    st.divider()
    st.caption("Sistema de Análise de Opções v2.0")
    st.caption("Dados ao vivo via OpLab API")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Nova análise",
    "Histórico",
    "Opções ao vivo",
    "Scanner de oportunidades",
    "Backtest",
    "Telegram"
])

# =============================================
# TAB 1 — NOVA ANÁLISE
# =============================================
with tab1:
    st.title("Nova análise de opção")
    st.caption("Busque dados ao vivo na OpLab ou preencha manualmente")

    busca_col1, busca_col2 = st.columns([1, 3])
    with busca_col1:
        ativo = st.text_input("Ativo", placeholder="Ex: PETR4")
    with busca_col2:
        st.write("")
        st.write("")
        buscar = st.button("Buscar na OpLab")

    opcao_selecionada = None

    if buscar and ativo:
        dados_ativo = get_ativo(ativo)
        if dados_ativo:
            st.session_state["oplab_ativo"] = dados_ativo
            opcoes_raw = get_opcoes(ativo) or []
            st.session_state["oplab_opcoes"] = opcoes_raw
            st.success(f"{ativo.upper()} — Preço: R$ {dados_ativo['close']:.2f} | IV: {dados_ativo.get('iv_current', 0):.2f}%")
        else:
            st.error(f"Ativo '{ativo}' não encontrado.")
            st.session_state["oplab_ativo"] = None
            st.session_state["oplab_opcoes"] = []

    dados_ativo = st.session_state.get("oplab_ativo")
    opcoes_raw = st.session_state.get("oplab_opcoes", [])

    if opcoes_raw:
        opcoes_filtradas = sorted(
            [o for o in opcoes_raw if o.get("days_to_maturity", 0) > 0 and (o.get("bid", 0) > 0 or o.get("ask", 0) > 0)],
            key=lambda o: (o.get("category", ""), o.get("due_date", ""), o.get("strike", 0))
        )
        if opcoes_filtradas:
            nomes = [
                f"{o['category']} | Strike {o['strike']:.2f} | {o['due_date']} | {o['days_to_maturity']}d | Bid {o.get('bid',0):.2f} Ask {o.get('ask',0):.2f}"
                for o in opcoes_filtradas
            ]
            idx_escolha = st.selectbox("Selecionar opção", range(len(nomes)), format_func=lambda i: nomes[i])
            opcao_selecionada = opcoes_filtradas[idx_escolha]

    st.divider()

    d_tipo = 0
    d_spot = d_strike = d_preco = 0.0
    d_dias = 1
    d_vol = 30.0
    d_lote = 100
    d_liq = 0

    if opcao_selecionada:
        d_tipo = 0 if opcao_selecionada["category"] == "CALL" else 1
        d_spot = float(opcao_selecionada.get("spot_price", 0) or (dados_ativo["close"] if dados_ativo else 0))
        d_strike = float(opcao_selecionada.get("strike", 0))
        d_dias = int(opcao_selecionada.get("days_to_maturity", 1))
        d_preco = float(opcao_selecionada.get("ask", 0) or opcao_selecionada.get("close", 0))
        d_lote = int(opcao_selecionada.get("contract_size", 100))
        d_vol = float(dados_ativo.get("iv_current", 30)) if dados_ativo else 30.0
        d_liq = ["Baixa", "Média", "Alta"].index(classificar_liquidez_volume(opcao_selecionada.get("volume", 0)))
    elif dados_ativo:
        d_spot = float(dados_ativo.get("close", 0))
        d_vol = float(dados_ativo.get("iv_current", 30))

    col1, col2 = st.columns(2)
    with col1:
        tipo = st.selectbox("Tipo da opção", ["Call", "Put"], index=d_tipo)
        quantidade_contratos = st.number_input("Contratos", min_value=1, step=1, value=1)
        lote_por_contrato = st.number_input("Lote por contrato", min_value=1, step=1, value=d_lote)
        spot = st.number_input("Preço atual do ativo", min_value=0.0, format="%.2f", value=d_spot)
        strike = st.number_input("Strike", min_value=0.0, format="%.2f", value=d_strike)
        dias_vencimento = st.number_input("Dias até vencimento", min_value=1, step=1, value=d_dias)
        vol_implicita_pct = st.number_input("Volatilidade implícita (%)", min_value=0.0, format="%.2f", value=d_vol)
        taxa_risco_pct = st.number_input("Taxa livre de risco (%)", min_value=0.0, format="%.2f", value=10.50)
        preco_pago = st.number_input("Preço pago por opção", min_value=0.0, format="%.2f", value=d_preco)

    with col2:
        liquidez = st.selectbox("Liquidez", ["Baixa", "Média", "Alta"], index=d_liq)
        tese = st.text_area("Tese / observações", height=160, placeholder="Explique a ideia com suas palavras.")
        status_operacao = st.selectbox("Status da operação", ["Aberta", "Encerrada", "Stopada", "Gain"])
        data_saida = st.text_input("Data de saída (opcional)", placeholder="Ex: 2026-04-07")
        observacao_pos = st.text_area("Observação pós-operação", height=70)
        resultado_real = st.number_input("Resultado real (opcional)", value=0.0, format="%.2f")

    if st.button("Analisar"):
        T = dias_vencimento / 365
        sigma = vol_implicita_pct / 100
        r = taxa_risco_pct / 100

        modelos = comparar_modelos(tipo, spot, strike, T, r, sigma)
        preco_teorico = modelos["black_scholes"]
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
        data_analise = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        break_even = strike + preco_pago if tipo.lower() == "call" else strike - preco_pago
        custo_tot = round(preco_pago * quantidade_contratos * lote_por_contrato, 2)
        perda_max = custo_tot
        ganho_max = "Ilimitado" if tipo.lower() == "call" else round((strike - preco_pago) * quantidade_contratos * lote_por_contrato, 2)

        # RESUMO
        st.subheader("Resumo da análise")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Preço teórico (B&S)", f"{preco_teorico:.4f}")
        c2.metric("Distorção", f"{distorcao}%")
        c3.metric("Nota média", f"{media}/5")
        c4.metric("Decisão", decisao)

        # 4 MODELOS + HESTON
        st.subheader("Comparação entre modelos de precificação")
        mod_col1, mod_col2, mod_col3, mod_col4, mod_col5 = st.columns(5)
        mod_col1.metric("Black-Scholes", f"{modelos['black_scholes']:.4f}")
        mod_col2.metric("Binomial (CRR)", f"{modelos['binomial']:.4f}")
        mod_col3.metric("Monte Carlo", f"{modelos['monte_carlo']:.4f}")
        mod_col4.metric("Heston", f"{modelos['heston']:.4f}")
        mod_col5.metric("Média (4 modelos)", f"{modelos['media_modelos']:.4f}")

        dist_bs = calcular_distorcao(preco_pago, modelos["black_scholes"])
        dist_bin = calcular_distorcao(preco_pago, modelos["binomial"])
        dist_mc = calcular_distorcao(preco_pago, modelos["monte_carlo"])
        dist_heston = calcular_distorcao(preco_pago, modelos["heston"])
        dist_media = calcular_distorcao(preco_pago, modelos["media_modelos"])

        comp_df = pd.DataFrame({
            "Modelo": ["Preço pago", "Black-Scholes", "Binomial", "Monte Carlo", "Heston", "Média"],
            "Valor": [preco_pago, modelos["black_scholes"], modelos["binomial"], modelos["monte_carlo"], modelos["heston"], modelos["media_modelos"]],
            "Distorção (%)": [0, dist_bs, dist_bin, dist_mc, dist_heston, dist_media]
        })

        graf_modelos = alt.Chart(comp_df).mark_bar(size=45).encode(
            x=alt.X("Modelo:N", sort=["Preço pago", "Black-Scholes", "Binomial", "Monte Carlo", "Heston", "Média"]),
            y=alt.Y("Valor:Q"),
            color=alt.Color("Modelo:N", scale=alt.Scale(
                domain=["Preço pago", "Black-Scholes", "Binomial", "Monte Carlo", "Heston", "Média"],
                range=["#dc2626", "#16a34a", "#2563eb", "#9333ea", "#0ea5e9", "#f59e0b"]
            ), legend=None),
            tooltip=["Modelo", alt.Tooltip("Valor:Q", format=".4f"), alt.Tooltip("Distorção (%):Q", format=".2f")]
        ).properties(height=320)
        st.altair_chart(graf_modelos, use_container_width=True)

        # LEITURA RÁPIDA
        st.subheader("Leitura rápida")
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Break-even", f"{break_even:.2f}")
        c6.metric("Custo total", f"{custo_tot:.2f}")
        c7.metric("Perda máxima", f"{perda_max:.2f}")
        c8.metric("Ganho máximo", str(ganho_max))

        if distorcao >= 0:
            st.success(f"Opção {distorcao}% abaixo do preço teórico (B&S).")
        else:
            st.error(f"Opção {abs(distorcao)}% acima do preço teórico (B&S).")

        # SCORECARD
        st.subheader("Scorecard")
        scores_df = pd.DataFrame({
            "Critério": ["Prazo", "Desconto", "Liquidez", "Probabilidade", "Qualidade do ativo", "Assimetria"],
            "Nota": [prazo_s, desconto_s, liquidez_s, prob_s, ativo_s, assimetria_s]
        })
        graf_scores = alt.Chart(scores_df).mark_bar().encode(
            x=alt.X("Nota:Q", scale=alt.Scale(domain=[0, 5])),
            y=alt.Y("Critério:N", sort="-x"),
            color=alt.condition(alt.datum.Nota >= 4, alt.value("#16a34a"), alt.value("#f59e0b")),
            tooltip=["Critério", "Nota"]
        ).properties(height=250)
        st.altair_chart(graf_scores, use_container_width=True)

        st.write(f"**Risco principal:** {risco}")

        # PAYOFF
        st.subheader("Gráfico de payoff no vencimento")
        payoff_df = gerar_payoff(tipo, strike, preco_pago, spot, quantidade_contratos, lote_por_contrato)
        base = alt.Chart(payoff_df).encode(
            x=alt.X("Preço do ativo no vencimento:Q"),
            y=alt.Y("Resultado total:Q", title="Lucro / prejuízo total"),
            tooltip=[alt.Tooltip("Preço do ativo no vencimento:Q", format=".2f"), alt.Tooltip("Resultado total:Q", format=".2f"), "Zona:N"]
        )
        area = base.mark_area(opacity=0.35).encode(color=alt.Color("Zona:N", scale=alt.Scale(domain=["Lucro", "Prejuízo"], range=["#16a34a", "#dc2626"]), legend=None))
        linha = base.mark_line(size=3, color="#2563eb")
        linha_zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#94a3b8").encode(y="y:Q")
        chart = (area + linha + linha_zero).properties(height=380).interactive()
        st.altair_chart(chart, use_container_width=True)

        # SALVAR
        salvar_csv([
            data_analise, ativo, tipo, quantidade_contratos, lote_por_contrato,
            spot, strike, dias_vencimento, vol_implicita_pct, taxa_risco_pct,
            preco_pago, preco_teorico, distorcao, prazo_s, desconto_s,
            liquidez_s, prob_s, ativo_s, assimetria_s, media, decisao,
            tese, risco, status_operacao, data_saida, observacao_pos, resultado_real
        ])
        st.info(f"Análise salva em {CSV_FILE}")

# =============================================
# TAB 2 — HISTÓRICO
# =============================================
with tab2:
    st.title("Histórico das análises")
    df = carregar_historico()

    if df.empty:
        st.warning("Ainda não há histórico.")
    else:
        df["media_final"] = pd.to_numeric(df["media_final"], errors="coerce")
        df["resultado_real"] = pd.to_numeric(df["resultado_real"], errors="coerce")

        total_ops = len(df)
        resultado_acum = df["resultado_real"].fillna(0).sum()
        encerradas = df[df["status_operacao"].astype(str).isin(["Encerrada", "Gain", "Stopada"])]
        taxa_acerto = round((len(encerradas[encerradas["resultado_real"] > 0]) / len(encerradas)) * 100, 2) if len(encerradas) > 0 else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total operações", total_ops)
        c2.metric("Resultado acumulado", f"{resultado_acum:.2f}")
        c3.metric("Taxa de acerto", f"{taxa_acerto}%")
        c4.metric("Média oportunidades", f"{df['media_final'].mean():.2f}" if not df["media_final"].dropna().empty else "-")

        st.subheader("Filtros")
        ativos_f = ["Todos"] + sorted([str(x) for x in df["ativo"].dropna().unique() if str(x).strip()])
        decisoes_f = ["Todas"] + sorted([str(x) for x in df["decisao"].dropna().unique() if str(x).strip()])
        status_f = ["Todos"] + sorted([str(x) for x in df["status_operacao"].dropna().unique() if str(x).strip()])

        f1, f2, f3 = st.columns(3)
        with f1: ativo_filtro = st.selectbox("Ativo", ativos_f)
        with f2: decisao_filtro = st.selectbox("Decisão", decisoes_f)
        with f3: status_filtro = st.selectbox("Status", status_f)

        df_f = df.copy()
        if ativo_filtro != "Todos": df_f = df_f[df_f["ativo"].astype(str) == ativo_filtro]
        if decisao_filtro != "Todas": df_f = df_f[df_f["decisao"].astype(str) == decisao_filtro]
        if status_filtro != "Todos": df_f = df_f[df_f["status_operacao"].astype(str) == status_filtro]

        st.dataframe(df_f, use_container_width=True)
        st.download_button("Baixar Excel", dataframe_para_excel_bytes(df_f), "historico.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        st.subheader("P&L por ativo")
        pnl = df.groupby("ativo", dropna=False)["resultado_real"].sum().reset_index()
        pnl.columns = ["Ativo", "Resultado"]
        graf_pnl = alt.Chart(pnl).mark_bar().encode(
            x=alt.X("Ativo:N", sort="-y"), y="Resultado:Q",
            color=alt.condition(alt.datum.Resultado >= 0, alt.value("#16a34a"), alt.value("#dc2626")),
            tooltip=["Ativo", alt.Tooltip("Resultado:Q", format=".2f")]
        ).properties(height=300)
        st.altair_chart(graf_pnl, use_container_width=True)

        st.subheader("Editar registro")
        opcoes_reg = [f"{i} | {df_f.iloc[i]['data']} | {df_f.iloc[i]['ativo']} | {df_f.iloc[i]['tipo']}" for i in range(len(df_f))]
        if opcoes_reg:
            reg = st.selectbox("Registro", opcoes_reg)
            idx_l = int(reg.split(" | ")[0])
            idx_r = df_f.index[idx_l]
            novo_status = st.selectbox("Status", ["Aberta", "Encerrada", "Stopada", "Gain"],
                index=["Aberta", "Encerrada", "Stopada", "Gain"].index(str(df.loc[idx_r, "status_operacao"])) if str(df.loc[idx_r, "status_operacao"]) in ["Aberta", "Encerrada", "Stopada", "Gain"] else 0, key="edit_status")
            nova_obs = st.text_area("Observação", value=str(df.loc[idx_r, "observacao_pos_operacao"]), key="edit_obs")
            novo_res = st.number_input("Resultado real", value=float(pd.to_numeric(df.loc[idx_r, "resultado_real"], errors="coerce") or 0), format="%.2f", key="edit_res")
            if st.button("Salvar edição"):
                df.loc[idx_r, "status_operacao"] = novo_status
                df.loc[idx_r, "observacao_pos_operacao"] = nova_obs
                df.loc[idx_r, "resultado_real"] = novo_res
                salvar_historico_df(df)
                st.success("Registro atualizado.")

# =============================================
# TAB 3 — OPÇÕES AO VIVO
# =============================================
with tab3:
    st.title("Opções ao vivo — OpLab")
    st.caption("Consulte todas as opções de qualquer ativo em tempo real com todos os dados da API")

    ticker_vivo = st.text_input("Ticker", placeholder="Ex: PETR4, VALE3", key="ticker_vivo")
    buscar_vivo = st.button("Buscar", key="btn_vivo")

    if buscar_vivo and ticker_vivo:
        with st.spinner("Buscando..."):
            info = get_ativo(ticker_vivo)
            opcoes_v = get_opcoes(ticker_vivo)

        if info:
            st.subheader(f"{ticker_vivo.upper()} — Dados completos do ativo")

            # MOSTRAR TODOS OS DADOS DO ATIVO
            dados_exibir = {
                "Preço atual": f"R$ {info.get('close', 0):.2f}",
                "Abertura": f"R$ {info.get('open', 0):.2f}",
                "Máxima": f"R$ {info.get('high', 0):.2f}",
                "Mínima": f"R$ {info.get('low', 0):.2f}",
                "Variação": f"{info.get('variation', 0):.2f}%",
                "Volume": f"{info.get('volume', 0):,}",
                "Volume financeiro": f"R$ {info.get('financial_volume', 0):,.0f}",
                "Bid": f"R$ {info.get('bid', 0):.2f}",
                "Ask": f"R$ {info.get('ask', 0):.2f}",
                "Vol. implícita atual": f"{info.get('iv_current', 0):.2f}%",
                "IV 1y máx": f"{info.get('iv_1y_max', 0):.2f}%",
                "IV 1y mín": f"{info.get('iv_1y_min', 0):.2f}%",
                "IV 1y percentil": f"{info.get('iv_1y_percentile', 0):.2f}%",
                "IV 1y rank": f"{info.get('iv_1y_rank', 0):.2f}%",
                "IV 6m máx": f"{info.get('iv_6m_max', 0):.2f}%",
                "IV 6m mín": f"{info.get('iv_6m_min', 0):.2f}%",
                "EWMA atual": f"{info.get('ewma_current', 0):.2f}%",
                "EWMA 1y máx": f"{info.get('ewma_1y_max', 0):.2f}%",
                "EWMA 1y mín": f"{info.get('ewma_1y_min', 0):.2f}%",
                "GARCH(1,1) 1y": f"{info.get('garch11_1y', 0):.2f}%",
                "Desvio padrão 1y": f"{info.get('stdv_1y', 0):.6f}",
                "Desvio padrão 5d": f"{info.get('stdv_5d', 0):.6f}",
                "Beta IBOV": f"{info.get('beta_ibov', 0):.4f}",
                "Correlação IBOV": f"{info.get('correl_ibov', 0):.4f}",
                "Semi-retorno 1y": f"{info.get('semi_return_1y', 0):.4f}",
                "Entropia": f"{info.get('entropy', 0):.4f}",
                "Tendência curto prazo": info.get("short_term_trend", ""),
                "Tendência médio prazo": info.get("middle_term_trend", ""),
                "Setor": info.get("sector", ""),
                "ISIN": info.get("isin", ""),
                "CNPJ": info.get("cnpj", ""),
                "OpLab Score": str(info.get("oplab_score", {}).get("value", "")),
                "Tem opções": str(info.get("has_options", "")),
                "Market maker": str(info.get("market_maker", "")),
                "Ranking vol. opções": str(info.get("highest_options_volume_rank", "")),
            }

            df_dados = pd.DataFrame(list(dados_exibir.items()), columns=["Campo", "Valor"])
            st.dataframe(df_dados, use_container_width=True, hide_index=True)

            if opcoes_v:
                opcoes_ativas = [o for o in opcoes_v if o.get("days_to_maturity", 0) > 0]

                if opcoes_ativas:
                    df_op = pd.DataFrame([{
                        "Símbolo": o["symbol"],
                        "Nome": o.get("name", ""),
                        "Tipo": o.get("category", o.get("type", "")),
                        "Exercício": o.get("maturity_type", ""),
                        "Strike": o.get("strike", 0),
                        "Spot": o.get("spot_price", 0),
                        "Vencimento": o.get("due_date", ""),
                        "Dias": o.get("days_to_maturity", 0),
                        "Bid": o.get("bid", 0),
                        "Ask": o.get("ask", 0),
                        "Último": o.get("close", 0),
                        "Abertura": o.get("open", 0),
                        "Máxima": o.get("high", 0),
                        "Mínima": o.get("low", 0),
                        "Volume": o.get("volume", 0),
                        "Vol. financeiro": o.get("financial_volume", 0),
                        "Variação %": o.get("variation", 0),
                        "Lote": o.get("contract_size", 100),
                        "Market maker": o.get("market_maker", False),
                        "Bid vol": o.get("bid_volume", 0),
                        "Ask vol": o.get("ask_volume", 0),
                        "ISIN": o.get("isin", ""),
                        "Liquidez": classificar_liquidez_volume(o.get("volume", 0)),
                    } for o in opcoes_ativas])

                    st.subheader(f"{len(df_op)} opções ativas")

                    fc1, fc2, fc3 = st.columns(3)
                    with fc1:
                        ft = st.selectbox("Tipo", ["Todos", "CALL", "PUT"], key="ft_vivo")
                    with fc2:
                        vencs = ["Todos"] + sorted(df_op["Vencimento"].unique().tolist())
                        fv = st.selectbox("Vencimento", vencs, key="fv_vivo")
                    with fc3:
                        min_dias = st.number_input("Dias mínimos", min_value=0, value=0, key="fd_vivo")

                    df_show = df_op.copy()
                    if ft != "Todos": df_show = df_show[df_show["Tipo"] == ft]
                    if fv != "Todos": df_show = df_show[df_show["Vencimento"] == fv]
                    if min_dias > 0: df_show = df_show[df_show["Dias"] >= min_dias]

                    st.dataframe(df_show.sort_values(["Tipo", "Vencimento", "Strike"]).reset_index(drop=True), use_container_width=True)
                    st.download_button("Baixar Excel", dataframe_para_excel_bytes(df_show), f"opcoes_{ticker_vivo}.xlsx", key="dl_opcoes_vivo")
        else:
            st.error("Ativo não encontrado.")

# =============================================
# TAB 4 — SCANNER DE OPORTUNIDADES
# =============================================
with tab4:
    st.title("Scanner de oportunidades")
    st.caption("Busca automática de opções descorrelacionadas com os modelos de precificação")

    st.subheader("Configuração do scanner")
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        scan_tickers = st.text_input("Ativos (separar por vírgula, vazio = todos)", placeholder="PETR4, VALE3, BBAS3", key="scan_tickers")
    with sc2:
        scan_dias_min = st.number_input("Dias mínimos até vencimento", min_value=1, value=180, key="scan_dias")
    with sc3:
        scan_liq_min = st.number_input("Liquidez mínima (R$/dia)", min_value=0.0, value=1000.0, key="scan_liq")

    sc4, sc5 = st.columns(2)
    with sc4:
        scan_top = st.number_input("Top N resultados", min_value=1, value=50, key="scan_top")
    with sc5:
        st.write("")
        st.write("")
        scan_btn = st.button("Escanear mercado", key="scan_btn")

    if scan_btn:
        tickers_list = None
        if scan_tickers.strip():
            tickers_list = [t.strip().upper() for t in scan_tickers.split(",") if t.strip()]

        with st.spinner("Escaneando... isso pode levar alguns minutos dependendo da quantidade de ativos."):
            df_scan = escanear_mercado(tickers=tickers_list, dias_min=scan_dias_min, liquidez_min=scan_liq_min, top_n=scan_top)

        if df_scan.empty:
            st.warning("Nenhuma oportunidade encontrada com os filtros atuais.")
        else:
            st.session_state["scan_resultado"] = df_scan
            st.success(f"{len(df_scan)} oportunidades encontradas!")

    df_scan = st.session_state.get("scan_resultado", pd.DataFrame())

    if not df_scan.empty:
        st.subheader("Resultados do scanner")

        # Métricas gerais
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Oportunidades", len(df_scan))
        m2.metric("Distorção média", f"{df_scan['distorcao_media_pct'].mean():.2f}%")
        m3.metric("Maior distorção", f"{df_scan['distorcao_media_pct'].max():.2f}%")
        m4.metric("Ativos únicos", df_scan["ativo"].nunique())

        # Envio automático ao Telegram
        tg_token_auto = st.session_state.get("tg_token_salvo", "")
        tg_chat_auto = st.session_state.get("tg_chat_salvo", "")
        if tg_token_auto and tg_chat_auto:
            from telegram_bot import gerar_relatorio_scanner
            with st.spinner("Enviando relatório ao Telegram..."):
                relatorio_tg = gerar_relatorio_scanner(tickers=tickers_list, dias_min=scan_dias_min, top=min(scan_top, 20))
                ok_tg = enviar_mensagem(relatorio_tg, chat_id=tg_chat_auto, token=tg_token_auto)
            if ok_tg:
                st.success("Relatório enviado ao Telegram automaticamente!")
            else:
                st.warning("Não foi possível enviar ao Telegram. Verifique as configurações na aba Telegram.")
        else:
            st.info("Configure o Telegram na aba 'Telegram' para envio automático dos relatórios.")

        # Tabela principal
        colunas_exibir = [
            "ativo", "simbolo", "tipo", "strike", "spot", "vencimento", "dias_vencimento",
            "preco_mercado", "bid", "ask", "volume", "volume_financeiro",
            "bs_preco", "binomial_preco", "monte_carlo_preco", "heston_preco", "media_modelos",
            "distorcao_bs_pct", "distorcao_binomial_pct", "distorcao_mc_pct", "distorcao_heston_pct", "distorcao_media_pct",
            "iv_ativo_pct", "tipo_exercicio", "market_maker", "setor"
        ]
        colunas_disponiveis = [c for c in colunas_exibir if c in df_scan.columns]
        st.dataframe(df_scan[colunas_disponiveis], use_container_width=True)
        st.download_button("Baixar resultados (Excel)", dataframe_para_excel_bytes(df_scan), "scanner_resultados.xlsx", key="dl_scanner")

        # Gráfico de distorção
        st.subheader("Top 20 — Distorção por opção")
        top20 = df_scan.head(20)
        graf_dist = alt.Chart(top20).mark_bar().encode(
            x=alt.X("distorcao_media_pct:Q", title="Distorção média (%)"),
            y=alt.Y("simbolo:N", sort="-x", title=""),
            color=alt.condition(alt.datum.distorcao_media_pct >= 20, alt.value("#16a34a"), alt.value("#f59e0b")),
            tooltip=["simbolo", "ativo", "tipo", alt.Tooltip("distorcao_media_pct:Q", format=".2f"), alt.Tooltip("preco_mercado:Q", format=".2f"), alt.Tooltip("media_modelos:Q", format=".4f")]
        ).properties(height=500)
        st.altair_chart(graf_dist, use_container_width=True)

        # Selecionar para backtest
        st.subheader("Selecionar para backtest")
        n_bt = st.number_input("Quantas opções para backtest?", min_value=1, max_value=len(df_scan), value=min(10, len(df_scan)), key="n_bt")
        if st.button("Adicionar ao backtest", key="btn_add_bt"):
            selecionadas = selecionar_backtest(df_scan, n=n_bt)
            carteira = adicionar_ao_backtest(selecionadas)
            st.success(f"{len(selecionadas)} opções adicionadas ao backtest! Total na carteira: {len(carteira)}")

# =============================================
# TAB 5 — BACKTEST
# =============================================
with tab5:
    st.title("Backtest — Acompanhamento de opções")
    st.caption("Acompanhe a variação das opções selecionadas e valide a estratégia")

    carteira = carregar_carteira()
    ativos_bt = [c for c in carteira if c["status"] == "ativo"]

    st.metric("Opções ativas no backtest", len(ativos_bt))

    if ativos_bt:
        if st.button("Atualizar preços agora", key="btn_atualizar_bt"):
            with st.spinner("Atualizando preços..."):
                df_att = atualizar_backtest()
            if not df_att.empty:
                st.success(f"{len(df_att)} opções atualizadas!")
            else:
                st.warning("Não foi possível atualizar.")

        # Carteira atual
        st.subheader("Carteira do backtest")
        df_cart = pd.DataFrame(ativos_bt)
        st.dataframe(df_cart, use_container_width=True)

        # Histórico
        df_hist = carregar_historico_backtest()
        if not df_hist.empty:
            st.subheader("Histórico de acompanhamento")
            st.dataframe(df_hist.tail(50), use_container_width=True)

            df_hist["variacao_pct"] = pd.to_numeric(df_hist["variacao_pct"], errors="coerce")
            df_hist["preco_atual"] = pd.to_numeric(df_hist["preco_atual"], errors="coerce")
            df_hist["preco_entrada"] = pd.to_numeric(df_hist["preco_entrada"], errors="coerce")
            df_hist["pnl_unitario"] = pd.to_numeric(df_hist.get("pnl_unitario", 0), errors="coerce")

            if "data" in df_hist.columns:
                # Gráfico 1: Evolução do preço de cada opção desde a indicação
                st.subheader("Evolução do preço das opções (desde a indicação)")

                simbolos_unicos = df_hist["simbolo"].unique().tolist()
                simb_selecionado = st.selectbox("Selecionar opção para detalhe", ["Todas"] + simbolos_unicos, key="sel_evolucao")

                df_graf = df_hist.copy()
                if simb_selecionado != "Todas":
                    df_graf = df_graf[df_graf["simbolo"] == simb_selecionado]

                # Linha do preço atual
                linha_preco = alt.Chart(df_graf).mark_line(point=True, strokeWidth=2).encode(
                    x=alt.X("data:N", title="Data"),
                    y=alt.Y("preco_atual:Q", title="Preço da opção (R$)"),
                    color="simbolo:N",
                    tooltip=["simbolo", "ativo", "data:N",
                             alt.Tooltip("preco_atual:Q", title="Preço atual", format=".4f"),
                             alt.Tooltip("preco_entrada:Q", title="Preço entrada", format=".4f"),
                             alt.Tooltip("variacao_pct:Q", title="Variação %", format=".2f")]
                )

                # Linha do preço de entrada (referência)
                if simb_selecionado != "Todas" and not df_graf.empty:
                    preco_ref = df_graf["preco_entrada"].iloc[0]
                    linha_entrada = alt.Chart(pd.DataFrame({"y": [preco_ref]})).mark_rule(
                        color="#f59e0b", strokeDash=[6, 4], strokeWidth=2
                    ).encode(y="y:Q")

                    texto_entrada = alt.Chart(pd.DataFrame({"y": [preco_ref], "label": [f"Entrada: R$ {preco_ref:.4f}"]})).mark_text(
                        align="left", dx=5, dy=-10, color="#f59e0b", fontSize=12
                    ).encode(y="y:Q", text="label:N")

                    chart_evolucao = (linha_preco + linha_entrada + texto_entrada).properties(height=400)
                else:
                    chart_evolucao = linha_preco.properties(height=400)

                st.altair_chart(chart_evolucao, use_container_width=True)

                # Gráfico 2: Zona de lucro/prejuízo por opção
                st.subheader("Zona de lucro / prejuízo por opção")

                df_ultimo = df_hist.sort_values("data").groupby("simbolo").last().reset_index()
                df_ultimo["pnl_calc"] = df_ultimo["preco_atual"] - df_ultimo["preco_entrada"]
                df_ultimo["zona"] = df_ultimo["pnl_calc"].apply(lambda x: "LUCRO" if x >= 0 else "PREJUÍZO")

                graf_zona = alt.Chart(df_ultimo).mark_bar().encode(
                    x=alt.X("pnl_calc:Q", title="P&L unitário (R$)"),
                    y=alt.Y("simbolo:N", sort="-x", title=""),
                    color=alt.Color("zona:N", scale=alt.Scale(
                        domain=["LUCRO", "PREJUÍZO"], range=["#16a34a", "#dc2626"]
                    )),
                    tooltip=["simbolo", "ativo",
                             alt.Tooltip("preco_entrada:Q", title="Entrada", format=".4f"),
                             alt.Tooltip("preco_atual:Q", title="Atual", format=".4f"),
                             alt.Tooltip("pnl_calc:Q", title="P&L", format=".4f"),
                             alt.Tooltip("variacao_pct:Q", title="Var %", format=".2f")]
                ).properties(height=max(200, len(df_ultimo) * 30))
                st.altair_chart(graf_zona, use_container_width=True)

                # Gráfico 3: Variação % ao longo do tempo
                st.subheader("Variação % desde a entrada")
                graf_var = alt.Chart(df_graf).mark_line(point=True).encode(
                    x=alt.X("data:N", title="Data"),
                    y=alt.Y("variacao_pct:Q", title="Variação (%)"),
                    color="simbolo:N",
                    tooltip=["simbolo", "ativo", alt.Tooltip("variacao_pct:Q", format=".2f")]
                ).properties(height=400)

                linha_zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#94a3b8", strokeDash=[4, 4]).encode(y="y:Q")
                st.altair_chart((graf_var + linha_zero), use_container_width=True)
                st.caption("Acima da linha cinza = lucro. Abaixo = prejuízo.")

            st.download_button("Baixar histórico backtest", dataframe_para_excel_bytes(df_hist), "backtest_historico.xlsx", key="dl_bt")

        # Remover do backtest
        st.subheader("Gerenciar carteira")
        simbolos_bt = [c["simbolo"] for c in ativos_bt]
        remover = st.selectbox("Remover opção", simbolos_bt, key="sel_remover_bt")
        if st.button("Remover do backtest", key="btn_remover_bt"):
            carteira = [c for c in carregar_carteira() if not (c["simbolo"] == remover and c["status"] == "ativo")]
            salvar_carteira(carteira)
            st.success(f"{remover} removido do backtest.")
            st.rerun()
    else:
        st.info("Nenhuma opção no backtest. Vá ao Scanner e adicione opções.")

# =============================================
# TAB 6 — TELEGRAM
# =============================================
with tab6:
    st.title("Bot Telegram — Relatórios diários")
    st.caption("Configure o bot para enviar relatórios automáticos")

    st.subheader("Configuração")
    st.markdown("""
    **Como configurar:**
    1. Abra o Telegram e fale com [@BotFather](https://t.me/BotFather)
    2. Envie `/newbot` e siga as instruções para criar um bot
    3. Copie o **token** do bot
    4. Fale com [@userinfobot](https://t.me/userinfobot) para descobrir seu **Chat ID**
    5. Cole os dados abaixo
    """)

    tg_token = st.text_input("Token do bot", type="password", key="tg_token",
                             value=st.session_state.get("tg_token_salvo", ""))
    tg_chat_id = st.text_input("Chat ID", key="tg_chat_id",
                               value=st.session_state.get("tg_chat_salvo", ""))
    tg_tickers = st.text_input("Ativos para monitorar (separar por vírgula)", placeholder="PETR4, VALE3, BBAS3", key="tg_tickers")

    if st.button("Salvar configurações do Telegram", key="btn_tg_salvar"):
        st.session_state["tg_token_salvo"] = tg_token
        st.session_state["tg_chat_salvo"] = tg_chat_id
        st.success("Configurações salvas! O scanner vai enviar relatórios automaticamente ao Telegram.")

    col_tg1, col_tg2 = st.columns(2)

    with col_tg1:
        if st.button("Enviar relatório agora", key="btn_tg_enviar"):
            if not tg_token or not tg_chat_id:
                st.error("Configure o token e chat ID primeiro.")
            else:
                st.session_state["tg_token_salvo"] = tg_token
                st.session_state["tg_chat_salvo"] = tg_chat_id
                tickers = [t.strip().upper() for t in tg_tickers.split(",") if t.strip()] if tg_tickers else None
                with st.spinner("Gerando e enviando relatório..."):
                    from telegram_bot import gerar_relatorio_scanner
                    relatorio = gerar_relatorio_scanner(tickers=tickers)
                    ok = enviar_mensagem(relatorio, chat_id=tg_chat_id, token=tg_token)

                    relatorio_bt = gerar_relatorio_backtest()
                    ok2 = enviar_mensagem(relatorio_bt, chat_id=tg_chat_id, token=tg_token)

                if ok:
                    st.success("Relatório enviado com sucesso!")
                else:
                    st.error("Erro ao enviar. Verifique token e chat ID.")

    with col_tg2:
        if st.button("Testar conexão", key="btn_tg_teste"):
            if not tg_token or not tg_chat_id:
                st.error("Configure o token e chat ID.")
            else:
                ok = enviar_mensagem("✅ Bot conectado ao Sistema de Análise de Opções!", chat_id=tg_chat_id, token=tg_token)
                if ok:
                    st.success("Teste OK! Mensagem enviada.")
                else:
                    st.error("Falha no teste.")

    st.divider()
    st.subheader("Prévia do relatório")
    if st.button("Gerar prévia", key="btn_tg_previa"):
        relatorio_bt = gerar_relatorio_backtest()
        st.code(relatorio_bt)
