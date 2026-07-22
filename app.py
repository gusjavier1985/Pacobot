import os
import glob
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from pypdf import PdfReader

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

# 3. Carga PROFUNDA de manuales clave y de fallas
print("Cargando manuales técnicos principales...")
context_text = ""
pdf_files = sorted(glob.glob("*.pdf"))

for pdf in pdf_files:
    try:
        reader = PdfReader(pdf)
        context_text += f"\n\n=== DOCUMENTO COMPLETO: {pdf} ===\n"
        # Leemos hasta 30 páginas por manual (cubre la totalidad de guías de fallas)
        for page in reader.pages[:30]:
            text = page.extract_text()
            if text:
                context_text += text + "\n"
    except Exception as e:
        print(f"Error procesando {pdf}: {e}")

# Límite ampliado a 35.000 caracteres (~8.000 tokens) perfecto para Llama-3.1-8b-instant
context_text = context_text[:35000]

# 4. Instrucción del Asistente
SYSTEM_INSTRUCTION = f"""
Eres Paco, un asistente técnico especializado para el personal de tráfico del Subte (motoristas, guardias, maniobristas).
Tu función es ayudar a resolver fallas técnicas, averías en formaciones y responder procedimientos de actuación.

MANUALES TÉCNICOS Y GUÍAS DE FALLAS DISPONIBLES:
{context_text}

Reglas estrictas:
1. Sé conciso, claro y directo.
2. Basate estrictamente en los manuales de consulta arriba provistos.
3. Para resolución de fallas o procedimientos paso a paso, usa listas numeradas precisas.
4. Si hay duda o riesgo operativo, aconseja consultar con la central de tráfico.
"""

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 **¡Hola, compañero!** Soy Paco, tu Asistente Técnico. ¿En qué duda o falla te ayudo hoy?", parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def answer_query(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')

        url = "https://api.groq.com/openai/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY.strip()}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": message.text}
            ],
            "temperature": 0.2
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        res_data = response.json()

        if response.status_code == 200:
            texto_respuesta = res_data['choices'][0]['message']['content']
            bot.reply_to(message, texto_respuesta)
        else:
            err_msg = res_data.get('error', {}).get('message', 'Error en la consulta')
            bot.reply_to(message, f"⚠️ Error {response.status_code}: {err_msg}")

    except Exception as e:
        bot.reply_to(message, f"⚠️ Error de conexión: {str(e)}")

if __name__ == "__main__":
    print("🤖 Paco listo...")
    bot.polling(non_stop=True)
