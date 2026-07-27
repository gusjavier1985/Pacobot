import os
import glob
import threading
import requests
import asyncio
import re
import uuid
import json
import unicodedata
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import telebot
from pypdf import PdfReader
import edge_tts

# Directorios para archivos estáticos
AUDIO_DIR = "static_audio"
IMAGE_DIR = "static_images"
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)

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
    response = send_from_directory(IMAGE_DIR, filename)
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response

# Configuración y Credenciales (Lee desde Variables de Entorno en Render)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8979818632:AAGxBHt2hCgXlIpAneCz1_qEiHTpFYb3BwU")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def normalize_text(text):
    """Remueve tildes, acentos y convierte a minúsculas."""
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return text.lower().strip()

# Indexación RAG optimizada para PDFs
print("Indexando manuales técnicos completos...")
chunks = []
pdf_files = sorted(glob.glob("*.pdf"))

for pdf in pdf_files:
    try:
        reader = PdfReader(pdf)
        full_text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t:
                full_text += t + "\n"
        
        clean_text = re.sub(r'\s+', ' ', full_text).strip()
        words = clean_text.split(" ")
        
        current_chunk = []
        current_len = 0
        for word in words:
            current_chunk.append(word)
            current_len += len(word) + 1
            if current_len >= 500:
                chunks.append(" ".join(current_chunk))
                current_chunk = current_chunk[-15:]
                current_len = sum(len(w) + 1 for w in current_chunk)
        if current_chunk:
            chunks.append(" ".join(current_chunk))
    except Exception as e:
        print(f"Error procesando {pdf}: {e}")

if not chunks:
    chunks = ["No hay manuales cargados en el sistema."]

print(f"Indexación completa. Total de fragmentos: {len(chunks)}")

SYNONYMS = {
    "prender": ["encendido", "puesta en servicio", "energizacion", "arranque", "mando", "bateria", "disyuntor", "preparacion"],
    "prendido": ["encendido", "puesta en servicio", "energizacion", "arranque", "mando"],
    "encender": ["encendido", "puesta en servicio", "energizacion", "mando"],
    "grifo": ["llave", "grifo", "valvula", "aislar", "puerta"],
    "matafuego": ["extintor", "matafuego", "fuego"],
    "matafuegos": ["extintor", "matafuego", "fuego"],
    "escalera": ["escalera", "evacuacion", "emergencia"]
}

def search_relevant_chunks(query, top_k=5):
    stopwords = {"el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "de", "del", "a", "ante", "en", "que", "por", "para", "con", "se", "es", "su", "lo", "como"}
    query_norm = normalize_text(query)
    words = re.findall(r'\b\w+\b', query_norm)
    keywords = [w for w in words if w not in stopwords and len(w) > 2]

    expanded_keywords = set(keywords)
    for kw in keywords:
        if kw in SYNONYMS:
            expanded_keywords.update(SYNONYMS[kw])

    scored_chunks = []
    for chunk in chunks:
        chunk_norm = normalize_text(chunk)
        score = sum(1 for kw in expanded_keywords if kw in chunk_norm)
        if score > 0:
            scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    
    relevant_text = ""
    for score, chunk in scored_chunks[:top_k]:
        relevant_text += f"\n- {chunk}\n"

    return relevant_text if relevant_text else "No se encontraron detalles específicos en los manuales."

def search_relevant_image(query, history=None):
    json_path = None
    for candidate in ["imagenes.json", "Imagenes.json", "IMAGENES.JSON"]:
        if os.path.exists(candidate):
            json_path = candidate
            break

    if not json_path:
        return {"type": "NONE", "image": None, "images": [], "options": [], "all_titles": []}
    
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            images_db = json.load(f)
    except Exception as e:
        print(f"Error leyendo {json_path}: {e}")
        return {"type": "NONE", "image": None, "images": [], "options": [], "all_titles": []}

    query_norm = normalize_text(query)
    all_titles = [f"{item.get('titulo', 'Sin título')} ({item.get('modelo', 'General')})" for item in images_db]

    if any(p in query_norm for p in ["imagenes", "fotos", "cargadas", "mostrar imagenes", "tienes imagenes", "tenes imagenes"]):
        return {"type": "GENERAL_QUERY", "image": None, "images": [], "options": [], "all_titles": all_titles}

    matches = []
    query_words = set(re.findall(r'\b\w+\b', query_norm))

    for item in images_db:
        keywords = [normalize_text(kw) for kw in item.get("palabras_clave", [])]
        score = 0
        for kw in keywords:
            if kw == query_norm:
                score += 15
            elif kw in query_norm:
                score += len(kw)
            elif any(kw in w or w in kw for w in query_words if len(w) > 2):
                score += 2

        if score > 0:
            matches.append((score, item))

    if not matches:
        return {"type": "NONE", "image": None, "images": [], "options": [], "all_titles": all_titles}

    matches.sort(key=lambda x: x[0], reverse=True)
    max_score = matches[0][0]
    
    top_matches = [m[1] for m in matches if m[0] == max_score]

    if len(top_matches) > 1:
        titles = [item.get("titulo") for item in top_matches]
        return {
            "type": "AMBIGUOUS_OPTIONS",
            "image": None,
            "images": [],
            "options": titles,
            "all_titles": all_titles
        }

    return {
        "type": "EXACT",
        "image": top_matches[0],
        "images": [top_matches[0]],
        "options": [],
        "all_titles": all_titles
    }

def generate_voice_file(text, output_file):
    """Genera audio MP3. Devuelve True si se generó con éxito, False si falló."""
    clean_text = text.replace("*", "").replace("#", "").replace("`", "").replace("_", "")
    if not clean_text.strip():
        return False

    async def _generate():
        communicate = edge_tts.Communicate(clean_text, "es-AR-TomasNeural")
        await communicate.save(output_file)
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(asyncio.wait_for(_generate(), timeout=10.0))
        loop.close()
        return os.path.exists(output_file)
    except Exception as e:
        print(f"Error generando audio TTS: {e}")
        return False

def limpiar_redundancia(texto):
    if not texto:
        return texto

    lineas = texto.split('\n')
    lineas_limpias = []
    i = 0
    while i < len(lineas):
        linea_actual = lineas[i].strip()
        if i + 1 < len(lineas):
            linea_siguiente = lineas[i + 1].strip()
            
            match_encab = re.match(r'^\d+\.\s*\*\*(.*?)\*\*:?$', linea_actual)
            match_vineta = re.match(r'^[-\*]\s*(.*)$', linea_siguiente)
            
            if match_encab and match_vineta:
                t_encab = match_encab.group(1).strip().lower().rstrip('.')
                t_vineta = match_vineta.group(1).strip().lower().rstrip('.')
                
                if t_encab in t_vineta or t_vineta in t_encab:
                    lineas_limpias.append(f"- {match_vineta.group(1).strip()}")
                    i += 2
                    continue

        lineas_limpias.append(lineas[i])
        i += 1

    return "\n".join(lineas_limpias)

def query_groq_llm(user_prompt, search_result=None, history=None):
    if not GROQ_API_KEY:
        return "- Error: No se ha configurado la clave GROQ_API_KEY en las variables de entorno de Render.", None

    if search_result and search_result.get("type") == "EXACT" and search_result.get("image"):
        desc = search_result["image"].get('descripcion', '')
        if desc:
            return limpiar_redundancia(desc), None

    if search_result and search_result.get("type") == "AMBIGUOUS_OPTIONS":
        opciones_str = "\n".join([f"- **{opt}**" for opt in search_result.get("options", [])])
        return f"- Para esa consulta tengo las siguientes opciones disponibles:\n\n{opciones_str}\n\n- ¿Cuál de las opciones necesitás?", None

    if search_result and search_result.get("type") == "GENERAL_QUERY":
        titles = search_result.get("all_titles", [])
        if titles:
            lista_str = "\n".join([f"- {t}" for t in titles])
            return f"Sí, tengo las siguientes imágenes técnicas cargadas en el sistema:\n\n{lista_str}\n\nPuedes preguntarme por cualquiera de ellas para ver la ubicación o detalles.", None
        else:
            return "Actualmente no hay imágenes cargadas en la base de datos `imagenes.json`.", None

    relevant_context = search_relevant_chunks(user_prompt, top_k=5)

    system_instruction = f"""
    Eres Paco, un asistente técnico experimentado para el personal de tráfico del Subte.
    Hablas de forma directa, profesional, fluida y al grano.

    REGLA DE ORO OBLIGATORIA (CERO ALUCINACIONES):
    1. Responde ÚNICAMENTE basándote en el CONTEXTO TÉCNICO facilitado abajo.
    2. Si el procedimiento o componente NO figura claramente en la información provista, responde estricta y únicamente:
       "- No dispongo de la información exacta para esa consulta en los manuales ni en las imágenes cargadas."
    3. NUNCA inventes términos mecánicos, motores de arranque ni pasos genéricos que no pertenezcan al Subte.

    ESTRUCTURA DE RESPUESTA OBLIGATORIA:
    Responde SIEMPRE usando listas simples con guiones (-). Sin preámbulos.

    INFORMACIÓN TÉCNICA Y CONTEXTO DISPONIBLE DE LOS MANUALES:
    {relevant_context}
    """

    messages = [{"role": "system", "content": system_instruction}]

    if history and isinstance(history, list):
        clean_history = []
        for msg in history[-6:]:
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                clean_history.append({"role": msg["role"], "content": msg["content"]})
        messages.extend(clean_history)

    messages.append({"role": "user", "content": user_prompt})

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY.strip()}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": messages,
        "temperature": 0.0
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            raw_text = response.json()['choices'][0]['message']['content']
            return limpiar_redundancia(raw_text), None
        else:
            err = response.json().get('error', {}).get('message', 'Error en la consulta')
            return f"- Error desde Groq ({response.status_code}): {err}", None
    except Exception as e:
        return f"- Error de conexión con el servicio de IA: {str(e)}", None

# --- ENDPOINT PARA BASE44 (CHAT) ---
@app.route('/preguntar', methods=['POST', 'OPTIONS'])
def api_preguntar():
    if request.method == 'OPTIONS':
        return '', 200

    try:
        data = request.get_json(silent=True) or {}
        
        # Lee la consulta sin importar qué nombre de variable use el frontend
        pregunta = data.get('pregunta') or data.get('message') or data.get('text') or data.get('query') or ''
        historial = data.get('historial', [])
        
        if not pregunta:
            return jsonify({
                'respuesta_texto': '- Por favor escribí una consulta.',
                'audio_url': None,
                'imagen_url': None
            }), 200

        search_result = search_relevant_image(pregunta, history=historial)
        host_url = request.host_url.rstrip('/')
        if host_url.startswith("http://"):
            host_url = host_url.replace("http://", "https://", 1)

        # Si es coincidencia exacta con imagen
        if search_result.get("type") == "EXACT" and search_result.get("image"):
            img_info = search_result["image"]
            respuesta_texto = limpiar_redundancia(img_info.get('descripcion', ''))
            
            filename_audio = f"audio_{uuid.uuid4().hex[:8]}.mp3"
            filepath_audio = os.path.join(AUDIO_DIR, filename_audio)
            
            audio_ok = generate_voice_file(respuesta_texto, filepath_audio)
            audio_url = f"{host_url}/audio/{filename_audio}" if audio_ok else None

            return jsonify({
                'respuesta_texto': respuesta_texto,
                'audio_url': audio_url,
                'imagen_url': f"{host_url}/images/{img_info.get('archivo')}" if img_info.get('archivo') else None
            }), 200

        # Consulta con la IA / Manuales
        respuesta_texto, error = query_groq_llm(pregunta, search_result=search_result, history=historial)
        if error:
            respuesta_texto = f"- No fue posible procesar la consulta: {error}"

        filename_audio = f"audio_{uuid.uuid4().hex[:8]}.mp3"
        filepath_audio = os.path.join(AUDIO_DIR, filename_audio)
        
        audio_ok = generate_voice_file(respuesta_texto, filepath_audio)
        audio_url = f"{host_url}/audio/{filename_audio}" if audio_ok else None

        return jsonify({
            'respuesta_texto': respuesta_texto,
            'audio_url': audio_url,
            'imagen_url': None
        }), 200

    except Exception as e:
        print(f"Error crítico en /preguntar: {str(e)}")
        return jsonify({
            'respuesta_texto': f"- Error interno del servidor: {str(e)}",
            'audio_url': None,
            'imagen_url': None
        }), 200

# --- ENDPOINT PARA GENERAR AUDIO DE NOVEDADES ---
@app.route('/generar-audio', methods=['POST'])
def api_generar_audio():
    data = request.get_json(silent=True) or {}
    texto = data.get('texto', '')
    
    if not texto:
        return jsonify({'error': 'Debes enviar el campo "texto"'}), 400

    filename_audio = f"audio_nov_{uuid.uuid4().hex[:8]}.mp3"
    filepath_audio = os.path.join(AUDIO_DIR, filename_audio)
    audio_ok = generate_voice_file(texto, filepath_audio)

    if not audio_ok:
        return jsonify({'error': 'No se pudo generar el audio'}), 500

    host_url = request.host_url.rstrip('/')
    if host_url.startswith("http://"):
        host_url = host_url.replace("http://", "https://", 1)

    return jsonify({'audio_url': f"{host_url}/audio/{filename_audio}"})

# --- MANEJADORES TELEGRAM ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 **¡Hola, compañero!** Soy Paco, tu Asistente Técnico. ¿En qué te ayudo?", parse_mode="Markdown")

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
        
        trans_resp = requests.post(transcribe_url, headers=headers, files=files, data=data, timeout=20)
        if trans_resp.status_code != 200:
            bot.reply_to(message, "⚠️ Error procesando nota de voz.")
            return
            
        transcribed_text = trans_resp.json().get('text', '')
        if not transcribed_text:
            bot.reply_to(message, "⚠️ No logré escuchar con claridad el audio.")
            return

        search_result = search_relevant_image(transcribed_text)
        respuesta_texto, _ = query_groq_llm(transcribed_text, search_result=search_result)

        bot.reply_to(message, f"🎤 *Escuché:* \"{transcribed_text}\"\n\n{respuesta_texto}", parse_mode="Markdown")

        if search_result.get("type") == "EXACT" and search_result.get("image"):
            img_info = search_result["image"]
            img_path = os.path.join(IMAGE_DIR, img_info.get('archivo', ''))
            if os.path.exists(img_path):
                with open(img_path, "rb") as photo:
                    bot.send_photo(message.chat.id, photo, caption=f"📸 {img_info.get('titulo', '')}")

        filename = f"resp_{message.message_id}.mp3"
        filepath = os.path.join(AUDIO_DIR, filename)
        if generate_voice_file(respuesta_texto, filepath):
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
        
        search_result = search_relevant_image(message.text)
        respuesta_texto, _ = query_groq_llm(message.text, search_result=search_result)

        bot.reply_to(message, respuesta_texto, parse_mode="Markdown")

        if search_result.get("type") == "EXACT" and search_result.get("image"):
            img_info = search_result["image"]
            img_path = os.path.join(IMAGE_DIR, img_info.get('archivo', ''))
            if os.path.exists(img_path):
                with open(img_path, "rb") as photo:
                    bot.send_photo(message.chat.id, photo, caption=f"📸 {img_info.get('titulo', '')}")

        filename = f"resp_{message.message_id}.mp3"
        filepath = os.path.join(AUDIO_DIR, filename)
        if generate_voice_file(respuesta_texto, filepath):
            with open(filepath, "rb") as audio:
                bot.send_voice(message.chat.id, audio)
            if os.path.exists(filepath):
                os.remove(filepath)

    except Exception as e:
        bot.reply_to(message, f"⚠️ Error: {str(e)}")

# Inicio del Bot de Telegram en hilo secundario (seguro para Gunicorn / WSGI)
def run_telegram_bot():
    try:
        print("Iniciando Bot de Telegram...")
        bot.polling(non_stop=True, timeout=30)
    except Exception as e:
        print(f"Error en hilo de Telegram: {e}")

bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"🤖 Paco API & Bot ejecutándose en el puerto {port}...")
    app.run(host="0.0.0.0", port=port)
