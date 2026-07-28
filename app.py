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

# Memoria de estado para navegación por chat
USER_STATES = {}

# --- MENÚS ESTÁTICOS ---

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

# --- MENÚ Y SUBMENÚ CAF 6000 ---

MENU_CAF6000 = """Seleccioná una opción para CAF 6000:

1 - PROCEDIMIENTO ANTE UNA AVERÍA
2 - INTERRUPCION DEL HILO DE LAZO
3 - PUERTAS NO ABREN
4 - PUERTAS NO CIERRAN
5 - ENCENDER UNA FORMACIÓN CAF 6000
6 - APAGAR UNA FORMACIÓN CAF 6000
7 - COCHE FRENADO - POR UNIDAD DE FRENO
8 - COCHE FRENADO - POR MICROCEF
9 - BOCINA TRABADA
10 - BAJAR UN PANTÓGRAFO
11 - SECCIONAMIENTO NEUMÁTICO
12 - ESQUEMA DE UBICACIÓN DE ELEMENTOS
13 - PANEL NEUMÁTICO DE CABINA
14 - PANEL NEUMÁTICO COCHE REMOLQUE
15 - B-115 DISTRIBUIDOR DEL FRENO DE ESTACIONAMIENTO
16 - DETALLE DEL BOGIE Y ANILLA PARA RETIRAR EL FRENO DE ESTACIONAMIENTO
17 - FORMACIÓN AFLOJA Y NO TRACCIONA (BYPASS DE TRACCIÓN APAGADO)
18 - DISTRIBUCIÓN DE PUERTAS, LADOS Y COCHES"""

SUBMENU_CAF_LAZO = """Opciones para 2 - INTERRUPCION DEL HILO DE LAZO:

1 - SETA APLICADA
2 - VARIOS INVERSORES
3 - TERMICO EN CUALQUIER COCHE
4 - TERMICO EN COCHE 1
5 - TERMICO EN COCHE 6"""

TEXTOS_CAF_LAZO = {
    "1": """1_SETA APLICADA :
Normalizar la seta aplicada.
Si no se puede normalizar desconectar en todos los coches térmica "Tiradores de alarma" 53-F1.
Pulsar Bypass de freno para conducir.
Descender los pasajeros en el primer anden.""",

    "2": """2_VARIOS INVERSORES:
Normalizar la inversora en la cabina correspondiente.
Si no se puede normalizar continuar marcha normal pulsando Bypass de freno y Bypass de tracción""",

    "3": """3_TERMICO EN CUALQUIER COCHE:
Reponer en el coche afectado térmica "Equipo antibloqueo" (33F1).
Si no repone proceder ídem. Coche frenado por Micromicef.""",

    "4": """4_TERMICO EN COCHE 1 :
Reponer térmica "Lazo de emergencia" 52-F1.
Si no repone pulsar setas de pupitre en cabinas 1 y 6 y desconectar en todos los coches térmica "Tiradores de alarma" 53-F1.
Pulsar Bypass de freno para conducir.
Descender los pasajeros en el primer anden.""",

    "5": """5_TERMICO EN COCHE 6 : 
Reponer térmica "Relé de cola" 57-F1.
Si no repone continuar marcha normal pulsando Bypass de freno y Bypass de tracción.
Presión en la cañería principal inferior a 8 kg/cm² :
Con 6,5 kg/cm² o más pulsar Bypass de freno para conducir.
Descender los pasajeros en el primer anden.
Con menos de 6,5 kg/cm² identificar la pérdida y seccionar neumáticamente."""
}

# TEXTOS DIRECTOS ESPECÍFICOS CAF 6000 (Opciones 1, 3 y 4)
TEXTOS_DIRECTOS_CAF = {
    "1": """1- PROCEDIMIENTO ANTE UNA AVERÍA:

- Identificar el fallo en la pantalla/panel de cabina.
- Verificar el estado de térmicos y lazos de seguridad.
- Aplicar el procedimiento específico según el código o síntoma del equipo.""",

    "3": """3- PUERTAS NO ABREN:

- Verificar habilitación de lado de plataforma.
- Revisar presión de aire en circuito auxiliar.
- Verificar estado de térmicos de mando de puertas.""",

    "4": """4- PUERTAS NO CIERRAN:

- Verificar si hay obstrucción física en el bucle de puertas.
- Comprobar que ninguna seta de emergencia esté accionada.
- Verificar indicador de lazo de puertas en pupitre de conducción."""
}

MAPA_TITULOS_CAF = {
    "5": "ENCENDER UNA FORMACIÓN CAF 6000",
    "6": "APAGAR UNA FORMACIÓN CAF 6000",
    "7": "COCHE FRENADO - POR UNIDAD DE FRENO",
    "8": "COCHE FRENADO - POR MICROCEF",
    "9": "BOCINA TRABADA",
    "10": "BAJAR UN PANTÓGRAFO",
    "11": "SECCIONAMIENTO NEUMÁTICO",
    "12": "ESQUEMA DE UBICACIÓN DE ELEMENTOS",
    "13": "PANEL NEUMÁTICO DE CABINA",
    "14": "PANEL NEUMÁTICO COCHE REMOLQUE",
    "15": "B-115 DISTRIBUIDOR DEL FRENO DE ESTACIONAMIENTO",
    "16": "DETALLE DEL BOGIE Y ANILLA PARA RETIRAR EL FRENO DE ESTACIONAMIENTO",
    "17": "FORMACIÓN AFLOJA Y NO TRACCIONA (BYPASS DE TRACCIÓN APAGADO)",
    "18": "DISTRIBUCIÓN DE PUERTAS, LADOS Y COCHES"
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
    return f"Información técnica para: {busqueda}\n\n{PDF_CONTENT[:1500]}..."

def obtener_item_caf_por_titulo_o_indice(num_opcion):
    images = load_imagenes_json()
    caf_items = [img for img in images if img.get("modelo") == "CAF 6000"]
    titulo_buscado = MAPA_TITULOS_CAF.get(num_opcion, "")
    titulo_norm = normalize_text(titulo_buscado)

    # 1. Coincidencia exacta por título
    for img in caf_items:
        t_json = normalize_text(img.get("titulo", ""))
        if titulo_norm and t_json == titulo_norm:
            desc = img.get("descripcion") or img.get("titulo") or titulo_buscado
            return desc, img.get("archivo")

    # 2. Coincidencia por índice de la lista en JSON si no es exacta
    try:
        idx = int(num_opcion) - 1
        if 0 <= idx < len(caf_items):
            item = caf_items[idx]
            desc = item.get("descripcion") or item.get("titulo") or titulo_buscado
            return desc, item.get("archivo")
    except ValueError:
        pass

    return f"Información sobre: {titulo_buscado}", None

# --- LÓGICA DE NAVEGACIÓN ---

def procesar_flujo_menu(mensaje_user, user_id="default"):
    msg_raw = mensaje_user.strip()
    msg_clean = normalize_text(msg_raw)
    
    # Excepción para Novedades (Base44)
    if msg_clean in ["novedad", "novedades"]:
        USER_STATES[user_id] = "INICIO"
        return None, "INICIO", None, False

    # Comando explícito de inicio o reseteo
    if msg_clean in ["hola", "inicio", "menu", "reset", "0"]:
        USER_STATES[user_id] = "MENU_PRINCIPAL"
        return MENU_INICIAL, "MENU_PRINCIPAL", None, False

    estado_actual = USER_STATES.get(user_id, "INICIO")

    # Si ingresan texto libre o no hay estado
    if estado_actual == "INICIO" or not msg_clean.isdigit():
        USER_STATES[user_id] = "MENU_PRINCIPAL"
        return MENU_INICIAL, "MENU_PRINCIPAL", None, False

    # --- MENU PRINCIPAL ---
    if estado_actual == "MENU_PRINCIPAL":
        if msg_clean == "1":
            USER_STATES[user_id] = "MENU_MITSUBISHI"
            return MENU_MITSUBISHI, "MENU_MITSUBISHI", None, False
        elif msg_clean == "2":
            USER_STATES[user_id] = "MENU_CAF"
            return MENU_CAF6000, "MENU_CAF", None, False
        else:
            return f"Opción no válida.\n\n{MENU_INICIAL}", "MENU_PRINCIPAL", None, False

    # --- SUBMENÚ MITSUBISHI ---
    if estado_actual == "MENU_MITSUBISHI":
        if msg_clean == "1":
            USER_STATES[user_id] = "MITSUBISHI_AVERIAS"
            return MENU_AVERIAS_MITSUBISHI, "MITSUBISHI_AVERIAS", None, False
        elif msg_clean == "2":
            images = load_imagenes_json()
            mitsu_images = [img for img in images if img.get("modelo") == "Mitsubishi"]
            if not mitsu_images:
                return "No hay esquemas cargados para Mitsubishi.\n\n" + MENU_MITSUBISHI, "MENU_MITSUBISHI", None, False
            
            USER_STATES[user_id] = "MITSUBISHI_ESQUEMAS"
            out = "Ubicación de instrumentos y esquemas Mitsubishi:\n\n"
            for i, img in enumerate(mitsu_images, start=1):
                out += f"{i} - {img.get('titulo')}\n"
            return out, "MITSUBISHI_ESQUEMAS", None, False
        else:
            return f"Opción no válida.\n\n{MENU_MITSUBISHI}", "MENU_MITSUBISHI", None, False

    # --- RESPUESTA FINAL: MITSUBISHI AVERÍAS ---
    if estado_actual == "MITSUBISHI_AVERIAS":
        if msg_clean in AVERIAS_MITSUBISHI_MAP:
            titulo_averia = AVERIAS_MITSUBISHI_MAP[msg_clean]
            respuesta_literal = buscar_contenido_literal(titulo_averia)
            USER_STATES[user_id] = "INICIO"
            return respuesta_literal, "INICIO", None, True  # Genera Audio
        else:
            return f"Opción no válida. Por favor ingresá un número del 1 al 14.\n\n{MENU_AVERIAS_MITSUBISHI}", "MITSUBISHI_AVERIAS", None, False

    # --- RESPUESTA FINAL: MITSUBISHI ESQUEMAS ---
    if estado_actual == "MITSUBISHI_ESQUEMAS":
        images = load_imagenes_json()
        mitsu_images = [img for img in images if img.get("modelo") == "Mitsubishi"]
        try:
            idx = int(msg_clean) - 1
            if 0 <= idx < len(mitsu_images):
                item = mitsu_images[idx]
                USER_STATES[user_id] = "INICIO"
                return item.get("descripcion", ""), "INICIO", item.get("archivo"), True  # Genera Audio
        except ValueError:
            pass
        return "Opción no válida. Por favor seleccioná un número de la lista.", "MITSUBISHI_ESQUEMAS", None, False

    # --- MENÚ CAF 6000 ---
    if estado_actual == "MENU_CAF":
        if msg_clean == "2":
            USER_STATES[user_id] = "CAF_LAZO"
            return SUBMENU_CAF_LAZO, "CAF_LAZO", None, False
        elif msg_clean in TEXTOS_DIRECTOS_CAF:
            res = TEXTOS_DIRECTOS_CAF[msg_clean]
            USER_STATES[user_id] = "INICIO"
            return res, "INICIO", None, True  # Respuesta final -> Genera Audio
        elif msg_clean in MAPA_TITULOS_CAF:
            desc, archivo = obtener_item_caf_por_titulo_o_indice(msg_clean)
            USER_STATES[user_id] = "INICIO"
            return desc, "INICIO", archivo, True  # Respuesta final -> Genera Audio
        else:
            return f"Opción no válida.\n\n{MENU_CAF6000}", "MENU_CAF", None, False

    # --- RESPUESTA FINAL: SUBMENÚ CAF LAZO ---
    if estado_actual == "CAF_LAZO":
        if msg_clean in TEXTOS_CAF_LAZO:
            res = TEXTOS_CAF_LAZO[msg_clean]
            USER_STATES[user_id] = "INICIO"
            return res, "INICIO", None, True  # Respuesta final -> Genera Audio
        else:
            return f"Opción no válida.\n\n{SUBMENU_CAF_LAZO}", "CAF_LAZO", None, False

    USER_STATES[user_id] = "MENU_PRINCIPAL"
    return MENU_INICIAL, "MENU_PRINCIPAL", None, False

# --- GENERACIÓN DE AUDIO ---

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
        print(f"Error TTS: {e}")
        return False

# --- RUTAS DE API ---

@app.route('/', methods=['GET'])
def health_check():
    return "Bot Paco API OK", 200

@app.route('/preguntar', methods=['POST', 'OPTIONS'])
def api_preguntar():
    if request.method == 'OPTIONS':
        return '', 200

    try:
        data = request.get_json(silent=True) or {}
        pregunta = data.get('pregunta') or data.get('message') or data.get('text') or ''
        user_id = data.get('user_id') or data.get('sender') or 'usuario_unico'

        respuesta_texto, nuevo_estado, archivo_imagen, es_respuesta_final = procesar_flujo_menu(pregunta, user_id=user_id)

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

        # Genera e incluye audio únicamente si se llegó a la respuesta final
        audio_url = None
        if es_respuesta_final and respuesta_texto:
            filename_audio = f"audio_{uuid.uuid4().hex[:8]}.mp3"
            filepath_audio = os.path.join(AUDIO_DIR, filename_audio)
            audio_ok = generate_voice_file(respuesta_texto, filepath_audio)
            if audio_ok:
                audio_url = f"{host_url}/audio/{filename_audio}"

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
    print(f"🤖 Bot Paco activo en el puerto {port}...")
    app.run(host="0.0.0.0", port=port)
