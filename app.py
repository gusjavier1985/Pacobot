import os
import glob
import threading
import requests
import asyncio
import re
import uuid
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import telebot
from pypdf import PdfReader
import edge_tts

# Directorios para archivos estáticos (Audios e Imágenes)
AUDIO_DIR = "static_audio"
IMAGE_DIR = "static_images"
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)

# Servidor Flask para la API Web
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route('/', methods=['GET'])
def health_check():
    return "Bot Paco API OK", 200

@app.route('/audio/<filename>', methods=['GET'])
def get_audio(filename):
    response = send_from_directory(AUDIO_DIR, filename)
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response

@app.route('/images/<filename>', methods=['GET'])
def get_image(filename):
    """Entrega imágenes con cabeceras CORS explícitas"""
    response = send_from_directory(IMAGE_DIR, filename)
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response

# Configuración y Credenciales
TELEGRAM_TOKEN = "8979818632:AAGxBHt2hCgXlIpAneCz1_qEiHTpFYb3BwU"
GROQ_API_KEY = "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"

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Indexación RAG Nativa de PDFs
print("Indexando manuales técnicos completos...")
chunks = []
pdf_files = sorted(glob.glob("*.pdf"))

for pdf in pdf_files:
    try:
        reader = PdfReader(pdf)
        for page in reader.pages:
            text = page.extract_text()
            if text:
                paragraphs = text.split("\n\n")
                for p in paragraphs:
                    clean_p = p.strip()
                    if len(clean_p) > 25:
                        chunks.append(clean_p)
    except Exception as e:
        print(f"Error procesando {pdf}: {e}")

if not chunks:
    chunks = ["No hay manuales cargados en el sistema."]

print(f"Indexación completa. Total de fragmentos: {len(chunks)}")

def search_relevant_chunks(query, top_k=3):
    stopwords = {"el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "de", "del", "a", "ante", "en", "que", "por", "para", "con", "se", "es", "su", "lo", "como"}
    words = re.findall(r'\b\w+\b', query.lower())
    keywords = [w for w in words if w not in stopwords and len(w) > 2]

    if not keywords:
        keywords = words

    scored_chunks = []
    for chunk in chunks:
        chunk_lower = chunk.lower()
        score = sum(1 for kw in keywords if kw in chunk_lower)
        if score > 0:
            scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    
    relevant_text = ""
    for score, chunk in scored_chunks[:top_k]:
        relevant_text += f"\n- {chunk}\n"

    return relevant_text if relevant_text else "No se encontraron detalles específicos en los manuales."

def search_relevant_image(query):
    """Busca si hay una imagen que coincida con las palabras clave y devuelve su objeto completo"""
    json_path = "imagenes.json"
    if not os.path.exists(json_path):
        return None
    
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            images_db = json.load(f)
    except Exception as e:
        print(f"Error leyendo imagenes.json: {e}")
        return None

    stopwords = {"el", "la", "los", "las", "un", "una", "de", "del", "en", "que", "por", "para", "con", "se", "es", "su", "lo", "donde", "esta", "se", "encuentra"}
    words = set(re.findall(r'\b\w+\b', query.lower())) - stopwords

    best_match = None
    best_score = 0

    for item in images_db:
        keywords = set([kw.lower() for kw in item.get("palabras_clave", [])])
        score = len(words.intersection(keywords))
        if score > best_score and score >= 1:
            best_score = score
            best_match = item

    return best_match

def generate_voice_file(text, output_file):
    clean_text = text.replace("*", "").replace("#", "").replace("`", "").replace("_", "")
    async def _generate():
        communicate = edge_tts.Communicate(clean_text, "es-AR-TomasNeural")
        await communicate.save(output_file)
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_generate())
        loop.close()
    except Exception as e:
        print(f"Error generando audio: {e}")

def query_groq_llm(user_prompt, image_info=None):
    relevant_context = search_relevant_chunks(user_prompt, top_k=3)
    
    image_context = ""
    if image_info:
        image_context = f"\nFICHA TÉCNICA OFICIAL DE LA IMAGEN ENCONTRADA:\n- Componente: {image_info.get('titulo')}\n- Explicación completa: {image_info.get('descripcion')}\n"

    system_instruction = f"""
    Eres Paco, un asistente técnico especializado para el personal de tráfico del Subte (motoristas, guardias, maniobristas).
    Tu función es ayudar a resolver fallas técnicas, averías en formaciones y responder procedimientos de actuación.

    CONTEXTO DE MANUALES Y FICHA TÉCNICA:
    {relevant_context}
    {image_context}

    Reglas estrictas de respuesta:
    1. SI HAY FICHA TÉCNICA DE IMAGEN DISPONIBLE (arriba): Explica de forma COMPLETA y DETALLADA todo lo indicado en 'Explicación completa' (ubicación, colores, ventanitas, pérdida de aire, funcionamiento). NO omitas ningún detalle técnico.
    2. PROHIBIDO NARRAR MULETILLAS O FRASES TIPO: "Según la información disponible", "De acuerdo al manual", "Según los datos". Empieza a responder directamente de forma natural y profesional.
    3. Sé claro, técnico, cordial y directo al grano.
    4. Para resolución de fallas o procedimientos, usa listas numeradas precisas.
    5. Si hay duda o riesgo operativo, aconseja consultar con la central de tráfico.
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
        "temperature": 0.1
    }
    response = requests.post(url, json=payload, headers=headers, timeout=30)
    if response.status_code == 200:
        return response.json()['choices'][0]['message']['content'], None
    else:
        err = response.json().get('error', {}).get('message', 'Error en la consulta')
        return None, f"⚠️ Error {response.status_code}: {err}"

# --- ENDPOINT PARA BASE44 ---
@app.route('/preguntar', methods=['POST'])
def api_preguntar():
    data = request.get_json(silent=True) or {}
    pregunta = data.get('pregunta', '')
    
    if not pregunta:
        return jsonify({'error': 'Debes enviar el campo "pregunta"'}), 400

    # Buscar si hay una imagen que coincida
    image_info = search_relevant_image(pregunta)

    # Consultar Groq pasándole la ficha de la imagen
    respuesta_texto, error = query_groq_llm(pregunta, image_info=image_info)
    if error:
        return jsonify({'error': error}), 500

    # Generar Audio
    filename_audio = f"audio_{uuid.uuid4().hex[:8]}.mp3"
    filepath_audio = os.path.join(AUDIO_DIR, filename_audio)
    generate_voice_file(respuesta_texto, filepath_audio)

    host_url = request.host_url.rstrip('/')
    if host_url.startswith("http://"):
        host_url = host_url.replace("http://", "https://", 1)

    audio_url = f"{host_url}/audio/{filename_audio}"
    imagen_url = f"{host_url}/images/{image_info.get('archivo')}" if image_info else None

    return jsonify({
        'respuesta_texto': respuesta_texto,
        'audio_url': audio_url,
        'imagen_url': imagen_url
    })

# --- MANEJADORES TELEGRAM ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 **¡Hola, compañero!** Soy Paco, tu Asistente Técnico. ¿En qué falla te ayudo?", parse_mode="Markdown")

@bot.message_handler(content_types=['voice'])
def handle_voice_message(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        transcribe_url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY.strip()}"}
        files = {'file': ('voice.ogg', downloaded_file, 'audio/ogg')}
        data = {'model': 'whisper-large-v3', 'language': 'es'}
        
        trans_resp = requests.post(transcribe_url, headers=headers, files=files, data=data, timeout=30)
        if trans_resp.status_code != 200:
            bot.reply_to(message, "⚠️ Error procesando nota de voz.")
            return
            
        transcribed_text = trans_resp.json().get('text', '')
        if not transcribed_text:
            bot.reply_to(message, "⚠️ No logré escuchar con claridad el audio.")
            return

        image_info = search_relevant_image(transcribed_text)
        respuesta_texto, error = query_groq_llm(transcribed_text, image_info=image_info)
        if error:
            bot.reply_to(message, error)
            return

        bot.reply_to(message, f"🎤 *Escuché:* \"{transcribed_text}\"\n\n{respuesta_texto}", parse_mode="Markdown")

        # Enviar foto en Telegram si existe
        if image_info:
            img_path = os.path.join(IMAGE_DIR, image_info.get('archivo'))
            if os.path.exists(img_path):
                with open(img_path, "rb") as photo:
                    bot.send_photo(message.chat.id, photo, caption=f"📸 {image_info.get('titulo', 'Imagen de referencia')}")

        bot.send_chat_action(message.chat.id, 'record_audio')
        filename = f"resp_{message.message_id}.mp3"
        filepath = os.path.join(AUDIO_DIR, filename)
        generate_voice_file(respuesta_texto, filepath)

        with open(filepath, "rb") as audio:
            bot.send_voice(message.chat.id, audio)

        if os.path.exists(filepath):
            os.remove(filepath)

    except Exception as e:
        bot.reply_to(message, f"⚠️ Error procesando nota de voz: {str(e)}")

@bot.message_handler(func=lambda message: True)
def handle_text_message(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        
        image_info = search_relevant_image(message.text)
        respuesta_texto, error = query_groq_llm(message.text, image_info=image_info)
        if error:
            bot.reply_to(message, error)
            return

        bot.reply_to(message, respuesta_texto, parse_mode="Markdown")

        # Enviar foto en Telegram si existe
        if image_info:
            img_path = os.path.join(IMAGE_DIR, image_info.get('archivo'))
            if os.path.exists(img_path):
                with open(img_path, "rb") as photo:
                    bot.send_photo(message.chat.id, photo, caption=f"📸 {image_info.get('titulo', 'Imagen de referencia')}")

        bot.send_chat_action(message.chat.id, 'record_audio')
        filename = f"resp_{message.message_id}.mp3"
        filepath = os.path.join(AUDIO_DIR, filename)
        generate_voice_file(respuesta_texto, filepath)

        with open(filepath, "rb") as audio:
            bot.send_voice(message.chat.id, audio)

        if os.path.exists(filepath):
            os.remove(filepath)

    except Exception as e:
        bot.reply_to(message, f"⚠️ Error: {str(e)}")

def run_bot():
    bot.polling(non_stop=True)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    print(f"🤖 Paco API & Bot ejecutándose en el puerto {port}...")
    app.run(host="0.0.0.0", port=port)
