#!/usr/bin/env bash
# ==============================================================================
# Script de Instalación Automatizada para Linux / macOS / WSL
# WhatsApp Batch Messaging CLI Tool (Anti-Spike Engine)
# ==============================================================================

set -e

echo ""
echo "=================================================================="
echo "   INSTALADOR DE WHATSAPP BATCH MESSAGING TOOL (LINUX / MAC / WSL)"
echo "=================================================================="
echo ""

# 1. Detectar o instalar automáticamente Python 3
PYTHON_CMD=""
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
fi

if [ -z "$PYTHON_CMD" ]; then
    echo "[!] Python 3 no fue detectado en el sistema."
    echo "[*] Intentando instalación automática de Python 3..."

    if command -v apt-get &>/dev/null; then
        echo "[*] Detectado gestor de paquetes APT (Ubuntu / Debian / Mint)..."
        sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
    elif command -v dnf &>/dev/null; then
        echo "[*] Detectado gestor de paquetes DNF (Fedora / RHEL)..."
        sudo dnf install -y python3 python3-pip
    elif command -v yum &>/dev/null; then
        echo "[*] Detectado gestor de paquetes YUM (CentOS / RHEL)..."
        sudo yum install -y python3 python3-pip
    elif command -v pacman &>/dev/null; then
        echo "[*] Detectado gestor de paquetes Pacman (Arch / Manjaro)..."
        sudo pacman -Sy --noconfirm python python-pip
    elif command -v apk &>/dev/null; then
        echo "[*] Detectado gestor de paquetes APK (Alpine)..."
        apk add python3 py3-pip
    elif command -v brew &>/dev/null; then
        echo "[*] Detectado Homebrew (macOS)..."
        brew install python
    else
        echo "[ERROR] No se pudo identificar el gestor de paquetes del sistema para instalar Python automáticamente."
        echo "        Por favor instala Python 3 manualmente y vuelve a ejecutar este script."
        exit 1
    fi

    if command -v python3 &>/dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &>/dev/null; then
        PYTHON_CMD="python"
    else
        echo "[ERROR] No se pudo verificar la instalación de Python."
        exit 1
    fi
fi

PY_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[✓] Python verificado: $PYTHON_CMD (Versión $PY_VERSION)"

# 2. Crear entorno virtual (.venv)
if [ ! -d ".venv" ]; then
    echo "[*] Creando entorno virtual en .venv/..."
    $PYTHON_CMD -m venv .venv || {
        echo "[!] Falló la creación de venv. Instalando paquete python3-venv..."
        if command -v apt-get &>/dev/null; then
            sudo apt-get install -y python3-venv
            $PYTHON_CMD -m venv .venv
        else
            echo "[ERROR] No fue posible crear el entorno virtual. Instala python3-venv."
            exit 1
        fi
    }
else
    echo "[✓] Entorno virtual existente detectado en .venv/"
fi

# 3. Activar entorno virtual
echo "[*] Activando entorno virtual..."
# shellcheck source=/dev/null
source .venv/bin/activate

# 4. Actualizar pip e instalar dependencias
echo "[*] Actualizando pip..."
python -m pip install --upgrade pip --quiet

echo "[*] Instalando dependencias desde requirements.txt..."
pip install -r requirements.txt --quiet
echo "[✓] Librerías de Python instaladas correctamente."

# 5. Instalar navegadores de Playwright
echo "[*] Instalando binarios de navegador de Playwright (Chromium)..."
python -m playwright install chromium

# En Linux, verificar si se requieren dependencias del sistema para Chromium
if [ "$(uname)" = "Linux" ]; then
    echo "[*] Sistema Linux detectado. Verificando dependencias del sistema para Chromium..."
    if command -v sudo &>/dev/null; then
        echo "    (Instalando librerías gráficas de Chromium):"
        sudo python -m playwright install-deps chromium 2>/dev/null || {
            echo "[!] Si Chromium reporta librerías faltantes, ejecuta: sudo playwright install-deps"
        }
    else
        python -m playwright install-deps chromium 2>/dev/null || true
    fi
fi

# 6. Ejecutar pruebas unitarias para certificar la instalación
echo ""
echo "[*] Ejecutando suite de pruebas unitarias (pytest)..."
pytest -v

echo ""
echo "=================================================================="
echo "   ¡INSTALACIÓN COMPLETADA EXITOSAMENTE!                         "
echo "=================================================================="
echo ""
echo "Para comenzar a usar la herramienta:"
echo "  1. Activa el entorno virtual:"
echo "     source .venv/bin/activate"
echo ""
echo "  2. Vincula tu WhatsApp Web por primera vez:"
echo "     python main.py --setup-session"
echo ""
echo "  3. Ejecuta una prueba en seco (dry-run):"
echo "     python main.py --campaign 'prueba' --input contactos_ejemplo.csv --dry-run --fast"
echo ""
echo "=================================================================="
