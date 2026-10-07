@echo off
chcp 65001 >nul
title AudioBook Studio AI - Inicializador

echo =======================================================
echo          🎙️ AUDIOBOOK STUDIO AI - INICIALIZADOR
echo =======================================================
echo.

cd /d "%~dp0"

:: 1. Verifica se o ambiente virtual existe
if not exist ".\.venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual não encontrado em .venv!
    echo Execute 'python -m venv .venv' e 'pip install -r requirements.txt' primeiro.
    pause
    exit /b 1
)

:: 2. Verifica se o servidor já está rodando na porta 8000
netstat -ano | findstr :8000 >nul
if %errorlevel% equ 0 (
    echo [INFO] Servidor FastAPI já está em execução na porta 8000.
) else (
    echo [INFO] Iniciando servidor FastAPI local em segundo plano...
    start "AudioBook Studio API" /b ".\.venv\Scripts\python.exe" -m uvicorn src.api:app --host 127.0.0.1 --port 8000
    timeout /t 2 /nobreak >nul
)

:: 3. Abre o navegador na interface web do estúdio
echo [INFO] Abrindo o estúdio no navegador em http://localhost:8000 ...
start http://localhost:8000

echo.
echo =======================================================
echo 🎉 Estúdio aberto no navegador! Pode fechar esta janela.
echo =======================================================
timeout /t 3 >nul
exit
