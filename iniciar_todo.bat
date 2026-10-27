@echo off
echo [1/3] Despertando el motor de datos (Backend)...
start cmd /k ".\start_backend.bat"

echo [2/3] Arrancando el panel visual (Frontend)...
start cmd /k "cd frontend && npm run dev"

echo [3/3] Abriendo LaLiga Fantasy en el navegador...
timeout /t 5 /nobreak > NUL
start http://localhost:3000
