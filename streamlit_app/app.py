"""Fase 7: chat em Streamlit que consome a API do Editais AI.

  streamlit run streamlit_app/app.py          # http://localhost:8501
  API_URL=http://localhost:8000 (padrão)      # endereço da API (Fase 6)

O app NÃO acessa OpenAI, BigQuery nem pgvector: tudo passa pela API. Assim a UI fica
fina e as proteções (API key, rate limit, limite de gasto) valem para ela também.
O visual (balões, cards, trilha do agente) é feito com CSS próprio em styles.css.
"""

from __future__ import annotations

import html
import os
import re
from pathlib import Path

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = 120

SUGESTOES = [
    "Quais cargos de nível superior pagam mais de 5 mil reais?",
    "No concurso da UFG, quem tem direito à isenção da taxa?",
    "Qual o maior salário inicial entre todos os editais?",
    "Qual percentual das vagas do TCE-SP é reservado a candidatos negros?",
    "Quantas vagas o concurso da SEE-MG oferece?",
]
MODOS = {"agente": "Agente · SQL + RAG + verificação", "sql": "Só SQL · dados da gold", "rag": "Só RAG · texto dos editais"}

st.set_page_config(page_title="Editais AI", page_icon="📄", layout="wide", initial_sidebar_state="auto")
st.markdown(f"<style>{(Path(__file__).parent / 'styles.css').read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True)


# ------------------------------------------------------------------ API
def _headers() -> dict:
    key = st.session_state.get("api_key") or os.getenv("API_KEY", "")
    return {"X-API-Key": key} if key else {}


@st.cache_data(ttl=600, show_spinner=False)
def carregar_editais() -> list[dict]:
    return requests.get(f"{API_URL}/api/editais", timeout=30).json()


def carregar_stats() -> dict | None:
    try:
        return requests.get(f"{API_URL}/api/stats", timeout=10).json()
    except requests.RequestException:
        return None


def perguntar(pergunta: str, modo: str) -> dict:
    r = requests.post(f"{API_URL}/api/ask", json={"pergunta": pergunta, "modo": modo},
                      headers=_headers(), timeout=TIMEOUT)
    if r.status_code != 200:
        try:
            detail = r.json().get("detail")
            detail = detail[0]["msg"] if isinstance(detail, list) else detail
        except ValueError:
            detail = r.text[:200]
        raise RuntimeError(f"{r.status_code}: {detail}")
    return r.json()


# ------------------------------------------------------------------ HTML dos balões
def _md(text: str) -> str:
    """Markdown mínimo (negrito e parágrafos) sobre texto ESCAPADO: a resposta do LLM nunca vira HTML."""
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(text or ""))
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in re.split(r"\n{2,}", t))


def brl(v) -> str:
    if v is None:
        return "-"
    return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def bubble_user(text: str) -> str:
    return f'<div class="row user"><div class="msg user">{html.escape(text)}</div></div>'


def bubble_bot(r: dict) -> str:
    fontes = "".join(f"<span>{html.escape(f)}</span>" for f in r.get("fontes") or [])
    steps = "".join(f"<li>{html.escape(s)}</li>" for s in r.get("caminho") or [])
    # SQL em <div> com <br>/&nbsp;: o Markdown do Streamlit junta as linhas de um <pre>.
    sql = ""
    if r.get("sql"):
        linhas = (html.escape(l).replace("  ", "&nbsp;&nbsp;") for l in r["sql"].splitlines())
        sql = f'<div class="sql">{"<br>".join(linhas)}</div>'

    n = len(r.get("caminho") or [])
    tokens = f"{r['tokens_entrada'] + r['tokens_saida']:,}".replace(",", ".")
    return f"""
<div class="row bot"><div class="msg bot">
  <div class="answer">{_md(r["resposta"])}</div>
  {f'<div class="sources">{fontes}</div>' if fontes else ''}
  <details class="trace"><summary>Como o agente chegou nisso ({n} passos{' + SQL' if r.get('sql') else ''})</summary>
    <ul class="steps">{steps}</ul>{sql}
  </details>
  <div class="meta"><span>modo: {html.escape(r["modo"])}</span><span>{tokens} tokens</span>
    <span>US$ {r["custo_usd"]:.4f}</span><span>{r["latencia_ms"] / 1000:.1f} s</span></div>
</div></div>"""


def bubble_error(text: str) -> str:
    return f'<div class="row bot"><div class="msg bot error">{html.escape(text)}</div></div>'


TYPING = ('<div class="row bot"><div class="msg bot"><span class="typing"><i></i><i></i><i></i></span>'
          '<span class="typing-label">Identificando o edital, consultando os dados e conferindo as fontes…</span>'
          '</div></div>')


# ------------------------------------------------------------------ sidebar
if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.markdown('<div class="brand"><div class="logo">E</div><div><strong>Editais AI</strong>'
                '<span>Pergunte sobre concursos públicos</span></div></div>', unsafe_allow_html=True)

    st.markdown('<h2 class="side-title">Editais na base</h2>', unsafe_allow_html=True)
    try:
        cards = []
        for e in carregar_editais():
            vagas = f"{e['vagas_total']:,}".replace(",", ".") + " vagas" if e.get("vagas_total") else "vagas n/i"
            faixa = brl(e.get("salario_min"))
            if e.get("salario_max") and e.get("salario_max") != e.get("salario_min"):
                faixa += f" a {brl(e['salario_max'])}"
            cards.append(f'<li><b>{html.escape(e["orgao"])}</b><span>{html.escape(e.get("uf") or "-")} · '
                         f'{e["qtd_cargos"]} cargos · {vagas} · {faixa}</span></li>')
        st.markdown(f'<ul class="editais">{"".join(cards)}</ul>', unsafe_allow_html=True)
    except requests.RequestException:
        st.markdown(f'<p class="muted">API indisponível em {html.escape(API_URL)}.</p>', unsafe_allow_html=True)

    st.markdown('<h2 class="side-title">Modo</h2>', unsafe_allow_html=True)
    modo = st.radio("Modo", list(MODOS), format_func=MODOS.get, label_visibility="collapsed")

    st.markdown('<h2 class="side-title">Uso hoje</h2>', unsafe_allow_html=True)
    s = carregar_stats()
    st.markdown(
        f'<div class="stats">{s["perguntas"]} pergunta(s) · US$ {s["gasto_usd"]:.4f}<br>'
        f'<span class="muted">limite diário: US$ {s["limite_usd"]:.2f}</span></div>' if s else
        '<div class="stats muted">-</div>', unsafe_allow_html=True)

    with st.expander("API key"):
        st.text_input("X-API-Key", type="password", key="api_key", placeholder="opcional",
                      label_visibility="collapsed")


# ------------------------------------------------------------------ chat
head_l, head_r = st.columns([5, 1], vertical_alignment="center")
head_l.markdown('<h1 class="chat-title">Assistente de editais</h1>', unsafe_allow_html=True)
if head_r.button("Nova conversa", key="clear", use_container_width=True):
    st.session_state.messages = []
    st.rerun()
st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

pendente = None
if not st.session_state.messages:
    st.markdown('<div class="welcome"><h2>O que você quer saber sobre os editais?</h2><p>Respostas com fonte '
                '(página do edital ou consulta SQL). Se a informação não estiver nos editais, o assistente diz '
                'que não encontrou.</p></div>', unsafe_allow_html=True)
    with st.container(key="chips"):
        for i, sug in enumerate(SUGESTOES):
            if st.button(sug, key=f"sug{i}"):
                pendente = sug
else:
    for m in st.session_state.messages:
        if m["role"] == "user":
            st.markdown(bubble_user(m["content"]), unsafe_allow_html=True)
        elif "erro" in m:
            st.markdown(bubble_error(m["erro"]), unsafe_allow_html=True)
        else:
            st.markdown(bubble_bot(m["content"]), unsafe_allow_html=True)

pergunta = st.chat_input("Pergunte sobre vagas, salários, datas, regras…", max_chars=500) or pendente
if pergunta:
    st.session_state.messages.append({"role": "user", "content": pergunta})
    if pendente:  # veio de uma sugestão: some a tela de boas-vindas antes de mostrar a conversa
        st.rerun()
    st.markdown(bubble_user(pergunta), unsafe_allow_html=True)
    espera = st.empty()
    espera.markdown(TYPING, unsafe_allow_html=True)
    try:
        st.session_state.messages.append({"role": "assistant", "content": perguntar(pergunta, modo)})
    except Exception as exc:  # API fora do ar, 429, timeout...
        st.session_state.messages.append({"role": "assistant", "erro": f"Não foi possível responder: {exc}"})
    st.rerun()

# Pergunta vinda de sugestão: processa no ciclo seguinte (com a conversa já na tela).
if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    espera = st.empty()
    espera.markdown(TYPING, unsafe_allow_html=True)
    try:
        st.session_state.messages.append(
            {"role": "assistant", "content": perguntar(st.session_state.messages[-1]["content"], modo)})
    except Exception as exc:
        st.session_state.messages.append({"role": "assistant", "erro": f"Não foi possível responder: {exc}"})
    st.rerun()
