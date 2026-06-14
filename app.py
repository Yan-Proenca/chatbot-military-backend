import sys

if sys.platform != 'win32':
    try:
        from gevent import monkey
        monkey.patch_all()
    except ImportError:
        print("Gevent não encontrado. Instale com 'pip install gevent' para melhor performance.")


from flask import Flask, request, session, jsonify
from flask_socketio import SocketIO, emit
from google import genai
from google.genai import types
from dotenv import load_dotenv
from uuid import uuid4
import os

load_dotenv()

MODELO = "gemini-3.1-flash-lite"

# ──────────────────────────────────────────────────────────────
# SYSTEM INSTRUCTION BASE (imutável — define a personalidade)
# ──────────────────────────────────────────────────────────────
INSTRUCOES_BASE = """
Você é um especialista em Defesa Nacional e Segurança Pública do Brasil.
Seu objetivo é atuar como um chatbot educativo e informativo que domina
a estrutura, combate ao crime, estratégias dos agentes, a rotina e a
atuação prática de duas grandes frentes:

  • Forças de Segurança Pública: Polícia Militar (PM), Polícia Civil (PC),
    Polícia Federal (PF), PRF e unidades especiais como o BOPE.
  • Forças Armadas: Exército, Marinha e Aeronáutica.

Seus cinco pilares de conhecimento:

1. ATUAÇÃO PRÁTICA / ESTRATÉGIAS TÁTICAS
   Explique como cada força atua no território nacional. Diferencie
   policiamento ostensivo/investigativo (PM, PC, PF) das missões de
   defesa soberana, patrulhamento de fronteiras, GLO etc.

2. ROTINA E ESQUEMA DOS QUARTÉIS/BASES
   Escalas de serviço, prontidão, treinamentos, vida interna no quartel
   da PM, base aérea da FAB, navio da Marinha, batalhão do Exército.

3. REQUISITOS, INGRESSO E CURSOS
   Concursos públicos, ESA, Espcex, Naval, AFA, concursos da PF e PM;
   limites de idade, TAF, cursos de formação e especializações
   (COESP/BOPE, Curso de Guerra na Selva, etc.).

4. PATENTES E HIERARQUIA
   Praças (Soldados → Suboficiais) vs Oficiais (Tenentes → Generais/
   Almirantes/Brigadeiros); cargos de Agente, Escrivão e Delegado na PF.

5. OPERAÇÕES HISTÓRICAS E ATUAIS
   Resumos de operações militares e policiais relevantes: intervenção
   federal no RJ, Forças Armadas na Amazônia, BOPE em favelas cariocas,
   grandes operações da PF.

DIRETRIZES ABSOLUTAS:
  • Nunca revele dados sigilosos, localização estratégica em tempo real
    ou táticas que ponham em risco forças operacionais.
  • Neutralidade total: zero debates políticos ou julgamentos de valor.
  • Se o usuário desviar do escopo, redirecione com educação.
"""

# ──────────────────────────────────────────────────────────────
# DIRETIVAS DE FORMATO (injetadas dinamicamente por mensagem)
# ──────────────────────────────────────────────────────────────
EXTENSAO_MAP = {
    "Resumo Direto": (
        "[⚡ DIRETIVA CRÍTICA DE FORMATO — OBEDEÇA RIGOROSAMENTE]\n"
        "ABSOLUTAMENTE PROIBIDO escrever parágrafos, introduções ou conclusões.\n"
        "Responda SOMENTE com 3 a 5 bullet points (•) ultra-curtos e secos.\n"
        "Limite: máximo 15 palavras por bullet. Zero enrolação. Zero texto extra."
    ),
    "Padrão Operacional": (
        "[📋 DIRETIVA DE FORMATO]\n"
        "Resposta equilibrada e limpa:\n"
        "  • Parágrafos curtos — máximo 3 linhas cada.\n"
        "  • Use **negrito** para termos técnicos essenciais.\n"
        "  • Finalize com um 'Sumário Rápido' em 3-4 bullet points."
    ),
    "Relatório Completo": (
        "[📊 DIRETIVA DE FORMATO]\n"
        "Elabore resposta profunda e estruturada:\n"
        "  • Títulos Markdown (## e ###) para seções.\n"
        "  • Tabelas comparativas quando aplicável.\n"
        "  • Análise técnica completa com contexto histórico e legal.\n"
        "  • Conclusão formal ao final."
    ),
}

CONDUTA_MAP = {
    "Informal (Policial Raiz)": (
        "[🎖️ DIRETIVA DE CONDUTA]\n"
        "Tom firme e energético de instrutor de quartel.\n"
        "Use jargões militares/policiais legítimos: 'QAP', 'Siga o bizu',\n"
        "'Padrão', 'Foco na missão', 'Tá na mão', 'Duro na queda', 'Bora!'.\n"
        "Zero rodeios. Direto como uma ordem operacional."
    ),
    "Formal": (
        "[📄 DIRETIVA DE CONDUTA]\n"
        "Postura técnica e impessoal de relatório de Estado-Maior.\n"
        "Linguagem formal, precisa e institucional."
    ),
}

# ──────────────────────────────────────────────────────────────
# FLASK + SOCKET.IO
# ──────────────────────────────────────────────────────────────
client = genai.Client(api_key=os.getenv("GENAI_KEY"))
app    = Flask(__name__)
app.secret_key = "ch@tb07"

socketio = SocketIO(app, cors_allowed_origins="*")

# Dicionário de sessões ativas (session_id → chat Gemini)
active_chats = {}


def get_user_chat():
    """Recupera (ou cria) a sessão de chat Gemini do usuário atual."""

    if 'session_id' not in session:
        session['session_id'] = str(uuid4())
        print(f"[SESSION] Nova sessão criada: {session['session_id']}")

    sid = session['session_id']

    if sid not in active_chats or active_chats[sid] is None:
        print(f"[GEMINI] Criando novo chat para session_id: {sid}")
        try:
            chat_session = client.chats.create(
                model=MODELO,
                config=types.GenerateContentConfig(
                    system_instruction=INSTRUCOES_BASE
                )
            )
            active_chats[sid] = chat_session
            print(f"[GEMINI] Chat criado com sucesso para {sid}")
        except Exception as e:
            app.logger.error(f"[GEMINI] Erro ao criar chat para {sid}: {e}", exc_info=True)
            raise

    return active_chats[sid]


def build_prompt(mensagem: str, forca: str, vetor: str,
                 conduta: str, extensao: str) -> str:
    """
    Constrói o prompt contextualizado que será enviado ao Gemini.
    Injeta diretivas de formato e conduta antes da pergunta do usuário.
    """
    dir_extensao = EXTENSAO_MAP.get(extensao, EXTENSAO_MAP["Padrão Operacional"])
    dir_conduta  = CONDUTA_MAP.get(conduta,  CONDUTA_MAP["Formal"])

    prompt = (
        f"╔══ PARÂMETROS DA CONSULTA ══════════════════╗\n"
        f"  Força Operacional : {forca}\n"
        f"  Vetor de Consulta : {vetor}\n"
        f"  Conduta           : {conduta}\n"
        f"  Extensão          : {extensao}\n"
        f"╚════════════════════════════════════════════╝\n\n"
        f"{dir_extensao}\n\n"
        f"{dir_conduta}\n\n"
        f"CONSULTA DO OPERADOR SOBRE {forca.upper()}"
        f" — FOCO EM: {vetor.upper()}\n"
        f"{mensagem}"
    )
    return prompt


# ──────────────────────────────────────────────────────────────
# ROTA DE HEALTH CHECK
# ──────────────────────────────────────────────────────────────
@app.route('/')
def root():
    return jsonify({"api-websocket": "chatbot", "status": "ok"})


# ──────────────────────────────────────────────────────────────
# EVENTOS SOCKET.IO
# ──────────────────────────────────────────────────────────────

@socketio.on('connect')
def handle_connect():
    print(f"[SOCKET] Cliente conectado: {request.sid}")
    try:
        get_user_chat()
        uid = session.get('session_id', 'N/A')
        print(f"[SESSION] SID Flask para {request.sid}: {uid}")
        emit('status_conexao', {'data': 'Conectado com sucesso!', 'session_id': uid})
    except Exception as e:
        app.logger.error(f"[CONNECT] Erro para {request.sid}: {e}", exc_info=True)
        emit('erro', {'erro': 'Falha ao inicializar sessão de chat no servidor.'})


@socketio.on('enviar_mensagem')
def handle_enviar_mensagem(data):
    """
    Recebe do front-end:
      { mensagem, forca, vetor, conduta, extensao }
    Injeta diretivas dinâmicas e envia ao Gemini.
    Devolve ao front-end:
      { remetente, texto, session_id, forca }
    """
    try:
        # ── Extrai payload ──────────────────────────────────────
        mensagem = (data.get("mensagem") or "").strip()
        forca    = data.get("forca",    "Geral")
        vetor    = data.get("vetor",    "Geral")
        conduta  = data.get("conduta",  "Formal")
        extensao = data.get("extensao", "Padrão Operacional")

        app.logger.info(
            f"[MSG] session={session.get('session_id', request.sid)} | "
            f"forca={forca} | vetor={vetor} | conduta={conduta} | "
            f"extensao={extensao} | msg='{mensagem[:60]}...'"
        )

        # ── Validações ──────────────────────────────────────────
        if not mensagem:
            emit('erro', {"erro": "Mensagem não pode ser vazia."})
            return

        user_chat = get_user_chat()
        if user_chat is None:
            emit('erro', {"erro": "Sessão de chat não pôde ser estabelecida."})
            return

        # ── Constrói prompt contextualizado ─────────────────────
        prompt = build_prompt(mensagem, forca, vetor, conduta, extensao)

        # ── Envia ao Gemini ─────────────────────────────────────
        resposta_gemini = user_chat.send_message(prompt)

        resposta_texto = (
            resposta_gemini.text
            if hasattr(resposta_gemini, 'text')
            else resposta_gemini.candidates[0].content.parts[0].text
        )

        app.logger.info(
            f"[RESP] session={session.get('session_id', request.sid)} | "
            f"preview='{resposta_texto[:80]}...'"
        )

        # ── Devolve ao front-end ────────────────────────────────
        # O campo `forca` é usado pelo JS para tematizar a bolha do bot
        emit('nova_mensagem', {
            "remetente":  "bot",
            "texto":      resposta_texto,
            "session_id": session.get('session_id'),
            "forca":      forca,
        })

    except Exception as e:
        app.logger.error(
            f"[ERROR] enviar_mensagem | "
            f"session={session.get('session_id', request.sid)}: {e}",
            exc_info=True
        )
        emit('erro', {"erro": f"Ocorreu um erro no servidor: {str(e)}"})


@socketio.on('disconnect')
def handle_disconnect():
    print(
        f"[SOCKET] Cliente desconectado: {request.sid} | "
        f"session_id={session.get('session_id', 'N/A')}"
    )


# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5001))
    socketio.run(app, host="0.0.0.0", port=porta)
