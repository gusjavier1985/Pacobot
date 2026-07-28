import os
import glob
import re
import uuid
import json
import unicodedata
import asyncio
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from pypdf import PdfReader
import edge_tts

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "static_audio")
IMAGE_DIR = os.path.join(BASE_DIR, "static_images")
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- MEMORIA TEMPORAL DE ESTADOS POR USUARIO/CHAT ---
# Guarda en qué punto del menú está el usuario activo
USER_STATES = {}

# --- TEXTOS Y MENÚS ESTÁTICOS ---

MENU_INICIAL = """Hola, ¿cómo estás? La consulta es por:

1 - Mitsubishi
2 - CAF 6000"""

MENU_MITSUBISHI = """Opciones para Mitsubishi:

1 - Averías
2 - Ubicación de instrumentos / Esquemas"""

MENU_AVERIAS_MITSUBISHI = """Seleccioná el número de la avería de Mitsubishi:

1 - Falla Fatal de ATP
2 - Ausencia de velocidad objetivo o velocidad objetivo cero
3 - BP no carga
4 - No se puede conducir desde la cabina delantera
5 - Seccionar en plataforma
6 - Tren no arranca con luz de aviso apagada
7 - Tren no arranca con luz de aviso encendida
8 - Luz de BO
9 - Luz de BO y OLR
10 - Puertas no abren
11 - Puertas no cierran
12 - Alarma sonora no funciona
13 - Temporizador
14 - Un compresor no para"""

AVERIAS_MITSUBISHI_MAP = {
    "1": "1 Falla Fatal de ATP",
    "2": "2 Ausencia de velocidad objetivo o velocidad objetivo cero",
    "3": "3 BP no carga",
    "4": "4 No se puede conducir desde la cabina delantera",
    "5": "5 Seccionar en plataforma",
    "6": "6 Tren no arranca con luz de aviso apagada",
    "7": "7 Tren no arranca con luz de aviso encendida",
    "8": "8 Luz de BO",
    "9": "9 Luz de BO y OLR",
    "10": "10 Puertas no abren",
    "11": "11 Puertas no cierran",
    "12": "12 Alarma sonora no funciona",
    "13": "13 Temporizador",
    "14": "14 Un compresor no para"
}

# --- FUNCIONES AUXILIARES ---

def normalize_text(text):
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return text.lower().strip()

def load_imagenes_json():
    for candidate in ["imagenes.json", "Imagenes.json", "IMAGENES.JSON"]:
        json_path = os.path.join(BASE_DIR, candidate)
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error leyendo {json_path}: {e}")
    return []

def get_pdf_text():
    full_text = ""
    pdf_files = sorted(glob.glob(os.path.join(BASE_DIR, "*.pdf")))
    for pdf in pdf_files:
        try:
            reader = PdfReader(pdf)
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    full_text += t + "\n"
        except Exception as e:
            print(f"Error leyendo PDF {pdf}: {e}")
    return full_text

PDF_CONTENT = get_pdf_text()

def buscar_contenido_literal(busqueda):
    pattern = re.compile(rf"({re.escape(busqueda)}.*?)(?=\n\d+\s+[A-Z]|\Z)", re.DOTALL | re.IGNORECASE)
    match = pattern.search(PDF_CONTENT)
    if match:
        return match.group(1).strip()
    return f"Información técnica completa para: {busqueda}\n\n{PDF_CONTENT[:1500]}..."

def get_menu_caf6000():
    images = load_imagenes_json()
    caf_images = [img for img in images if img.get("modelo") == "CAF 6000"]
    
    text = "Opciones disponibles para CAF 6000:\n\n"
    text += "1 - Procedimientos generales de averías (Manual PDF)\n"
    
    idx = 2
    for img in caf_images:
        text += f"{idx} - {img.get('titulo', 'Esquema / Imagen CAF')}\n"
        idx += 1
        
    return text, caf_images

# --- LÓGICA DE NAVEGACIÓN CORREGIDA ---

def procesar_flujo_menu(mensaje_user, user_id="default"):
    msg_raw = mensaje_user.strip()
    msg_clean = normalize_text(msg_raw)
    
    # 1. Excepción para Novedades (Base44)
    if msg_clean in ["novedad", "novedades"]:
        USER_STATES[user_id] = "INICIO"
        return None, "INICIO", None

    # 2. Comando explícito de inicio o reseteo
    if msg_clean in ["hola", "inicio", "menu", "reset", "0"]:
        USER_STATES[user_id] = "MENU_PRINCIPAL"
        return MENU_INICIAL, "MENU_PRINCIPAL", None

    # Obtenemos el estado actual del usuario
    estado_actual = USER_STATES.get(user_id, "INICIO")

    # Si no hay estado previo o enviaron cualquier texto libre no numérico
    if estado_actual == "INICIO" or not msg_clean.isdigit():
        USER_STATES[user_id] = "MENU_PRINCIPAL"
        return MENU_INICIAL, "MENU_PRINCIPAL", None

    # --- NAVEGACIÓN PASO A PASO ---

    # PASO 1: Eligió opción del Menú Principal
    if estado_actual == "MENU_PRINCIPAL":
        if msg_clean == "1":
            USER_STATES[user_id] = "MENU_MITSUBISHI"
            return MENU_MITSUBISHI, "MENU_MITSUBISHI", None
        elif msg_clean == "2":
            USER_STATES[user_id] = "MENU_CAF"
            menu_caf, _ = get_menu_caf6000()
            return menu_caf, "MENU_CAF", None
        else:
            return f"Opción no válida.\n\n{MENU_INICIAL}", "MENU_PRINCIPAL", None

    # PASO 2: Submenú Mitsubishi
    if estado_actual == "MENU_MITSUBISHI":
        if msg_clean == "1":
            USER_STATES[user_id] = "MITSUBISHI_AVERIAS"
            return MENU_AVERIAS_MITSUBISHI, "MITSUBISHI_AVERIAS", None
        elif msg_clean == "2":
            images = load_imagenes_json()
            mitsu_images = [img for img in images if img.get("modelo") == "Mitsubishi"]
            if not mitsu_images:
                return "No hay esquemas cargados para Mitsubishi.\n\n" + MENU_MITSUBISHI, "MENU_MITSUBISHI", None
            
            USER_STATES[user_id] = "MITSUBISHI_ESQUEMAS"
            out = "Ubicación de instrumentos y esquemas Mitsubishi:\n\n"
            for i, img in enumerate(mitsu_images, start=1):
                out += f"{i} - {img.get('titulo')}\n"
            return out, "MITSUBISHI_ESQUEMAS", None
        else:
            return f"Opción no válida.\n\n{MENU_MITSUBISHI}", "MENU_MITSUBISHI", None

    # PASO 3: Selección de una de las 14 Averías Mitsubishi
    if estado_actual == "MITSUBISHI_AVERIAS":
        if msg_clean in AVERIAS_MITSUBISHI_MAP:
            titulo_averia = AVERIAS_MITSUBISHI_MAP[msg_clean]
            respuesta_literal = buscar_contenido_literal(titulo_averia)
            USER_STATES[user_id] = "INICIO"  # Reinicia estado tras mostrar la respuesta
            return respuesta_literal, "INICIO", None
        else:
            return f"Opción no válida. Por favor ingresá un número del 1 al 14.\n\n{MENU_AVERIAS_MITSUBISHI}", "MITSUBISHI_AVERIAS", None

    # PASO 4: Esquemas Mitsubishi
    if estado_actual == "MITSUBISHI_ESQUEMAS":
        images = load_imagenes_json()
        mitsu_images = [img for img in images if img.get("modelo") == "Mitsubishi"]
        try:
            idx = int(msg_clean) - 1
            if 0 <= idx < len(mitsu_images):
                item = mitsu_images[idx]
                USER_STATES[user_id] = "INICIO"
                return item.get("descripcion", ""), "INICIO", item.get("archivo")
        except ValueError:
            pass
        return "Opción no válida. Por favor seleccioná un número de la lista.", "MITSUBISHI_ESQUEMAS", None

    # PASO 5: Opciones CAF 6000
    if estado_actual == "MENU_CAF":
        menu_caf, caf_images = get_menu_caf6000()
        if msg_clean == "1":
            res = buscar_contenido_literal("CAF 6000")
            USER_STATES[user_id] = "INICIO"
            return res, "INICIO", None
        else:
            try:
                opc_idx = int(msg_clean) - 2
                if 0 <= opc_idx < len(caf_images):
                    item = caf_images[opc_idx]
                    USER_STATES[user_id] = "INICIO"
                    return item.get("descripcion", ""), "INICIO", item.get("archivo")
            except ValueError:
                pass
            return f"Opción no válida.\n\n{menu_caf}", "MENU_CAF", None

    # Por defecto ante cualquier inconsistencia, reinicia al Menú Principal
    USER_STATES[user_id] = "MENU_PRINCIPAL"
    return MENU_INICIAL, "MENU_PRINCIPAL", None

# --- GENERACIÓN DE AUDIO (TTS) ---

def generate_voice_file(text, output_file):
    if not text:
        return False
    clean_text = re.sub(r'[*#`_•-]', '', text)
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

# --- API ENDPOINTS ---

@app.route('/', methods=['GET'])
def health_check():
    return "Bot Paco API Activo", 200

@app.route('/preguntar', methods=['POST', 'OPTIONS'])
def api_preguntar():
    if request.method == 'OPTIONS':
        return '', 200

    try:
        data = request.get_json(silent=True) or {}
        pregunta = data.get('pregunta') or data.get('message') or data.get('text') or ''
        user_id = data.get('user_id') or data.get('sender') or 'usuario_unico'

        respuesta_texto, nuevo_estado, archivo_imagen = procesar_flujo_menu(pregunta, user_id=user_id)

        if respuesta_texto is None:
            return jsonify({
                'passthrough': True,
                'respuesta_texto': None,
                'nuevo_estado': 'INICIO'
            }), 200

        host_url = request.host_url.rstrip('/')
        if host_url.startswith("http://"):
            host_url = host_url.replace("http://", "https://", 1)

        imagen_url = f"{host_url}/images/{archivo_imagen}" if archivo_imagen else None

        filename_audio = f"audio_{uuid.uuid4().hex[:8]}.mp3"
        filepath_audio = os.path.join(AUDIO_DIR, filename_audio)
        audio_ok = generate_voice_file(respuesta_texto, filepath_audio)
        audio_url = f"{host_url}/audio/{filename_audio}" if audio_ok else None

        return jsonify({
            'respuesta_texto': respuesta_texto,
            'nuevo_estado': nuevo_estado,
            'audio_url': audio_url,
            'imagen_url': imagen_url
        }), 200

    except Exception as e:
        print(f"Error en /preguntar: {str(e)}")
        return jsonify({
            'respuesta_texto': f"Error interno: {str(e)}",
            'nuevo_estado': 'INICIO',
            'audio_url': None,
            'imagen_url': None
        }), 200

@app.route('/audio/<filename>', methods=['GET'])
def get_audio(filename):
    return send_from_directory(AUDIO_DIR, filename)

@app.route('/images/<filename>', methods=['GET'])
def get_image(filename):
    return send_from_directory(IMAGE_DIR, filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"🤖 Bot Paco en ejecución en puerto {port}...")
    app.run(host="0.0.0.0", port=port)
