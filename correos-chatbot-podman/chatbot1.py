from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
import os
import re
import json
import threading
import subprocess
import chromadb
from sentence_transformers import SentenceTransformer
from tqdm import tqdm
import requests
import uuid
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
app.secret_key = "correos-bolivia-2026"
CORS(app)

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
EMBEDDING_MODEL     = "paraphrase-multilingual-MiniLM-L12-v2"
LLM_MODEL           = "gemma3:4b"
DATA_FILE           = "data/correos_bolivia.txt"
SUCURSALES_FILE     = "data/sucursales_contacto.json"
CHROMA_PATH         = "chroma_db"
CHUNK_SIZE          = 600
BATCH_SIZE          = 500
OLLAMA_URL          = "http://127.0.0.1:11434/api/chat"
OLLAMA_TIMEOUT      = 600
N_RESULTADOS        = 3
MAX_HISTORIAL       = 6
HORAS_ACTUALIZACION = 24   # ← cada cuántas horas se actualiza la BD

PALABRAS_DESPEDIDA = [
    "adios", "adiós", "chau", "chao", "hasta luego", "hasta pronto",
    "nos vemos", "bye", "gracias ya", "eso era todo", "eso es todo",
    "me voy", "hasta mañana", "ciao",
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
#  IDIOMAS SOPORTADOS
# ─────────────────────────────────────────────
IDIOMAS = {
    "es": {
        "nombre"        : "Español",
        "bienvenida"    : (
            "¡Hola! Bienvenido al asistente oficial de la Agencia Boliviana de Correos (AGBC). "
            "Puedo ayudarte con envíos, tarifas, sucursales, ubicaciones y más. ¿En qué puedo ayudarte hoy?"
        ),
        "despedida"     : (
            "Ha sido un placer ayudarte. Que tengas un excelente día. "
            "Recuerda que puedes visitarnos en correos.gob.bo. ¡Hasta pronto!"
        ),
        "sin_info"      : "No tengo esa información. Visita correos.gob.bo",
        "instruccion"   : "Responde en español, de forma clara y amable.",
        "pedir_ciudad"  : "Tenemos sucursales en: {ciudades}. ¿De cuál necesitas la ubicación?",
        "no_disponible" : "No disponible",
    },
    "en": {
        "nombre"        : "English",
        "bienvenida"    : (
            "Hello! Welcome to the official assistant of the Bolivian Postal Agency (AGBC). "
            "I can help you with shipments, rates, branches, locations and more. How can I help you today?"
        ),
        "despedida"     : (
            "It was a pleasure helping you. Have a great day. "
            "Remember you can visit us at correos.gob.bo. Goodbye!"
        ),
        "sin_info"      : "I don't have that information. Visit correos.gob.bo",
        "instruccion"   : "Respond in English, clearly and politely.",
        "pedir_ciudad"  : "We have branches in: {ciudades}. Which city do you need the location for?",
        "no_disponible" : "Not available",
    },
    "fr": {
        "nombre"        : "Français",
        "bienvenida"    : (
            "Bonjour! Bienvenue chez l'assistant officiel de l'Agence Bolivienne des Postes (AGBC). "
            "Je peux vous aider avec les envois, les tarifs, les succursales et plus encore. Comment puis-je vous aider?"
        ),
        "despedida"     : (
            "Ce fut un plaisir de vous aider. Bonne journée. "
            "N'oubliez pas de visiter correos.gob.bo. Au revoir!"
        ),
        "sin_info"      : "Je n'ai pas cette information. Visitez correos.gob.bo",
        "instruccion"   : "Répondez en français, clairement et poliment.",
        "pedir_ciudad"  : "Nous avons des succursales à: {ciudades}. Pour quelle ville avez-vous besoin de la localisation?",
        "no_disponible" : "Non disponible",
    },
    "pt": {
        "nombre"        : "Português",
        "bienvenida"    : (
            "Olá! Bem-vindo ao assistente oficial da Agência Boliviana de Correios (AGBC). "
            "Posso ajudá-lo com envios, tarifas, agências, localizações e mais. Como posso ajudá-lo hoje?"
        ),
        "despedida"     : (
            "Foi um prazer ajudá-lo. Tenha um ótimo dia. "
            "Lembre-se de visitar correos.gob.bo. Até logo!"
        ),
        "sin_info"      : "Não tenho essa informação. Visite correos.gob.bo",
        "instruccion"   : "Responda em português, de forma clara e amigável.",
        "pedir_ciudad"  : "Temos agências em: {cidades}. De qual cidade você precisa da localização?",
        "no_disponible" : "Não disponível",
    },
    "zh": {
        "nombre"        : "中文",
        "bienvenida"    : (
            "您好！欢迎使用玻利维亚邮政局（AGBC）官方助手。"
            "我可以帮助您了解邮寄、费率、分支机构、位置等信息。请问有什么可以帮助您？"
        ),
        "despedida"     : (
            "很高兴为您服务。祝您有美好的一天。"
            "请记得访问 correos.gob.bo。再见！"
        ),
        "sin_info"      : "我没有该信息。请访问 correos.gob.bo",
        "instruccion"   : "请用中文回答，清晰友好。",
        "pedir_ciudad"  : "我们在以下城市有分支机构：{ciudades}。您需要哪个城市的位置？",
        "no_disponible" : "不可用",
    },
}

IDIOMA_DEFAULT = "es"


# ─────────────────────────────────────────────
#  ESTADO GLOBAL DE ACTUALIZACIÓN
# ─────────────────────────────────────────────
estado_actualizacion = {
    "en_proceso"      : False,
    "ultima_vez"      : None,        # str "dd/mm/yyyy hh:mm"
    "proxima_vez"     : None,        # str "dd/mm/yyyy hh:mm"
    "ultimo_resultado": "Pendiente",
}
_lock_reindex = threading.Lock()     # evita ejecuciones simultáneas


# ─────────────────────────────────────────────
#  CARGA DE SUCURSALES
# ─────────────────────────────────────────────

def limpiar_campo(valor: str) -> str:
    if not valor:
        return ""
    return re.sub(
        r'^(direcci[oó]n|contacto|tel[eé]fono|email|horario)\s*:\s*',
        '', valor, flags=re.I
    ).strip()


# ─────────────────────────────────────────────
#  NOMINATIM — solo fallback para ciudades
#  que no estén en COORDS_CIUDADES
# ─────────────────────────────────────────────
_coords_cache: dict = {}

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
    """
    Lee sucursales_contacto.json.
    Prioridad de coords: JSON del scraper → COORDS_CIUDADES → Nominatim.
    """
    if not os.path.exists(SUCURSALES_FILE):
        print(f"⚠️  No se encontró {SUCURSALES_FILE} — ejecuta primero: python scraper.py")
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
            ciudad = re.sub(r'^(regional|oficina\s+central)\s*:\s*', '', s.get("nombre", "").lower()).strip()
            coords = _nominatim_fallback(s.get("direccion", ""), ciudad)
            if coords:
                s["lat"] = coords["lat"]
                s["lng"] = coords["lng"]
                print(f"   🌍 '{ciudad}': lat={coords['lat']:.5f}, lng={coords['lng']:.5f}")
            else:
                print(f"   ⚠️  Sin coords: {ciudad}")

    con_coords = sum(1 for s in sucursales if s.get("lat") and s.get("lng"))
    print(f"✅ {len(sucursales)} sucursales cargadas | {con_coords} con coordenadas")
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


# ─────────────────────────────────────────────
#  AUTO-ACTUALIZACIÓN
#  Flujo: correr scraper.py → re-indexar ChromaDB
# ─────────────────────────────────────────────

def _reindexar() -> bool:
    """
    Limpia ChromaDB y la reconstruye con los archivos data/ frescos.
    Retorna True si fue exitoso.
    """
    global SUCURSALES

    chunks    = []
    chunk_ids = []

    if not os.path.exists(DATA_FILE):
        print("⚠️  correos_bolivia.txt no encontrado — abortando reindex")
        return False

    print("🛠️  Reindexando texto scrapeado...")
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        texto = f.read()
    idx, start = 0, 0
    while start < len(texto):
        chunks.append(texto[start:start + CHUNK_SIZE])
        chunk_ids.append(f"txt_{idx}")
        start += CHUNK_SIZE - 100
        idx   += 1
    print(f"   → {idx} chunks de texto web")

    SUCURSALES = cargar_sucursales_json()
    if SUCURSALES:
        print("🏢  Indexando sucursales...")
        for i, s in enumerate(SUCURSALES):
            chunks.append(sucursal_a_texto(s))
            chunk_ids.append(f"suc_{i}")
        print(f"   → {len(SUCURSALES)} sucursales agregadas")

    # ── Agregar secciones (Aplicativos, Servicios, etc.) ──────────
    try:
        if os.path.exists("data/secciones_home.json"):
            with open("data/secciones_home.json", "r", encoding="utf-8") as f:
                secciones = json.load(f)
            
            for seccion_nombre, items in secciones.items():
                if items:
                    # Crear un documento con toda la sección
                    seccion_texto = f"## {seccion_nombre}\n\n"
                    seccion_texto += "\n".join(f"- {item}" for item in items)
                    chunks.append(seccion_texto)
                    chunk_ids.append(f"sec_{seccion_nombre.replace(' ', '_')}")
            
            total_sec = sum(1 for items in secciones.values() if items)
            print(f"📋 {total_sec} secciones agregadas (Servicios, Aplicativos, etc.)")
    except Exception as e:
        print(f"⚠️  No se pudieron agregar secciones: {e}")

    if not chunks:
        print("⚠️  Sin contenido para indexar")
        return False

    print(f"📦 {len(chunks)} chunks — calculando embeddings...")

    # Limpiar colección antes de re-insertar
    try:
        todos = collection.get()
        if todos and todos.get("ids"):
            collection.delete(ids=todos["ids"])
            print(f"   🗑️  {len(todos['ids'])} chunks anteriores eliminados")
    except Exception as e:
        print(f"   ⚠️  No se pudo limpiar colección: {e}")

    embeddings  = embedder.encode(chunks, show_progress_bar=False, batch_size=64)
    total_lotes = (len(chunks) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in tqdm(range(0, len(chunks), BATCH_SIZE), total=total_lotes, desc="Indexando"):
        collection.add(
            documents  = chunks[i:i + BATCH_SIZE],
            embeddings = embeddings[i:i + BATCH_SIZE].tolist(),
            ids        = chunk_ids[i:i + BATCH_SIZE],
        )

    print(f"✅ Reindex completo — {len(chunks)} chunks en ChromaDB")
    return True


def actualizar_bd() -> None:
    """
    Tarea programada (y manual):
      1. Corre scraper.py
      2. Re-indexa ChromaDB con los datos frescos
    """
    global estado_actualizacion

    if not _lock_reindex.acquire(blocking=False):
        print("⏳ Actualización ya en proceso — saltando")
        return

    bolivia = timezone(timedelta(hours=-4))
    estado_actualizacion["en_proceso"] = True
    ahora_str = datetime.now(bolivia).strftime("%d/%m/%Y %H:%M")
    print(f"\n{'─'*55}")
    print(f"🔄 [{ahora_str}] Iniciando actualización automática...")
    print(f"{'─'*55}")

    try:
        # ── Paso 1: correr scraper ─────────────────────────────────
        print("🕷️  Ejecutando scraper.py ...")
        resultado = subprocess.run(
            ["python", "scraper.py"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if resultado.returncode != 0:
            msg = f"Scraper falló (código {resultado.returncode})"
            print(f"❌ {msg}")
            if resultado.stderr:
                print(resultado.stderr[-500:])
            estado_actualizacion["ultimo_resultado"] = f"❌ {msg}"
            return

        print("✅ Scraper terminó correctamente")

        # ── Paso 2: re-indexar ─────────────────────────────────────
        exito = _reindexar()
        ahora = datetime.now(bolivia)

        if exito:
            estado_actualizacion["ultima_vez"]       = ahora.strftime("%d/%m/%Y %H:%M")
            estado_actualizacion["ultimo_resultado"] = "✅ Actualización exitosa"
            print(f"🎉 BD actualizada el {estado_actualizacion['ultima_vez']}")
        else:
            estado_actualizacion["ultimo_resultado"] = "⚠️ Scraper OK pero reindex falló"

    except subprocess.TimeoutExpired:
        estado_actualizacion["ultimo_resultado"] = "❌ Scraper tardó más de 10 min"
        print("❌ Timeout del scraper")
    except Exception as e:
        estado_actualizacion["ultimo_resultado"] = f"❌ Error: {e}"
        print(f"❌ Error en actualización: {e}")
    finally:
        estado_actualizacion["en_proceso"] = False
        _lock_reindex.release()
        print(f"{'─'*55}\n")


# ─────────────────────────────────────────────
#  DETECTOR DE CONSULTAS DE UBICACIÓN
# ─────────────────────────────────────────────

def detectar_consulta_ubicacion(texto: str) -> dict | None:
    ciudades_str = ", ".join(
        re.sub(r'^(regional|oficina\s+central)\s*:\s*', '', s.get("nombre", "").lower()).strip()
        for s in SUCURSALES
    )
    prompt = f"""Analiza este mensaje: "{texto}"

¿El usuario está pidiendo la ubicación, dirección o sucursal de Correos de Bolivia?
¿Menciona alguna de estas ciudades: {ciudades_str}?

Responde SOLO con JSON, sin explicaciones, sin texto extra:
{{"es_ubicacion": true/false, "ciudad": "nombre exacto de la ciudad o null"}}

Ejemplos:
- "la paz dame ubicacion" → {{"es_ubicacion": true, "ciudad": "la paz"}}
- "dond queda la ofisina de cbba" → {{"es_ubicacion": true, "ciudad": "cochabamba"}}
- "cuanto cuesta enviar un paquete" → {{"es_ubicacion": false, "ciudad": null}}
- "sucursal" → {{"es_ubicacion": true, "ciudad": null}}
"""
    try:
        payload = {
            "model"   : LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream"  : False,
            "options" : {"num_predict": 60, "temperature": 0},
        }
        resp = requests.post(OLLAMA_URL, json=payload, timeout=30)
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()

        match = re.search(r'\{.*?\}', raw, re.DOTALL)
        if not match:
            return _detectar_fallback(texto)

        resultado = json.loads(match.group())
        if not resultado.get("es_ubicacion"):
            return None

        ciudad = (resultado.get("ciudad") or "").lower().strip()
        if not ciudad:
            return {"ciudad": None}

        ciudad = ALIAS_CIUDADES.get(ciudad, ciudad)

        for s in SUCURSALES:
            nombre_lower    = s.get("nombre", "").lower()
            ciudad_sucursal = re.sub(r'^(regional|oficina\s+central)\s*:\s*', '', nombre_lower).strip()
            if ciudad in ciudad_sucursal:
                return s

        return {"ciudad": None}

    except Exception as e:
        print(f"⚠️  IA no pudo analizar, usando fallback: {e}")
        return _detectar_fallback(texto)


def _detectar_fallback(texto: str) -> dict | None:
    PALABRAS = [
        "ubicacion", "ubicación", "ibucacion", "ubicasion",
        "donde", "dónde", "dond",
        "direccion", "dirección", "direcion",
        "sucursal", "surcusal", "sucusal",
        "oficina", "mapa", "maps", "coordenadas",
        "como llego", "cómo llego",
    ]
    texto_lower = texto.lower()
    for alias, ciudad_real in ALIAS_CIUDADES.items():
        if alias in texto_lower:
            texto_lower = texto_lower.replace(alias, ciudad_real)

    if not any(p in texto_lower for p in PALABRAS):
        return None

    for s in SUCURSALES:
        nombre_lower    = s.get("nombre", "").lower()
        ciudad_sucursal = re.sub(r'^(regional|oficina\s+central)\s*:\s*', '', nombre_lower).strip()
        if ciudad_sucursal and ciudad_sucursal in texto_lower:
            return s

    return {"ciudad": None}


# ─────────────────────────────────────────────
#  INICIALIZACIÓN
# ─────────────────────────────────────────────
SUCURSALES  = cargar_sucursales_json()
historiales = {}

print("⏳ Cargando modelo de embeddings...")
embedder = SentenceTransformer(EMBEDDING_MODEL)
print("✅ Modelo cargado")

client     = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client.get_or_create_collection(name="correos")

if collection.count() == 0:
    chunks    = []
    chunk_ids = []

    if not os.path.exists(DATA_FILE):
        print(f"⚠️  No se encontró {DATA_FILE}. Ejecuta: python scraper.py")
    else:
        print("🛠️  Indexando texto scrapeado...")
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            texto = f.read()
        idx, start = 0, 0
        while start < len(texto):
            chunks.append(texto[start:start + CHUNK_SIZE])
            chunk_ids.append(f"txt_{idx}")
            start += CHUNK_SIZE - 100
            idx   += 1
        print(f"   → {idx} chunks de texto web")

    if SUCURSALES:
        print("🏢  Indexando sucursales en ChromaDB...")
        for i, s in enumerate(SUCURSALES):
            chunks.append(sucursal_a_texto(s))
            chunk_ids.append(f"suc_{i}")
        print(f"   → {len(SUCURSALES)} sucursales agregadas")

    if chunks:
        print(f"📦 Total: {len(chunks)} chunks — calculando embeddings...")
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
    print(f"✅ Base de datos lista ({collection.count()} chunks)")

try:
    r = requests.get("http://127.0.0.1:11434", timeout=5)
    print(f"✅ Ollama conectado ({r.text.strip()})")
except Exception as e:
    print(f"⚠️  Ollama no responde: {e}")

# ─────────────────────────────────────────────
#  SCHEDULER — actualización automática
# ─────────────────────────────────────────────
scheduler = BackgroundScheduler(timezone="America/La_Paz")
scheduler.add_job(
    actualizar_bd,
    trigger       = "interval",
    hours         = HORAS_ACTUALIZACION,
    id            = "actualizar_bd",
    max_instances = 1,
)
scheduler.start()

_prox = scheduler.get_job("actualizar_bd").next_run_time
estado_actualizacion["proxima_vez"] = _prox.strftime("%d/%m/%Y %H:%M") if _prox else "—"
print(f"⏰ Próxima actualización automática: {estado_actualizacion['proxima_vez']} (hora Bolivia)")


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def llamar_ollama(mensajes: list) -> str:
    payload = {
        "model"   : LLM_MODEL,
        "messages": mensajes,
        "stream"  : False,
        "options" : {"num_predict": 80, "temperature": 0.1, "top_p": 0.8},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def es_despedida(texto: str) -> bool:
    return any(p in texto.lower().strip() for p in PALABRAS_DESPEDIDA)


def get_sid() -> str:
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return session['session_id']


def get_hora_bolivia() -> dict:
    bolivia    = timezone(timedelta(hours=-4))
    ahora      = datetime.now(bolivia)
    dias_es    = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
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

@app.route('/')
def serve_chat():
    get_sid()
    return send_from_directory('.', 'chatbot.html')


@app.route('/widget.js')
def serve_widget():
    return send_from_directory('.', 'widget.js', mimetype='application/javascript')


@app.route('/api/welcome', methods=['GET'])
def welcome():
    lang = request.args.get('lang', IDIOMA_DEFAULT)
    if lang not in IDIOMAS:
        lang = IDIOMA_DEFAULT
    return jsonify({'response': IDIOMAS[lang]['bienvenida']})


@app.route('/api/chat', methods=['POST'])
def chat():
    sid = get_sid()
    if sid not in historiales:
        historiales[sid] = []

    data = request.json
    if not data or 'message' not in data:
        return jsonify({'error': 'Falta el campo message'}), 400

    pregunta = data['message'].strip()
    if not pregunta:
        return jsonify({'error': 'Pregunta vacía'}), 400

    lang = data.get('lang', IDIOMA_DEFAULT)
    if lang not in IDIOMAS:
        lang = IDIOMA_DEFAULT
    t_lang = IDIOMAS[lang]

    # ── 1. Despedida ──────────────────────────────────────────────
    if es_despedida(pregunta):
        historiales.pop(sid, None)
        return jsonify({'response': t_lang['despedida'], 'despedida': True})

    # ── 2. ¿Solo nombre de ciudad? ────────────────────────────────
    pregunta_norm = ALIAS_CIUDADES.get(pregunta.lower().strip(), pregunta.lower().strip())

    geo = None
    for s in SUCURSALES:
        nombre_lower    = s.get("nombre", "").lower()
        ciudad_sucursal = re.sub(r'^(regional|oficina\s+central)\s*:\s*', '', nombre_lower).strip()
        if ciudad_sucursal and (pregunta_norm == ciudad_sucursal or pregunta_norm in ciudad_sucursal):
            geo = s
            break

    # ── 3. Detectar intención con Ollama ──────────────────────────
    if geo is None:
        geo = detectar_consulta_ubicacion(pregunta)

    # ── Responder con tarjeta de sucursal ─────────────────────────
    if geo is not None:
        if geo.get("ciudad") is None and "nombre" not in geo:
            nombres = " | ".join(s.get("nombre", "") for s in SUCURSALES)
            return jsonify({
                'response': t_lang['pedir_ciudad'].format(ciudades=nombres, cidades=nombres)
            })

        lat      = geo.get("lat")
        lng      = geo.get("lng")
        maps_url = generar_maps_url(lat, lng) if lat and lng else None

        nd = t_lang['no_disponible']
        texto_resp = (
            f"📍 {geo.get('nombre', '')}\n"
            f"Dirección : {geo.get('direccion') or nd}\n"
            f"Teléfono  : {geo.get('telefono') or nd}\n"
            f"Email     : {geo.get('email') or nd}\n"
            f"Horario   : {geo.get('horario') or nd}"
        )
        if maps_url:
            texto_resp += f"\nVer en mapa: {maps_url}"

        historiales[sid].append({"role": "user",     "content": pregunta})
        historiales[sid].append({"role": "assistant", "content": texto_resp})

        respuesta_json = {'response': texto_resp}
        if lat and lng:
            respuesta_json['ubicacion'] = {
                "nombre"   : geo.get("nombre", ""),
                "direccion": geo.get("direccion", ""),
                "telefono" : geo.get("telefono", ""),
                "email"    : geo.get("email", ""),
                "horario"  : geo.get("horario", ""),
                "lat"      : lat,
                "lng"      : lng,
                "maps_url" : maps_url,
            }
        return jsonify(respuesta_json)

    # ── 4. Consulta general → RAG + Ollama ────────────────────────
    try:
        results  = collection.query(query_texts=[pregunta], n_results=N_RESULTADOS)
        contexto = "\n\n".join(results['documents'][0])
    except Exception as e:
        return jsonify({'error': f'Error buscando contexto: {e}'}), 500

    t = get_hora_bolivia()
    sistema = f"""Eres el asistente oficial de la Agencia Boliviana de Correos (AGBC).
Usa el siguiente texto para responder. Recuerda el contexto de la conversación anterior.

FECHA Y HORA EN BOLIVIA:
- Fecha  : {t['fecha']}  Hora: {t['hora']}  Día: {t['dia']}
- Estado : {t['estado']}
- Horario: {t['horario']}

TEXTO OFICIAL:
{contexto}

INSTRUCCIONES:
- Responde SOLO con la información del texto
- Si preguntan si está abierto, usa el ESTADO de arriba
- Máximo 3 párrafos cortos, sin asteriscos ni markdown
- Si no tienes la info di: "{t_lang['sin_info']}"
- {t_lang['instruccion']}
"""

    historial = historiales[sid]
    mensajes  = [
        {"role": "user",      "content": sistema},
        {"role": "assistant", "content": "Entendido. Listo para ayudarte con Correos Bolivia."},
        *historial[-MAX_HISTORIAL:],
        {"role": "user",      "content": pregunta},
    ]

    try:
        print(f"📨 [{sid[:8]}] {pregunta[:60]} (historial: {len(historial)} msgs)")
        respuesta = llamar_ollama(mensajes)
        respuesta = respuesta.replace("**", "").replace("* ", "• ").replace("*", "")

        historiales[sid].append({"role": "user",     "content": pregunta})
        historiales[sid].append({"role": "assistant", "content": respuesta})
        if len(historiales[sid]) > MAX_HISTORIAL * 2:
            historiales[sid] = historiales[sid][-(MAX_HISTORIAL * 2):]

        print(f"✅ Respuesta ({len(respuesta)} chars)")
        return jsonify({'response': respuesta})

    except requests.exceptions.Timeout:
        return jsonify({'error': 'El modelo tardó demasiado. Intenta de nuevo.'}), 504
    except Exception as e:
        return jsonify({'error': f'Error generando respuesta: {e}'}), 500


@app.route('/api/sucursales', methods=['GET'])
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


@app.route('/api/idiomas', methods=['GET'])
def listar_idiomas():
    return jsonify({
        "idiomas": [
            {"code": code, "nombre": data["nombre"]}
            for code, data in IDIOMAS.items()
        ]
    })


@app.route('/api/reset', methods=['POST'])
def reset():
    if 'session_id' in session:
        historiales.pop(session['session_id'], None)
    return jsonify({'ok': True})


@app.route('/api/status', methods=['GET'])
def status():
    try:
        requests.get("http://127.0.0.1:11434", timeout=3)
        ollama_ok = True
    except Exception:
        ollama_ok = False

    return jsonify({
        'status'          : 'ok',
        'chunks'          : collection.count(),
        'modelo'          : LLM_MODEL,
        'ollama'          : ollama_ok,
        'sesiones_activas': len(historiales),
        'sucursales'      : len(SUCURSALES),
        'actualizacion'   : {
            'en_proceso'      : estado_actualizacion["en_proceso"],
            'ultima_vez'      : estado_actualizacion["ultima_vez"] or "Nunca",
            'proxima_vez'     : estado_actualizacion["proxima_vez"] or "—",
            'ultimo_resultado': estado_actualizacion["ultimo_resultado"],
            'cada_horas'      : HORAS_ACTUALIZACION,
        },
    })


@app.route('/api/actualizar', methods=['POST'])
def actualizar_manual():
    """Dispara la actualización manualmente en segundo plano."""
    if estado_actualizacion["en_proceso"]:
        return jsonify({
            'ok'     : False,
            'mensaje': '⏳ Ya hay una actualización en proceso. Espera a que termine.'
        }), 409

    threading.Thread(target=actualizar_bd, daemon=True).start()
    return jsonify({
        'ok'     : True,
        'mensaje': '🔄 Actualización iniciada. Consulta /api/status para ver el progreso.'
    })


# ─────────────────────────────────────────────
#  INICIO
# ─────────────────────────────────────────────
if __name__ == '__main__':
    print("\n🚀 Chatbot corriendo en → http://localhost:5000\n")
    try:
        app.run(host='0.0.0.0', port=5000, debug=False)
    finally:
        scheduler.shutdown()