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
    """
    Controla que el usuario no pase de 10 consultas al día.
    Se resetea automáticamente si cambia el día.
    """
    if session.get("is_dev"):
        return True # El modo desarrollador no tiene límite diario

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
    """
    Mantiene el texto limpio para el lector de voz.
    Elimina la URL del encabezado y cualquier dirección web del string 
    que va hacia el sintetizador de voz.
    """
    if not texto:
        return ""
    # Remueve URLs completas (http://, https://, www., etc.)
    texto_limpio = re.sub(r'https?://\S+|www\.\S+', '', texto)
    # Remueve menciones de dominios sueltos o nombres de la web tipo bolsilloguatemala.onrender.com
    texto_limpio = re.sub(r'\b[a-zA-Z0-9-]+\.(com|org|net|uy|edu|gov|mil|biz|info|mobi|name|aero|jobs|museum)\b', '', texto_limpio, flags=re.IGNORECASE)
    # Limpia espacios dobles o saltos sobrantes dejados por la limpieza
    texto_limpio = re.sub(r'\s+', ' ', texto_limpio).strip()
    return texto_limpio

def extraer_lugar_para_mapa(consulta):
    """
    Traduce la consulta del usuario a una categoría o lugar físico real de Google Maps
    para evitar enviar frases de síntomas, dolores o textos largos al mapa.
    """
    c = consulta.lower()
    
    # Salud y Emergencias
    if any(k in c for k in ["dolor", "orino", "ardor", "fiebre", "hospital", "clínica", "medico", "médico", "doctor", "emergencia", "salud", "enfermo", "farmacia", "pastilla", "receta"]):
        if "farmacia" in c:
            return "farmacia"
        return "hospital clinica centro de salud"
    
    # Trámites y Gobierno en Guatemala
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
    
    # Economía y Comercio
    if "mercado" in c or "cenma" in c or "canasta" in c or "comida" in c or "abastos" in c:
        return "mercado municipal central de abastos"
    if "gas" in c or "propano" in c or "combustible" in c or "gasolinera" in c:
        return "gasolinera"
    if "banco" in c or "dinero" in c or "pago" in c:
        return "banco"
        
    # Por defecto, si menciona un lugar específico o genérico, limpiamos conectores y usamos palabras clave
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
# --- MÓDULO DE PRECARGA Y ASISTENCIA LOCAL DE ALTA VELOCIDAD ---

@app.route("/ping", methods=["GET"])
def ping_server():
    """
    Ruta pública ultrarrápida para despertar el contenedor en Render
    en segundo plano desde el paywall, eliminando la latencia inicial.
    """
    return jsonify({"status": "ready"}), 200

# Diccionario estático unificado para consulta masiva de tránsito, multas y licencias en Guatemala
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

def limpiar_texto_para_voz(texto):
    """
    Función Helper de Audio Inmediata:
    Remueve asteriscos (*), numerales (#), guiones de viñetas (-) y URLs completas
    para que la síntesis de voz nativa procese un texto plano puro y fluido.
    """
    if not texto:
        return ""
    # Elimina URLs completas y dominios web
    texto_limpio = re.sub(r'https?://\S+|www\.\S+', '', texto)
    texto_limpio = re.sub(r'\b[a-zA-Z0-9-]+\.(com|org|net|uy|edu|gov|mil|biz|info|mobi|name|aero|jobs|museum)\b', '', texto_limpio, flags=re.IGNORECASE)
    # Elimina caracteres de formato Markdown (*, #, guiones de lista sueltos)
    texto_limpio = re.sub(r'[*#\-]', ' ', texto_limpio)
    # Limpia espacios dobles y saltos sobrantes
    texto_limpio = re.sub(r'\s+', ' ', texto_limpio).strip()
    return texto_limpio

@app.route("/tramites_locales", methods=["POST"])
def tramites_locales():
    """
    Ruta centralizada ultrarrápida protegida para resolver de forma instantánea 
    las consultas de tránsito, multas y licencias sin sobrecargar la IA.
    """
    if not verificar_acceso_pagado():
        return jsonify({"respuesta": f"BolsilloGuatemala - {URL_BASE_OFICIAL}\n\nSu acceso de asesoría ha concluido. Le sugerimos renovar su plan para continuar recibiendo orientación."}), 403

    data = request.get_json() or {}
    tipo = data.get("tipo", "general").lower().strip()

    # Selecciona la estructura adecuada según la categoría solicitada
    contenido = TRAMITES_TRANSITO_GUATEMALA.get(tipo, TRAMITES_TRANSITO_GUATEMALA["general"])
    
    cuerpo_respuesta = contenido["respuesta"]
    botones = contenido["botones"]
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

    # Incrementamos el contador de uso diario exitoso
    if not session.get("is_dev"):
        session["consultas_hoy"] = session.get("consultas_hoy", 0) + 1

    historial = session.get("historial", [])
    
    # LÓGICA: Extraemos el lugar físico real para Google Maps
    lugar_mapa = extraer_lugar_para_mapa(consulta)
    query_mapa_url = lugar_mapa.replace(" ", "+")

    # PROPOSITO, ALCANCE Y BLINDAJE LEGAL PARA MAY ROGA LLC EN GUATEMALA
    # Instrucciones del sistema optimizadas para BolsilloGuatemala: Cobertura universal con foco en el día a día
    system_instruction = (
        "ROL Y IDENTIDAD:\n"
        "Eres el asesor experto de la aplicación BolsilloGuatemala, operada por MAY ROGA LLC. "
        "Tu tono es el de un asesor prudente, empático, altamente resolutivo y muy profesional. Usa frases como 'Sugerencia de asesoría' o 'Le sugerimos'. "
        "No actúes como una autoridad estatal y jamás menciones que eres una IA ni tecnologías internas.\n\n"

        "MISIÓN CRÍTICA Y ENFOQUE SOCIAL UNIVERSAL:\n"
        "La aplicación debe IDENTIFICAR Y RESOLVER el problema del cliente directamente. Está prohibido mandarlo a investigar por su cuenta o responder con generalidades genéricas o evasivas. "
        "Si te piden un producto, servicio o trámite, tú debes darle la respuesta con datos concretos de Guatemala.\n"
        "1. ENFOQUE PRINCIPAL (SUPERVIVENCIA DIARIA): Resuelve necesidades cotidianas de todas las clases sociales (precios de alimentos, canasta básica, gas propano, combustibles, alquileres, casas y transporte), priorizando el ahorro y el cuidado de cada centavo para la mayoría que lo necesita (desde el agricultor en el interior hasta el habitante de la capital). Debes ofrecer SIEMPRE un mínimo de 3 opciones o alternativas físicas reales (ejemplo: mercados cantonales, centrales de abastos como CENMA o La Terminal, distribuidoras locales o supermercados) indicando rangos de precios estimados o zonas clave de abasto.\n"
        "2. ENFOQUE PREMIUM: Si un usuario con recursos económicos elevados consulta por opciones costosas, servicios exclusivos o zonas de alta gama (ejemplo: zonas residenciales exclusivas en la capital), guíalo de igual manera dándole las 3 mejores opciones premium sin escatimar información ni forzar el ahorro.\n"
        "3. TRÁMITES Y LUCHA CONTRA EL COYOTAJE: Guía paso a paso al usuario para resolver trámites en RENAP, SAT, IGSS, MINTRAB, IGM y PMT de forma directa y gratuita, evitando intermediarios o coyotes costosos.\n"
        "Tu objetivo es guiar con claridad, con geografía social real de Guatemala y llevar al usuario hasta la puerta de la solución. Lo que ocurra después de llegar ya depende del cliente y del prestador, sin responsabilidad para la app.\n\n"

        "REGLAS CRÍTICAS DE SEGURIDAD LEGAL:\n"
        "- SOLO REALIDAD ESTRICTA: Prohibido inventar comercios o direcciones inexistentes. Usa tu conocimiento del mercado guatemalteco real. Si no posees el precio exacto del día, ofrece el rango de costo estimado actual en el mercado de Guatemala (en quetzales) y menciona los puntos de venta o mercados más económicos.\n"
        "- CERO DIAGNÓSTICOS MÉDICOS: Indica dónde están los hospitales o clínicas del IGSS, pero JAMÁS emitas diagnósticos, opiniones médicas ni recetes medicamentos.\n"
        "- PROHIBIDO FACILITAR ACTIVIDADES ILEGALES: Rechaza categóricamente cualquier solicitud sobre fraudes, evasiones de impuestos, falsificación de documentos o actos fuera de la ley.\n\n"

        "REGLAS ESTRICTAS DE FORMATO (CRÍTICO PARA LECTOR DE VOZ):\n"
        "- ENCABEZADO OBLIGATORIO: Comienza siempre la primera línea de tu respuesta exactamente con la frase: BolsilloGuatemala - https://bolsilloguatemala.onrender.com\n"
        "- OTRAS URLS PROHIBIDAS: A excepción del encabezado obligatorio, no incluyas ninguna otra dirección web o enlace HTTP intermedio en el cuerpo del texto.\n"
        "- TEXTO PLANO PURO: Está TERMINANTEMENTE PROHIBIDO el uso de asteriscos (*), almohadillas (#), guiones de lista (- ) o cualquier formato Markdown. Escribe exclusivamente en párrafos limpios, directos y conversacionales para que el lector de voz digital de la app lea el texto de forma fluida, natural, humana y sin tropiezos.\n"
    )
    cuerpo_respuesta = None

    # INTENTO 1: USAR GEMINI (PRINCIPAL)
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

    # INTENTO 2: RESPALDO CON OPENAI (CHATGPT) SI GEMINI FALLA
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

    # RESPALDO FINAL DE EMERGENCIA SI AMBOS FALLAN
    if not cuerpo_respuesta:
        cuerpo_respuesta = (
            f"BolsilloGuatemala - {URL_BASE_OFICIAL}\n\n"
            f"Sugerencia de asesoría para su consulta sobre {consulta}:\n\n"
            "1. Identifique los requisitos y dependencias institucionales o comerciales oficiales en Guatemala.\n"
            "2. Verifique la documentación necesaria antes de realizar su gestión o compra.\n"
            "3. Utilice el mapa interactivo para ubicar la oficina, mercado o servicio más próximo."
        )

    # Texto exclusivo para que el sintetizador de voz (SpeechSynthesis) lea en voz alta de forma limpia, sin URLs ni webs
    voz_texto_limpio = limpiar_texto_para_voz(cuerpo_respuesta)

    # Los botones buscan establecimientos físicos reales y limpios en Google Maps
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
