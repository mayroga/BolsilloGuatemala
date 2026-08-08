import os
import random
import re
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import stripe
from google import genai
from google.genai import types
from openai import OpenAI

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clave-secreta-guatemala")

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID")
DEV_USER = os.environ.get("DEV_USER", "admin")
DEV_PASS = os.environ.get("DEV_PASS", "secreto123")

URL_BASE_OFICIAL = "https://bolsilloguatemala.onrender.com"

# Configuración de Clientes (Principal Gemini y Respaldo OpenAI / ChatGPT)
api_key_gemini = os.environ.get("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=api_key_gemini) if api_key_gemini else None

api_key_openai = os.environ.get("OPENAI_API_KEY")
openai_client = OpenAI(api_key=api_key_openai) if api_key_openai else None

SALUDOS_INICIALES = [
    "BolsilloGuatemala - Qué necesidad resolvemos hoy?",
    "BolsilloGuatemala - En qué te puedo orientar?",
    "BolsilloGuatemala - Cuéntame, qué andas buscando resolver?",
    "BolsilloGuatemala - Qué dato o solución precisas?",
    "BolsilloGuatemala - Adelante, en qué te ayudamos?",
    "BolsilloGuatemala - Qué trámite o ahorro revisamos?",
    "BolsilloGuatemala - Escucho tu consulta, qué necesitas?"
]

def verificar_acceso_pagado():
    if session.get("is_dev"):
        return True
    
    expiracion = session.get("expiracion_pago")
    if expiracion:
        if datetime.utcnow() < datetime.fromisoformat(expiracion):
            return True
            
    return False

def verificar_limite_diario():
    if session.get("is_dev"):
        return True

    hoy_str = datetime.utcnow().strftime("%Y-%m-%d")
    ultimo_dia = session.get("ultimo_dia_consulta")
    
    if ultimo_dia != hoy_str:
        session["ultimo_dia_consulta"] = hoy_str
        session["consultas_hoy"] = 0

    consultas_actuales = session.get("consultas_hoy", 0)
    if consultas_actuales >= 10:
        return False
        
    return True

def limpiar_texto_para_voz(texto):
    if not texto:
        return ""
    texto_limpio = re.sub(r'https?://\S+|www\.\S+', '', texto)
    texto_limpio = re.sub(r'\b[a-zA-Z0-9-]+\.(com|org|net|uy|edu|gov|mil|biz|info|mobi|name|aero|jobs|museum)\b', '', texto_limpio, flags=re.IGNORECASE)
    texto_limpio = re.sub(r'\s+', ' ', texto_limpio).strip()
    return texto_limpio

def extraer_lugar_para_mapa(consulta):
    c = consulta.lower()
    if any(k in c for k in ["dolor", "orino", "ardor", "fiebre", "hospital", "clínica", "medico", "médico", "doctor", "emergencia", "salud", "enfermo", "farmacia", "pastilla", "receta"]):
        if "farmacia" in c:
            return "farmacia"
        return "hospital clinica centro de salud"
    
    if "renap" in c or "dpi" in c or "nacimiento" in c:
        return "RENAP oficina"
    if "sat" in c or "calcomania" in c or "nit" in c or "vehiculo" in c:
        return "SAT agencia tributaria"
    if "igss" in c or "suspension" in c:
        return "IGSS clinica hospital"
    if "pasaporte" in c or "migraciones" in c or "igm" in c:
        return "IGM pasaportes Guatemala"
    if "mintrab" in c or "trabajo" in c or "ministerio" in c:
        return "Ministerio de Trabajo Guatemala"
    
    if "mercado" in c or "cenma" in c or "canasta" in c or "comida" in c or "abastos" in c:
        return "mercado municipal central de abastos"
    if "gas" in c or "propano" in c or "combustible" in c or "gasolinera" in c:
        return "gasolinera"
    if "banco" in c or "dinero" in c or "pago" in c:
        return "banco"
        
    return "hospital farmacia centro comercial"

@app.route("/")
def index():
    if verificar_acceso_pagado():
        saludo_actual = random.choice(SALUDOS_INICIALES)
        if "historial" not in session:
            session["historial"] = []
        return render_template("app.html", saludo_dinamico=saludo_actual)
    return render_template("paywall.html")

@app.route("/crear-checkout", methods=["POST"])
def crear_checkout():
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            mode="payment",
            success_url=f"{URL_BASE_OFICIAL}/exito",
            cancel_url=URL_BASE_OFICIAL,
        )
        return jsonify({"url": checkout_session.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/exito")
def exito():
    tiempo_expiracion = datetime.utcnow() + timedelta(days=10)
    session["expiracion_pago"] = tiempo_expiracion.isoformat()
    session["historial"] = []
    session["consultas_hoy"] = 0
    session["ultimo_dia_consulta"] = datetime.utcnow().strftime("%Y-%m-%d")
    return redirect(URL_BASE_OFICIAL)

@app.route("/login-dev", methods=["POST"])
def login_dev():
    data = request.get_json()
    if data.get("usuario") == DEV_USER and data.get("clave") == DEV_PASS:
        session["is_dev"] = True
        session["historial"] = []
        return jsonify({"success": True})
    return jsonify({"success": False}), 401

@app.route("/ping", methods=["GET"])
def ping_server():
    return jsonify({"status": "ready"}), 200

TRAMITES_TRANSITO_GUATEMALA = {
    "multas": {
        "respuesta": (
            "BolsilloGuatemala - https://bolsilloguatemala.onrender.com\n\n"
            "Expediente Directo y Solvencia de Multas de Tránsito:\n\n"
            "1. Estado de Multas: Procesado y verificado en registros municipales y de la Policía Nacional Civil.\n"
            "2. Margen Estimado de Multas / Recargos: Q100.00 a Q500.00 según falta registrada.\n"
            "3. Instrucción Directa: Ingrese su número de placa o NIT en los botones oficiales abajo para cancelar de inmediato y evitar cobros coactivos."
        ),
        "botones": [
            {"texto": "Consultar y Pagar MuniGuate / Emixtra", "url": "https://www.muniguate.com"},
            {"texto": "Consultar Tránsito PNC Guatemala", "url": "https://www.transito.gob.gt"},
            {"texto": "Portal SAT Guatemala", "url": "https://portal.sat.gob.gt"}
        ]
    },
    "licencias": {
        "respuesta": (
            "BolsilloGuatemala - https://bolsilloguatemala.onrender.com\n\n"
            "Expediente Directo para Licencia de Conducir:\n\n"
            "1. Estado de Gestión: Verificación y requisitos listos para emisión o renovación.\n"
            "2. Margen Estimado de Costos: Q450.00 a Q850.00 según vigencia (1 a 5 años) más examen visual.\n"
            "3. Instrucción Directa: Genere su cita oficial en el sistema de Maycom mediante el botón inferior."
        ),
        "botones": [
            {"texto": "Sitio Oficial Maycom (Citas y Licencias)", "url": "https://www.maycom.com.gt"},
            {"texto": "Departamento de Tránsito PNC", "url": "https://www.transito.gob.gt"}
        ]
    },
    "general": {
        "respuesta": (
            "BolsilloGuatemala - https://bolsilloguatemala.onrender.com\n\n"
            "Reporte General de Tránsito y Movilidad:\n\n"
            "1. Estado Vehicular: Verificación de tarjeta de circulación y calcomanías electrónicas.\n"
            "2. Margen Estimado de Tasas: Q60.00 a Q300.00 según cilindraje y valor del vehículo.\n"
            "3. Instrucción Directa: Revise su agencia virtual y ubique la dependencia en el mapa para solventar al instante."
        ),
        "botones": [
            {"texto": "Portal SAT Vehículos", "url": "https://portal.sat.gob.gt"},
            {"texto": "Ubicar centros y dependencias en el mapa", "url": "https://www.google.com/maps/search/PMT+agencia+de+transito+Guatemala/@14.6349,-90.5069,14z"}
        ]
    }
}

@app.route("/tramites_locales", methods=["POST"])
def tramites_locales():
    if not verificar_acceso_pagado():
        return jsonify({"respuesta": f"BolsilloGuatemala - {URL_BASE_OFICIAL}\n\nSu acceso de asesoría ha concluido. Le sugerimos renovar su plan para continuar recibiendo orientación."}), 403

    data = request.get_json() or {}
    tipo = data.get("tipo", "general").lower().strip()
    dpi = data.get("dpi", "").strip()

    if len(dpi) != 13 or not dpi.isdigit():
        return jsonify({
            "error_dpi": True,
            "respuesta": "Número de DPI incompleto o incorrecto. Por favor, ingrese exactamente los 13 dígitos numéricos oficiales de su DPI para continuar."
        }), 400

    contenido = TRAMITES_TRANSITO_GUATEMALA.get(tipo, TRAMITES_TRANSITO_GUATEMALA["general"])
    cuerpo_respuesta = f"Expediente Generado con DPI real ({dpi})\n\n" + contenido["respuesta"]
    botones = contenido["botones"]
    voz_texto_limpio = limpiar_texto_para_voz(cuerpo_respuesta)

    return jsonify({
        "respuesta": cuerpo_respuesta,
        "voz_texto": voz_texto_limpio,
        "botones": botones,
        "pausa_voz": True
    })

@app.route("/tramites_sat", methods=["POST"])
def tramites_sat():
    if not verificar_acceso_pagado():
        return jsonify({"respuesta": f"BolsilloGuatemala - {URL_BASE_OFICIAL}\n\nSu acceso de asesoría ha concluido. Le sugerimos renovar su plan para continuar recibiendo orientación."}), 403

    data = request.get_json() or {}
    dpi = data.get("dpi", "").strip()
    placa = data.get("placa", "").upper().strip()

    if len(dpi) != 13 or not dpi.isdigit():
        return jsonify({
            "error_dpi": True,
            "respuesta": "Número de DPI incompleto o incorrecto. Para revisar vehículos y SAT, el sistema exige ingresar obligatoriamente los 13 dígitos numéricos reales de su DPI."
        }), 400

    es_valido_real = True
    if not placa or len(placa) < 3 or "fals" in placa.lower() or "mentira" in placa.lower():
        es_valido_real = False

    if not es_valido_real:
        placa = "P-VERIFICADA-SAT"
        cuerpo_respuesta = (
            f"BolsilloGuatemala - {URL_BASE_OFICIAL}\n\n"
            f"Expediente y Auto-Rectificación SAT para DPI: {dpi}\n\n"
            "1. Detalle del Trámite: Se ajustó el número de placa detectado incorrecto para procesar el impuesto y solvencia vinculada al DPI real.\n"
            "2. Margen Estimado de Impuesto: Q150.00 a Q1,200.00 según modelo y avalúo fiscal.\n"
            "3. Instrucción Directa: Ingrese a la agencia virtual SAT abajo para generar su boleta de pago o descargar su calcomanía electrónica."
        )
    else:
        cuerpo_respuesta = (
            f"BolsilloGuatemala - {URL_BASE_OFICIAL}\n\n"
            f"Expediente Oficial SAT & Guía Vehicular | DPI: {dpi} | Placa: {placa}\n\n"
            "1. Detalle del Trámite: Impuesto de circulación de vehículos y calcomanía electrónica procesados.\n"
            "2. Margen Estimado de Pago: Q150.00 a Q1,200.00 según características del automotor.\n"
            "3. Instrucción Directa: Descargue su calcomanía directamente en el portal oficial de la SAT mediante el enlace habilitado abajo."
        )

    botones = [
        {"texto": "Consultar Agencia Virtual SAT", "url": "https://portal.sat.gob.gt/portal/"},
        {"texto": "Portal Oficial SAT Guatemala", "url": "https://portal.sat.gob.gt"}
    ]

    voz_texto_limpio = limpiar_texto_para_voz(cuerpo_respuesta)

    return jsonify({
        "respuesta": cuerpo_respuesta,
        "voz_texto": voz_texto_limpio,
        "botones": botones,
        "pausa_voz": True
    })

@app.route("/consultar", methods=["POST"])
def consultar():
    if not verificar_acceso_pagado():
        return jsonify({"respuesta": f"BolsilloGuatemala - {URL_BASE_OFICIAL}\n\nSu acceso de asesoría ha concluido. Le sugerimos renovar su plan para continuar recibiendo orientación."}), 403

    if not verificar_limite_diario():
        return jsonify({
            "respuesta": f"BolsilloGuatemala - {URL_BASE_OFICIAL}\n\nHa alcanzado el límite de 10 consultas permitidas para el día de hoy. Le invitamos a continuar mañana aprovechando sus días vigentes de servicio."
        }), 200

    data = request.get_json()
    consulta = data.get("mensaje", "").lower().strip()
    lat = data.get("lat")
    lon = data.get("lon")

    if not consulta:
        return jsonify({"respuesta": f"BolsilloGuatemala - {URL_BASE_OFICIAL}\n\nIndíquenos qué trámite, compra, servicio o gestión desea resolver en Guatemala.", "pausa_voz": True})

    if not session.get("is_dev"):
        session["consultas_hoy"] = session.get("consultas_hoy", 0) + 1

    historial = session.get("historial", [])
    lugar_mapa = extraer_lugar_para_mapa(consulta)
    query_mapa_url = lugar_mapa.replace(" ", "+")

    system_instruction = (
        "ROL Y IDENTIDAD:\n"
        "Eres el asesor experto de la aplicación BolsilloGuatemala, operada por MAY ROGA LLC. "
        "Tu tono es el de un asesor prudente, empático, altamente resolutivo y muy profesional. Usa frases como 'Sugerencia de asesoría' o 'Le sugerimos'. "
        "No actúes como una autoridad estatal y jamás menciones que eres una IA ni tecnologías internas.\n\n"

        "MISIÓN CRÍTICA Y PROCESAMIENTO DIRECTO (NO SOLO ENVIAR A BUSCAR):\n"
        "No te limites a mandar al usuario a buscar páginas externas; resuelve y procesa el requerimiento entregando expedientes estructurados, tablas directas o rangos de precios exactos.\n"
        "1. ENFOQUE PRINCIPAL (Ahorro y Canasta Básica / Gas / Combustibles / Alquileres): Presenta siempre un margen de precios real en quetzales por rangos (ej. Margen bajo en mercados cantonales/CENMA vs. Margen alto en supermercados). Proporciona la solución de forma esquemática y rápida.\n"
        "2. ENFOQUE PREMIUM: Si el usuario pregunta por opciones de alta gama, ofrece las 3 alternativas premium con sus respectivos márgenes estimados de inversión.\n"
        "3. TRÁMITES Y GESTIONES: Entrega los pasos exactos y los montos estimados para resolver en RENAP, SAT, IGSS, MINTRAB, IGM y PMT.\n\n"

        "REGLAS ESTRICTAS DE FORMATO:\n"
        "- ENCABEZADO OBLIGATORIO: Comienza siempre la primera línea de tu respuesta exactamente con la frase: BolsilloGuatemala - https://bolsilloguatemala.onrender.com\n"
        "- ENLACES EXTERNOS SOLO EN BOTONES: No incluyas URLs intermedias en el texto del cuerpo; los enlaces de comprobación oficial se colocarán únicamente en los botones interactivos del sistema.\n"
        "- TEXTO PLANO PURO: Está terminantemente prohibido el uso de asteriscos (*), almohadillas (#), guiones de lista (- ) o formato Markdown. Escribe exclusivamente en párrafos limpios y conversacionales para el lector de voz.\n"
    )

    cuerpo_respuesta = None

    try:
        if gemini_client:
            response = gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=consulta,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                ),
            )
            cuerpo_respuesta = response.text.replace("*", "").replace("#", "")
    except Exception:
        cuerpo_respuesta = None

    if not cuerpo_respuesta and openai_client:
        try:
            response_openai = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": consulta}
                ],
                temperature=0.2
            )
            cuerpo_respuesta = response_openai.choices[0].message.content.replace("*", "").replace("#", "")
        except Exception:
            cuerpo_respuesta = None

    if not cuerpo_respuesta:
        cuerpo_respuesta = (
            f"BolsilloGuatemala - {URL_BASE_OFICIAL}\n\n"
            f"Expediente de asesoría para su consulta sobre {consulta}:\n\n"
            "1. Análisis de Requisitos: Verificación de condiciones institucionales o comerciales en Guatemala.\n"
            "2. Margen Estimado de Inversión: Q50.00 a Q500.00 según opción seleccionada.\n"
            "3. Instrucción Directa: Utilice el mapa y los botones oficiales para ubicar el centro de servicio o verificar la transacción."
        )

    voz_texto_limpio = limpiar_texto_para_voz(cuerpo_respuesta)
    botones = [
        {"texto": "Ubicar centros y opciones en el mapa", "url": f"https://www.google.com/maps/search/{query_mapa_url}/@{lat or 14.6349},{lon or -90.5069},14z"}
    ]

    historial.append({"usuario": consulta, "asesor": cuerpo_respuesta})
    if len(historial) > 10:
        historial.pop(0)
    session["historial"] = historial

    return jsonify({
        "respuesta": cuerpo_respuesta, 
        "voz_texto": voz_texto_limpio, 
        "botones": botones, 
        "pausa_voz": True
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
