import os
import glob
import threading
import requests
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from pypdf import PdfReader
import edge_tts
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# 1. Servidor Web auxiliar para mantener Render activo
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Paco RAG OK")

def run_health_check():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_check, daemon=True).start()

# 2. Configuración y Credenciales
TELEGRAM_TOKEN = "8979818632:AAGxBHt2hCgXlIpAneCz1_qEiHTpFYb3BwU"
GROQ_API_KEY = "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"

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# 3. Indexación RAG: Carga y fragmentación de todos los PDFs sin límite de páginas
print("Indexando manuales técnicos completos para RAG...")
chunks = []
pdf_files = sorted(glob.glob("*.pdf"))

for pdf in pdf_files:
    try:
        reader = PdfReader(pdf)
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                # Dividir la página en párrafos o bloques lógicos
                paragraphs = text.split("\n\n")
                for p in paragraphs:
                    clean_p = p.strip()
                    if len(clean_p) > 30: # Ignorar líneas muy cortas o basura
                        chunks.append(clean_p)
    except Exception as e:
        print(f"Error procesando {pdf}: {e}")

if not chunks:
    chunks = ["No hay manuales cargados en el sistema."]

# Crear el vectorizador TF-IDF para búsqueda semántica local
vectorizer = TfidfVectorizer(stop_words='spanish')
tfidf_matrix = vectorizer.fit_transform(chunks)
print(f"Indexación completa. Total de fragmentos indexados: {len(chunks)}")

def search_relevant_chunks(query, top_k=3):
    """Busca los fragmentos más relevantes en los manuales según la pregunta"""
    try:
        query_vec = vectorizer.transform([query])
        similarities = cosine_similarity(query_vec, tfidf_matrix).flatten()
        top_indices = similarities.argsort()[-top_k:][::-1]
        
        relevant_text = ""
        for idx in top_indices:
            if similarities[idx] > 0.03: # Umbral mínimo de relevancia
                relevant_text += f"\n- {chunks[idx]}\n"
                
        return relevant_text if relevant_text else "No se encontró un procedimiento exacto en los fragmentos principales."
    except Exception as e:
        print(f"Error en búsqueda RAG: {e}")
        return "Error al buscar en los manuales."

def generate_voice_file(text, output_file="respuesta.mp3"):
    """Genera audio con voz masculina en español argentino (es-AR-TomasNeural)"""
    clean_text = text.replace("*", "").replace("#", "").replace("`", "").replace("_", "")
    async def _generate():
        communicate = edge_tts.Communicate(clean_text, "es-AR-TomasNeural")
        await communicate.save(output_file)
    
    asyncio.run(_generate())

def query_groq_llm(user_prompt):
    # Buscar dinámicamente los fragmentos del manual correspondientes a esta pregunta
    relevant_context = search_relevant_chunks(user_prompt, top_k=3)
    
    system_instruction = f"""
    Eres Paco, un asistente técnico especializado para el personal de tráfico del Subte (motoristas, guardias, maniobristas).
    Tu función es ayudar a resolver fallas técnicas, averías en formaciones y responder procedimientos de actuación.

    FRAGMENTOS DE MANUALES RECUPERADOS PARA ESTA CONSULTA:
    {relevant_context}

    Reglas estrictas:
    1. Sé conciso, claro y directo. Ve al grano sin introducciones ni formalismos innecesarios.
    2. NO menciones códigos de anexos, números de revisión, nombres de archivos PDF ni frases como "Según el manual..." o "En el anexo LXVII...".
    3. Basate estrictamente en los fragmentos de manuales provistos arriba.
    4. Para resolución de fallas o procedimientos paso a paso, usa listas numeradas precisas.
    5. Si la información no está en los fragmentos provistos, indicalo de forma directa o aconseja consultar con la central de tráfico.
    """

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY.strip()}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.2
    }
    response = requests.post(url, json=payload, headers=headers, timeout=30)
    if response.status_code == 200:
        return response.json()['choices'][0]['message']['content'], None
    else:
        err = response.json().get('error', {}).get('message', 'Error en la consulta')
        return None, f"⚠️ Error {response.status_code}: {err}"

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 **¡Hola, compañero!** Soy Paco, tu Asistente Técnico con RAG activo. Podés consultarme sobre cualquier falla y buscaré en todos los manuales completos. ¿En qué te ayudo?", parse_mode="Markdown")

# Manejador de Notas de Voz
@bot.message_handler(content_types=['voice'])
def handle_voice_message(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        transcribe_url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY.strip()}"}
        
        files = {
            'file': ('voice.ogg', downloaded_file, 'audio/ogg')
        }
        data = {
            'model': 'whisper-large-v3',
            'language': 'es'
        }
        
        trans_resp = requests.post(transcribe_url, headers=headers, files=files, data=data, timeout=30)
        
        if trans_resp.status_code != 200:
            err_detail = trans_resp.json().get('error', {}).get('message', 'Error procesando audio')
            bot.reply_to(message, f"⚠️ Error transcripción ({trans_resp.status_code}): {err_detail}")
            return
            
        transcribed_text = trans_resp.json().get('text', '')
        if not transcribed_text:
            bot.reply_to(message, "⚠️ No logré escuchar con claridad el audio.")
            return

        respuesta_texto, error = query_groq_llm(transcribed_text)
        if error:
            bot.reply_to(message, error)
            return

        bot.reply_to(message, f"🎤 *Escuché:* \"{transcribed_text}\"\n\n{respuesta_texto}", parse_mode="Markdown")

        bot.send_chat_action(message.chat.id, 'record_audio')
        audio_filename = f"resp_{message.message_id}.mp3"
        generate_voice_file(respuesta_texto, audio_filename)

        with open(audio_filename, "rb") as audio:
            bot.send_voice(message.chat.id, audio)

        if os.path.exists(audio_filename):
            os.remove(audio_filename)

    except Exception as e:
        bot.reply_to(message, f"⚠️ Error procesando nota de voz: {str(e)}")

# Manejador de Mensajes de Texto
@bot.message_handler(func=lambda message: True)
def handle_text_message(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')

        respuesta_texto, error = query_groq_llm(message.text)
        if error:
            bot.reply_to(message, error)
            return

        bot.reply_to(message, respuesta_texto, parse_mode="Markdown")

        bot.send_chat_action(message.chat.id, 'record_audio')
        audio_filename = f"resp_{message.message_id}.mp3"
        generate_voice_file(respuesta_texto, audio_filename)

        with open(audio_filename, "rb") as audio:
            bot.send_voice(message.chat.id, audio)

        if os.path.exists(audio_filename):
            os.remove(audio_filename)

    except Exception as e:
        bot.reply_to(message, f"⚠️ Error: {str(e)}")

if __name__ == "__main__":
    print("🤖 Paco con RAG listo...")
    bot.polling(non_stop=True)
