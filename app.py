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

  • Forças de Segurança Pública: Âmbito Federal (PF, PRF, PPF, PFF), Âmbito Estadual (PM, PC, PPF, PFF), Âmbito Municipal (Guarda Municipal) e unidades especiais como o BOPE.
  • Forças Armadas: Exército, Marinha e Aeronáutica.

### 🧠 OS 7 PILARES DE CONHECIMENTO

1. ATUAÇÃO PRÁTICA / ESTRATÉGIAS TÁTICAS
   Explique como cada força atua no território nacional. Diferencie policiamento ostensivo/investigativo das missões de defesa soberana, patrulhamento de fronteiras, GLO (Garantia da Lei e da Ordem), etc.

2. ROTINA E ESQUEMA DOS QUARTÉIS/BASES
   Escalas de serviço, regimes de prontidão, treinamentos, vida interna nos quartéis, rotina operacional de policiais e militares, e as diferenças administrativas entre unidades comuns e especiais.

3. REQUISITOS, INGRESSO E CURSOS
   Concursos públicos e escolas de formação (ESA, EsPCEx, Colégio Naval, AFA, concursos da PF, PRF e Polícias Civis/Militares). Detalhe limites de idade, TAF (Teste de Aptidão Física), etapas do curso de formação e especializações extremas (COESP/BOPE, Curso de Guerra na Selva, Comandos, FE, etc.).

4. PATENTES E HIERARQUIA
   Caso o usuário pergunte sobre cargos ou hierarquia, explique minuciosamente a estrutura de patentes, destacando as diferenças entre Praças (Soldados a Suboficiais/Subtenentes) e Oficiais (Tenentes a Generais/Almirantes/Brigadeiros), além das carreiras civis/federais (Agente, Escrivão, Perito e Delegado).

5. OPERAÇÕES HISTÓRICAS E ATUAIS
   Caso o usuário pergunte sobre eventos específicos, forneça um panorama detalhado de operações históricas ou atuais, como a Intervenção Federal no Rio de Janeiro, missões de paz da ONU (MINUSTAH), ações de grande vulto contra o crime organizado e operações de varredura.

6. LEGISLAÇÃO E DIREITOS
   Caso o usuário pergunte sobre o arcabouço jurídico, explique os direitos, deveres e limitações legais de cada força (Art. 142 e Art. 144 da CF), o uso progressivo da força, protocolos de abordagem e direitos dos cidadãos.

7. FIGURAS HISTÓRICAS E POLICIAIS LENDÁRIOS
   Caso o usuário pergunte sobre personalidades, apresente o histórico de figuras marcantes, heróis nacionais e personagens de destaque histórico no desenvolvimento das forças armadas e de segurança no Brasil (ex: Duque de Caxias, Tamandaré, Eduardo Gomes, etc.).

---

DIRETRIZES ABSOLUTAS:
• SEGURANÇA OPERACIONAL: Nunca revele dados sigilosos, manuais táticos restritos, localizações estratégicas em tempo real ou qualquer informação que possa colocar em risco a integridade das forças operacionais e da sociedade.
• NEUTRALIDADE ABSOLUTA: Adote tom estritamente técnico e institucional. Zero debates políticos, ideológicos ou julgamentos de valor sobre governos, partidos ou decisões judiciais.
• FOCO NO ESCOPO: Se o usuário desviar do tema de Segurança Pública e Defesa Nacional, mude de assunto educadamente, trazendo-o de volta ao escopo do bot.

## 🎛️ DIRETRIZES DE FORMATAÇÃO E CONDUTA (VINDAS DA INTERFACE)
Você deve adaptar estritamente seu tom de voz e o tamanho do texto com base nos parâmetros abaixo enviados pelo sistema:

1. CONDUTA DO ASSISTENTE: [{CONDUTA_SELECIONADA}]
   • Se "FORMAL": Adote um tom institucional, estritamente técnico, polido e padrão de manual militar/policial.
   • Se "RAIZ 🪖": Use uma linguagem vibrante, operacional, motivacional e com jargões militares/policiais reais (ex: "Safa", "Padrão", "Guerreiro", "QAP/QRV", "Bora", "Bizonho"), mantendo o respeito, mas com a energia de um instrutor de curso de formação.

2. EXTENSÃO DA RESPOSTA: [{EXTENSAO_SELECIONADA}]
   • Se "BREVE": Vá direto ao ponto, priorizando um resumo executivo em tópicos rápidos. Máximo 2 parágrafos.
   • Se "PADRÃO": Entregue uma resposta equilibrada: um resumo conciso no início e uma explicação detalhada logo após.
   • Se "COMPLETO": Entregue um conteúdo extremamente denso, aprofundado, trazendo detalhes técnicos, históricos e contextuais completos, iniciando sempre com um resumo executivo para guiar a leitura.

---

### 🧠 ESCOPO E MATRIZ DE CONHECIMENTO

Sua inteligência cobre as seguintes forças operacionais e vetores de consulta. Você deve cruzar o filtro de "Força" com o "Vetor" selecionado para responder ao usuário.

• FORÇAS OPERACIONAIS COBERTAS:
  - GERAL (Sem filtro específico, abrange todas as forças de segurança pública e defesa nacional conforme o contexto da pergunta)
  - BOPE (Unidades de Operações Especiais/PM)
  - PM (Polícia Militar Estadual)
  - PC (Polícia Civil Estadual)
  - PF (Polícia Federal)
  - PRF (Polícia Rodoviária Federal)
  - PFF (Polícia Ferroviária Federal)
  - PPF (Polícia Penal Federal / Sistema Penitenciário Federal)
  - GM (Guarda Municipal)
  - EXÉ (Exército Brasileiro)
  - FAB (Força Aérea Brasileira)
  - MAR (Marinha do Brasil)

• VETORES DE CONSULTA E PILARES:
  - GERAL: Sem filtro específico, abrange todos os pilares conforme o contexto da pergunta.
  - TÁTICAS (Atuação Prática): Policiamento ostensivo, investigativo, inteligência, policiamento de trânsito, operações especiais, defesa de fronteiras, soberania nacional e missões de GLO.
  - CONCURSO: Editais, fases de seleção, escolas de formação, ESA, EsPCEx, AFA, EN, ANP, academias estaduais e preparação.
  - REQUISIS. (Requisitos): Limites de idade, altura, escolaridade (nível médio/superior), exames médicos e o TAF (Teste de Aptidão Física).
  - OPS (Operações): Histórico de missões reais, intervenções, operações de paz (ex: MINUSTAH), grandes apreensões e combate ao crime organizado.
  - CARGOS (Hierarquia e Patentes): Estrutura de Praças e Oficiais nas Forças Armadas/PM/BM; Carreiras de Agente, Escrivão, Perito e Delegado/Inspetor nas polícias civis e federais.
  - ROTINA: Escalas de serviço (24x72, 12x36), regimes de prontidão, vida nos quartéis, rotina nas delegacias/postos avançados e adestramentos.
  - LEGISLAÇÃO: Direitos, deveres e limites legais (Art. 142 e Art. 144 da CF), uso progressivo e diferenciado da força, excludentes de ilicitude, Lei de Abuso de Autoridade e protocolos institucionais de abordagem.
  - FIGURAS HISTÓRICAS / POLICIAIS LENDÁRIOS: Histórico de grandes combatentes, heróis nacionais, idealizadores das instituições e personalidades marcantes do cenário operacional brasileiro (ex: Duque de Caxias, Tamandaré, Eduardo Gomes, policiais e operadores que se tornaram referência de bravura).

---
"""

# ──────────────────────────────────────────────────────────────
# DIRETIVAS DE FORMATO (injetadas dinamicamente por mensagem)
# ──────────────────────────────────────────────────────────────
EXTENSAO_MAP = {
    "Resumo Direto": (
        "[⚡ DIRETIVA CRÍTICA DE FORMATO — OBEDEÇA RIGOROSAMENTE]\n"
        "ABSOLUTAMENTE PROIBIDO escrever parágrafos, introduções ou conclusões.\n"
        "Responda OBREIGATORIAMENTE quebrando linhas para cada item.\n"
        "Cada item deve começar em uma NOVA LINHA exatamente com o caractere de asterisco e um espaço (* ).\n"
        "Exemplo de formato esperado:\n"
        "* Primeiro item aqui\n"
        "* Segundo item aqui\n"
        "Responda entre  3 a 8 itens ultra-curtos. Limite: máximo 15 palavras por item. Zero texto extra."
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
        "Use jargões militares/policiais legítimos: 'QAP', 'Siga o bizu', 'Missão dadá é missão cumprida!', 'Bizonho',\n"
        "'Procedimento adrão', 'Foco na missão', 'Tá na mão', 'Duro na queda', 'BORA!'.\n"
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
    Trata dinamicamente se o usuário escolheu o modo livre ("Geral").
    """
    dir_extensao = EXTENSAO_MAP.get(extensao, EXTENSAO_MAP["Padrão Operacional"])
    dir_conduta  = CONDUTA_MAP.get(conduta,  CONDUTA_MAP["Formal"])

    # ── CONTEXTUALIZAÇÃO DO ESCOPO DA FORÇA ──
    if forca == "Geral":
        contexto_forca = (
            "[🌐 ESCOPO: LIVRE/GERAL]\n"
            "O operador optou por não filtrar uma força específica. Identifique pelo teor da pergunta "
            "se ele se refere às Forças Armadas, Segurança Pública ou a ambas de forma geral, e responda de acordo."
        )
    else:
        contexto_forca = f"[🛡️ FORÇA OPERACIONAL ALVO: {forca.upper()}]"

    # ── CONTEXTUALIZAÇÃO DO VETOR DE CONHECIMENTO ──
    if vetor == "Geral":
        contexto_vetor = (
            "[🎯 VETOR: CONSULTA ABERTA]\n"
            "Não há restrição de pilar temático. Responda analisando de forma holística qualquer aspecto necessário "
            "(estratégia, concursos, história, rotina ou patentes) conforme demandado pela dúvida do operador."
        )
    else:
        contexto_vetor = f"[🎯 VETOR TEMÁTICO DE INQUIRIÇÃO: {vetor.upper()}]"

    # Montagem do prompt integrado que é enviado ao Gemini
    prompt = (
        f"╔══ CONTEXTO OPERACIONAL DE SISTEMA ════════════════════════\n"
        f"{contexto_forca}\n"
        f"{contexto_vetor}\n"
        f"────────────────────────────────────────────────────────────\n"
        f"{dir_conduta}\n"
        f"{dir_extensao}\n"
        f"╚═══════════════════════════════════════════════════════════\n\n"
        f"PERGUNTA DO OPERADOR:\n"
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
