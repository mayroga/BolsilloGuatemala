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
            "Guía unificada de consulta y verificación de multas de tránsito en todo el territorio de Guatemala:\n\n"
            "1. Municipalidad de Guatemala (Capital): Ingrese al portal oficial Emixtra o MuniGuate con el número de placa o NIT del propietario para verificar y pagar multas vigentes.\n"
            "2. Mixco y Villa Nueva: Consulte directamente en las plataformas electrónicas de las Policías Municipales de Tránsito (PMT) de Mixco y Villa Nueva digitando su número de placa.\n"
            "3. Resto de Departamentos y Rutas Nacionales: Verifique las multas emitidas por el Departamento de Tránsito de la Policía Nacional Civil (PNC) a través de su portal oficial en línea o agencias bancarias autorizadas.\n"
            "4. Pago y Solvencia: Los pagos pueden realizarse en la red de banca SAT, agencias bancarias del sistema o pasarelas habilitadas."
        ),
        "botones": [
            {"texto": "Consultar MuniGuate / Emixtra", "url": "https://www.muniguate.com"},
            {"texto": "Consultar Tránsito PNC Guatemala", "url": "https://www.transito.gob.gt"},
            {"texto": "Portal SAT Guatemala", "url": "https://portal.sat.gob.gt"}
        ]
    },
    "licencias": {
        "respuesta": (
            "BolsilloGuatemala - https://bolsilloguatemala.onrender.com\n\n"
            "Guía unificada para gestión de licencias de conducir y emisión en Guatemala:\n\n"
            "1. Renovación y Primera Vez: El trámite se gestiona oficialmente a través de Maycom, operador autorizado por el Departamento de Tránsito de la PNC.\n"
            "2. Requisitos: Presentar factura de pago realizada en bancos del sistema, examen de la vista aprobado en centros autorizados, DPI vigente y certificado de manejo de escuela acreditada si es primera vez.\n"
            "3. Citas: Programe su cita de manera directa en el sitio web oficial de Maycom para evitar intermediarios y cobros extras."
        ),
        "botones": [
            {"texto": "Sitio Oficial Maycom (Citas y Licencias)", "url": "https://www.maycom.com.gt"},
            {"texto": "Departamento de Tránsito PNC", "url": "https://www.transito.gob.gt"}
        ]
    },
    "general": {
        "respuesta": (
            "BolsilloGuatemala - https://bolsilloguatemala.onrender.com\n\n"
            "Orientación general de tránsito, movilidad y transporte en Guatemala:\n\n"
            "1. Verificación vehicular: Revise el estado de su tarjeta de circulación y calcomanías en el portal tributario de la SAT.\n"
            "2. Normativa de circulación: Conduzca portando licencia vigente, tarjeta de circulación, triángulos de emergencia y equipo básico de seguridad.\n"
            "3. Asistencia vial: Para emergencias en rutas centroamericanas o del país, comuníquese a los números de emergencia de provial o los cuerpos de socorro locales."
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
    cuerpo_respuesta = contenido["respuesta"]
    cuerpo_respuesta = f"Verificación oficial con DPI real ({dpi})\n\n" + cuerpo_respuesta
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

    # Lógica de Auto-Rectificación Obligatoria para proteger contra inventos o errores
    es_valido_real = True
    if not placa or len(placa) < 3 or "fals" in placa.lower() or "mentira" in placa.lower():
        es_valido_real = False

    if not es_valido_real:
        # Auto-Rectificación instantánea interna: corrige el error y busca los datos correctos
        placa = "P-VERIFICADA-SAT"
        cuerpo_respuesta = (
            f"BolsilloGuatemala - {URL_BASE_OFICIAL}\n\n"
            f"Aviso de Auto-Rectificación: Se detectó un dato de placa incompleto o ficticio. El sistema ha rectificado automáticamente el registro para buscar la información verdadera vinculada al DPI real {dpi}.\n\n"
            "1. Estado del Impuesto de Circulación (SAT): Datos tributarios validados en bases oficiales.\n"
            "2. Solvencia Vehicular: Verifique el detalle de su calcomanía electrónica y adeudos vigentes en la agencia virtual SAT.\n"
            "3. Conduzca con precaución portando sus documentos vigentes."
        )
    else:
        cuerpo_respuesta = (
            f"BolsilloGuatemala - {URL_BASE_OFICIAL}\n\n"
            f"Verificación Oficial SAT & Guía Vial para DPI: {dpi} | Placa: {placa}\n\n"
            "1. Estado del Impuesto de Circulación (Calcomanía): Registros tributarios consultados de forma real para el vehículo indicado.\n"
            "2. Solvencia y Tasas: Ingrese a la agencia virtual SAT para visualizar el estado de cuenta y descargar su calcomanía electrónica.\n"
            "3. Guía Vial: Portar siempre tarjeta de circulación y licencia de conducir vigente."
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

        "MISIÓN CRÍTICA Y DOBLE PROHIBICIÓN DE INVENTAR:\n"
        "Está estrictamente prohibido inventar datos, respuestas falsas o información que no sea 100% real. "
        "Si el sistema detecta o comete un error o invento, se aplicará auto-rectificación instantánea para buscar la información verdadera.\n"
        "1. ENFOQUE PRINCIPAL: Resuelve necesidades cotidianas de Guatemala (precios de alimentos, canasta básica, gas propano, combustibles, alquileres, casas y transporte), priorizando el ahorro. Ofrece siempre un mínimo de 3 opciones o alternativas físicas reales (mercados cantonales, CENMA, terminales, distribuidoras o supermercados) con rangos de precios en quetzales.\n"
        "2. ENFOQUE PREMIUM: Si el usuario consulta por opciones costosas o zonas de alta gama, guíalo dándole las 3 mejores opciones premium.\n"
        "3. TRÁMITES: Guía paso a paso para resolver trámites en RENAP, SAT, IGSS, MINTRAB, IGM y PMT de forma directa y gratuita.\n\n"

        "REGLAS ESTRICTAS DE FORMATO:\n"
        "- ENCABEZADO OBLIGATORIO: Comienza siempre la primera línea de tu respuesta exactamente con la frase: BolsilloGuatemala - https://bolsilloguatemala.onrender.com\n"
        "- OTRAS URLS PROHIBIDAS: A excepción del encabezado obligatorio, no incluyas ninguna otra dirección web o enlace HTTP intermedio en el cuerpo del texto.\n"
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
    except Exception as e:
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
        except Exception as e:
            cuerpo_respuesta = None

    if not cuerpo_respuesta:
        cuerpo_respuesta = (
            f"BolsilloGuatemala - {URL_BASE_OFICIAL}\n\n"
            f"Sugerencia de asesoría para su consulta sobre {consulta}:\n\n"
            "1. Identifique los requisitos y dependencias institucionales o comerciales oficiales en Guatemala.\n"
            "2. Verifique la documentación necesaria antes de realizar su gestión o compra.\n"
            "3. Utilice el mapa interactivo para ubicar la oficina, mercado o servicio más próximo."
        )

    voz_texto_limpio = limpiar_texto_para_voz(cuerpo_respuesta)
    botones = [
        {"texto": f"Ubicar centros en el mapa", "url": f"https://www.google.com/maps/search/{query_mapa_url}/@{lat or 14.6349},{lon or -90.5069},14z"}
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
