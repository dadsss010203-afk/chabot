@echo off
echo Deteniendo contenedores...
podman pod stop correos-pod
echo Detenido correctamente.
pause
