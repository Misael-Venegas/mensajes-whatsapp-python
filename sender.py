"""
sender.py - Capa de abstracción para el envío de mensajes.
Incluye MessageSender (base), DryRunSender (simulación) y PlaywrightWhatsAppSender (producción).
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote

from models import normalize_phone

logger = logging.getLogger("whatsapp_sender")


class MessageSender(ABC):
    """Interfaz abstracta para el envío de mensajes."""

    @abstractmethod
    def initialize(self) -> None:
        """Inicializa los recursos necesarios (navegador, sesión, etc.)."""
        pass

    @abstractmethod
    def send(self, phone: str, message: str) -> bool:
        """
        Envía un mensaje al número indicado.
        Retorna True si fue exitoso, False en caso de error.
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Libera los recursos."""
        pass


class DryRunSender(MessageSender):
    """
    Cliente de simulación en seco.
    No abre navegador, no envía mensajes reales y registra la actividad en consola/memoria.
    """

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.history: List[Tuple[str, str]] = []
        self.is_initialized = False

    def initialize(self) -> None:
        self.is_initialized = True
        if self.verbose:
            print("[DRY-RUN] Inicializando cliente de simulación (sin navegador)...")

    def send(self, phone: str, message: str) -> bool:
        clean = normalize_phone(phone)
        self.history.append((clean, message))
        if self.verbose:
            preview = message.replace("\n", " ")
            if len(preview) > 60:
                preview = preview[:57] + "..."
            print(f"[DRY-RUN] Simulado envío a {clean} | Msg: \"{preview}\"")
        return True

    def close(self) -> None:
        if self.verbose:
            print(f"[DRY-RUN] Sesión simulada finalizada. Total simulados: {len(self.history)}")
        self.is_initialized = False


class PlaywrightWhatsAppSender(MessageSender):
    """
    Cliente de envío en WhatsApp Web utilizando Playwright con sesión persistente
    (user_data_dir) para conservar inicio de sesión / cookies entre campañas esporádicas.
    """

    def __init__(
        self,
        user_data_dir: str = "./whatsapp_session",
        headless: bool = False,
        sync_delay: float = 15.0,
        page_timeout_ms: int = 40000,
        browser_channel: Optional[str] = "chrome",
    ):
        self.user_data_dir = Path(user_data_dir).resolve()
        self.headless = headless
        self.sync_delay = sync_delay
        self.page_timeout_ms = page_timeout_ms
        self.browser_channel = browser_channel

        self._playwright = None
        self._browser_context = None
        self._page = None

    def initialize(self) -> None:
        """Abre el navegador con el perfil persistente y espera sincronización inicial."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as err:
            raise RuntimeError(
                "Playwright no está instalado. Ejecuta: pip install playwright"
            ) from err

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        print(f"[*] Iniciando navegador con sesión persistente en: {self.user_data_dir}")

        self._playwright = sync_playwright().start()

        # Intentar con el canal solicitado (ej. chrome del sistema), con fallback a msedge o chromium
        channels_to_try = [self.browser_channel, "chrome", "msedge", None]
        # Eliminar duplicados preservando orden
        channels_to_try = list(dict.fromkeys(channels_to_try))

        context_opened = False
        last_error = None

        for ch in channels_to_try:
            try:
                launch_kwargs = {
                    "user_data_dir": str(self.user_data_dir),
                    "headless": self.headless,
                    "viewport": None,
                    "args": [
                        "--disable-blink-features=AutomationControlled",
                        "--start-maximized",
                    ],
                }
                if ch:
                    launch_kwargs["channel"] = ch

                self._browser_context = self._playwright.chromium.launch_persistent_context(**launch_kwargs)
                context_opened = True
                ch_name = ch if ch else "Chromium empaquetado"
                print(f"[✓] Navegador iniciado exitosamente (Canal: {ch_name}).")
                break
            except Exception as e:
                last_error = e
                continue

        if not context_opened:
            raise RuntimeError(f"No fue posible iniciar el navegador: {last_error}")

        self._page = (
            self._browser_context.pages[0]
            if self._browser_context.pages
            else self._browser_context.new_page()
        )
        self._page.set_default_timeout(self.page_timeout_ms)

        print("[*] Abriendo WhatsApp Web (https://web.whatsapp.com)...")
        self._page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")

        print(
            f"[*] Esperando {self.sync_delay:.1f}s para sincronización inicial de chats..."
        )
        time.sleep(self.sync_delay)
        print("[✓] WhatsApp Web listo para iniciar envíos.")

    def send(self, phone: str, message: str) -> bool:
        """
        Envía un mensaje cargando el chat vía URL de WhatsApp Web y accionando el botón Enviar.
        """
        if not self._page:
            raise RuntimeError("El cliente no ha sido inicializado. Llama a initialize() primero.")

        clean = normalize_phone(phone)
        encoded_message = quote(message)
        send_url = f"https://web.whatsapp.com/send?phone={clean}&text={encoded_message}"

        try:
            self._page.goto(send_url, wait_until="domcontentloaded")

            # Verificar si aparece popup de número inválido
            # En WhatsApp Web aparece un diálogo con texto indicando número no válido
            invalid_popup_selector = "div[data-animate-modal-popup='true']"
            send_btn_selector = (
                "button[data-tab='11'], span[data-icon='send'], button[aria-label='Send'], button[aria-label='Enviar']"
            )

            start_wait = time.time()
            send_button = None

            while time.time() - start_wait < (self.page_timeout_ms / 1000.0):
                # Revisar popup de error
                if self._page.locator(invalid_popup_selector).count() > 0:
                    popup_text = self._page.locator(invalid_popup_selector).inner_text()
                    if "inválido" in popup_text.lower() or "invalid" in popup_text.lower():
                        logger.warning("Número telefónico inválido reportado por WhatsApp: %s", clean)
                        # Cerrar modal si es posible
                        try:
                            self._page.keyboard.press("Escape")
                        except Exception:
                            pass
                        return False

                # Revisar si el botón de enviar ya está visible y habilitado
                btn_locator = self._page.locator(send_btn_selector).first
                if btn_locator.count() > 0 and btn_locator.is_visible():
                    send_button = btn_locator
                    break

                self._page.wait_for_timeout(500)

            if not send_button:
                # Intentar fallback de presionar Enter en el input editable
                input_selector = "footer div[contenteditable='true']"
                if self._page.locator(input_selector).count() > 0:
                    input_box = self._page.locator(input_selector).first
                    input_box.press("Enter")
                    time.sleep(1.5)
                    return True

                logger.error("Timeout esperando botón de envío para %s", clean)
                return False

            send_button.click()
            # Pausa breve para asegurar que el socket despache el mensaje antes de cambiar de URL
            time.sleep(2.0)
            return True

        except Exception as e:
            logger.error("Error al enviar mensaje a %s: %s", clean, e)
            return False

    def close(self) -> None:
        """Cierra el contexto y finaliza el proceso de Playwright."""
        try:
            if self._browser_context:
                self._browser_context.close()
        except Exception as e:
            logger.debug("Error cerrando browser context: %s", e)
        finally:
            try:
                if self._playwright:
                    self._playwright.stop()
            except Exception as e:
                logger.debug("Error deteniendo playwright: %s", e)

