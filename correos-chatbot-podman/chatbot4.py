import os
import re
import json
import threading
import subprocess
from datetime import datetime, timezone, timedelta
import uuid

import requests
from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from sentence_transformers import SentenceTransformer
import chromadb
from tqdm import tqdm

# pip install langdetect
from langdetect import detect, LangDetectException


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "correos-agbc-2026")
CORS(app)

# ─────────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────────
EMBEDDING_MODEL     = os.environ.get("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
LLM_MODEL           = os.environ.get("LLM_MODEL", "correos-bot")
DATA_FILE           = os.environ.get("DATA_FILE",       "data/correos_bolivia.txt")
SUCURSALES_FILE     = os.environ.get("SUCURSALES_FILE", "data/sucursales_contacto.json")
CHROMA_PATH         = os.environ.get("CHROMA_PATH",     "chroma_db")
CHUNK_SIZE          = int(os.environ.get("CHUNK_SIZE",          "600"))
BATCH_SIZE          = int(os.environ.get("BATCH_SIZE",          "500"))
OLLAMA_URL          = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_TIMEOUT      = int(os.environ.get("OLLAMA_TIMEOUT",      "600"))
N_RESULTADOS        = int(os.environ.get("N_RESULTADOS",         "3"))
MAX_HISTORIAL       = int(os.environ.get("MAX_HISTORIAL",        "6"))
HORAS_ACTUALIZACION = int(os.environ.get("HORAS_ACTUALIZACION", "24"))

# ─────────────────────────────────────────────
#  PATRONES DE SALUDO Y DESPEDIDA
# ─────────────────────────────────────────────
PATRON_SALUDO = re.compile(
    r"^(hola\b|holi\b|holis\b|buenas?\b|buenas?\s+(dias?|tardes?|noches?)"
    r"|hey\b|hi\b|hello\b|saludos|que\s+tal|como\s+estas|buen\s+dia"
    r"|привет|здравствуй|добрый\s+(день|вечер|утро)"
    r"|你好|您好|嗨"
    r"|ol[aá]\b|bom\s+dia|boa\s+(tarde|noite)"
    r"|bonjour|bonsoir|salut)",
    re.IGNORECASE,
)

PALABRAS_DESPEDIDA = [
    # Español
    "adios", "adiós", "chau", "chao", "hasta luego", "hasta pronto",
    "nos vemos", "gracias ya", "eso era todo", "eso es todo",
    "me voy", "hasta mañana", "ciao",
    # Inglés
    "bye", "goodbye", "see you", "farewell", "take care",
    # Portugués
    "tchau", "até logo", "até mais", "obrigado já",
    # Ruso
    "пока", "до свидания", "всего хорошего", "до встречи",
    # Chino
    "再见", "拜拜", "谢谢了",
    # Francés
    "au revoir", "à bientôt", "adieu",
]

ALIAS_CIUDADES = {
    "lpb"                    : "la paz",
    "cba"                    : "cochabamba",
    "cbba"                   : "cochabamba",
    "scz"                    : "santa cruz",
    "santa cruz de la sierra": "santa cruz",
    "trinidad"               : "beni",
    "cobija"                 : "pando",
    "potosí"                 : "potosi",
}

# ─────────────────────────────────────────────
#  MAPA langdetect → código interno
# ─────────────────────────────────────────────
LANG_MAP = {
    "es"   : "es",
    "en"   : "en",
    "pt"   : "pt",
    "fr"   : "fr",
    "zh-cn": "zh",
    "zh-tw": "zh",
    "ko"   : "zh",   # langdetect a veces confunde chino con coreano en textos cortos
    "ru"   : "ru",
}

IDIOMA_DEFAULT = "es"

# ─────────────────────────────────────────────
#  IDIOMAS
# ─────────────────────────────────────────────
IDIOMAS = {
    "es": {
        "nombre"       : "Español",
        "bienvenida"   : (
            "¡Hola! Bienvenido al asistente oficial de la Agencia Boliviana de Correos (AGBC). "
            "Puedo ayudarte con envíos, tarifas, sucursales, ubicaciones y más. ¿En qué puedo ayudarte hoy?"
        ),
        "saludo"       : (
            "¡Hola! Soy el asistente de Correos Bolivia. "
            "Puedo ayudarte con envíos, tarifas, sucursales y más. ¿En qué puedo ayudarte?"
        ),
        "despedida"    : (
            "Ha sido un placer ayudarte. Que tengas un excelente día. "
            "Recuerda que puedes visitarnos en correos.gob.bo. ¡Hasta pronto!"
        ),
        "sin_info"     : "No tengo esa información. Visita correos.gob.bo o llama al +591 22152423.",
        "instruccion"  : "Responde en español, de forma clara y amable.",
        "pedir_ciudad" : "Tenemos sucursales en: {ciudades}. ¿De cuál necesitas la ubicación?",
        "no_disponible": "No disponible",
    },
    "en": {
        "nombre"       : "English",
        "bienvenida"   : (
            "Hello! Welcome to the official assistant of the Bolivian Postal Agency (AGBC). "
            "I can help you with shipments, rates, branches, locations and more. How can I help you today?"
        ),
        "saludo"       : "Hello! I am the Correos Bolivia assistant. How can I help you?",
        "despedida"    : (
            "It was a pleasure helping you. Have a great day. "
            "Remember you can visit us at correos.gob.bo. Goodbye!"
        ),
        "sin_info"     : "I don't have that information. Visit correos.gob.bo or call +591 22152423.",
        "instruccion"  : "Respond in English, clearly and politely.",
        "pedir_ciudad" : "We have branches in: {ciudades}. Which city do you need the location for?",
        "no_disponible": "Not available",
    },
    "fr": {
        "nombre"       : "Français",
        "bienvenida"   : (
            "Bonjour! Bienvenue chez l'assistant officiel de l'Agence Bolivienne des Postes (AGBC). "
            "Je peux vous aider avec les envois, les tarifs, les succursales et plus encore. Comment puis-je vous aider?"
        ),
        "saludo"       : "Bonjour! Je suis l'assistant de Correos Bolivia. Comment puis-je vous aider?",
        "despedida"    : (
            "Ce fut un plaisir de vous aider. Bonne journée. "
            "N'oubliez pas de visiter correos.gob.bo. Au revoir!"
        ),
        "sin_info"     : "Je n'ai pas cette information. Visitez correos.gob.bo ou appelez le +591 22152423.",
        "instruccion"  : "Répondez en français, clairement et poliment.",
        "pedir_ciudad" : "Nous avons des succursales à: {ciudades}. Pour quelle ville avez-vous besoin de la localisation?",
        "no_disponible": "Non disponible",
    },
    "pt": {
        "nombre"       : "Português",
        "bienvenida"   : (
            "Olá! Bem-vindo ao assistente oficial da Agência Boliviana de Correios (AGBC). "
            "Posso ajudá-lo com envios, tarifas, agências, localizações e mais. Como posso ajudá-lo hoje?"
        ),
        "saludo"       : "Olá! Sou o assistente de Correos Bolivia. Como posso ajudá-lo?",
        "despedida"    : (
            "Foi um prazer ajudá-lo. Tenha um ótimo dia. "
            "Lembre-se de visitar correos.gob.bo. Até logo!"
        ),
        "sin_info"     : "Não tenho essa informação. Visite correos.gob.bo ou ligue para +591 22152423.",
        "instruccion"  : "Responda em português, de forma clara e amigável.",
        "pedir_ciudad" : "Temos agências em: {ciudades}. De qual cidade você precisa da localização?",
        "no_disponible": "Não disponível",
    },
    "zh": {
        "nombre"       : "中文",
        "bienvenida"   : (
            "您好！欢迎使用玻利维亚邮政局（AGBC）官方助手。"
            "我可以帮助您了解邮寄、费率、分支机构、位置等信息。请问有什么可以帮助您？"
        ),
        "saludo"       : "您好！我是玻利维亚邮政助手。有什么可以帮助您？",
        "despedida"    : (
            "很高兴为您服务。祝您有美好的一天。"
            "请记得访问 correos.gob.bo。再见！"
        ),
        "sin_info"     : "我没有该信息。请访问 correos.gob.bo 或致电 +591 22152423。",
        "instruccion"  : "请用中文回答，清晰友好。",
        "pedir_ciudad" : "我们在以下城市有分支机构：{ciudades}。您需要哪个城市的位置？",
        "no_disponible": "不可用",
    },
    "ru": {
        "nombre"       : "Русский",
        "bienvenida"   : (
            "Здравствуйте! Добро пожаловать в официальный помощник "
            "Боливийского почтового агентства (AGBC). "
            "Я могу помочь вам с отправлениями, тарифами, отделениями и местоположениями. "
            "Чем могу помочь?"
        ),
        "saludo"       : "Здравствуйте! Я помощник Correos Bolivia. Чем могу помочь?",
        "despedida"    : (
            "Был рад помочь. Хорошего дня! "
            "Не забудьте посетить наш сайт correos.gob.bo. До свидания!"
        ),
        "sin_info"     : "У меня нет этой информации. Посетите correos.gob.bo или позвоните +591 22152423.",
        "instruccion"  : "Отвечай на русском языке, чётко и вежливо.",
        "pedir_ciudad" : "У нас есть отделения в: {ciudades}. Какой город вас интересует?",
        "no_disponible": "Недоступно",
    },
}

# ─────────────────────────────────────────────
#  ESTADO GLOBAL
# ─────────────────────────────────────────────
estado_actualizacion = {
    "en_proceso"      : False,
    "ultima_vez"      : None,
    "proxima_vez"     : None,
    "ultimo_resultado": "Pendiente",
}
_lock_reindex = threading.Lock()
_coords_cache: dict = {}

scheduler  = None
embedder   = None
collection = None
SUCURSALES: list = []
historiales: dict = {}


# ─────────────────────────────────────────────
#  DETECCIÓN DE IDIOMA AUTOMÁTICA
# ─────────────────────────────────────────────

def detectar_idioma(texto: str) -> str:
    """
    Detecta el idioma del texto con langdetect.
    - Si el frontend envía 'lang', ese tiene prioridad (selector manual).
    - Textos < 4 chars son ambiguos → devuelve IDIOMA_DEFAULT.
    - Si langdetect falla → devuelve IDIOMA_DEFAULT.
    """
    texto_limpio = texto.strip()
    if len(texto_limpio) < 4:
        return IDIOMA_DEFAULT
    try:
        codigo = detect(texto_limpio)
        return LANG_MAP.get(codigo, IDIOMA_DEFAULT)
    except LangDetectException:
        return IDIOMA_DEFAULT


# ─────────────────────────────────────────────
#  HELPERS DE DATOS
# ─────────────────────────────────────────────

def limpiar_campo(valor: str) -> str:
    if not valor:
        return ""
    return re.sub(
        r"^(direcci[oó]n|contacto|tel[eé]fono|email|horario)\s*:\s*",
        "", valor, flags=re.I,
    ).strip()


def _nominatim_fallback(direccion: str, ciudad: str) -> dict | None:
    for query in [f"{direccion}, {ciudad}, Bolivia", f"{ciudad}, Bolivia"]:
        if query in _coords_cache:
            return _coords_cache[query]
        try:
            resp = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 1},
                headers={"User-Agent": "CorreosBoliviaBot/1.0 agbc@correos.gob.bo"},
                timeout=8,
            )
            data = resp.json()
            if data:
                coords = {"lat": float(data[0]["lat"]), "lng": float(data[0]["lon"])}
                if -23 < coords["lat"] < -9 and -70 < coords["lng"] < -57:
                    _coords_cache[query] = coords
                    return coords
        except Exception:
            pass
    return None


def cargar_sucursales_json() -> list:
    if not os.path.exists(SUCURSALES_FILE):
        print(f"⚠️  No se encontró {SUCURSALES_FILE}")
        return []
    with open(SUCURSALES_FILE, "r", encoding="utf-8") as f:
        sucursales = json.load(f)
    sin_coords = []
    for s in sucursales:
        s["direccion"] = limpiar_campo(s.get("direccion", ""))
        s["telefono"]  = limpiar_campo(s.get("telefono", ""))
        s["email"]     = limpiar_campo(s.get("email", ""))
        s["horario"]   = limpiar_campo(s.get("horario", ""))
        if not s.get("lat") or not s.get("lng"):
            sin_coords.append(s)
    if sin_coords:
        print(f"📍 {len(sin_coords)} sucursales sin coords → usando Nominatim...")
        for s in sin_coords:
            ciudad = re.sub(r"^(regional|oficina\s+central)\s*:\s*", "", s.get("nombre", "").lower()).strip()
            coords = _nominatim_fallback(s.get("direccion", ""), ciudad)
            if coords:
                s["lat"] = coords["lat"]
                s["lng"] = coords["lng"]
                print(f"   🌍 {ciudad}: {coords}")
            else:
                print(f"   ⚠️  Sin coords: {ciudad}")
    con_coords = sum(1 for s in sucursales if s.get("lat") and s.get("lng"))
    print(f"✅ {len(sucursales)} sucursales | {con_coords} con coordenadas")
    return sucursales


def sucursal_a_texto(s: dict) -> str:
    partes = [f"Sucursal: {s.get('nombre', '')}"]
    if s.get("direccion"): partes.append(f"Dirección: {s['direccion']}")
    if s.get("telefono"):  partes.append(f"Teléfono: {s['telefono']}")
    if s.get("email"):     partes.append(f"Email: {s['email']}")
    if s.get("horario"):   partes.append(f"Horario: {s['horario']}")
    return "\n".join(partes)


def generar_maps_url(lat: float, lng: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"


def _cargar_secciones(chunks: list, chunk_ids: list) -> int:
    total = 0
    try:
        if os.path.exists("data/secciones_home.json"):
            with open("data/secciones_home.json", "r", encoding="utf-8") as f:
                secciones = json.load(f)
            for nombre_sec, items in secciones.items():
                if items:
                    texto = f"## {nombre_sec}\n\n" + "\n".join(f"- {it}" for it in items)
                    chunks.append(texto)
                    chunk_ids.append(f"sec_{nombre_sec.replace(' ', '_')}")
                    total += 1
            print(f"📋 {total} secciones indexadas")
    except Exception as e:
        print(f"⚠️  Secciones: {e}")
    return total


# ─────────────────────────────────────────────
#  REINDEXADO
# ─────────────────────────────────────────────

def _reindexar() -> bool:
    global SUCURSALES
    chunks, chunk_ids = [], []

    if not os.path.exists(DATA_FILE):
        print("⚠️  correos_bolivia.txt no encontrado")
        return False

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        texto = f.read()
    idx, start = 0, 0
    while start < len(texto):
        chunks.append(texto[start:start + CHUNK_SIZE])
        chunk_ids.append(f"txt_{idx}")
        start += CHUNK_SIZE - 100
        idx   += 1
    print(f"   → {idx} chunks de texto")

    SUCURSALES = cargar_sucursales_json()
    for i, s in enumerate(SUCURSALES):
        chunks.append(sucursal_a_texto(s))
        chunk_ids.append(f"suc_{i}")

    _cargar_secciones(chunks, chunk_ids)

    if not chunks:
        return False

    try:
        todos = collection.get()
        if todos and todos.get("ids"):
            collection.delete(ids=todos["ids"])
    except Exception as e:
        print(f"   ⚠️  Limpieza: {e}")

    embeddings  = embedder.encode(chunks, show_progress_bar=False, batch_size=64)
    total_lotes = (len(chunks) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in tqdm(range(0, len(chunks), BATCH_SIZE), total=total_lotes, desc="Indexando"):
        collection.add(
            documents  = chunks[i:i + BATCH_SIZE],
            embeddings = embeddings[i:i + BATCH_SIZE].tolist(),
            ids        = chunk_ids[i:i + BATCH_SIZE],
        )
    print(f"✅ {len(chunks)} chunks indexados")
    return True


def actualizar_bd() -> None:
    global estado_actualizacion
    if not _lock_reindex.acquire(blocking=False):
        print("⏳ Actualización ya en proceso")
        return
    bolivia = timezone(timedelta(hours=-4))
    estado_actualizacion["en_proceso"] = True
    try:
        print(f"🔄 Iniciando actualización...")
        resultado = subprocess.run(
            ["python", "scraper.py"], capture_output=True, text=True, timeout=600,
        )
        if resultado.returncode != 0:
            msg = f"Scraper falló (código {resultado.returncode})"
            estado_actualizacion["ultimo_resultado"] = f"❌ {msg}"
            return
        exito = _reindexar()
        ahora = datetime.now(bolivia)
        if exito:
            estado_actualizacion["ultima_vez"]       = ahora.strftime("%d/%m/%Y %H:%M")
            estado_actualizacion["ultimo_resultado"] = "✅ Exitosa"
        else:
            estado_actualizacion["ultimo_resultado"] = "⚠️ Reindex falló"
    except subprocess.TimeoutExpired:
        estado_actualizacion["ultimo_resultado"] = "❌ Scraper timeout"
    except Exception as e:
        estado_actualizacion["ultimo_resultado"] = f"❌ {e}"
    finally:
        estado_actualizacion["en_proceso"] = False
        _lock_reindex.release()


# ─────────────────────────────────────────────
#  DETECCIÓN DE INTENCIÓN
# ─────────────────────────────────────────────

def es_saludo(texto: str) -> bool:
    return bool(PATRON_SALUDO.match(texto.strip()))


def es_despedida(texto: str) -> bool:
    return any(p in texto.lower().strip() for p in PALABRAS_DESPEDIDA)


def detectar_consulta_ubicacion(texto: str) -> dict | None:
    PALABRAS_UBICACION = [
        # Español
        "ubicacion", "ubicación", "donde", "dónde", "direccion", "dirección",
        "sucursal", "oficina", "mapa", "maps", "coordenadas",
        "como llego", "como llegar", "donde queda", "donde se encuentra",
        # Inglés
        "location", "address", "branch", "where is", "how to get",
        # Portugués
        "localização", "endereço", "agência", "onde fica",
        # Ruso
        "адрес", "где находится", "местоположение", "отделение",
        # Chino
        "地址", "位置", "在哪", "分支机构",
        # Francés
        "adresse", "succursale", "où se trouve",
    ]
    texto_lower = texto.lower()
    for alias, ciudad_real in ALIAS_CIUDADES.items():
        if alias in texto_lower:
            texto_lower = texto_lower.replace(alias, ciudad_real)
    if not any(p in texto_lower for p in PALABRAS_UBICACION):
        return None
    for s in SUCURSALES:
        nombre_lower    = s.get("nombre", "").lower()
        ciudad_sucursal = re.sub(r"^(regional|oficina\s+central)\s*:\s*", "", nombre_lower).strip()
        if ciudad_sucursal and ciudad_sucursal in texto_lower:
            return s
    return {"ciudad": None}


# ─────────────────────────────────────────────
#  OLLAMA
# ─────────────────────────────────────────────

def llamar_ollama(mensajes: list) -> str:
    payload = {
        "model"   : LLM_MODEL,
        "messages": mensajes,
        "stream"  : False,
        "options" : {"num_predict": 200, "temperature": 0, "num_ctx": 1500},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def limpiar_respuesta(texto: str) -> str:
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL)
    texto = texto.replace("**", "").replace("* ", "• ").replace("*", "")
    return texto.strip()


# ─────────────────────────────────────────────
#  HELPERS DE SESIÓN
# ─────────────────────────────────────────────

def get_sid() -> str:
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
    return session["session_id"]


def get_hora_bolivia() -> dict:
    bolivia    = timezone(timedelta(hours=-4))
    ahora      = datetime.now(bolivia)
    dias_es    = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    hora_float = ahora.hour + ahora.minute / 60
    if ahora.weekday() < 5:
        abierto = 8.5 <= hora_float < 18.5
        horario = "lunes a viernes de 8:30 a 18:30"
    elif ahora.weekday() == 5:
        abierto = 9.0 <= hora_float < 13.0
        horario = "sábados de 9:00 a 13:00"
    else:
        abierto = False
        horario = "cerrado los domingos"
    return {
        "fecha"  : ahora.strftime("%d/%m/%Y"),
        "hora"   : ahora.strftime("%H:%M"),
        "dia"    : dias_es[ahora.weekday()],
        "abierto": abierto,
        "horario": horario,
        "estado" : "ABIERTO ✅" if abierto else "CERRADO ❌",
    }


# ─────────────────────────────────────────────
#  RUTAS
# ─────────────────────────────────────────────

@app.route("/")
def serve_chat():
    get_sid()
    return send_from_directory(".", "chatbot.html")


@app.route("/widget.js")
def serve_widget():
    return send_from_directory(".", "widget.js", mimetype="application/javascript")


@app.route("/api/welcome", methods=["GET"])
def welcome():
    lang = request.args.get("lang", IDIOMA_DEFAULT)
    if lang not in IDIOMAS:
        lang = IDIOMA_DEFAULT
    return jsonify({"response": IDIOMAS[lang]["bienvenida"], "lang": lang})


@app.route("/api/chat", methods=["POST"])
def chat():
    sid = get_sid()
    if sid not in historiales:
        historiales[sid] = []

    data = request.get_json(silent=True) or {}
    if "message" not in data:
        return jsonify({"error": "Falta el campo message"}), 400

    pregunta = data["message"].strip()
    if not pregunta:
        return jsonify({"error": "Pregunta vacía"}), 400

    # ── Detección de idioma
    # Prioridad: lang explícito del frontend > detección automática del texto
    lang_forzado = data.get("lang")
    if lang_forzado and lang_forzado in IDIOMAS:
        lang = lang_forzado
    else:
        lang = detectar_idioma(pregunta)

    t = IDIOMAS[lang]

    # ── 1. Saludo → respuesta inmediata sin Ollama
    if es_saludo(pregunta):
        return jsonify({"response": t["saludo"], "lang": lang})

    # ── 2. Despedida
    if es_despedida(pregunta):
        historiales.pop(sid, None)
        return jsonify({"response": t["despedida"], "despedida": True, "lang": lang})

    # ── 3. ¿Solo nombre de ciudad?
    pregunta_norm = ALIAS_CIUDADES.get(pregunta.lower().strip(), pregunta.lower().strip())
    geo = None
    for s in SUCURSALES:
        nombre_lower    = s.get("nombre", "").lower()
        ciudad_sucursal = re.sub(r"^(regional|oficina\s+central)\s*:\s*", "", nombre_lower).strip()
        if ciudad_sucursal and (pregunta_norm == ciudad_sucursal or pregunta_norm in ciudad_sucursal):
            geo = s
            break

    # ── 4. Detectar intención de ubicación
    if geo is None:
        geo = detectar_consulta_ubicacion(pregunta)

    # ── 5. Responder con tarjeta de sucursal
    if geo is not None:
        if geo.get("ciudad") is None and "nombre" not in geo:
            nombres = " | ".join(s.get("nombre", "") for s in SUCURSALES)
            return jsonify({
                "response": t["pedir_ciudad"].format(ciudades=nombres, cidades=nombres),
                "lang": lang,
            })

        lat      = geo.get("lat")
        lng      = geo.get("lng")
        maps_url = generar_maps_url(lat, lng) if lat and lng else None
        nd       = t["no_disponible"]
        texto_resp = (
            f"📍 {geo.get('nombre', '')}\n"
            f"Dirección : {geo.get('direccion') or nd}\n"
            f"Teléfono  : {geo.get('telefono') or nd}\n"
            f"Email     : {geo.get('email') or nd}\n"
            f"Horario   : {geo.get('horario') or nd}"
        )
        if maps_url:
            texto_resp += f"\nVer en mapa: {maps_url}"

        historiales[sid].extend([
            {"role": "user",      "content": pregunta},
            {"role": "assistant", "content": texto_resp},
        ])
        resp_json = {"response": texto_resp, "lang": lang}
        if lat and lng:
            resp_json["ubicacion"] = {
                "nombre"   : geo.get("nombre", ""),
                "direccion": geo.get("direccion", ""),
                "telefono" : geo.get("telefono", ""),
                "email"    : geo.get("email", ""),
                "horario"  : geo.get("horario", ""),
                "lat"      : lat,
                "lng"      : lng,
                "maps_url" : maps_url,
            }
        return jsonify(resp_json)

    # ── 6. Consulta general → RAG + Ollama
    try:
        results  = collection.query(query_texts=[pregunta], n_results=N_RESULTADOS)
        contexto = "\n\n".join(results["documents"][0])
        contexto = contexto[:800].rsplit(" ", 1)[0] if len(contexto) > 800 else contexto
    except Exception as e:
        return jsonify({"error": f"Error en búsqueda: {e}"}), 500

    hora = get_hora_bolivia()

    sistema = (
        f"⚠️ CRITICAL LANGUAGE RULE: {t['instruccion']} You MUST respond ONLY in that language. NEVER switch to Spanish or any other language.\n\n"
        "Eres el asistente oficial de la Agencia Boliviana de Correos (AGBC).\n"
        "Usa el siguiente texto para responder y recuerda el contexto de la conversación.\n\n"
        f"FECHA Y HORA EN BOLIVIA:\n"
        f"  Fecha: {hora['fecha']}  Hora: {hora['hora']}  Día: {hora['dia']}\n"
        f"  Estado: {hora['estado']}  Horario: {hora['horario']}\n\n"
        f"INFORMACIÓN OFICIAL:\n{contexto}\n\n"
        "INSTRUCCIONES:\n"
        "- Responde SOLO con la información del texto\n"
        "- Si preguntan si está abierto, usa el Estado de arriba\n"
        "- Máximo 3 párrafos cortos, sin asteriscos ni markdown\n"
        f"- Si no tienes la info di: \"{t['sin_info']}\"\n"
        f"-  IDIOMA OBLIGATORIO: {t['instruccion']} NO uses otro idioma bajo ninguna circunstancia.\n"
    )

    mensajes = [
        {"role": "system", "content": sistema},
        *historiales[sid][-MAX_HISTORIAL:],
        {"role": "user",   "content": pregunta},
    ]

    try:
        print(f"📨 [{sid[:8]}] [{lang}] {pregunta[:60]}")
        respuesta = llamar_ollama(mensajes)
        respuesta = limpiar_respuesta(respuesta)

        historiales[sid].extend([
            {"role": "user",      "content": pregunta},
            {"role": "assistant", "content": respuesta},
        ])
        if len(historiales[sid]) > MAX_HISTORIAL * 2:
            historiales[sid] = historiales[sid][-(MAX_HISTORIAL * 2):]

        print(f"✅ [{lang}] {len(respuesta)} chars")
        return jsonify({"response": respuesta, "lang": lang})

    except requests.exceptions.Timeout:
        return jsonify({"error": "El modelo tardó demasiado. Intenta de nuevo."}), 504
    except Exception as e:
        return jsonify({"error": f"Error generando respuesta: {e}"}), 500


@app.route("/api/sucursales", methods=["GET"])
def listar_sucursales():
    resultado = []
    for s in SUCURSALES:
        lat = s.get("lat")
        lng = s.get("lng")
        resultado.append({
            "nombre"   : s.get("nombre", ""),
            "direccion": s.get("direccion", ""),
            "telefono" : s.get("telefono", ""),
            "email"    : s.get("email", ""),
            "horario"  : s.get("horario", ""),
            "lat"      : lat,
            "lng"      : lng,
            "maps_url" : generar_maps_url(lat, lng) if lat and lng else None,
        })
    return jsonify({"sucursales": resultado})


@app.route("/api/idiomas", methods=["GET"])
def listar_idiomas():
    return jsonify({"idiomas": [{"code": c, "nombre": d["nombre"]} for c, d in IDIOMAS.items()]})


@app.route("/api/reset", methods=["POST"])
def reset():
    if "session_id" in session:
        historiales.pop(session["session_id"], None)
    return jsonify({"ok": True})


@app.route("/api/status", methods=["GET"])
def status():
    try:
        requests.get("http://127.0.0.1:11434", timeout=3)
        ollama_ok = True
    except Exception:
        ollama_ok = False
    return jsonify({
        "status"          : "ok",
        "chunks"          : collection.count(),
        "modelo"          : LLM_MODEL,
        "ollama"          : ollama_ok,
        "sesiones_activas": len(historiales),
        "sucursales"      : len(SUCURSALES),
        "idiomas"         : list(IDIOMAS.keys()),
        "actualizacion"   : {
            "en_proceso"      : estado_actualizacion["en_proceso"],
            "ultima_vez"      : estado_actualizacion["ultima_vez"] or "Nunca",
            "proxima_vez"     : estado_actualizacion["proxima_vez"] or "—",
            "ultimo_resultado": estado_actualizacion["ultimo_resultado"],
            "cada_horas"      : HORAS_ACTUALIZACION,
        },
    })


@app.route("/api/actualizar", methods=["POST"])
def actualizar_manual():
    if estado_actualizacion["en_proceso"]:
        return jsonify({"ok": False, "mensaje": "⏳ Actualización ya en proceso."}), 409
    threading.Thread(target=actualizar_bd, daemon=True).start()
    return jsonify({"ok": True, "mensaje": "🔄 Actualización iniciada."})


# ─────────────────────────────────────────────
#  INICIALIZACIÓN
# ─────────────────────────────────────────────

def initialize_chatbot():
    global SUCURSALES, embedder, collection, scheduler

    SUCURSALES = cargar_sucursales_json()

    print("⏳ Cargando modelo de embeddings...")
    embedder = SentenceTransformer(EMBEDDING_MODEL)
    print("✅ Modelo cargado")

    client     = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(name="correos")

    if collection.count() == 0:
        chunks, chunk_ids = [], []
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                texto = f.read()
            idx, start = 0, 0
            while start < len(texto):
                chunks.append(texto[start:start + CHUNK_SIZE])
                chunk_ids.append(f"txt_{idx}")
                start += CHUNK_SIZE - 100
                idx   += 1
            print(f"   → {idx} chunks de texto")
        for i, s in enumerate(SUCURSALES):
            chunks.append(sucursal_a_texto(s))
            chunk_ids.append(f"suc_{i}")
        _cargar_secciones(chunks, chunk_ids)
        if chunks:
            print(f"📦 {len(chunks)} chunks — calculando embeddings...")
            embeddings  = embedder.encode(chunks, show_progress_bar=True, batch_size=64)
            total_lotes = (len(chunks) + BATCH_SIZE - 1) // BATCH_SIZE
            for i in tqdm(range(0, len(chunks), BATCH_SIZE), total=total_lotes, desc="Indexando"):
                collection.add(
                    documents  = chunks[i:i + BATCH_SIZE],
                    embeddings = embeddings[i:i + BATCH_SIZE].tolist(),
                    ids        = chunk_ids[i:i + BATCH_SIZE],
                )
            print(f"✅ {len(chunks)} chunks indexados")
    else:
        print(f"✅ BD lista ({collection.count()} chunks)")

    try:
        requests.get("http://127.0.0.1:11434", timeout=5)
        print("✅ Ollama conectado")
    except Exception as e:
        print(f"⚠️  Ollama no responde: {e}")

    scheduler = BackgroundScheduler(timezone="America/La_Paz")
    scheduler.add_job(
        actualizar_bd, trigger="interval", hours=HORAS_ACTUALIZACION,
        id="actualizar_bd", max_instances=1,
    )
    scheduler.start()
    prox = scheduler.get_job("actualizar_bd").next_run_time
    estado_actualizacion["proxima_vez"] = prox.strftime("%d/%m/%Y %H:%M") if prox else "—"
    print(f"⏰ Próxima actualización: {estado_actualizacion['proxima_vez']}")
    print(f"🌍 Idiomas disponibles: {', '.join(IDIOMAS.keys())}")


# ─────────────────────────────────────────────
#  INICIO
# ─────────────────────────────────────────────
if __name__ == "__main__":
    initialize_chatbot()
    print("\n🚀 Chatbot en http://localhost:5000\n")
    try:
        app.run(host="0.0.0.0", port=5000, debug=False)
    finally:
        if scheduler and scheduler.running:
            scheduler.shutdown()