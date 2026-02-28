from flask import Flask, request, jsonify, send_from_directory
import os
import chromadb
from sentence_transformers import SentenceTransformer
import ollama
from tqdm import tqdm

app = Flask(__name__)

# ================= CONFIG =================
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
LLM_MODEL = "gemma3:1b"
DATA_FILE = "data/correos_bolivia.txt"
CHROMA_PATH = "chroma_db"
CHUNK_SIZE = 600
BATCH_SIZE = 500  # Límite seguro para ChromaDB (máximo real: 5461)

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

        # Dividir texto en chunks con overlap de 100 chars
        chunks = []
        start = 0
        while start < len(texto):
            chunks.append(texto[start:start + CHUNK_SIZE])
            start += CHUNK_SIZE - 100

        print(f"📦 {len(chunks)} chunks generados — calculando embeddings...")
        embeddings = embedder.encode(
            chunks,
            show_progress_bar=True,
            batch_size=64,
        )

        print(f"💾 Guardando en ChromaDB en lotes de {BATCH_SIZE}...")
        total_lotes = (len(chunks) + BATCH_SIZE - 1) // BATCH_SIZE
        for i in tqdm(range(0, len(chunks), BATCH_SIZE), total=total_lotes, desc="Indexando"):
            lote_docs = chunks[i:i + BATCH_SIZE]
            lote_embs = embeddings[i:i + BATCH_SIZE].tolist()
            lote_ids  = [f"chk_{j}" for j in range(i, i + len(lote_docs))]
            collection.add(
                documents=lote_docs,
                embeddings=lote_embs,
                ids=lote_ids,
            )

        print(f"✅ {len(chunks)} chunks indexados correctamente")

else:
    print(f"✅ Base de datos lista ({collection.count()} chunks ya indexados)")

# ================= RUTAS =================

@app.route('/')
def serve_chat():
    return send_from_directory('.', 'chatbot.html')


@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    if not data or 'message' not in data:
        return jsonify({'error': 'Falta el campo "message"'}), 400

    pregunta = data['message'].strip()
    if not pregunta:
        return jsonify({'error': 'La pregunta está vacía'}), 400

    # Buscar chunks relevantes en ChromaDB
    results = collection.query(query_texts=[pregunta], n_results=6)
    contexto = "\n\n".join(results['documents'][0])

    prompt = f"""Eres el asistente oficial de la Agencia Boliviana de Correos (Correos Bolivia).
Responde ÚNICAMENTE con información del contexto proporcionado.
Si la respuesta no está en el contexto, di: "No tengo información sobre eso. Te recomiendo contactar a Correos Bolivia directamente."
Sé amable, claro y preciso. Responde en español.

CONTEXTO:
{contexto}

PREGUNTA: {pregunta}

RESPUESTA:"""

    try:
        respuesta = ollama.chat(
            model=LLM_MODEL,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return jsonify({'response': respuesta['message']['content']})
    except Exception as e:
        return jsonify({'error': f'Error al generar respuesta: {str(e)}'}), 500


@app.route('/api/status', methods=['GET'])
def status():
    """Endpoint para verificar que el servidor está activo."""
    return jsonify({
        'status': 'ok',
        'chunks_indexados': collection.count(),
        'modelo_llm': LLM_MODEL,
        'modelo_embeddings': EMBEDDING_MODEL,
    })


# ================= INICIO =================
if __name__ == '__main__':
    print("\n🚀 CHATBOT iniciado → http://localhost:5000\n")
    app.run(host='0.0.0.0', port=5000, debug=False)