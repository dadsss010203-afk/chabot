@echo off
echo Iniciando Correos Bolivia Chatbot...
podman pod rm -f correos-pod 2>nul
podman pod create --name correos-pod -p 5000:5000 -p 11434:11434
podman run -d --pod correos-pod --name ollama-correos docker.io/ollama/ollama:latest
podman run -d --pod correos-pod --name chatbot-correos -v %CD%\data:/app/data -v %CD%\chroma_db:/app/chroma_db chatbot-correos-img
echo.
echo Esperando que Ollama arranque...
timeout /t 10 /nobreak
podman exec ollama-correos ollama pull gemma3:4b
echo.
echo Chatbot listo en http://localhost:5000
pause
