"""
Ejecuta este script UNA SOLA VEZ para crear todos los archivos necesarios.
Uso: python setup.py
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))

archivos = {
    "Dockerfile": """\
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 300 --retries 5 -r requirements.txt
COPY chatbot.py .
COPY chatbot.html .
EXPOSE 5000
CMD ["python", "chatbot.py"]
""",

    "requirements.txt": """\
flask
chromadb
sentence-transformers
ollama
tqdm
""",

    "docker-compose.yml": """\
version: "3.8"
services:
  ollama:
    image: docker.io/ollama/ollama:latest
    container_name: ollama-correos
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    restart: unless-stopped

  chatbot:
    build: .
    container_name: chatbot-correos
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
      - ./chroma_db:/app/chroma_db
    depends_on:
      - ollama
    restart: unless-stopped

volumes:
  ollama_data:
""",

    "iniciar.bat": """\
@echo off
echo Iniciando Correos Bolivia Chatbot...
podman pod rm -f correos-pod 2>nul
podman pod create --name correos-pod -p 5000:5000 -p 11434:11434
podman run -d --pod correos-pod --name ollama-correos docker.io/ollama/ollama:latest
podman run -d --pod correos-pod --name chatbot-correos -v %CD%\\data:/app/data -v %CD%\\chroma_db:/app/chroma_db chatbot-correos-img
echo.
echo Esperando que Ollama arranque...
timeout /t 10 /nobreak
podman exec ollama-correos ollama pull gemma3:4b
echo.
echo Chatbot listo en http://localhost:5000
pause
""",

    "detener.bat": """\
@echo off
echo Deteniendo contenedores...
podman pod stop correos-pod
echo Detenido correctamente.
pause
""",
}

print("Creando archivos del proyecto...\n")
for nombre, contenido in archivos.items():
    ruta = os.path.join(BASE, nombre)
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write(contenido)
    print(f"  OK  {nombre}")

print("\nTodo listo. Ahora ejecuta:")
print("  1. podman build -t chatbot-correos-img .")
print("  2. iniciar.bat")