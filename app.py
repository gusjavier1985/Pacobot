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

# --- MENÚS ESTÁTICOS GENERALES ---

MENU_INICIAL = """Hola, ¿cómo estás? La consulta es por:

1 - Mitsubishi
2 - CAF 6000
3 - por qué PACO?"""

TEXTO_POR_QUE_PACO = """Me llamo PACO por un juego de palabras y en reconocimiento a nuestros instructores Paleo (PA) y Greco (CO)"""

# --- MENÚS Y TEXTOS MITSUBISHI ---

MENU_MITSUBISHI = """Seleccioná una opción para Mitsubishi:

1_RESOLUCION DE AVERIAS
2_ENCENDIDO
3_ESTACIONAMIENTO

resultados con imágenes:
4_UBICACION Y ESQUEMAS
5_CONDUCCION
6_PUERTAS
7_EXTERIOR Y RELAY"""

TEXTO_MITSUBISHI_ENCENDIDO = """ENCENDIDO

1-En la cabina del coche n°1 (Punta Rosas),Encender el coche conectando los NFB que se encuentran pintados de blanco a saber:

•Batería
•Compresor
•Motogenerador
•Auxiliar de alta

2- Confirmar que el conmutador de dirección se encuentre en posición trasero y proceder a la apertura de puertas de ambos lados

3- Efectuar una revisión visual del buen estado de todos los elementos dentro de la cabina:
•Asiento del conductor
•Vidrios
•Amperímetro
•Voltímetros
•Manómetros
•Llaves NFB (estado y posición)
•Teléfonos (estado y funcionamiento)
•Llave o cuchilla de enclavamiento en la posición adelante (Enclavamiento habilitado)
•Estado de la llave de modalidad y AL (Aislado Limitado)

4- Comprobar el encendido de las luces de cola, cabecera y cabina"""

TEXTO_MITSUBISHI_ESTACIONAMIENTO = """ESTACIONAMIENTO

1-En la cabina del coche n°1 (Punta Rosas),Apagar el coche desconectando los NFB que se encuentran pintados de blanco a saber:
• Auxiliar de alta
• Motogenerador
•Compresor
•Batería

2- Colocar el conmutador de dirección en posición trasero.
En todos los coches:

3- Apagar el coche de acuerdo al punto 1 de estacionamiento

4- Retirar las herramientas

5- Calzar el tren"""

SUBMENU_MITSUBISHI_AVERIAS = """Seleccioná el número de la avería de Mitsubishi:

1 - Falla fatal ATP
2 - Ausencia de velocidad objetivo o velocidad objetivo Cero
3 - BP no Carga
4 - No se puede conducir de cabina delantera
5 - Seccionar en Plataforma
6 - Tren no arranca con luz de aviso apagada
7 - Tren no arranca con luz de aviso encendida
8 - Luz de BO
9 - Luces de BO y OLR encendidas
10 - Puertas no Abren
11 - Puertas no Cierran
12 - Alarma sonora no funciona
13 - Falla de Temporizador
14 - Compresor no para"""

TEXTOS_MITSUBISHI_AVERIAS = {
    "1": """Falla fatal ATP

•Verificar código de falla.
•Resetear y verificar
•Pasar a CL y verificar
•Pedir autorización al PCO / CTC, pasar a
•AL y verificar
•Solicitar presencia de MR

Toda vez que se efectúe una verificación, de ser el resultado positivo, continuar la marcha poniendo en conocimiento al PCO""",

    "2": """Ausencia de velocidad objetivo o velocidad objetivo Cero

-Confirmar con el PCO
-Solicitar autorización al PCO y pasar a CL""",

    "3": """BP no Carga

MPI Apagado:
Verificar:
-NFB de Control conectada
-NFB de freno conectada
-NFB de ATP conectada

MPI Encendido:
-Verificar inversora de marcha en posición correcta
-Falla de ATP
-Verificar Paratren
-Emergencias de cabina
-Electrovávulas EMV1 o EMV2
-Pérdidas a localizar""",

    "4": """No se puede conducir de cabina delantera

Previo aviso al PCO:
-Ir a la cabina trasera
-Desconectar enclavamiento de puertas
-Colocar ATP en modalidad AL.
-Colocar personal idóneo para la tarea de piloto
-Verificar sistemas de comunicación
-Viaje directo sin Pasajeros.""",

    "5": """Seccionar en Plataforma

-Solicitar corte de corriente en plataforma
-Accionar grifos interruptores
-Conducir con la mayor cantidad de coches a favor
-Liberar freno de los coches afectados (palanca roja y grifo verde)
-Anular enclavamiento
-Colocar en AL""",

    "6": """Tren no arranca con luz de aviso apagada

-Verificar aire en el BP
-Verificar conmutadores
-Verificar Puertas Cerradas
-Verificar NFB de luz de aviso en la cabina del Guarda
-Si el tren no arranca, sacar el enclavamiento de puertas y probar
-Dar aviso al PCO y realizar viaje normal a cabecera con las precauciones de circular sin enclavamiento de puertas""",

    "7": """Tren no arranca con luz de aviso encendida

-Verificar aire en el BP
-Verificar tensión (650 Vcc)
-Verificar en el control maestro un punto atrás
-Accionar varias veces el Hombre Muerto
-Sacar enclavamiento de puertas y probar
-De no arrancar manejar de la cabina de cola según procedimiento""",

    "8": """Luz de BO

-Indica que en un coche de la formación no circula corriente por los motores de tracción (a remolque sin freno dinámico)
-Colocar la inversión en posición NEUTRO, volver a la posición ADELANTE y verificar si la falla desaparece
-Determinar con el Guarda si es un coche de punta o intermedio mediante los amperímetros de cabina
-Continuar viaje dando aviso al PCO y tomando las precauciones del caso""",

    "9": """Luces de BO y OLR encendidas

-Identificar el coche en el que actuó la protección del circuito de tracción
-Reponer""",

    "10": """Puertas no Abren

De toda la formación:
-Verificar falso contacto en control de puertas
-Verificar conmutadores
-NFB de motor de puertas coche trasero
-Anular SPD (cuchilla arriba)
-Anular sistema temporizador de puertas

De un coche:
-Eléctrico: NFB o cuchillas de ese coche
-Neumático: Grifos generales o emergencia de puertas

Una puerta:
-Neumático: Grifo individual
-Mecánico: puerta trabada o descarrilada""",

    "11": """Puertas no Cierran

De toda la formación:
-Verificar conmutadores
-Anular sistema temporizador de puertas

De un coche:
-Verificar grifo general de puertas.
-Verificar emergencia de puertas

Una puerta:
-Verificar grifo de esa puerta
-Puerta trabada o descarrilada
-Si no se puede solucionar desairar y encerrojar""",

    "12": """Alarma sonora no funciona

-Verificar llave metálica tipo perilla en posición IZQUIERDA
-Si no normaliza finalizar el viaje dando aviso de cierre de puertas con el silbato""",

    "13": """Falla de Temporizador

-Verificar cuchilla del SPD
-Verificar Conmutadores de Dirección

-De no solucionarse la avería volver al sistema original:
-Conectar cuchillas del SPD hacia arriba
-Romper precinto de temporizado de puertas
-Continuar viaje de acuerdo a procedimiento de falta de alarma sonora""",

    "14": """Compresor no para

-Verificar el accionamiento de la válvula de seguridad y de drenaje mediante el manómetro de compresor (lectura normal entre 7 y 9 Kg)
-De no parar desconectar NFB de compresor del coche afectado
-Si el coche afectado es desde el cual se está conduciendo se puede verificar una reducción del frenado por lo cual se deben extremar las precauciones del caso"""
}

# --- SUBMENÚS CON IMÁGENES MITSUBISHI ---

SUBMENU_MITSU_CAT4 = """4_UBICACION Y ESQUEMAS:

1 - Extinguidor de incendios
2 - Escaleras de evacuación
3 - Emergencia acústica
4 - Emergencia de puertas
5 - Probador de tensión
6 - Esquema de distribución de los elementos de seguridad
7 - Luz indicadora de alarma
8 - NFB de Cabina (ubicación)
9 - Armario lateral
10 - Conmutador de dirección
11 - Distribucion de puertas y lados"""

MAPA_CAT4 = {
    "1": "Extinguidor de incendios",
    "2": "Escaleras de evacuación",
    "3": "Emergencia acústica",
    "4": "Emergencia de puertas",
    "5": "Probador de tensión",
    "6": "Esquema de distribución de los elementos de seguridad",
    "7": "Luz indicadora de alarma",
    "8": "NFB de Cabina (ubicación)",
    "9": "Armario lateral",
    "10": "Conmutador de dirección",
    "11": "Distribucion de puertas y lados"
}

SUBMENU_MITSU_CAT5 = """5_CONDUCCIÓN:

1 - Manómetro doble
2 - Velocímetro
3 - Control de marcha
4 - Control de freno (ME42)
5 - Luz de aviso al conductor
6 - Amperímetro
7 - Voltímetro de alta tensión
8 - Voltímetro de baja tensión
9 - Luces indicadoras
10 - Dispositivo de paratren ( caja de control )
11 - Interruptor de control CT (Anulado)
12 - Botón de reset del OLR
13 - Llave de modalidad CMC - CL
14 - Botón de arranque
15 - Llave de A.L y Llave de reset
16 - Caja controladora del MG
17 - Modo de operación CMC (Conducción Manual Controlada)
18 - Modo de operación CL (Conducción Limitada)
19 - Modo de operación AL (Aislado Limitado)
20 - Detección y gestión de falla del ATP de Abordo
21 - MPI (Modulo Principal de Informaciones)
22 - MPI sus funciones"""

MAPA_CAT5 = {
    "1": "Manómetro doble",
    "2": "Velocímetro",
    "3": "Control de marcha",
    "4": "Control de freno (ME42)",
    "5": "Luz de aviso al conductor",
    "6": "Amperímetro",
    "7": "Voltímetro de alta tensión",
    "8": "Voltímetro de baja tensión",
    "9": "Luces indicadoras",
    "10": "Dispositivo de paratren ( caja de control )",
    "11": "Interruptor de control CT (Anulado)",
    "12": "Botón de reset del OLR",
    "13": "Llave de modalidad CMC - CL",
    "14": "Botón de arranque",
    "15": "Llave de A.L y Llave de reset",
    "16": "Caja controladora del MG",
    "17": "Modo de operación CMC (Conducción Manual Controlada)",
    "18": "Modo de operación CL (Conducción Limitada)",
    "19": "Modo de operación AL (Aislado Limitado)",
    "20": "Detección y gestión de falla del ATP de Abordo",
    "21": "MPI (Modulo Principal de Informaciones)",
    "22": "MPI sus funciones"
}

SUBMENU_MITSU_CAT6 = """6_PUERTAS:

1 - Interruptor de enclavamiento
2 - Emergencia de cabina
3 - Control de puertas
4 - Temporizado de puertas
5 - Llave de conmutación de cierre de puertas
6 - Control de puertas para el conductor (sin habilitar)
7 - Interruptor de cortocircuito de cierre de puertas
8 - Grifos de puertas
9 - Motor de puertas"""

MAPA_CAT6 = {
    "1": "Interruptor de enclavamiento",
    "2": "Emergencia de cabina",
    "3": "Control de puertas",
    "4": "Temporizado de puertas",
    "5": "Llave de conmutación de cierre de puertas",
    "6": "Control de puertas para el conductor (sin habilitar)",
    "7": "Interruptor de cortocircuito de cierre de puertas",
    "8": "Grifos de puertas",
    "9": "Motor de puertas"
}

SUBMENU_MITSU_CAT7 = """7_EXTERIOR, GRIFOS Y RELAY:

1 - Grifo interruptor
2 - Electroválvulas de emergencia (EMV1 y EMV2)
3 - Dispositivo de accionamiento A1
4 - Caja controladora del MG"""

MAPA_CAT7 = {
    "1": "Grifo interruptor",
    "2": "Electroválvulas de emergencia (EMV1 y EMV2)",
    "3": "Dispositivo de accionamiento A1",
    "4": "Caja controladora del MG"
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
    "1": """SETA APLICADA

Normalizar la seta aplicada.
Si no se puede normalizar desconectar en todos los coches térmica "Tiradores de alarma" 53-F1.
Pulsar Bypass de freno para conducir.
Descender los pasajeros en el primer anden.""",

    "2": """VARIOS INVERSORES

Normalizar la inversora en la cabina correspondiente.
Si no se puede normalizar continuar marcha normal pulsando Bypass de freno y Bypass de tracción""",

    "3": """TERMICO EN CUALQUIER COCHE

Reponer en el coche afectado térmica "Equipo antibloqueo" (33F1).
Si no repone proceder ídem. Coche frenado por Micromicef.""",

    "4": """TERMICO EN COCHE 1

Reponer térmica "Lazo de emergencia" 52-F1.
Si no repone pulsar setas de pupitre en cabinas 1 y 6 y desconectar en todos los coches térmica "Tiradores de alarma" 53-F1.
Pulsar Bypass de freno para conducir.
Descender los pasajeros en el primer anden.""",

    "5": """TERMICO EN COCHE 6

Reponer térmica "Relé de cola" 57-F1.
Si no repone continuar marcha normal pulsando Bypass de freno y Bypass de tracción.
Presión en la cañería principal inferior a 8 kg/cm² :
Con 6,5 kg/cm² o más pulsar Bypass de freno para conducir.
Descender los pasajeros en el primer anden.
Con menos de 6,5 kg/cm² identificar la pérdida y seccionar neumáticamente."""
}

TEXTOS_DIRECTOS_CAF = {
    "1": """PROCEDIMIENTO ANTE UNA AVERÍA

Este procedimiento es para evitar una evacuación dentro del túnel.
Debe ser realizado siempre que se presente una avería en la formación y que la misma se encuentre dentro del túnel. Realizando estos pasos se logrará llegar en primera instancia a la próxima estación o a las estaciones de cabecera Alem / Rosas.

LEER LAS INDICACIONES DEL MAC
REALIZAR LAS 3 ACCIONES BASICAS

Desconectar y conectar llave de toma de mando (A.T.P)
Conectar disyuntores
Anular freno de retención

APAGAR Y ENCENDER LA FORMACIÓN EN CASO DE SER PROCEDENTE
"Si no se normaliza el desperfecto proceder de acuerdo a instrucción recibida por manual para la resolución de la avería""",

    "3": """PUERTAS NO ABREN

•Toda la formación :
Verificar la posición habilitada de la llave de pulsadores de puertas.
Reponer la térmica "Mando puertas" 55-F1 en la cabina del guarda.
Si no repone solicitar la apertura de puertas al conductor.

•Un coche :
Desbloqueo de puertas accionado: dirigirse al coche afectado y normalizar la llave de desbloqueo correspondiente.
Térmico en el coche afectado: dirigirse al coche afectado y reponer la térmica "Alimentación puertas" 55-F2.
Si no repone descender a los pasajeros de la formación.

•Una puerta :
Dirigirse a la puerta trabada y tratar de normalizarla, de no ser posible o si figura desbloqueada, condenarla y continuar marcha normal.""",

    "4": """PUERTAS NO CIERRAN

•Toda la formación :
Verificar la posición habilitada de la llave de pulsadores de puertas.
Reponer la térmica "Mando puertas" 55-F1 en la cabina del guarda.
Si no repone solicitar el cierre de puertas al conductor.

•Un coche :
Desbloqueo de puertas accionado: dirigirse al coche afectado y normalizar la llave de desbloqueo correspondiente.
Térmico en el coche afectado: dirigirse al coche afectado y reponer la térmica "Alimentación puertas" 55-F2.
Si no repone descender a los pasajeros de la formación.

•Una puerta :
Dirigirse a la puerta trabada y tratar de normalizarla, de no ser posible o si figura desbloqueada, condenarla y continuar marcha normal.
Si no puede cerrarse descender a los pasajeros de la formación."""
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

def obtener_detalles_imagen(modelo, titulo_buscado):
    # Caso especial opción 22 de Conducción
    if modelo == "Mitsubishi" and normalize_text(titulo_buscado) == normalize_text("MPI sus funciones"):
        images = load_imagenes_json()
        for img in images:
            if img.get("archivo") == "mitsu_46_mpi_funciones.jpg":
                titulo_limpio = img.get("titulo", "MPI sus funciones")
                desc = img.get("descripcion", "")
                text_out = f"{titulo_limpio}\n\n{desc}".strip() if desc else titulo_limpio
                return text_out, "mitsu_46_mpi_funciones.jpg"

    # Caso especial reutilización de foto CAF 6000 para opción 11 de Mitsubishi
    if modelo == "Mitsubishi" and "distribucion de puertas y lados" in normalize_text(titulo_buscado):
        images = load_imagenes_json()
        for img in images:
            if img.get("modelo") == "CAF 6000" and "distribucion de puertas y lados" in normalize_text(img.get("titulo", "")):
                desc = img.get("descripcion", "")
                text_out = f"DISTRIBUCIÓN DE PUERTAS Y LADOS\n\n{desc}".strip() if desc else "DISTRIBUCIÓN DE PUERTAS Y LADOS"
                return text_out, img.get("archivo")

    images = load_imagenes_json()
    t_norm = normalize_text(titulo_buscado)
    
    for img in images:
        if img.get("modelo") == modelo:
            t_json = normalize_text(img.get("titulo", ""))
            if t_norm and (t_norm in t_json or t_json in t_norm):
                titulo_limpio = img.get("titulo", titulo_buscado)
                desc = img.get("descripcion", "")
                text_out = f"{titulo_limpio}\n\n{desc}".strip() if desc else titulo_limpio
                return text_out, img.get("archivo")
                
    return titulo_buscado, None

def obtener_item_caf_por_titulo_o_indice(num_opcion):
    images = load_imagenes_json()
    caf_items = [img for img in images if img.get("modelo") == "CAF 6000"]
    titulo_buscado = MAPA_TITULOS_CAF.get(num_opcion, "")
    titulo_norm = normalize_text(titulo_buscado)

    for img in caf_items:
        t_json = normalize_text(img.get("titulo", ""))
        if titulo_norm and t_json == titulo_norm:
            titulo_limpio = img.get("titulo", titulo_buscado)
            desc = img.get("descripcion", "")
            text_out = f"{titulo_limpio}\n\n{desc}".strip() if desc else titulo_limpio
            return text_out, img.get("archivo")

    try:
        idx = int(num_opcion) - 1
        if 0 <= idx < len(caf_items):
            item = caf_items[idx]
            titulo_limpio = item.get("titulo", titulo_buscado)
            desc = item.get("descripcion", "")
            text_out = f"{titulo_limpio}\n\n{desc}".strip() if desc else titulo_limpio
            return text_out, item.get("archivo")
    except ValueError:
        pass

    return titulo_buscado, None

# --- LÓGICA DE NAVEGACIÓN COMPLETA ---

def procesar_flujo_menu(mensaje_user, user_id="default"):
    msg_raw = mensaje_user.strip()
    msg_clean = normalize_text(msg_raw)
    
    if msg_clean in ["novedad", "novedades"]:
        USER_STATES[user_id] = "INICIO"
        return None, "INICIO", None, False

    if msg_clean in ["hola", "inicio", "menu", "reset", "0"]:
        USER_STATES[user_id] = "MENU_PRINCIPAL"
        return MENU_INICIAL, "MENU_PRINCIPAL", None, False

    estado_actual = USER_STATES.get(user_id, "INICIO")

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
        elif msg_clean == "3":
            USER_STATES[user_id] = "INICIO"
            return TEXTO_POR_QUE_PACO, "INICIO", None, True
        else:
            return f"Opción no válida.\n\n{MENU_INICIAL}", "MENU_PRINCIPAL", None, False

    # --- MENU MITSUBISHI ---
    if estado_actual == "MENU_MITSUBISHI":
        if msg_clean == "1":
            USER_STATES[user_id] = "MITSU_AVERIAS"
            return SUBMENU_MITSUBISHI_AVERIAS, "MITSU_AVERIAS", None, False
        elif msg_clean == "2":
            USER_STATES[user_id] = "INICIO"
            return TEXTO_MITSUBISHI_ENCENDIDO, "INICIO", None, True
        elif msg_clean == "3":
            USER_STATES[user_id] = "INICIO"
            return TEXTO_MITSUBISHI_ESTACIONAMIENTO, "INICIO", None, True
        elif msg_clean == "4":
            USER_STATES[user_id] = "MITSU_CAT4"
            return SUBMENU_MITSU_CAT4, "MITSU_CAT4", None, False
        elif msg_clean == "5":
            USER_STATES[user_id] = "MITSU_CAT5"
            return SUBMENU_MITSU_CAT5, "MITSU_CAT5", None, False
        elif msg_clean == "6":
            USER_STATES[user_id] = "MITSU_CAT6"
            return SUBMENU_MITSU_CAT6, "MITSU_CAT6", None, False
        elif msg_clean == "7":
            USER_STATES[user_id] = "MITSU_CAT7"
            return SUBMENU_MITSU_CAT7, "MITSU_CAT7", None, False
        else:
            return f"Opción no válida.\n\n{MENU_MITSUBISHI}", "MENU_MITSUBISHI", None, False

    # --- MITSUBISHI: AVERÍAS ---
    if estado_actual == "MITSU_AVERIAS":
        if msg_clean in TEXTOS_MITSUBISHI_AVERIAS:
            res = TEXTOS_MITSUBISHI_AVERIAS[msg_clean]
            USER_STATES[user_id] = "INICIO"
            return res, "INICIO", None, True
        else:
            return f"Opción no válida.\n\n{SUBMENU_MITSUBISHI_AVERIAS}", "MITSU_AVERIAS", None, False

    # --- MITSUBISHI: CAT 4 (UBICACIÓN Y ESQUEMAS) ---
    if estado_actual == "MITSU_CAT4":
        if msg_clean in MAPA_CAT4:
            titulo = MAPA_CAT4[msg_clean]
            texto_final, archivo = obtener_detalles_imagen("Mitsubishi", titulo)
            USER_STATES[user_id] = "INICIO"
            return texto_final, "INICIO", archivo, True
        else:
            return f"Opción no válida.\n\n{SUBMENU_MITSU_CAT4}", "MITSU_CAT4", None, False

    # --- MITSUBISHI: CAT 5 (CONDUCCIÓN) ---
    if estado_actual == "MITSU_CAT5":
        if msg_clean in MAPA_CAT5:
            titulo = MAPA_CAT5[msg_clean]
            texto_final, archivo = obtener_detalles_imagen("Mitsubishi", titulo)
            USER_STATES[user_id] = "INICIO"
            return texto_final, "INICIO", archivo, True
        else:
            return f"Opción no válida.\n\n{SUBMENU_MITSU_CAT5}", "MITSU_CAT5", None, False

    # --- MITSUBISHI: CAT 6 (PUERTAS) ---
    if estado_actual == "MITSU_CAT6":
        if msg_clean in MAPA_CAT6:
            titulo = MAPA_CAT6[msg_clean]
            texto_final, archivo = obtener_detalles_imagen("Mitsubishi", titulo)
            USER_STATES[user_id] = "INICIO"
            return texto_final, "INICIO", archivo, True
        else:
            return f"Opción no válida.\n\n{SUBMENU_MITSU_CAT6}", "MITSU_CAT6", None, False

    # --- MITSUBISHI: CAT 7 (EXTERIOR, GRIFOS Y RELAY) ---
    if estado_actual == "MITSU_CAT7":
        if msg_clean in MAPA_CAT7:
            titulo = MAPA_CAT7[msg_clean]
            texto_final, archivo = obtener_detalles_imagen("Mitsubishi", titulo)
            USER_STATES[user_id] = "INICIO"
            return texto_final, "INICIO", archivo, True
        else:
            return f"Opción no válida.\n\n{SUBMENU_MITSU_CAT7}", "MITSU_CAT7", None, False

    # --- MENÚ CAF 6000 ---
    if estado_actual == "MENU_CAF":
        if msg_clean == "2":
            USER_STATES[user_id] = "CAF_LAZO"
            return SUBMENU_CAF_LAZO, "CAF_LAZO", None, False
        elif msg_clean in TEXTOS_DIRECTOS_CAF:
            res = TEXTOS_DIRECTOS_CAF[msg_clean]
            USER_STATES[user_id] = "INICIO"
            return res, "INICIO", None, True
        elif msg_clean in MAPA_TITULOS_CAF:
            desc, archivo = obtener_item_caf_por_titulo_o_indice(msg_clean)
            USER_STATES[user_id] = "INICIO"
            return desc, "INICIO", archivo, True
        else:
            return f"Opción no válida.\n\n{MENU_CAF6000}", "MENU_CAF", None, False

    # --- SUBMENÚ CAF LAZO ---
    if estado_actual == "CAF_LAZO":
        if msg_clean in TEXTOS_CAF_LAZO:
            res = TEXTOS_CAF_LAZO[msg_clean]
            USER_STATES[user_id] = "INICIO"
            return res, "INICIO", None, True
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

        # SI VIENE DE BASE44/NOVEDADES (Texto libre que devolvió el menú principal por defecto),
        # forzamos que devuelva el texto original que envió Base44 y le generamos el audio.
        es_novedad_o_libre = not pregunta.strip().isdigit() and pregunta.strip().lower() not in ["hola", "inicio", "menu", "reset", "0"]
        if es_novedad_o_libre:
            respuesta_texto = pregunta
            es_respuesta_final = True

        host_url = request.host_url.rstrip('/')
        if host_url.startswith("http://"):
            host_url = host_url.replace("http://", "https://", 1)

        imagen_url = f"{host_url}/images/{archivo_imagen}" if archivo_imagen else None

        # Audio si es respuesta final O si es un texto libre/novedad
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
