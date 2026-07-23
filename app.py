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

def search_relevant_image(query, history=None):
    """
    Busca coincidencias directas de frases/palabras clave en la base de datos de imágenes.
    """
    json_path = "imagenes.json"
    if not os.path.exists(json_path):
        return {"type": "NONE", "image": None, "models": []}
    
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            images_db = json.load(f)
    except Exception as e:
        print(f"Error leyendo imagenes.json: {e}")
        return {"type": "NONE", "image": None, "models": []}

    query_lower = query.lower()

    model_keywords = {
        "Mitsubishi": ["mitsubishi", "mitsu", "japonés", "japones"],
        "CAF 6000": ["caf", "caf6000", "caf 6000", "6000", "seis mil", "6 mil"]
    }
    
    requested_model = None
    # 1. Buscar modelo en la pregunta actual
    for model_name, kw_list in model_keywords.items():
        if any(kw in query_lower for kw in kw_list):
            requested_model = model_name
            break

    # 2. Si no especifica modelo en la pregunta actual, buscar en el historial reciente
    if not requested_model and history and isinstance(history, list):
        recent_text = " ".join([m.get("content", "") for m in history[-4:]]).lower()
        for model_name, kw_list in model_keywords.items():
            if any(kw in recent_text for kw in kw_list):
                requested_model = model_name
                break

    matches = []
    for item in images_db:
        keywords = [kw.lower() for kw in item.get("palabras_clave", [])]
        score = sum(1 for kw in keywords if kw in query_lower)
        if score >= 1:
            matches.append((score, item))

    if not matches:
        return {"type": "NONE", "image": None, "models": []}

    matches.sort(key=lambda x: x[0], reverse=True)
    max_score = matches[0][0]
    best_matches = [m[1] for m in matches if m[0] == max_score]

    available_models = list(set(item.get("modelo", "General") for item in best_matches))

    if requested_model:
        model_match = next((item for item in best_matches if item.get("modelo", "").lower() == requested_model.lower()), None)
        if not model_match:
            model_match = next((m[1] for m in matches if m[1].get("modelo", "").lower() == requested_model.lower()), None)
        
        if model_match:
            return {"type": "EXACT", "image": model_match, "models": [requested_model]}

    if len(available_models) > 1 and not requested_model:
        return {"type": "AMBIGUOUS", "image": None, "models": available_models}

    return {"type": "EXACT", "image": best_matches[0], "models": available_models}

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

def query_groq_llm(user_prompt, search_result=None, history=None):
    image_context = ""
    relevant_context = ""

    # Si hay coincidencia de imagen EXACTA, usamos ÚNICAMENTE la ficha del JSON y ANULAMOS la búsqueda en PDFs
    if search_result and search_result.get("type") == "EXACT":
        img_info = search_result["image"]
        image_context = f"\nFICHA TÉCNICA OFICIAL OBLIGATORIA:\n- Texto exacto a responder: {img_info.get('descripcion')}\n"
        relevant_context = "" # Se limpia para evitar interferencias de PDFs o inventos
    else:
        relevant_context = search_relevant_chunks(user_prompt, top_k=3)
        if search_result and search_result.get("type") == "AMBIGUOUS":
            models_str = " o ".join(search_result["models"])
            image_context = f"\nNOTA DE DESAMBIGUACIÓN: La consulta aplica a varios modelos ({models_str}). Pregúntale directo al usuario a qué tren se refiere.\n"

    system_instruction = f"""
    Eres Paco, un asistente técnico experimentado para el personal de tráfico del Subte.
    Hablas de forma directa, profesional, fluida y al grano.

    REGLAS ESTRUCTURALES OBLIGATORIAS Y ESTRICTAS:
    1. SI EL USUARIO SOLO SALUDA (ej: "hola", "buenas", "buenos días"): Responde ÚNICAMENTE: "¡Hola! ¿En qué te puedo ayudar?".
    2. SI EXISTE FICHA TÉCNICA OFICIAL (IMAGEN DETECTADA): Tu respuesta DEBE SER EXACTAMENTE Y PALABRA POR PALABRA el texto que aparece en 'Texto exacto a responder'. Queda TOTALMENTE PROHIBIDO modificarlo, resumirlo, reescribirlo, agregar datos inventados (como decir que está en el techo o en el lado opuesto) o interpretarlo. REPRODUCE EL TEXTO COMPLETO TAL CUAL ESTÁ REDACTADO EN LA FICHA TÉCNICA.
    3. TOTALMENTE PROHIBIDAS LAS MULETILLAS Y PREÁMBULOS: Nunca uses frases como "Según la información proporcionada", "De acuerdo al manual", "En la página X", "En resumen", "Según la ficha técnica".
    4. RESPUESTA DIRECTA: Comienza tu respuesta inmediatamente con la información técnica necesaria, sin saludos repetitivos.
    5. CONTINUIDAD CONVERSACIONAL: Mantén la memoria del hilo de la charla.

    INFORMACIÓN TÉCNICA Y CONTEXTO DISPONIBLE:
    {relevant_context}
    {image_context}
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
    historial = data.get('historial', [])
    
    if not pregunta:
        return jsonify({'error': 'Debes enviar el campo "pregunta"'}), 400

    search_result = search_relevant_image(pregunta, history=historial)
    respuesta_texto, error = query_groq_llm(pregunta, search_result=search_result, history=historial)
    if error:
        return jsonify({'error': error}), 500

    filename_audio = f"audio_{uuid.uuid4().hex[:8]}.mp3"
    filepath_audio = os.path.join(AUDIO_DIR, filename_audio)
    generate_voice_file(respuesta_texto, filepath_audio)

    host_url = request.host_url.rstrip('/')
    if host_url.startswith("http://"):
        host_url = host_url.replace("http://", "https://", 1)

    audio_url = f"{host_url}/audio/{filename_audio}"
    imagen_url = None
    if search_result.get("type") == "EXACT" and search_result.get("image"):
        imagen_url = f"{host_url}/images/{search_result['image'].get('archivo')}"

    return jsonify({
        'respuesta_texto': respuesta_texto,
        'audio_url': audio_url,
        'imagen_url': imagen_url
    })

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
        
        trans_resp = requests.post(transcribe_url, headers=headers, files=files, data=data, timeout=30)
        if trans_resp.status_code != 200:
            bot.reply_to(message, "⚠️ Error procesando nota de voz.")
            return
            
        transcribed_text = trans_resp.json().get('text', '')
        if not transcribed_text:
            bot.reply_to(message, "⚠️ No logré escuchar con claridad el audio.")
            return

        search_result = search_relevant_image(transcribed_text)
        respuesta_texto, error = query_groq_llm(transcribed_text, search_result=search_result)
        if error:
            bot.reply_to(message, error)
            return

        bot.reply_to(message, f"🎤 *Escuché:* \"{transcribed_text}\"\n\n{respuesta_texto}", parse_mode="Markdown")

        if search_result.get("type") == "EXACT" and search_result.get("image"):
            img_info = search_result["image"]
            img_path = os.path.join(IMAGE_DIR, img_info.get('archivo'))
            if os.path.exists(img_path):
                with open(img_path, "rb") as photo:
                    bot.send_photo(message.chat.id, photo, caption=f"📸 {img_info.get('titulo', 'Imagen de referencia')}")

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
        
        search_result = search_relevant_image(message.text)
        respuesta_texto, error = query_groq_llm(message.text, search_result=search_result)
        if error:
            bot.reply_to(message, error)
            return

        bot.reply_to(message, respuesta_texto, parse_mode="Markdown")

        if search_result.get("type") == "EXACT" and search_result.get("image"):
            img_info = search_result["image"]
            img_path = os.path.join(IMAGE_DIR, img_info.get('archivo'))
            if os.path.exists(img_path):
                with open(img_path, "rb") as photo:
                    bot.send_photo(message.chat.id, photo, caption=f"📸 {img_info.get('titulo', 'Imagen de referencia')}")

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
