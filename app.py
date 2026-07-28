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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "static_audio")
IMAGE_DIR = os.path.join(BASE_DIR, "static_images")
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

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8979818632:AAGxBHt2hCgXlIpAneCz1_qEiHTpFYb3BwU")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def normalize_text(text):
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return text.lower().strip()

def check_direct_intents(query):
    q_norm = normalize_text(query)
    
    paco_patterns = [
        "por que paco", "porque paco", "por que te llamas paco", 
        "porque te llamas paco", "que significa paco", "de donde viene paco", 
        "por que el nombre paco", "porque el nombre paco", "quien es paco"
    ]
    if any(p in q_norm for p in paco_patterns):
        return "Me llamo PACO por un juego de palabras y en reconocimiento a nuestros instructores Paleo (PA) y Greco (CO)."

    saludos = ["hola", "buen dia", "buenos dias", "buenas tardes", "buenas noches", "buenas", "saludos", "hola paco", "que tal"]
    words = q_norm.split()
    
    es_saludo_puro = q_norm in saludos or (len(words) <= 2 and any(w in saludos for w in words))
    if es_saludo_puro:
        return "¡Hola! Buen día. ¿En qué te puedo ayudar hoy?"

    return None

# Indexación RAG etiquetando explícitamente el modelo de tren
print("Indexando manuales técnicos completos...")
chunks = []
pdf_files = sorted(glob.glob(os.path.join(BASE_DIR, "*.pdf")))

for pdf in pdf_files:
    try:
        filename_lower = os.path.basename(pdf).lower()
        if "caf" in filename_lower:
            model_tag = "CAF 6000"
        elif "mitsu" in filename_lower:
            model_tag = "Mitsubishi"
        else:
            model_tag = "General"

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
            if current_len >= 1200:
                chunk_str = f"[MODELO: {model_tag}] " + " ".join(current_chunk)
                chunks.append(chunk_str)
                current_chunk = current_chunk[-30:]
                current_len = sum(len(w) + 1 for w in current_chunk)
        if current_chunk:
            chunk_str = f"[MODELO: {model_tag}] " + " ".join(current_chunk)
            chunks.append(chunk_str)
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

def analyze_models_in_chunks(query):
    stopwords = {"el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "de", "del", "a", "ante", "en", "que", "por", "para", "con", "se", "es", "su", "lo", "como"}
    query_norm = normalize_text(query)
    words = re.findall(r'\b\w+\b', query_norm)
    keywords = [w for w in words if w not in stopwords and len(w) > 1]

    expanded_keywords = set(keywords)
    for kw in keywords:
        if kw in SYNONYMS:
            expanded_keywords.update(SYNONYMS[kw])

    mitsu_found = False
    caf_found = False

    for chunk in chunks:
        chunk_norm = normalize_text(chunk)
        score = sum(1 for kw in expanded_keywords if kw in chunk_norm)
        if score >= 1:
            if "[modelo: mitsubishi]" in chunk_norm:
                mitsu_found = True
            elif "[modelo: caf 6000]" in chunk_norm:
                caf_found = True

    return mitsu_found, caf_found

def search_relevant_chunks(query, target_model=None, top_k=10):
    stopwords = {"el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "de", "del", "a", "ante", "en", "que", "por", "para", "con", "se", "es", "su", "lo", "como"}
    query_norm = normalize_text(query)
    words = re.findall(r'\b\w+\b', query_norm)
    keywords = [w for w in words if w not in stopwords and len(w) > 1]

    if not target_model:
        if any(m in query_norm for m in ["caf", "6000", "sicas", "microcef"]):
            target_model = "CAF 6000"
        elif any(m in query_norm for m in ["mitsubishi", "mitsu", "nfb", "atp"]):
            target_model = "Mitsubishi"

    expanded_keywords = set(keywords)
    for kw in keywords:
        if kw in SYNONYMS:
            expanded_keywords.update(SYNONYMS[kw])

    scored_chunks = []
    for chunk in chunks:
        chunk_norm = normalize_text(chunk)
        score = sum(1 for kw in expanded_keywords if kw in chunk_norm)
        
        if target_model:
            if f"[modelo: {target_model.lower()}]" in chunk_norm:
                score += 5
            elif "[modelo: general]" not in chunk_norm:
                score -= 5

        if score > 0:
            scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    
    relevant_text = ""
    for score, chunk in scored_chunks[:top_k]:
        relevant_text += f"\n{chunk}\n"

    return relevant_text if relevant_text else "No se encontraron detalles específicos en los manuales."

def load_imagenes_json():
    for candidate in ["imagenes.json", "Imagenes.json", "IMAGENES.JSON"]:
        json_path = os.path.join(BASE_DIR, candidate)
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error leyendo {json_path}: {e}")
    return None

def search_relevant_image_by_title(query):
    """Busca imágenes estrictamente por coincidencia directa de TÍTULO."""
    images_db = load_imagenes_json()
    if not images_db:
        return None

    query_norm = normalize_text(query)
    target_model = None
    if "mitsubishi" in query_norm or "mitsu" in query_norm:
        target_model = "Mitsubishi"
    elif "caf" in query_norm or "6000" in query_norm:
        target_model = "CAF 6000"

    for item in images_db:
        titulo_norm = normalize_text(item.get("titulo", ""))
        item_model = item.get("modelo", "")

        if target_model and item_model and item_model != target_model:
            continue

        # Coincidencia casi exacta en el título
        if titulo_norm and (titulo_norm == query_norm or titulo_norm in query_norm or query_norm in titulo_norm):
            return item

    return None

def generate_voice_file(text, output_file):
    clean_text = text.replace("*", "").replace("#", "").replace("`", "").replace("_", "").replace("•", "")
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

def query_groq_llm(user_prompt, target_model=None, history=None):
    clean_user_input = user_prompt.strip()

    # Manejo de selección explícita 1 o 2 en el chat
    if clean_user_input in ["1", "2"] and history and len(history) >= 2:
        last_assistant_msg = ""
        last_user_msg = ""
        for msg in reversed(history):
            if isinstance(msg, dict):
                if msg.get("role") == "assistant" and not last_assistant_msg:
                    last_assistant_msg = msg.get("content", "")
                elif msg.get("role") == "user" and not last_user_msg and msg.get("content", "").strip() not in ["1", "2"]:
                    last_user_msg = msg.get("content", "")
            if last_assistant_msg and last_user_msg:
                break

        if "Opción 1: Ver el procedimiento" in last_assistant_msg:
            # Caso elección entre Falla o Imagen
            if clean_user_input == "1":
                user_prompt = last_user_msg
            else:
                img_item = search_relevant_image_by_title(last_user_msg)
                if img_item:
                    return img_item.get('descripcion', ''), img_item.get('archivo')
                return "No se encontró una imagen asociada.", None

        if "Para el Mitsubishi enviar 1" in last_assistant_msg or "enviar 1" in last_assistant_msg:
            target_model = "Mitsubishi" if clean_user_input == "1" else "CAF 6000"
            user_prompt = last_user_msg

    direct_response = check_direct_intents(user_prompt)
    if direct_response:
        return direct_response, None

    if not GROQ_API_KEY:
        return "- Error: No se ha configurado la clave GROQ_API_KEY en Render.", None

    # Si la consulta aplica a ambos trenes y no se especificó tren, se pide opción de forma sobria
    if not target_model and clean_user_input not in ["1", "2"]:
        q_norm = normalize_text(user_prompt)
        has_mitsu = "mitsubishi" in q_norm or "mitsu" in q_norm
        has_caf = "caf" in q_norm or "6000" in q_norm

        if not has_mitsu and not has_caf:
            in_mitsu, in_caf = analyze_models_in_chunks(user_prompt)
            if in_mitsu and in_caf:
                return f"Si te referís a la consulta:\n\n• Para el Mitsubishi enviar 1\n• Para el CAF 6000 enviar 2", None
            elif in_mitsu:
                target_model = "Mitsubishi"
            elif in_caf:
                target_model = "CAF 6000"

    # Verificar si el título coincide con imagen Y también con procedimiento
    img_match = search_relevant_image_by_title(user_prompt)
    if img_match and clean_user_input not in ["1", "2"]:
        q_norm = normalize_text(user_prompt)
        if any(w in q_norm for w in ["foto", "imagen", "ver imagen", "esquema"]):
            return img_match.get('descripcion', ''), img_match.get('archivo')
        else:
            # Ofrecer opción de ver resolución o imagen
            return (f"Para la consulta se encontraron dos opciones disponibles:\n\n"
                    f"• Opción 1: Ver el procedimiento / resolución de la falla\n"
                    f"• Opción 2: Ver la imagen explicativa\n\n"
                    f"Por favor indicá 1 o 2."), None

    relevant_context = search_relevant_chunks(user_prompt, target_model=target_model, top_k=10)

    system_instruction = f"""
    Eres Paco, un asistente técnico experimentado para el personal de tráfico del Subte (Línea B).

    REGLAS STRICTAS E INVIOLABLES DE RESPUESTA:
    1. SI TE PREGUNTAN QUÉ AVERÍAS O FALLAS TIENE UN TREN (Mitsubishi o CAF 6000):
       - DEBES listar TODAS las averías y títulos de fallas que figuren en el manual provisto para ese modelo, sin omitir ninguna.
    2. TRANSCRIBE ÚNICAMENTE LO QUE FIGURA LITERALMENTE EN EL MANUAL PROVISTO.
    3. PROHIBIDO TOTALMENTE INVENTAR PASOS, DIAGNÓSTICOS, SISTEMAS O COMPONENTES QUE NO ESTÉN EN EL TEXTO.
    4. MANTÉN EL FORMATO Y VIÑETAS ORIGINALES DEL MANUAL.
    5. NO agregues saludos, frases de cortesía, ni frases tipo "Según el manual..." ni "Para solucionar...". Ve DIRECTO a la información.
    6. Si la información no se encuentra en el texto provisto, responde estrictamente:
       "- No dispongo de la información exacta para esa consulta en los manuales cargados."

    CONTENIDO EXTRAÍDO DE LOS MANUALES:
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
            return raw_text, None
        else:
            err = response.json().get('error', {}).get('message', 'Error en la consulta')
            return f"- Error desde Groq ({response.status_code}): {err}", None
    except Exception as e:
        return f"- Error de conexión con el servicio de IA: {str(e)}", None

# --- ENDPOINT CHAT ---
@app.route('/preguntar', methods=['POST', 'OPTIONS'])
def api_preguntar():
    if request.method == 'OPTIONS':
        return '', 200

    try:
        data = request.get_json(silent=True) or {}
        pregunta = data.get('pregunta') or data.get('message') or data.get('text') or data.get('query') or ''
        historial = data.get('historial', [])
        
        if not pregunta:
            return jsonify({
                'respuesta_texto': '- Por favor escribí una consulta.',
                'audio_url': None,
                'imagen_url': None
            }), 200

        host_url = request.host_url.rstrip('/')
        if host_url.startswith("http://"):
            host_url = host_url.replace("http://", "https://", 1)

        respuesta_texto, archivo_imagen = query_groq_llm(pregunta, history=historial)

        imagen_url = f"{host_url}/images/{archivo_imagen}" if archivo_imagen else None

        filename_audio = f"audio_{uuid.uuid4().hex[:8]}.mp3"
        filepath_audio = os.path.join(AUDIO_DIR, filename_audio)
        
        audio_ok = generate_voice_file(respuesta_texto, filepath_audio)
        audio_url = f"{host_url}/audio/{filename_audio}" if audio_ok else None

        return jsonify({
            'respuesta_texto': respuesta_texto,
            'audio_url': audio_url,
            'imagen_url': imagen_url
        }), 200

    except Exception as e:
        print(f"Error crítico en /preguntar: {str(e)}")
        return jsonify({
            'respuesta_texto': f"- Error interno del servidor: {str(e)}",
            'audio_url': None,
            'imagen_url': None
        }), 200

# --- ENDPOINT AUDIO ---
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
    bot.reply_to(message, "👋 **¡Hola, compañero!** Soy Paco, tu Asistente Técnico. ¿En qué te puedo ayudar hoy?", parse_mode="Markdown")

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

        respuesta_texto, archivo_imagen = query_groq_llm(transcribed_text)

        bot.reply_to(message, f"🎤 *Escuché:* \"{transcribed_text}\"\n\n{respuesta_texto}", parse_mode="Markdown")

        if archivo_imagen:
            img_path = os.path.join(IMAGE_DIR, archivo_imagen)
            if os.path.exists(img_path):
                with open(img_path, "rb") as photo:
                    bot.send_photo(message.chat.id, photo)

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
        
        respuesta_texto, archivo_imagen = query_groq_llm(message.text)

        bot.reply_to(message, respuesta_texto, parse_mode="Markdown")

        if archivo_imagen:
            img_path = os.path.join(IMAGE_DIR, archivo_imagen)
            if os.path.exists(img_path):
                with open(img_path, "rb") as photo:
                    bot.send_photo(message.chat.id, photo)

        filename = f"resp_{message.message_id}.mp3"
        filepath = os.path.join(AUDIO_DIR, filename)
        if generate_voice_file(respuesta_texto, filepath):
            with open(filepath, "rb") as audio:
                bot.send_voice(message.chat.id, audio)
            if os.path.exists(filepath):
                os.remove(filepath)

    except Exception as e:
        bot.reply_to(message, f"⚠️ Error: {str(e)}")

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
