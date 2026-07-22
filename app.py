import os
import glob
import threading
import requests
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from pypdf import PdfReader
import edge_tts

# 1. Servidor Web auxiliar para mantener Render activo
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Paco OK")

def run_health_check():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_check, daemon=True).start()

# 2. Configuración y Credenciales
TELEGRAM_TOKEN = "8979818632:AAGxBHt2hCgXlIpAneCz1_qEiHTpFYb3BwU"
GROQ_API_KEY = "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"

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# 3. Carga optimizada de manuales
print("Cargando manuales técnicos principales...")
context_text = ""
pdf_files = sorted(glob.glob("*.pdf"))

for pdf in pdf_files:
    try:
        reader = PdfReader(pdf)
        context_text += f"\n\n=== DOCUMENTO: {pdf} ===\n"
        pdf_text = ""
        for page in reader.pages[:10]:
            text = page.extract_text()
            if text:
                pdf_text += text + "\n"
        context_text += pdf_text[:3500] + "\n"
    except Exception as e:
        print(f"Error procesando {pdf}: {e}")

context_text = context_text[:18000]

# 4. Instrucción del Asistente
SYSTEM_INSTRUCTION = f"""
Eres Paco, un asistente técnico especializado para el personal de tráfico del Subte (motoristas, guardias, maniobristas).
Tu función es ayudar a resolver fallas técnicas, averías en formaciones y responder procedimientos de actuación.

MANUALES TÉCNICOS Y GUÍAS DE FALLAS DISPONIBLES:
{context_text}

Reglas strictly:
1. Sé conciso, claro y directo.
2. Basate estrictamente en los manuales de consulta arriba provistos.
3. Para resolución de fallas o procedimientos paso a paso, usa listas numeradas precisas.
4. Si hay duda o riesgo operativo, aconseja consultar con la central de tráfico.
"""

def generate_voice_file(text, output_file="respuesta.mp3"):
    """Genera audio con voz masculina en español argentino (es-AR-TomasNeural)"""
    # Limpiamos marcas de edición para que la lectura por voz sea fluida
    clean_text = text.replace("*", "").replace("#", "").replace("`", "").replace("_", "")
    async def _generate():
        communicate = edge_tts.Communicate(clean_text, "es-AR-TomasNeural")
        await communicate.save(output_file)
    
    asyncio.run(_generate())

def query_groq_llm(user_prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY.strip()}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
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
    bot.reply_to(message, "👋 **¡Hola, compañero!** Soy Paco, tu Asistente Técnico. Podés escribirme o enviarme notas de voz. ¿En qué falla te ayudo hoy?", parse_mode="Markdown")

# Manejador de Notas de Voz recibidas (Speech-to-Text con Groq Whisper)
@bot.message_handler(content_types=['voice'])
def handle_voice_message(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        
        # 1. Descargar el audio de Telegram
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # 2. Transcribir el audio usando Groq Whisper
        transcribe_url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY.strip()}"}
        files = {
            'file': ('voice.oga', downloaded_file, 'audio/ogg'),
            'model': (None, 'whisper-large-v3')
        }
        
        trans_resp = requests.post(transcribe_url, headers=headers, files=files, timeout=30)
        
        if trans_resp.status_code != 200:
            bot.reply_to(message, "⚠️ No pude procesar tu nota de voz. Intenta nuevamente o escribe la consulta.")
            return
            
        transcribed_text = trans_resp.json().get('text', '')
        if not transcribed_text:
            bot.reply_to(message, "⚠️ No logré escuchar con claridad el audio.")
            return

        # 3. Consultar a la IA
        respuesta_texto, error = query_groq_llm(transcribed_text)
        if error:
            bot.reply_to(message, error)
            return

        # 4. Responder con Texto
        bot.reply_to(message, f"🎤 *Escuché:* \"{transcribed_text}\"\n\n{respuesta_texto}", parse_mode="Markdown")

        # 5. Generar y responder con Audio (Voz masculina argentina)
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

        # Responder en Texto
        bot.reply_to(message, respuesta_texto, parse_mode="Markdown")

        # Generar y enviar Audio
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
    print("🤖 Paco listo con voz argentina (Tomas)...")
    bot.polling(non_stop=True)
