from flask import Flask, request, jsonify, send_from_directory, session
import os
import chromadb
from sentence_transformers import SentenceTransformer
from tqdm import tqdm
import requests
import uuid

app = Flask(__name__)
app.secret_key = "correos-bolivia-2026"

# ================= CONFIG =================
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
LLM_MODEL = "gemma3:4b"
DATA_FILE = "data/correos_bolivia.txt"
CHROMA_PATH = "chroma_db"
CHUNK_SIZE = 600
BATCH_SIZE = 500
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_TIMEOUT = 600
N_RESULTADOS = 3
MAX_HISTORIAL = 6

# Historial en memoria { session_id: [ {role, content}, ... ] }
historiales = {}

# ================= CARGAR MODELOS =================
print("⏳ Cargando modelo de embeddings...")
embedder = SentenceTransformer(EMBEDDING_MODEL)
print("✅ Modelo cargado")

# ================= CHROMADB =================
client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client.get_or_create_collection(name="correos")

# ================= INDEXAR (solo la primera vez) =================
if collection.count() == 0:
    if not os.path.exists(DATA_FILE):
        print(f"⚠️  No se encontró {DATA_FILE}")
        print("    Ejecuta primero: python scraper.py")
    else:
        print("🛠️  Indexando documentos por primera vez...")
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            texto = f.read()

        chunks = []
        start = 0
        while start < len(texto):
            chunks.append(texto[start:start + CHUNK_SIZE])
            start += CHUNK_SIZE - 100

        print(f"📦 {len(chunks)} chunks — calculando embeddings...")
        embeddings = embedder.encode(chunks, show_progress_bar=True, batch_size=64)

        print(f"💾 Guardando en ChromaDB en lotes de {BATCH_SIZE}...")
        total_lotes = (len(chunks) + BATCH_SIZE - 1) // BATCH_SIZE
        for i in tqdm(range(0, len(chunks), BATCH_SIZE), total=total_lotes, desc="Indexando"):
            lote_docs = chunks[i:i + BATCH_SIZE]
            lote_embs = embeddings[i:i + BATCH_SIZE].tolist()
            lote_ids  = [f"chk_{j}" for j in range(i, i + len(lote_docs))]
            collection.add(documents=lote_docs, embeddings=lote_embs, ids=lote_ids)

        print(f"✅ {len(chunks)} chunks indexados")
else:
    print(f"✅ Base de datos lista ({collection.count()} chunks)")

# ================= VERIFICAR OLLAMA =================
try:
    r = requests.get("http://127.0.0.1:11434", timeout=5)
    print(f"✅ Ollama conectado ({r.text.strip()})")
except Exception as e:
    print(f"⚠️  Ollama no responde: {e}")
    print("   Asegúrate de que Ollama esté abierto en tu PC")

# ================= FUNCIÓN OLLAMA =================
def llamar_ollama(mensajes: list) -> str:
    payload = {
        "model": LLM_MODEL,
        "messages": mensajes,
        "stream": False,
        "options": {
            "num_predict": 250,   # Reducido para responder más rápido
            "temperature": 0.2,
            "top_p": 0.9,
        }
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["message"]["content"]

# ================= RUTAS =================
@app.route('/')
def serve_chat():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return send_from_directory('.', 'chatbot.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    sid = session['session_id']

    if sid not in historiales:
        historiales[sid] = []

    data = request.json
    if not data or 'message' not in data:
        return jsonify({'error': 'Falta el campo message'}), 400

    pregunta = data['message'].strip()
    if not pregunta:
        return jsonify({'error': 'Pregunta vacía'}), 400

    # Buscar contexto relevante en ChromaDB
    try:
        results = collection.query(query_texts=[pregunta], n_results=N_RESULTADOS)
        contexto = "\n\n".join(results['documents'][0])
    except Exception as e:
        print(f"ERROR ChromaDB: {e}")
        return jsonify({'error': f'Error buscando contexto: {str(e)}'}), 500

    # Instrucciones del sistema
    sistema = f"""Eres el asistente oficial de la Agencia Boliviana de Correos (AGBC).
Usa el siguiente texto para responder. Recuerda el contexto de la conversación anterior.

TEXTO OFICIAL:
{contexto}

INSTRUCCIONES:
- Responde usando SOLO la información del texto
- Sé breve y directo, máximo 3 párrafos cortos
- Recuerda lo que el usuario mencionó antes
- No uses asteriscos ni markdown
- Responde en español de forma clara y amable
- Si no hay información di: "No tengo esa información. Visita correos.gob.bo"
"""

    # Construir mensajes con historial
    historial = historiales[sid]
    mensajes = [
        {"role": "user", "content": sistema},
        {"role": "assistant", "content": "Entendido. Listo para ayudarte con Correos Bolivia."}
    ]
    mensajes += historial[-MAX_HISTORIAL:]
    mensajes.append({"role": "user", "content": pregunta})

    try:
        print(f"📨 [{sid[:8]}] {pregunta} (historial: {len(historial)} msgs)")
        respuesta = llamar_ollama(mensajes)

        # Limpiar markdown residual
        respuesta = respuesta.replace("**", "").replace("* ", "• ").replace("*", "")

        # Guardar en historial
        historiales[sid].append({"role": "user", "content": pregunta})
        historiales[sid].append({"role": "assistant", "content": respuesta})

        # Limitar tamaño del historial
        if len(historiales[sid]) > MAX_HISTORIAL * 2:
            historiales[sid] = historiales[sid][-(MAX_HISTORIAL * 2):]

        print(f"✅ Respuesta ({len(respuesta)} chars)")
        return jsonify({'response': respuesta})

    except requests.exceptions.Timeout:
        print("⏱️  Timeout")
        return jsonify({'error': 'El modelo tardó demasiado. Intenta de nuevo.'}), 504
    except Exception as e:
        print(f"ERROR Ollama: {e}")
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/api/reset', methods=['POST'])
def reset():
    if 'session_id' in session:
        historiales.pop(session['session_id'], None)
    return jsonify({'ok': True})

@app.route('/api/status')
def status():
    try:
        requests.get("http://127.0.0.1:11434", timeout=3)
        ollama_ok = True
    except Exception:
        ollama_ok = False

    return jsonify({
        'status': 'ok',
        'chunks': collection.count(),
        'modelo': LLM_MODEL,
        'ollama': ollama_ok,
        'sesiones_activas': len(historiales),
    })

# ================= INICIO =================
if __name__ == '__main__':
    print("\n🚀 Chatbot corriendo en → http://localhost:5000\n")
    print("Presiona Ctrl+C para detener\n")
    app.run(host='0.0.0.0', port=5000, debug=False)