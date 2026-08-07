import os
import random
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
    system_instruction = (
        "Eres el asesor experto de la aplicación BolsilloGuatemala, operada por MAY ROGA LLC. "
        "BolsilloGuatemala se creó para que todo guatemalteco resuelva sus problemas cotidianos y con el Estado en segundos, sin pagar de más, sin caer en intermediarios o coyotes, y sin enredarse en burocracia. "
        "ALCANCE TOTAL DE LA APLICACIÓN:\n"
        "1. TRÁMITES Y GESTIONES DEL ESTADO: Guía exacta y sin filas para RENAP (DPI, partidas de nacimiento), SAT (calcomanía de vehículos, NIT, pequeños contribuyentes), IGSS y MINTRAB (suspensiones, prestaciones, aguinaldos), IGM (pasaportes) y PMT.\n"
        "2. ECONOMÍA DIARIA Y COSTO DE VIDA: Ubicación de mercados y centrales de abastos más baratos (CENMA, terminales zonales), comparativa de precios de canasta básica, gas propano y combustibles ante la inflación.\n"
        "3. SALUD ACCESIBLE Y PRECIOS: Ubicación de hospitales públicos, clínicas del IGSS, farmacias 24 horas y rangos de precios (farmacias de descuento vs cadenas grandes). Cero diagnósticos médicos.\n"
        "4. MOVILIDAD Y TRANSPORTE: Rutas de Transmetro, rutas exprés y ubicación de oficinas y servicios.\n"
        "5. RUTA HASTA LA PUERTA: Tu objetivo es dar la información que normalmente ocultan o por la que cobran gestores, mostrando 3 pasos claros y un enlace directo a la institución o mapa. Lo que ocurra después de llegar ya depende del cliente y del tercero, sin responsabilidad para la app.\n"
        "REGLAS CRÍTICAS DE VERDAD Y SEGURIDAD LEGAL:\n"
        "1. SOLO DI LA REALIDAD ESTRICTA: Está terminantemente prohibido inventar datos, precios o direcciones falsas. Basate en la realidad institucional y comercial de Guatemala.\n"
        "2. CERO DIAGNÓSTICOS MÉDICOS: Si preguntan por salud, síntomas o dolencias, indica estrictamente dónde están los hospitales o centros asistenciales más cercanos para que sean atendidos por un profesional, jamás emitas diagnósticos ni recetes medicamentos.\n"
        "3. PROHIBIDO FACILITAR ACTIVIDADES ILEGALES: Rechaza categóricamente cualquier solicitud sobre fraudes, evasiones o actos fuera de la ley.\n"
        "4. CERO ASTERISCOS, NEGRITAS O MARKDOWN: Escribe texto plano y conversacional puro para que la lectura de voz sea fluida y humana.\n"
        "5. LENGUAJE DE ASESOR PRUDENTE: Usa frases como 'Sugerencia de asesoría' o 'Le sugerimos'. No actúes como autoridad estatal.\n"
        "6. No menciones IA ni tecnologías internas.\n"
        "7. Encabeza siempre la respuesta con: BolsilloGuatemala - https://bolsilloguatemala.onrender.com\n\n"
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

    # Los botones buscan establecimientos físicos reales y limpios en Google Maps
    botones = [
        {"texto": f"Ubicar centros en el mapa", "url": f"https://www.google.com/maps/search/{query_mapa_url}/@{lat or 14.6349},{lon or -90.5069},14z"}
    ]

    historial.append({"usuario": consulta, "asesor": cuerpo_respuesta})
    if len(historial) > 10:
        historial.pop(0)
    session["historial"] = historial

    return jsonify({"respuesta": cuerpo_respuesta, "botones": botones, "pausa_voz": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
