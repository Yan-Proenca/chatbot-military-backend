import sys

if sys.platform != 'win32':
    try:
        from gevent import monkey
        monkey.patch_all()
    except ImportError:
        print("Gevent não encontrado. O desempenho do WebSocket pode ser afetado. Instale com 'pip install gevent' para melhor performance.")


from flask import Flask, request, session, jsonify
from flask_socketio import SocketIO, emit
from google import genai
from google.genai import types
from dotenv import load_dotenv
from uuid import uuid4
import os

# Carrega as variáveis ocultas do arquivo .env (como a chave da API do Gemini)
load_dotenv()

# Define qual versão da IA vamos usar. O modelo "flash" é rápido e ideal para chatbots.
MODELO = "gemini-3.1-flash-lite"

instrucoes = """
Você é um especialista em Defesa Nacional e Segurança Pública do Brasil. Seu objetivo é atuar como um chatbot educativo e informativo que domina a estrutura, a rotina e a atuação prática de duas grandes frentes: as Forças de Segurança Pública (Polícia Militar, Polícia Federal e unidades especiais como o BOPE) e as Forças Armadas (Exército, Marinha e Aeronáutica).

Suas atribuições obrigatórias estão divididas em quatro pilares principais:
1. ATUAÇÃO PRÁTICA NO BRASIL: Explicar claramente como cada força atua no território nacional. Diferenciar a segurança pública interna e o policiamento ostensivo/investigativo (PM e PF) das missões de defesa soberana, patrulhamento de fronteiras, controle do espaço aéreo, guarda costeira e Operações de Garantia da Lei e da Ordem - GLO (Exército, Marinha e Aeronáutica).
2. ROTINA E ESQUEMA DOS QUARTÉIS/BASES: Detalhar a vida interna nas instituições. Como funcionam as escalas de serviço, a prontidão, a rotina de treinamentos, as diferenças entre a vida no quartel da PM, em uma base aérea da FAB, em um navio da Marinha ou em um batalhão do Exército.
3. REQUISITOS, INGRESSO E CURSOS: Explicar as formas de entrada para cada uma (concursos públicos, ESA, Espcex, Naval, AFA, concursos da PF e PM), limites de idade, exigências físicas (TAF), e como funcionam os cursos de formação e especializações (como o COESP do BOPE ou o curso de Guerra na Selva do Exército).
4. PATENTES E HIERARQUIA: Mapear a escala hierárquica comparada, explicando a divisão rigorosa entre Praças (Soldados, Cabos, Sargentos, Suboficiais) e Oficiais (Tenentes, Capitães, Majores, Coronéis/Generais/Almirantes/Brigadeiros), além dos cargos de Agentes, Escrivães e Delegados na PF.

DIRETRIZES DE SEGURANÇA, COMPORTAMENTO E FILTRO DE CONTEÚDO (RIGOROSO):
- SIGILO E SEGURANÇA OPERACIONAL: Sob nenhuma circunstância revele dados sigilosos, localizações estratégicas em tempo real, planos de defesa confidenciais ou táticas que ponham em risco as forças operacionais. O tom deve ser estritamente técnico, histórico e institucional. Proibida apologia à violência.
- NEUTRALIDADE ABSOLUTA: Recuse debates políticos, ideológicos ou julgamentos de valor sobre as forças ou operações passadas/presentes. O foco é a estrutura legal, a atribuição constitucional de cada força e o funcionamento prático.
- FOCO NO ESCOPO: Se o usuário tentar desviar para assuntos não relacionados a essas forças (como política partidária, jogos ou outros temas cotidianos), mude o foco educadamente de volta para a estrutura de defesa e segurança.

FORMATO DE RESPOSTA:
Suas respostas devem ser profundas, detalhadas e completas. No entanto, para garantir uma excelente legibilidade, você DEVE sempre iniciar ou finalizar cada resposta complexa com um "Resumo Direto" em tópicos (Markdown). Use negritos para destacar patentes, siglas e termos institucionais importantes.
"""

# Inicializa a conexão com a inteligência artificial do Google usando a chave da API
client = genai.Client(api_key=os.getenv("GENAI_KEY"))

# Cria o nosso aplicativo web principal (o servidor)
app = Flask(__name__)

# A 'secret_key' funciona como uma senha interna do servidor para proteger 
# e criptografar os dados da sessão (as "lembranças" de quem é quem).
app.secret_key = "ch@tb07"

# Adiciona a funcionalidade de WebSockets (comunicação em tempo real) ao nosso app.
# O 'cors_allowed_origins="*"' é crucial: ele permite que o nosso front-end (HTML/JS) 
# consiga se conectar com esse back-end, mesmo que estejam em arquivos ou portas diferentes.
socketio = SocketIO(app, cors_allowed_origins="*")

# Dicionário que funciona como a "memória temporária" do servidor. 
# Ele guarda a conversa de cada aluno separadamente usando um ID único.
active_chats = {}

def get_user_chat():
    """
    Função principal de gerenciamento de usuários.
    Ela verifica quem está mandando a mensagem e recupera a conversa correta,
    garantindo que o bot não misture o chat do Aluno A com o do Aluno B.
    """
    
    # Passo 1: Se o usuário é novo (não tem um 'session_id'), criamos um ID único para ele.
    # Usamos o 'uuid4' para gerar um código aleatório impossível de repetir.
    if 'session_id' not in session:
        session['session_id'] = str(uuid4())
        print(f"Nova sessão Flask criada: {session['session_id']}")

    session_id = session['session_id']

    # Passo 2: Se o usuário já tem um ID, mas ainda não tem uma conversa aberta com o Gemini...
    if session_id not in active_chats:
        print(f"Criando novo chat Gemini para session_id: {session_id}")
        try:
            # ...nós criamos uma nova conversa e passamos as instruções (personalidade).
            chat_session = client.chats.create(
                model=MODELO,
                config=types.GenerateContentConfig(system_instruction=instrucoes)
            )
            # Guardamos essa conversa no nosso dicionário (memória).
            active_chats[session_id] = chat_session
            print(f"Novo chat Gemini criado e armazenado para {session_id}")
        except Exception as e:
            app.logger.error(f"Erro ao criar chat Gemini para {session_id}: {e}", exc_info=True)
            raise  # Se der erro aqui, repassa para o sistema avisar que falhou
    
    # Passo 3: Segurança extra. Se o servidor reiniciou (apagou a variável active_chats), 
    # mas o usuário ainda estava no navegador com o mesmo ID, nós recriamos a conexão dele.
    if session_id in active_chats and active_chats[session_id] is None:
        print(f"Recriando chat Gemini para session_id existente (estava None): {session_id}")
        try:
            chat_session = client.chats.create(
                model=MODELO,
                config=types.GenerateContentConfig(system_instruction=instrucoes)
            )
            active_chats[session_id] = chat_session
        except Exception as e:
            app.logger.error(f"Erro ao recriar chat Gemini para {session_id}: {e}", exc_info=True)
            raise

    # Retorna o histórico de mensagens exato daquele usuário.
    return active_chats[session_id]

# Rota simples para verificar se o servidor está rodando.
# Ao acessar o localhost no navegador, o aluno verá este aviso em formato JSON.
@app.route('/')
def root():
    return jsonify({
        "api-websocket": "chatbot",
        "status": "ok"
    })


# ------------------------------------------------------------------
# EVENTOS SOCKET.IO (Onde a mágica do tempo real acontece)
# ------------------------------------------------------------------

@socketio.on('connect')
def handle_connect():
    """
    EVENTO: Disparado no momento exato em que o Front-end (navegador) se conecta ao servidor.
    """
    print(f"Cliente conectado: {request.sid}")
    
    try:
        # Tenta criar a pasta do usuário assim que ele entra
        get_user_chat()
        user_session_id = session.get('session_id', 'N/A')
        print(f"Sessão Flask para {request.sid} usa session_id: {user_session_id}")
        
        # O comando 'emit' serve para enviar um pacote de dados do servidor PARA o front-end.
        emit('status_conexao', {'data': 'Conectado com sucesso!', 'session_id': user_session_id})
    except Exception as e:
        app.logger.error(f"Erro durante o evento connect para {request.sid}: {e}", exc_info=True)
        emit('erro', {'erro': 'Falha ao inicializar a sessão de chat no servidor.'})


@socketio.on('enviar_mensagem')
def handle_enviar_mensagem(data):
    """
    EVENTO: O Front-end mandou uma mensagem (ex: o usuário clicou em 'Enviar' no chat).
    A variável 'data' traz os dados enviados pelo HTML (o texto que o usuário digitou).
    """
    try:
        # Pega o texto de dentro do dicionário enviado pelo JS
        mensagem_usuario = data.get("mensagem")
        app.logger.info(f"Mensagem recebida de {session.get('session_id', request.sid)}: {mensagem_usuario}")

        # Validação básica: não deixa enviar mensagens vazias
        if not mensagem_usuario:
            emit('erro', {"erro": "Mensagem não pode ser vazia."})
            return

        # Puxa o histórico de conversa desse aluno específico
        user_chat = get_user_chat()
        if user_chat is None:
            emit('erro', {"erro": "Sessão de chat não pôde ser estabelecida."})
            return

        # ==========================================
        # COMUNICAÇÃO COM O GOOGLE GEMINI
        # ==========================================
        # Aqui o nosso servidor repassa a pergunta para a IA do Google...
        resposta_gemini = user_chat.send_message(mensagem_usuario)

        # ... e aqui extraímos apenas o texto da resposta que o Gemini devolveu.
        # (O 'if/else' garante que vamos achar o texto independente de como a API estruturar a resposta)
        resposta_texto = (
            resposta_gemini.text
            if hasattr(resposta_gemini, 'text')
            else resposta_gemini.candidates[0].content.parts[0].text
        )
        
        # O servidor usa o 'emit' para devolver a resposta final do bot lá para a tela do Front-end.
        emit('nova_mensagem', {"remetente": "bot", "texto": resposta_texto, "session_id": session.get('session_id')})
        app.logger.info(f"Resposta enviada para {session.get('session_id', request.sid)}: {resposta_texto}")

    except Exception as e:
        app.logger.error(f"Erro ao processar 'enviar_mensagem' para {session.get('session_id', request.sid)}: {e}", exc_info=True)
        # Se algo quebrar (ex: falha de internet), avisamos o front-end educadamente.
        emit('erro', {"erro": f"Ocorreu um erro no servidor: {str(e)}"})


@socketio.on('disconnect')
def handle_disconnect():
    """
    EVENTO: Disparado quando o usuário fecha a aba do navegador ou perde a conexão.
    """
    print(f"Cliente desconectado: {request.sid}, session_id: {session.get('session_id', 'N/A')}")


# Inicia o servidor local. A porta padrão do Flask costuma ser a 5000.
if __name__ == "__main__":
    # A Render vai injetar a porta correta aqui. Se não houver (local), usa a 5001.
    porta = int(os.environ.get("PORT", 5001))
    
    # O host="0.0.0.0" é OBRIGATÓRIO para a Render, pois permite conexões externas.
    socketio.run(app)
