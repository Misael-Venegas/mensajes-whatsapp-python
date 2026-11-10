@echo off
REM ==============================================================================
REM Script de Instalación Automatizada para Windows (CMD / Doble Clic)
REM WhatsApp Batch Messaging CLI Tool (Anti-Spike Engine)
REM ==============================================================================

chcp 65001 >nul
title Instalador - WhatsApp Batch Messaging Tool

echo.
echo ==================================================================
echo    INSTALADOR DE WHATSAPP BATCH MESSAGING TOOL (WINDOWS)
echo ==================================================================
echo.

REM 1. Verificar si Python está instalado, si no, instalarlo automáticamente
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [!] Python no fue detectado en el sistema.
    echo [*] Iniciando instalación automática de Python 3.11...
    echo.
    where winget >nul 2>nul
    if %errorlevel% equ 0 (
        echo [*] Instalando Python vía Windows Package Manager (winget)...
        winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements
    ) else (
        echo [*] Descargando instalador oficial de Python desde python.org...
        powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '%TEMP%\python_installer.exe'"
        echo [*] Ejecutando instalación silenciosa de Python...
        "%TEMP%\python_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
        del "%TEMP%\python_installer.exe" 2>nul
    )

    REM Refrescar PATH de la sesión actual
    for /f "tokens=*" %%a in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')"') do set "PATH=%%a"

    if exist "%LOCALAPPDATA%\Programs\Python\Python311" (
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
    )

    where python >nul 2>nul
    if %errorlevel% neq 0 (
        echo [!] Se completó la instalación de Python, pero requiere reiniciar la ventana de consola.
        echo     Por favor cierra y vuelve a abrir este instalador.
        pause
        exit /b 0
    )
)

for /f "tokens=*" %%i in ('python --version') do set PY_VER=%%i
echo [✓] %PY_VER% detectado y listo.

REM 2. Crear entorno virtual (.venv) si no existe
if not exist ".venv" (
    echo [*] Creando entorno virtual aislado en .venv...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Falló la creación del entorno virtual.
        pause
        exit /b 1
    )
) else (
    echo [✓] Entorno virtual existente detectado en .venv\
)

REM 3. Activar entorno virtual
echo [*] Activando entorno virtual (.venv)...
call .venv\Scripts\activate.bat

REM 4. Actualizar pip e instalar librerías
echo [*] Actualizando pip...
python -m pip install --upgrade pip --quiet

echo [*] Instalando dependencias desde requirements.txt...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Ocurrió un error al instalar las dependencias con pip.
    pause
    exit /b 1
)
echo [✓] Librerías de Python instaladas con éxito.

REM 5. Instalar binarios de Playwright
echo [*] Configurando navegador Playwright (Chromium)...
python -m playwright install chromium

REM 6. Ejecutar pruebas unitarias para certificar la instalación
echo.
echo [*] Ejecutando suite de pruebas unitarias para certificar instalación...
pytest -v
if %errorlevel% neq 0 (
    echo [!] Advertencia: Algunas pruebas reportaron error. Revisa la consola arriba.
)

echo.
echo ==================================================================
echo    ¡INSTALACIÓN COMPLETADA EXITOSAMENTE!
echo ==================================================================
echo.
echo Para comenzar a usar la herramienta:
echo   1. Activa el entorno virtual:
echo      .venv\Scripts\activate
echo.
echo   2. Vincula tu WhatsApp Web por primera vez:
echo      python main.py --setup-session
echo.
echo   3. Ejecuta una prueba en seco (dry-run):
echo      python main.py --campaign "prueba" --input contactos_ejemplo.csv --dry-run --fast
echo.
echo ==================================================================
echo.
pause
