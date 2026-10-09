@echo off
chcp 65001 >nul
title AudioBook Studio AI - Servidor Local

cd /d "%~dp0"

echo =======================================================
echo          🎙️ AUDIOBOOK STUDIO AI - SERVIDOR
echo =======================================================
echo.

if not exist ".venv\Scripts\activate.bat" (
    echo [ERRO] Ambiente virtual não encontrado em .venv!
    echo Execute 'python -m venv .venv' e 'pip install -r requirements.txt' primeiro.
    pause
    exit /b 1
)

echo [INFO] Ativando ambiente virtual (.venv)...
call .venv\Scripts\activate.bat

echo [INFO] Aguardando o servidor carregar para abrir o navegador (delay de 5s)...
start /B cmd /c "timeout /t 5 >nul && start http://localhost:8000"

echo [INFO] Iniciando servidor FastAPI local...
echo [INFO] Para encerrar o servidor, feche esta janela ou pressione Ctrl+C.
echo.
python -m uvicorn src.api:app --host 127.0.0.1 --port 8000

echo.
echo =======================================================
echo [AVISO] O servidor FastAPI foi finalizado.
echo =======================================================
pause
