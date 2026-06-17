import sys
import re

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

  • Forças de Segurança Pública: Âmbito Federal (PF, PRF, PPF), Âmbito Estadual (PM, PC) e Âmbito Municipal (Guarda Municipal - GM), além de unidades especiais como o BOPE.
  • Forças Armadas: Exército (EXÉ), Marinha (MAR) e Aeronáutica (FAB).

### 🧠 OS 7 PILARES DE CONHECIMENTO

1. ATUAÇÃO PRÁTICA / ESTRATÉGIAS TÁTICAS (TÁTICAS)
   Explique como cada força atua no território nacional. Diferencie policiamento ostensivo/investigativo das missões de defesa soberana, patrulhamento de fronteiras, GLO (Garantia da Lei e da Ordem), etc.

2. ROTINA E ESQUEMA DOS QUARTÉIS/BASES (ROTINA)
   Escalas de serviço, regimes de prontidão, treinamentos, vida interna nos quartéis, rotina operacional de policiais e militares, e as diferenças administrativas entre unidades comuns e especiais.

3. REQUISITOS, INGRESSO E CURSOS (CONCURSO / REQUISIS.)
   Concursos públicos e escolas de formação (ESA, EsPCEx, Colégio Naval, AFA, concursos da PF, PRF e Polícias Civis/Militares). Detalhe limites de idade, TAF (Teste de Aptidão Física), etapas do curso de formação e especializações extremas (COESP/BOPE, Curso de Guerra na Selva, Comandos, FE, etc.).

4. PATENTES E HIERARQUIA (CARGOS)
   Caso o usuário pergunte sobre cargos ou hierarquia, explique minuciosamente a estrutura de patentes, destacando as diferenças entre Praças (Soldados a Suboficiais/Subtenentes) e Oficiais (Tenentes a Generais/Almirantes/Brigadeiros), além das carreiras civis/federais (Agente, Escrivão, Perito e Delegado).

5. OPERAÇÕES HISTÓRICAS E ATUAIS (OPS)
   Caso o usuário pergunte sobre eventos específicos, forneça um panorama detalhado de operações históricas ou atuais, como a Intervenção Federal no Rio de Janeiro, missões de paz da ONU (MINUSTAH), ações de grande vulto contra o crime organizado e operações de varredura.

6. LEGISLAÇÃO E DIREITOS (LEGISLAÇÃO)
   Caso o usuário pergunte sobre o arcabouço jurídico, explique os direitos, deveres e limitations legais de cada força (Art. 142 e Art. 144 da CF), o uso progressivo da força, protocols de abordagem e direitos dos cidadãos.

7. FIGURAS HISTÓRICAS E POLICIAIS LENDÁRIOS (FIGURAS HISTÓRICAS)
   Caso o usuário pergunte sobre personalidades, apresente o histórico de figuras marcantes, heróis nacionais e personagens de destaque histórico no desenvolvimento das forças armadas e de segurança no Brasil (ex: Duque de Caxias, Tamandaré, Eduardo Gomes, etc.).

---

DIRETRIZES ABSOLUTAS:
• SEGURANÇA OPERACIONAL: Nunca revele dados sigilosos, manuais táticos restritos, localizações estratégicas em tempo real ou qualquer informação que possa colocar em risco a integridade das forças operacionais e da sociedade.
• NEUTRALIDADE ABSOLUTA: Adote tom estritamente técnico e institucional. Zero debates políticos, ideológicos ou julgamentos de valor sobre governos, partidos ou decisões judiciais.
• FOCO NO ESCOPO: Se o usuário desviar do tema de Segurança Pública e Defesa Nacional, mude de assunto educadamente, trazendo-o de volta ao escopo do bot.
"""

# ──────────────────────────────────────────────────────────────
# DIRETIVAS DE FORMATO (Injetadas dinamicamente mapeando a interface)
# ──────────────────────────────────────────────────────────────
EXTENSAO_MAP = {
    "BREVE": (
        "[⚡ DIRETIVA CRÍTICA DE FORMATO — OBEDEÇA RIGOROSAMENTE]\n"
        "ABSOLUTAMENTE PROIBIDO escrever parágrafos, introduções ou conclusões.\n"
        "Responda OBRIGATORIAMENTE quebrando linhas para cada item.\n"
        "Cada item deve começar em uma NOVA LINHA exatamente com o caractere de asterisco e um espaço (* ).\n"
        "Exemplo de formato esperado:\n"
        "* Primeiro item aqui\n"
        "* Segundo item aqui\n"
        "Responda entre 3 a 8 itens ultra-curtos. Limite: máximo 15 palavras por item. Zero texto extra."
    ),
    "PADRÃO": (
        "[📋 DIRETIVA DE FORMATO]\n"
        "Resposta equilibrada e limpa:\n"
        "  • Parágrafos curtos — máximo 3 linhas cada.\n"
        "  • Use **negrito** para termos técnicos essenciais.\n"
        "  • Finalize com um 'Sumário Rápido' em 3-4 bullet points."
    ),
    "COMPLETO": (
        "[📊 DIRETIVA DE FORMATO]\n"
        "Elabore resposta profunda e estruturada:\n"
        "  • Títulos Markdown (## e ###) para seções.\n"
        "  • Tabelas comparativas quando aplicável.\n"
        "  • Análise técnica completa com contexto histórico e legal.\n"
        "  • Conclusão formal ao final."
    ),
}

# ──────────────────────────────────────────────────────────────
# ALIAS DE EXTENSÃO
# O front-end envia o data-value completo ("Resumo Direto", etc.)
# mas o EXTENSAO_MAP usa chaves curtas ("BREVE", "PADRÃO", "COMPLETO").
# Este alias resolve a incompatibilidade sem alterar nenhum dos dois lados.
# ──────────────────────────────────────────────────────────────
EXTENSAO_ALIAS = {
    # Nomes completos vindos do front-end
    "RESUMO DIRETO":      "BREVE",
    "PADRÃO OPERACIONAL": "PADRÃO",
    "PADRAO OPERACIONAL": "PADRÃO",
    "RELATÓRIO COMPLETO": "COMPLETO",
    "RELATORIO COMPLETO": "COMPLETO",
    # Chaves curtas (retrocompatibilidade)
    "BREVE":   "BREVE",
    "PADRÃO":  "PADRÃO",
    "PADRAO":  "PADRÃO",
    "COMPLETO": "COMPLETO",
}

CONDUTA_MAP = {
    "RAIZ 🪖": (
        "[🎖️ DIRETIVA DE CONDUTA]\n"
        "Tom firme e energético de instrutor de quartel.\n"
        "Use jargões militares/policiais legítimos: 'QAP', 'Siga o bizu', 'Missão dada é missão cumprida!', 'Bizonho',\n"
        "'Procedimento padrão', 'Foco na missão', 'Tá na mão', 'Duro na queda', 'BORA!'.\n"
        "Zero rodeios. Direto como uma ordem operacional."
    ),
    "FORMAL": (
        "[📄 DIRETIVA DE CONDUTA]\n"
        "Postura técnica e impessoal de relatório de Estado-Maior.\n"
        "Linguagem formal, precisa e institucional."
    ),
}

# ──────────────────────────────────────────────────────────────
# DETECÇÃO DE INCONSISTÊNCIA FILTRO vs. CONTEÚDO DA PERGUNTA
# Quando o usuário seleciona uma força/vetor mas pergunta sobre outro,
# o bot recebe instrução de avisar a inconsistência e responder pelo prompt.
# ──────────────────────────────────────────────────────────────

# Palavras-chave associadas a cada Força Operacional
# Intencionalmente específicas para evitar falsos positivos
FORCA_KEYWORDS: dict[str, list[str]] = {
    'BOPE':        ['bope', 'batalhão de operações policiais especiais'],
    'PM':          ['polícia militar', 'policia militar', 'policial militar'],
    'PC':          ['polícia civil', 'policia civil', 'policial civil', 'delegacia'],
    'PF':          ['polícia federal', 'policia federal', 'policial federal',
                    'delegado federal', 'agente federal'],
    'PRF':         ['polícia rodoviária federal', 'policia rodoviaria federal', 'prf'],
    'PPF':         ['polícia penal federal', 'policia penal federal',
                    'agente penal federal', 'ppf'],
    'GM':          ['guarda municipal', 'guarda-municipal'],
    'EXÉRCITO':    ['exército', 'exercito', 'força terrestre', 'forca terrestre'],
    'AERONÁUTICA': ['aeronáutica', 'aeronautica', 'força aérea', 'forca aerea', 'fab'],
    'MARINHA':     ['marinha do brasil', 'força naval', 'forca naval', 'marinheiro'],
}

# Palavras-chave associadas a cada Vetor de Consulta
VETOR_KEYWORDS: dict[str, list[str]] = {
    'ESTRATÉGIAS TÁTICAS': ['estratégia tática', 'estrategia tatica',
                             'tática policial', 'tatica policial',
                             'técnica de abordagem', 'tecnica de abordagem'],
    'CONCURSO PÚBLICO':    ['concurso público', 'concurso publico',
                             'edital de concurso', 'prova objetiva', 'gabarito'],
    'REQUISITOS MÍNIMOS':  ['requisito mínimo', 'requisito minimo',
                             'altura mínima', 'limite de idade',
                             'peso mínimo', 'pré-requisito'],
    'OPERAÇÕES':           ['operação policial', 'operacao policial',
                             'operação especial', 'missão tática',
                             'missao tatica', 'operação de'],
    'CARGOS':              ['patente militar', 'hierarquia militar',
                             'hierarquia policial', 'promoção de posto',
                             'graduação militar', 'graduacao militar'],
    'ROTINA':              ['rotina policial', 'escala de serviço',
                             'escala de servico', 'plantão', 'rotina do quartel'],
    'LEGISLAÇÃO':          ['código penal', 'codigo penal',
                             'constituição federal', 'constituicao federal',
                             'decreto-lei', 'lei complementar',
                             'lei n°', 'lei nº', 'artigo da lei',
                             'resolução normativa'],
}


def _keyword_in_text(keyword: str, text: str) -> bool:
    """
    Verifica se `keyword` aparece em `text`.
    Para siglas curtas (sem espaço, ex: 'prf', 'fab'), usa regex com
    \\b (word boundary) para não confundir com substrings de outras palavras
    (ex: 'pf' não deve casar dentro de 'perfeito').
    Para frases com espaço, usa busca simples por substring.
    """
    if ' ' in keyword:
        return keyword in text
    pattern = r'\b' + re.escape(keyword) + r'\b'
    return re.search(pattern, text) is not None


def detect_inconsistency(mensagem: str, forca: str, vetor: str) -> list[str]:
    """
    Verifica se o conteúdo da mensagem menciona uma força ou vetor
    diferente do que foi selecionado nos filtros.

    Retorna uma lista de strings descrevendo cada inconsistência encontrada.
    Retorna lista vazia quando está tudo consistente ou filtro é "Geral".
    """
    msg_lower = mensagem.lower()
    inconsistencias: list[str] = []

    # ── Verificar Força Operacional ───────────────────────────
    # Só checa quando o usuário selecionou uma força específica (não "Geral")
    if forca.lower() != 'geral':
        forca_key = forca.upper()
        for f_key, keywords in FORCA_KEYWORDS.items():
            if f_key == forca_key:
                continue  # Pula a própria força selecionada
            if any(_keyword_in_text(kw, msg_lower) for kw in keywords):
                inconsistencias.append(
                    f'o filtro de **Força Operacional** está definido como **"{forca}"**, '
                    f'mas o texto da pergunta menciona **{f_key.title()}**'
                )
                break  # Relata apenas a primeira inconsistência de força

    # ── Verificar Vetor de Consulta ───────────────────────────
    # Só checa quando o usuário selecionou um vetor específico (não "Geral")
    if vetor.lower() != 'geral':
        vetor_key = vetor.upper()
        for v_key, keywords in VETOR_KEYWORDS.items():
            if v_key == vetor_key:
                continue  # Pula o próprio vetor selecionado
            if any(_keyword_in_text(kw, msg_lower) for kw in keywords):
                inconsistencias.append(
                    f'o filtro de **Vetor de Consulta** está definido como **"{vetor}"**, '
                    f'mas a pergunta parece abordar **{v_key.title()}**'
                )
                break  # Relata apenas a primeira inconsistência de vetor

    return inconsistencias


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
    # ── Mapeia extensão: o front-end envia o nome completo, ex: "Resumo Direto"
    # O alias converte para a chave curta usada pelo EXTENSAO_MAP ("BREVE", etc.)
    extensao_raw = extensao.upper() if extensao else "RESUMO DIRETO"
    extensao_key = EXTENSAO_ALIAS.get(extensao_raw, "PADRÃO")

    # ── Mapeia conduta
    conduta_key = conduta.upper() if conduta else "FORMAL"
    if "RAIZ" in conduta_key:
        conduta_key = "RAIZ 🪖"

    dir_extensao = EXTENSAO_MAP.get(extensao_key, EXTENSAO_MAP["PADRÃO"])
    dir_conduta  = CONDUTA_MAP.get(conduta_key,  CONDUTA_MAP["FORMAL"])

    # ── CONTEXTUALIZAÇÃO DO ESCOPO DA FORÇA ──
    if forca.lower() == "geral":
        contexto_forca = (
            "[🌐 ESCOPO: LIVRE/GERAL]\n"
            "O operador optou por não filtrar uma força específica. Identifique pelo teor da pergunta "
            "se ele se refere às Forças Armadas, Segurança Pública ou a ambas de forma geral, e responda de acordo."
        )
    else:
        contexto_forca = f"[🛡️ FORÇA OPERACIONAL ALVO: {forca.upper()}]"

    # ── CONTEXTUALIZAÇÃO DO VETOR DE CONHECIMENTO ──
    if vetor.lower() == "geral":
        contexto_vetor = (
            "[🎯 VETOR: CONSULTA ABERTA]\n"
            "Não há restrição de pilar temático. Responda analisando de forma holística qualquer aspect necessário "
            "(estratégia, concursos, história, rotina ou patentes) conforme demandado pela dúvida do operador."
        )
    else:
        contexto_vetor = f"[🎯 VETOR TEMÁTICO DE INQUIRIÇÃO: {vetor.upper()}]"

    # ── DETECÇÃO DE INCONSISTÊNCIA FILTRO vs. PERGUNTA ──
    # Verifica se a pergunta menciona uma força/vetor diferente do filtro selecionado.
    # Quando houver, o prompt do conteúdo (mensagem) prevalece sobre o filtro,
    # mas a IA é instruída a avisar o operador sobre a divergência antes de responder.
    inconsistencias = detect_inconsistency(mensagem, forca, vetor)

    if inconsistencias:
        lista_avisos = "\n".join(f"  {i+1}. {texto}" for i, texto in enumerate(inconsistencias))
        contexto_inconsistencia = (
            "\n[⚠️ DIRETIVA DE INCONSISTÊNCIA DETECTADA — OBEDEÇA OBRIGATORIAMENTE]\n"
            "Foi identificada uma divergência entre os parâmetros selecionados pelo operador "
            "e o conteúdo da pergunta:\n"
            f"{lista_avisos}\n"
            "AÇÃO OBRIGATÓRIA: Inicie sua resposta com um aviso breve e objetivo (1-2 frases) informando "
            "essa(s) divergência(s) ao operador, deixando claro que você seguirá o que foi efetivamente "
            "perguntado no texto (e não apenas o filtro selecionado na interface). Em seguida, responda "
            "normalmente priorizando o conteúdo da pergunta do operador sobre o filtro da interface.\n"
        )
    else:
        contexto_inconsistencia = ""

    # Montagem do prompt integrado que é enviado ao Gemini
    prompt = (
        f"╔══ CONTEXTO OPERACIONAL DE SISTEMA ════════════════════════\n"
        f"{contexto_forca}\n"
        f"{contexto_vetor}\n"
        f"{contexto_inconsistencia}"
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
        conduta  = data.get("conduta",  "FORMAL")
        extensao = data.get("extensao", "PADRÃO")

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
