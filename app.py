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
PDF_PATH = os.path.join(BASE_DIR, "Instrucciones_de_servicio.pdf")

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
3 - Instrucciones de servicios al toque (resumidas)
4 - por qué PACO?"""

TEXTO_POR_QUE_PACO = """Me llamo PACO por un juego de palabras y en reconocimiento a nuestros instructores Paleo (PA) y Greco (CO)"""

# --- ESTRUCTURA DE CATEGORÍAS DE INSTRUCCIONES DE SERVICIO (OPCIÓN 3) ---

MENU_IS_CATEGORIAS = """Seleccioná una categoría de Instrucciones de Servicio:

1. Operativa y Conducción
• IS N° 17: Marcas de Centro de Vías
• IS N° 19: Velocidades de circulación
• IS N° 41: Cambio de cabina en cabecera
• IS N° 47: Cambio de cabina en cabeceras - Coches Mitsubishi

2. Operativa y Comunicaciones
• IS N° 1: Ubicación del guarda y utilización del sistema Tierra - Tren en situaciones especiales

3. Operativa y Emergencias
• IS N° 25: Retorno de un tren a la estación anterior
• IS N° 50: Normas para conducción desde cabina de cola
• IS N° 61: Evacuación de formaciones en estaciones cerradas por obra

4. Operativa y Maniobras
• IS N° 8: Maniobras que afecten a las vías de servicio
• IS N° 13: Cambio de Maniobras en caso de Emergencia o por Razones Operativas
• IS N° 14: Maniobras con cambio de cabina Conductores Especializados
• IS N° 24: Operatoria de cambios Taller Urquiza
• IS N° 32: Maniobras de contramano

5. Operativa y Material Rodante
• IS N° 16: Movimiento de Vehículos de gran porte
• IS N° 21: Traslado de trenes de línea B al Ferrocarril Urquiza y viceversa
• IS N° 35: Accionamiento de puertas con temporizador y aviso sonoro
• IS N° 54: Uso del freno de estacionamiento en flota CAF 6000
• IS N° 57: Protocolo para el acople de formaciones averiadas

6. Operativa y Señalamiento
• IS N° 3: Normativa para la circulación en modo Aislado Total (AT)
• IS N° 27: Circulación en modo "Aislado Limitado" (AL) Supervisores de P.C.O.
• IS N° 29: Utilización de comando "Tren Directo"
• IS N° 37: Tablero de indicación de destino

7. Operativa y Seguridad
• IS N° 36: Obligaciones del Guarda durante el servicio
• IS N° 38: Anuncios del personal del tren hacia los pasajeros a través del audio interno

8. Mantenimiento, Servicio y Pruebas
• IS N° 5: Procedimiento para realizar las pruebas de Zonas de Cambios con un Tren
• IS N° 15: Ingreso y operación en Estaciones Terminales
• IS N° 20: Pruebas de trenes equipados con ATP fuera del horario del servicio comercial
• IS N° 34: Zona de ocupación especial de vía para el mantenimiento o pruebas programadas

9. Material Rodante, Mantenimiento y Emergencias
• IS N° 18: Accionamiento del grifo de la electro-válvula EMV-2
• IS N° 23: Emergencia de Puertas (Coches Mitsubishi)
• IS N° 44: Acciones a tomar cuando se enciende OLR en flota Mitsubishi
• IS N° 45: Ninguna puerta abre - Trenes Mitsubishi
• IS N° 48: Acciones a tomar cuando BP no carga - Coches Mitsubishi
• IS N° 49: Falla de arranque - Coches Mitsubishi
• IS N° 51: Anulación del circuito de enclavamiento de puertas

10. Emergencias, Comunicaciones y Señalamiento
• IS N° 4: Señal de "Orden a 10 Km/h"
• IS N° 10: Comunicaciones con el PCO
• IS N° 11: Falta de iluminación en estaciones
• IS N° 39: Plan de emergencia para operar el servicio de trenes ante la interrupción del sistema Tierra - Tren
• IS N° 40: Procedimiento a cumplir ante una señal semi-automática a peligro
• IS N° 55: Pérdida de código de ATP en marcha

11. Seguridad, Infraestructura y Normativa General
• IS N° 2: Circulación de tren escuela en líneas con ATP
• IS N° 6: Revisión de elementos del tren para la puesta en servicio (check list)
• IS N° 7: Normativas para viajar en cabina
• IS N° 9: Ingreso de personal de Emova al túnel en horarios de servicio de trenes
• IS N° 12: Intento de suicidio o persona caída en las vías
• IS N° 22: Utilización de alimentadores "Puente T" entre Lacroze y Alem
• IS N° 26: Sistema Tierra-Tren
• IS N° 28: Procedimiento para el traslado de hinchadas y/o grupos numerosos
• IS N° 30: Sistema de Señales ALSTOM Función Liberación del Seguido de la Ocupación
• IS N° 31: Enclavamiento de puertas coches Mitsubishi
• IS N° 33: Comunicaciones Especiales
• IS N° 42: Detector de Tensión en el Tercer Riel
• IS N° 43: Comportamiento durante el viaje al Personal de Guardas
• IS N° 46: Acciones a tomar ante un principio de incendio
• IS N° 52: Procedimiento ante la evacuación de un tren en túnel
• IS N° 53: Protocolo ante presencia de humo en estación o túnel
• IS N° 56: Notificación de objetos extraños o anomalías en vía
• IS N° 58: Normas de seguridad para trabajos en vía con tensión"""

SUBMENUS_IS_POR_CATEGORIA = {
    "1": """1. Operativa y Conducción - Seleccioná una opción:

1 - IS N° 17: Marcas de Centro de Vías
2 - IS N° 19: Velocidades de circulación
3 - IS N° 41: Cambio de cabina en cabecera
4 - IS N° 47: Cambio de cabina en cabeceras - Coches Mitsubishi""",

    "2": """2. Operativa y Comunicaciones - Seleccioná una opción:

1 - IS N° 1: Ubicación del guarda y utilización del sistema Tierra - Tren en situaciones especiales""",

    "3": """3. Operativa y Emergencias - Seleccioná una opción:

1 - IS N° 25: Retorno de un tren a la estación anterior
2 - IS N° 50: Normas para conducción desde cabina de cola
3 - IS N° 61: Evacuación de formaciones en estaciones cerradas por obra""",

    "4": """4. Operativa y Maniobras - Seleccioná una opción:

1 - IS N° 8: Maniobras que afecten a las vías de servicio
2 - IS N° 13: Cambio de Maniobras en caso de Emergencia o por Razones Operativas
3 - IS N° 14: Maniobras con cambio de cabina Conductores Especializados
4 - IS N° 24: Operatoria de cambios Taller Urquiza
5 - IS N° 32: Maniobras de contramano""",

    "5": """5. Operativa y Material Rodante - Seleccioná una opción:

1 - IS N° 16: Movimiento de Vehículos de gran porte
2 - IS N° 21: Traslado de trenes de línea B al Ferrocarril Urquiza y viceversa
3 - IS N° 35: Accionamiento de puertas con temporizador y aviso sonoro
4 - IS N° 54: Uso del freno de estacionamiento en flota CAF 6000
5 - IS N° 57: Protocolo para el acople de formaciones averiadas""",

    "6": """6. Operativa y Señalamiento - Seleccioná una opción:

1 - IS N° 3: Normativa para la circulación en modo Aislado Total (AT)
2 - IS N° 27: Circulación en modo "Aislado Limitado" (AL) Supervisores de P.C.O.
3 - IS N° 29: Utilización de comando "Tren Directo"
4 - IS N° 37: Tablero de indicación de destino""",

    "7": """7. Operativa y Seguridad - Seleccioná una opción:

1 - IS N° 36: Obligaciones del Guarda durante el servicio
2 - IS N° 38: Anuncios del personal del tren hacia los pasajeros a través del audio interno""",

    "8": """8. Mantenimiento, Servicio y Pruebas - Seleccioná una opción:

1 - IS N° 5: Procedimiento para realizar las pruebas de Zonas de Cambios con un Tren
2 - IS N° 15: Ingreso y operación en Estaciones Terminales
3 - IS N° 20: Pruebas de trenes equipados con ATP fuera del horario del servicio comercial
4 - IS N° 34: Zona de ocupación especial de vía para el mantenimiento o pruebas programadas""",

    "9": """9. Material Rodante, Mantenimiento y Emergencias - Seleccioná una opción:

1 - IS N° 18: Accionamiento del grifo de la electro-válvula EMV-2
2 - IS N° 23: Emergencia de Puertas (Coches Mitsubishi)
3 - IS N° 44: Acciones a tomar cuando se enciende OLR en flota Mitsubishi
4 - IS N° 45: Ninguna puerta abre - Trenes Mitsubishi
5 - IS N° 48: Acciones a tomar cuando BP no carga - Coches Mitsubishi
6 - IS N° 49: Falla de arranque - Coches Mitsubishi
7 - IS N° 51: Anulación del circuito de enclavamiento de puertas""",

    "10": """10. Emergencias, Comunicaciones y Señalamiento - Seleccioná una opción:

1 - IS N° 4: Señal de "Orden a 10 Km/h"
2 - IS N° 10: Comunicaciones con el PCO
3 - IS N° 11: Falta de iluminación en estaciones
4 - IS N° 39: Plan de emergencia para operar el servicio de trenes ante la interrupción del sistema Tierra - Tren
5 - IS N° 40: Procedimiento a cumplir ante una señal semi-automática a peligro
6 - IS N° 55: Pérdida de código de ATP en marcha""",

    "11": """11. Seguridad, Infraestructura y Normativa General - Seleccioná una opción:

1 - IS N° 2: Circulación de tren escuela en líneas con ATP
2 - IS N° 6: Revisión de elementos del tren para la puesta en servicio (check list)
3 - IS N° 7: Normativas para viajar en cabina
4 - IS N° 9: Ingreso de personal de Emova al túnel en horarios de servicio de trenes
5 - IS N° 12: Intento de suicidio o persona caída en las vías
6 - IS N° 22: Utilización de alimentadores "Puente T" entre Lacroze y Alem
7 - IS N° 26: Sistema Tierra-Tren
8 - IS N° 28: Procedimiento para el traslado de hinchadas y/o grupos numerosos
9 - IS N° 30: Sistema de Señales ALSTOM Función Liberación del Seguido de la Ocupación
10 - IS N° 31: Enclavamiento de puertas coches Mitsubishi
11 - IS N° 33: Comunicaciones Especiales
12 - IS N° 42: Detector de Tensión en el Tercer Riel
13 - IS N° 43: Comportamiento durante el viaje al Personal de Guardas
14 - IS N° 46: Acciones a tomar ante un principio de incendio
15 - IS N° 52: Procedimiento ante la evacuación de un tren en túnel
16 - IS N° 53: Protocolo ante presencia de humo en estación o túnel
17 - IS N° 56: Notificación de objetos extraños o anomalías en vía
18 - IS N° 58: Normas de seguridad para trabajos en vía con tensión"""
}

MAPEO_OPCIONES_IS = {
    "1": {"1": "17", "2": "19", "3": "41", "4": "47"},
    "2": {"1": "1"},
    "3": {"1": "25", "2": "50", "3": "61"},
    "4": {"1": "8", "2": "13", "3": "14", "4": "24", "5": "32"},
    "5": {"1": "16", "2": "21", "3": "35", "4": "54", "5": "57"},
    "6": {"1": "3", "2": "27", "3": "29", "4": "37"},
    "7": {"1": "36", "2": "38"},
    "8": {"1": "5", "2": "15", "3": "20", "4": "34"},
    "9": {"1": "18", "2": "23", "3": "44", "4": "45", "5": "48", "6": "49", "7": "51"},
    "10": {"1": "4", "2": "10", "3": "11", "4": "39", "5": "40", "6": "55"},
    "11": {"1": "2", "2": "6", "3": "7", "4": "9", "5": "12", "6": "22", "7": "26", "8": "28", "9": "30", "10": "31", "11": "33", "12": "42", "13": "43", "14": "46", "15": "52", "16": "53", "17": "56", "18": "58"}
}

# --- LECTURA Y BÚSQUEDA EN EL PDF DE INSTRUCCIONES DE SERVICIO ---

def buscar_instruccion_en_pdf(num_is):
    if not os.path.exists(PDF_PATH):
        return f"Instrucción de Servicio N° {num_is}\n\n(No se encontró el archivo Instrucciones_de_servicio.pdf en la raíz del proyecto)."

    try:
        reader = PdfReader(PDF_PATH)
        texto_completo = ""
        for i, page in enumerate(reader.pages):
            t = page.extract_text() or ""
            texto_completo += f"\n--- PAGINA {i+1} ---\n" + t

        # Patrón para localizar el inicio de la instrucción solicitada (Ejemplo: IS N° 17, IS N°17, IS 17)
        pattern = rf"(IS\s*N[°º]?\s*{num_is}\b|INSTRUCCION\s*DE\s*SERVICIO\s*N[°º]?\s*{num_is}\b)"
        matches = list(re.finditer(pattern, texto_completo, re.IGNORECASE))

        if not matches:
            return f"Se seleccionó la IS N° {num_is}, pero no se localizó la sección exacta dentro del PDF."

        inicio = matches[0].start()
        # Cortamos un fragmento representativo (~1800 caracteres) desde el inicio encontrado
        contenido = texto_completo[inicio:inicio + 1800].strip()

        # Si el fragmento incluye el inicio de otra IS posterior, recortamos hasta ese punto
        siguiente_is = re.search(r"\n\s*(IS\s*N[°º]?\s*\d+|INSTRUCCION\s*DE\s*SERVICIO\s*N[°º]?\s*\d+)", contenido[50:], re.IGNORECASE)
        if siguiente_is:
            contenido = contenido[:50 + siguiente_is.start()].strip()

        return contenido

    except Exception as e:
        return f"Error al leer el archivo PDF: {str(e)}"

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
    if modelo == "Mitsubishi" and normalize_text(titulo_buscado) == normalize_text("MPI sus funciones"):
        images = load_imagenes_json()
        for img in images:
            if img.get("archivo") == "mitsu_46_mpi_funciones.jpg":
                titulo_limpio = img.get("titulo", "MPI sus funciones")
                desc = img.get("descripcion", "")
                text_out = f"{titulo_limpio}\n\n{desc}".strip() if desc else titulo_limpio
                return text_out, "mitsu_46_mpi_funciones.jpg"

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

    # --- MENÚ PRINCIPAL ---
    if estado_actual == "MENU_PRINCIPAL":
        if msg_clean == "1":
            USER_STATES[user_id] = "MENU_MITSUBISHI"
            return MENU_MITSUBISHI, "MENU_MITSUBISHI", None, False
        elif msg_clean == "2":
            USER_STATES[user_id] = "MENU_CAF"
            return MENU_CAF6000, "MENU_CAF", None, False
        elif msg_clean == "3":
            USER_STATES[user_id] = "IS_CATEGORIAS"
            return MENU_IS_CATEGORIAS, "IS_CATEGORIAS", None, False
        elif msg_clean == "4":
            USER_STATES[user_id] = "INICIO"
            return TEXTO_POR_QUE_PACO, "INICIO", None, True
        else:
            return f"Opción no válida.\n\n{MENU_INICIAL}", "MENU_PRINCIPAL", None, False

    # --- NAVEGACIÓN OPCIÓN 3: INSTRUCCIONES DE SERVICIO ---
    if estado_actual == "IS_CATEGORIAS":
        if msg_clean in SUBMENUS_IS_POR_CATEGORIA:
            USER_STATES[user_id] = f"IS_SUBCAT_{msg_clean}"
            return SUBMENUS_IS_POR_CATEGORIA[msg_clean], f"IS_SUBCAT_{msg_clean}", None, False
        else:
            return f"Opción no válida.\n\n{MENU_IS_CATEGORIAS}", "IS_CATEGORIAS", None, False

    if estado_actual.startswith("IS_SUBCAT_"):
        cat_num = estado_actual.replace("IS_SUBCAT_", "")
        mapeo_subcat = MAPEO_OPCIONES_IS.get(cat_num, {})
        if msg_clean in mapeo_subcat:
            num_is = mapeo_subcat[msg_clean]
            contenido_is = buscar_instruccion_en_pdf(num_is)
            USER_STATES[user_id] = "INICIO"
            return contenido_is, "INICIO", None, True
        else:
            submenu_texto = SUBMENUS_IS_POR_CATEGORIA.get(cat_num, MENU_IS_CATEGORIAS)
            return f"Opción no válida.\n\n{submenu_texto}", estado_actual, None, False

    # --- MENÚ MITSUBISHI ---
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

    # --- MITSUBISHI: CATEGORÍAS CON IMÁGENES ---
    if estado_actual == "MITSU_CAT4":
        if msg_clean in MAPA_CAT4:
            titulo = MAPA_CAT4[msg_clean]
            texto_final, archivo = obtener_detalles_imagen("Mitsubishi", titulo)
            USER_STATES[user_id] = "INICIO"
            return texto_final, "INICIO", archivo, True
        else:
            return f"Opción no válida.\n\n{SUBMENU_MITSU_CAT4}", "MITSU_CAT4", None, False

    if estado_actual == "MITSU_CAT5":
        if msg_clean in MAPA_CAT5:
            titulo = MAPA_CAT5[msg_clean]
            texto_final, archivo = obtener_detalles_imagen("Mitsubishi", titulo)
            USER_STATES[user_id] = "INICIO"
            return texto_final, "INICIO", archivo, True
        else:
            return f"Opción no válida.\n\n{SUBMENU_MITSU_CAT5}", "MITSU_CAT5", None, False

    if estado_actual == "MITSU_CAT6":
        if msg_clean in MAPA_CAT6:
            titulo = MAPA_CAT6[msg_clean]
            texto_final, archivo = obtener_detalles_imagen("Mitsubishi", titulo)
            USER_STATES[user_id] = "INICIO"
            return texto_final, "INICIO", archivo, True
        else:
            return f"Opción no válida.\n\n{SUBMENU_MITSU_CAT6}", "MITSU_CAT6", None, False

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

        es_novedad_o_libre = not pregunta.strip().isdigit() and pregunta.strip().lower() not in ["hola", "inicio", "menu", "reset", "0"]
        if es_novedad_o_libre and es_respuesta_final:
            respuesta_texto = pregunta

        host_url = request.host_url.rstrip('/')
        if host_url.startswith("http://"):
            host_url = host_url.replace("http://", "https://", 1)

        imagen_url = f"{host_url}/images/{archivo_imagen}" if archivo_imagen else None

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
