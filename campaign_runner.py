"""
campaign_runner.py - Motor de ejecución de campañas con Anti-Spike Engine,
gestión de lotes, cooldown, hard stop y persistencia de estado.
"""

from __future__ import annotations

import csv
import json
import logging
import random
import signal
import sys
import time
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from models import CampaignState, Contact, EngineConfig, normalize_phone
from sender import MessageSender
from spintax import SpintaxMessageGenerator

logger = logging.getLogger("campaign_runner")


def load_contacts_from_file(file_path: Path) -> List[Contact]:
    """
    Carga contactos desde un archivo CSV o JSON.
    Soporta múltiples encabezados usuales (telefono, phone, celular, mobile, nombre, name).
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Archivo de contactos no encontrado: {file_path}")

    contacts: List[Contact] = []
    suffix = file_path.suffix.lower()

    if suffix == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("El archivo JSON debe contener una lista de contactos.")
            for row in data:
                phone = str(
                    row.get("telefono")
                    or row.get("phone")
                    or row.get("celular")
                    or row.get("mobile")
                    or ""
                )
                name = str(row.get("nombre") or row.get("name") or "")
                extra = {k: v for k, v in row.items() if k not in ["telefono", "phone", "celular", "mobile", "nombre", "name"]}
                if normalize_phone(phone):
                    contacts.append(Contact(phone=phone, name=name, extra=extra))

    elif suffix in [".csv", ".txt"]:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            # Detectar delimitador si es posible
            sample = f.read(2048)
            f.seek(0)
            delimiter = ","
            try:
                sniffer = csv.Sniffer()
                dialect = sniffer.sniff(sample, delimiters=",;\t|")
                delimiter = dialect.delimiter
            except Exception:
                delimiter = ","

            reader = csv.DictReader(f, delimiter=delimiter)
            # Si tiene encabezados
            if reader.fieldnames and any(
                f.lower() in ["telefono", "phone", "celular", "mobile", "nombre", "name"]
                for f in reader.fieldnames
            ):
                for row in reader:
                    phone_val = ""
                    name_val = ""
                    extra_data = {}
                    for k, v in row.items():
                        if not k:
                            continue
                        k_lower = k.lower().strip()
                        if k_lower in ["telefono", "phone", "celular", "mobile"]:
                            phone_val = v
                        elif k_lower in ["nombre", "name"]:
                            name_val = v
                        else:
                            extra_data[k] = v
                    if normalize_phone(phone_val):
                        contacts.append(Contact(phone=phone_val, name=name_val, extra=extra_data))
            else:
                # CSV sin encabezados: Columna 0 = Teléfono, Columna 1 = Nombre (opcional)
                f.seek(0)
                raw_reader = csv.reader(f, delimiter=delimiter)
                for row in raw_reader:
                    if not row:
                        continue
                    phone_val = row[0]
                    name_val = row[1] if len(row) > 1 else ""
                    if normalize_phone(phone_val):
                        contacts.append(Contact(phone=phone_val, name=name_val))
    else:
        raise ValueError(f"Formato no soportado: {suffix}. Usa CSV o JSON.")

    return contacts


def chunk_list(items: List[Contact], chunk_size: int) -> List[List[Contact]]:
    """Divide una lista en trozos (lotes) de tamaño máximo chunk_size."""
    if chunk_size <= 0:
        return [items]
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


class CampaignRunner:
    """
    Orquestador principal de la campaña.
    Controla el flujo de envíos, lotes, pausas anti-ban y persistencia.
    """

    def __init__(
        self,
        campaign_name: str,
        sender: MessageSender,
        config: Optional[EngineConfig] = None,
        state_dir: Optional[Path] = None,
        generator: Optional[SpintaxMessageGenerator] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        self.campaign_name = campaign_name
        self.sender = sender
        self.config = config or EngineConfig()
        self.state_dir = Path(state_dir or ".").resolve()
        self.state_file = self.state_dir / f"estado_{self.campaign_name}.json"
        self.generator = generator or SpintaxMessageGenerator()
        self.on_progress = on_progress

        self.state = CampaignState.load_from_file(self.state_file, self.campaign_name)
        self.interrupted = False
        self._setup_signals()

    def _setup_signals(self) -> None:
        """Registra manejadores de señales para apagado limpio (Graceful Shutdown)."""
        def handle_shutdown(signum, frame):
            print("\n[!] Señal de interrupción recibida (Ctrl+C). Iniciando apagado limpio...")
            self.interrupted = True

        try:
            signal.signal(signal.SIGINT, handle_shutdown)
            signal.signal(signal.SIGTERM, handle_shutdown)
        except (ValueError, AttributeError):
            # En hilos secundarios o entornos limitados de Windows, signal puede diferir
            pass

    def _log_progress(self, message: str) -> None:
        if self.on_progress:
            self.on_progress(message)
        else:
            print(message)

    def calculate_message_delay(self, session_count: int) -> float:
        """
        Calcula el jitter anti-ban para el mensaje actual de la sesión:
        - Mensajes 1 a 5 (Warm-up): Pausa conservadora entre 35.0 y 65.0 s.
        - Mensaje 6 en adelante: Jitter estándar entre 20.0 y 45.0 s.
        """
        if session_count <= self.config.warmup_threshold:
            return random.uniform(self.config.warmup_min_delay, self.config.warmup_max_delay)
        return random.uniform(self.config.standard_min_delay, self.config.standard_max_delay)

    def calculate_batch_cooldown(self) -> float:
        """Calcula el descanso entre lotes (25 a 40 minutos en segundos)."""
        return random.uniform(self.config.cooldown_min_seconds, self.config.cooldown_max_seconds)

    def run(self, contacts: List[Contact]) -> int:
        """
        Ejecuta la campaña sobre la lista de contactos dada.
        Retorna la cantidad de mensajes enviados con éxito en esta sesión.
        """
        # 1. Filtrar idempotente: excluir números ya enviados previamente
        pending_contacts = [c for c in contacts if not self.state.is_sent(c.clean_phone)]
        total_initial = len(contacts)
        already_sent = total_initial - len(pending_contacts)

        self._log_progress(
            f"=== Iniciando Campaña: '{self.campaign_name}' ==="
        )
        self._log_progress(
            f"Total contactos cargados: {total_initial} | Ya enviados: {already_sent} | Pendientes: {len(pending_contacts)}"
        )

        if not pending_contacts:
            self._log_progress("[✓] Todos los contactos de esta campaña ya fueron enviados.")
            return 0

        # 2. Inicializar sender
        self.sender.initialize()

        # 3. Partición en lotes
        batches = chunk_list(pending_contacts, self.config.batch_size)
        total_batches = len(batches)
        session_sent_count = 0
        stop_reason = ""

        try:
            for batch_idx, batch in enumerate(batches, start=1):
                if self.interrupted:
                    stop_reason = "Interrupción por el usuario (Ctrl+C)"
                    break

                batch_total = len(batch)
                self._log_progress(f"\n--- Iniciando Lote {batch_idx}/{total_batches} ({batch_total} contactos) ---")

                for item_idx, contact in enumerate(batch, start=1):
                    if self.interrupted:
                        stop_reason = "Interrupción por el usuario (Ctrl+C)"
                        break

                    # Verificar Hard Stop antes de despachar
                    if session_sent_count >= self.config.hard_stop_limit:
                        stop_reason = f"Hard Stop alcanzado ({self.config.hard_stop_limit} envíos en esta sesión)"
                        self._log_progress(f"[!] {stop_reason}. Deteniendo ejecución.")
                        break

                    # Calcular delay correspondiente al mensaje a enviar (1-indexed para el mensaje de esta sesión)
                    next_session_count = session_sent_count + 1
                    delay = self.calculate_message_delay(next_session_count)

                    # Formato requerido: [Lote 1/3] Enviando 4/20... Esperando 34.2s
                    warmup_flag = " (Warm-up)" if next_session_count <= self.config.warmup_threshold else ""
                    self._log_progress(
                        f"[Lote {batch_idx}/{total_batches}] Enviando {item_idx}/{batch_total} a {contact.clean_phone}{warmup_flag}... Esperando {delay:.1f}s"
                    )

                    # Construir mensaje Spintax
                    message_text = self.generator.build_message(contact)

                    # Enviar mensaje
                    success = self.sender.send(contact.clean_phone, message_text)

                    if success:
                        self.state.mark_sent(contact.clean_phone)
                        session_sent_count += 1
                    else:
                        self.state.mark_failed(contact.clean_phone, "Error al enviar mensaje")
                        self._log_progress(f"[x] Error enviando a {contact.clean_phone}")

                    # Guardado inmediato del estado para resiliencia ante cortes abruptos
                    self.state.save_to_file(self.state_file)

                    if self.interrupted:
                        stop_reason = "Interrupción por el usuario (Ctrl+C)"
                        break

                    # Verificar si acabamos de alcanzar el hard stop
                    if session_sent_count >= self.config.hard_stop_limit:
                        stop_reason = f"Hard Stop alcanzado ({self.config.hard_stop_limit} envíos)"
                        break

                    # Pausa inter-mensaje obligatoria (anti-ban / warm-up)
                    time.sleep(delay)

                    if self.interrupted:
                        stop_reason = "Interrupción por el usuario (Ctrl+C)"
                        break

                # Si salimos del lote por hard stop o interrupción, detener
                if session_sent_count >= self.config.hard_stop_limit or self.interrupted:
                    break

                # Cooldown entre lotes:
                # Se ejecuta ÚNICAMENTE si quedan lotes pendientes por procesar en esta ejecución
                has_more_batches = batch_idx < total_batches
                if has_more_batches:
                    cooldown = self.calculate_batch_cooldown()
                    cooldown_min = cooldown / 60.0
                    self._log_progress(
                        f"\n[⏸] Lote {batch_idx}/{total_batches} completado. "
                        f"Enfriamiento entre lotes: descansando {cooldown_min:.1f} min ({cooldown:.0f}s)..."
                    )
                    time.sleep(cooldown)

        except KeyboardInterrupt:
            self._log_progress("\n[!] Interrupción detectada en bucle principal.")
            stop_reason = "KeyboardInterrupt (Ctrl+C)"

        finally:
            # Guardado final de estado y liberación de recursos
            self.state.save_to_file(self.state_file)
            self.sender.close()

            status_msg = f" Motivo de parada: {stop_reason}" if stop_reason else " Ejecución regular completada."
            self._log_progress(f"\n=== Resumen de Sesión ===")
            self._log_progress(f"Mensajes enviados en esta sesión: {session_sent_count}")
            self._log_progress(f"Total acumulado en campaña: {len(self.state.sent)}")
            self._log_progress(f"Estado persistido en: {self.state_file}")
            self._log_progress(f"{status_msg}\n")

        return session_sent_count