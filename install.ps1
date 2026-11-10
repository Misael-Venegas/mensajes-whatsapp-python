# ==============================================================================
# Script de Instalación Automatizada para Windows PowerShell
# WhatsApp Batch Messaging CLI Tool (Anti-Spike Engine)
# ==============================================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "   INSTALADOR DE WHATSAPP BATCH MESSAGING TOOL (POWERSHELL)      " -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Verificar si Python está instalado; si no, instalarlo automáticamente
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "[!] Python no fue detectado en el sistema." -ForegroundColor Yellow
    Write-Host "[*] Iniciando instalación automática de Python 3.11..." -ForegroundColor Cyan

    $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
    if ($wingetCmd) {
        Write-Host "[*] Instalando Python 3.11 vía Windows Package Manager (winget)..." -ForegroundColor Yellow
        winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements
    } else {
        Write-Host "[*] Descargando instalador oficial de Python 3.11 desde python.org..." -ForegroundColor Yellow
        $installerPath = "$env:TEMP\python_installer.exe"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $installerPath
        Write-Host "[*] Ejecutando instalación silenciosa de Python..." -ForegroundColor Yellow
        Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait
        Remove-Item -Force $installerPath -ErrorAction SilentlyContinue
    }

    # Refrescar variables de entorno PATH en la sesión actual
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $env:Path = "$userPath;$machinePath"

    $localPyPath = "$env:LOCALAPPDATA\Programs\Python\Python311"
    if (Test-Path $localPyPath) {
        $env:Path = "$localPyPath;$localPyPath\Scripts;$env:Path"
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCmd) {
        Write-Host "[!] Python fue instalado con éxito, pero Windows requiere reiniciar la consola para cargar las nuevas variables PATH." -ForegroundColor Yellow
        Write-Host "    Por favor cierra esta ventana de terminal y vuelve a ejecutar .\install.ps1" -ForegroundColor White
        Exit 0
    }
}

$pyVersion = python --version
Write-Host "[✓] $pyVersion detectado y verificado." -ForegroundColor Green

# 2. Crear entorno virtual (.venv)
if (-not (Test-Path ".venv")) {
    Write-Host "[*] Creando entorno virtual en .venv..." -ForegroundColor Yellow
    python -m venv .venv
} else {
    Write-Host "[✓] Entorno virtual existente detectado en .venv\" -ForegroundColor Green
}

# 3. Determinar rutas ejecutables del entorno virtual
$venvPython = ".\.venv\Scripts\python.exe"
$venvPip = ".\.venv\Scripts\pip.exe"
$venvPytest = ".\.venv\Scripts\pytest.exe"

# 4. Actualizar pip e instalar dependencias
Write-Host "[*] Actualizando pip e instalando dependencias..." -ForegroundColor Yellow
& $venvPython -m pip install --upgrade pip --quiet
& $venvPip install -r requirements.txt --quiet
Write-Host "[✓] Librerías instaladas correctamente." -ForegroundColor Green

# 5. Playwright Chromium
Write-Host "[*] Configurando binarios de Playwright (Chromium)..." -ForegroundColor Yellow
& $venvPython -m playwright install chromium

# 6. Ejecutar pruebas unitarias
Write-Host ""
Write-Host "[*] Ejecutando suite de pruebas unitarias (pytest)..." -ForegroundColor Yellow
& $venvPytest -v

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "   ¡INSTALACIÓN COMPLETADA EXITOSAMENTE!                         " -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Para comenzar a usar la herramienta:" -ForegroundColor White
Write-Host "  1. Activa el entorno virtual:" -ForegroundColor Gray
Write-Host "     .\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "  2. Vincula tu WhatsApp Web por primera vez:" -ForegroundColor Gray
Write-Host "     python main.py --setup-session" -ForegroundColor Yellow
Write-Host ""
Write-Host "  3. Ejecuta una prueba en seco (dry-run):" -ForegroundColor Gray
Write-Host "     python main.py --campaign `"prueba`" --input contactos_ejemplo.csv --dry-run --fast" -ForegroundColor Yellow
Write-Host ""
Write-Host "==================================================================" -ForegroundColor Cyan
