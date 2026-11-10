"""
test_campaign_runner.py - Suite de pruebas unitarias para el motor de WhatsApp.
Ejecución rápida (cero esperas reales) usando unittest.mock y pytest.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from campaign_runner import CampaignRunner, chunk_list, load_contacts_from_file
from models import CampaignState, Contact, EngineConfig, normalize_phone
from sender import DryRunSender, MessageSender
from spintax import OPT_OUT_NOTE, SpintaxMessageGenerator, resolve_spintax


@pytest.fixture
def temp_campaign_dir(tmp_path: Path) -> Path:
    """Provee un directorio temporal limpio para cada test."""
    return tmp_path


def create_mock_contacts(count: int, prefix: str = "52155000") -> list[Contact]:
    """Genera una lista de N contactos con datos válidos."""
    return [
        Contact(
            phone=f"{prefix}{i:04d}",
            name=f"Contacto {i}",
        )
        for i in range(1, count + 1)
    ]


class TestAntiSpikeAndEngine:
    """Casos 1 al 4: Motor de lotes, anti-ban, idempotencia y hard stop."""

    @patch("time.sleep", return_value=None)
    def test_warmup_vs_ritmo_normal(self, mock_sleep: MagicMock, temp_campaign_dir: Path):
        """
        Caso 1: Verificar que los primeros 5 mensajes llamen a time.sleep
        con valores de Warm-up [35.0, 65.0] seg, y del 6º en adelante
        con Jitter regular [20.0, 45.0] seg.
        """
        contacts = create_mock_contacts(8)  # 8 contactos en un solo lote
        config = EngineConfig(
            warmup_threshold=5,
            warmup_min_delay=35.0,
            warmup_max_delay=65.0,
            standard_min_delay=20.0,
            standard_max_delay=45.0,
            batch_size=20,
        )

        sender = DryRunSender(verbose=False)
        runner = CampaignRunner(
            campaign_name="test_warmup",
            sender=sender,
            config=config,
            state_dir=temp_campaign_dir,
        )

        sent_count = runner.run(contacts)
        assert sent_count == 8

        # Extraer los argumentos pasados a time.sleep
        sleep_durations = [c.args[0] for c in mock_sleep.call_args_list]

        # Debe haber al menos 8 pausas inter-mensaje
        assert len(sleep_durations) == 8

        # Mensajes 1 al 5: Warm-up (35 a 65 segundos)
        for i in range(5):
            delay = sleep_durations[i]
            assert 35.0 <= delay <= 65.0, (
                f"Mensaje {i+1} no respetó rango de Warm-up [35.0, 65.0]: fue {delay}"
            )

        # Mensajes 6 al 8: Ritmo estándar (20 a 45 segundos)
        for i in range(5, 8):
            delay = sleep_durations[i]
            assert 20.0 <= delay <= 45.0, (
                f"Mensaje {i+1} no respetó rango estándar [20.0, 45.0]: fue {delay}"
            )

    @patch("time.sleep", return_value=None)
    def test_particion_lotes_y_cooldown(self, mock_sleep: MagicMock, temp_campaign_dir: Path):
        """
        Caso 2: Con 50 contactos y lotes de 20 (3 lotes: 20, 20 y 10),
        verificar que el Cooldown largo (25-40 min = 1500-2400s) se ejecute
        exactamente 2 veces (tras lote 1 y 2, pero NO tras el último lote).
        """
        contacts = create_mock_contacts(50)
        config = EngineConfig(
            batch_size=20,
            cooldown_min_seconds=1500.0,  # 25 min
            cooldown_max_seconds=2400.0,  # 40 min
            hard_stop_limit=200,
        )

        sender = DryRunSender(verbose=False)
        runner = CampaignRunner(
            campaign_name="test_cooldown",
            sender=sender,
            config=config,
            state_dir=temp_campaign_dir,
        )

        sent_count = runner.run(contacts)
        assert sent_count == 50

        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]

        # Identificar llamadas de Cooldown largo (entre 1500 y 2400 s)
        cooldown_calls = [s for s in sleep_calls if 1500.0 <= s <= 2400.0]

        assert len(cooldown_calls) == 2, (
            f"Se esperaban exactamente 2 descansos de Cooldown largo, se obtuvieron: {len(cooldown_calls)}"
        )

        # Verificar que la última llamada a sleep NO sea un cooldown
        # (tras el último lote no hay cooldown)
        assert sleep_calls[-1] < 1500.0, "El último sleep no debió ser un Cooldown largo."

    @patch("time.sleep", return_value=None)
    def test_reanudacion_campana_idempotencia(self, mock_sleep: MagicMock, temp_campaign_dir: Path):
        """
        Caso 3: Simular un estado previo donde 15 de 40 contactos ya fueron enviados,
        comprobando que el motor procesa únicamente los 25 restantes.
        """
        contacts = create_mock_contacts(40)

        # Pre-poblar estado con los primeros 15 contactos como 'ya enviados'
        already_sent_phones = [c.clean_phone for c in contacts[:15]]
        state_file = temp_campaign_dir / "estado_test_idempotencia.json"
        state_data = {
            "campaign_name": "test_idempotencia",
            "sent": already_sent_phones,
            "failed": {},
            "last_updated": "2026-03-01T10:00:00",
        }
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f)

        mock_sender = MagicMock(spec=MessageSender)
        mock_sender.send.return_value = True

        runner = CampaignRunner(
            campaign_name="test_idempotencia",
            sender=mock_sender,
            state_dir=temp_campaign_dir,
        )

        sent_count = runner.run(contacts)

        # Solo debe haber enviado los 25 contactos pendientes
        assert sent_count == 25
        assert mock_sender.send.call_count == 25

        # Verificar que ninguno de los primeros 15 teléfonos fue enviado de nuevo
        called_phones = [c.args[0] for c in mock_sender.send.call_args_list]
        for phone in already_sent_phones:
            assert phone not in called_phones, f"El teléfono {phone} ya estaba enviado y fue reprocesado."

        # El estado final debe contener los 40 contactos
        assert len(runner.state.sent) == 40

    @patch("time.sleep", return_value=None)
    def test_limite_sesion_hard_stop(self, mock_sleep: MagicMock, temp_campaign_dir: Path):
        """
        Caso 4: Simular 150 contactos con límite de sesión (Hard Stop) de 120
        y comprobar que se detiene exactamente en el envío 120.
        """
        contacts = create_mock_contacts(150)
        config = EngineConfig(
            batch_size=20,
            hard_stop_limit=120,
        )

        mock_sender = MagicMock(spec=MessageSender)
        mock_sender.send.return_value = True

        runner = CampaignRunner(
            campaign_name="test_hard_stop",
            sender=mock_sender,
            config=config,
            state_dir=temp_campaign_dir,
        )

        sent_count = runner.run(contacts)

        assert sent_count == 120
        assert mock_sender.send.call_count == 120
        assert len(runner.state.sent) == 120


class TestSpintaxGenerator:
    """Caso 5: Generador de mensajes dinámicos y cláusula de Opt-Out."""

    def test_spintax_incluye_nombre_y_opt_out_y_genera_variaciones(self):
        """
        Caso 5: Comprobar que el texto incluye el nombre del contacto,
        la nota de baja y genera variaciones entre diferentes llamadas.
        """
        generator = SpintaxMessageGenerator()
        contact = Contact(phone="5215512345678", name="Carlos Mendoza")

        generated_messages = [generator.build_message(contact) for _ in range(30)]

        for msg in generated_messages:
            # 1. Comprobar que incluye el nombre
            assert "Carlos Mendoza" in msg, "El mensaje generado debe incluir el nombre del contacto."

            # 2. Comprobar que incluye la nota de baja (Opt-out)
            assert "Responde BAJA para no recibir más avisos" in msg, (
                "El mensaje generado debe incluir la nota obligatoria de opt-out."
            )

        # 3. Comprobar que genera variaciones
        unique_messages = set(generated_messages)
        assert len(unique_messages) > 1, (
            "Se esperaba variabilidad entre los 30 mensajes generados (Spintax)."
        )

    def test_resolve_spintax_syntax(self):
        """Verifica la resolución sintáctica de patrones {A|B|C}."""
        pattern = "{Hola|Buen día|Saludos} {amigo|colega}"
        resolved_results = {resolve_spintax(pattern) for _ in range(50)}
        assert len(resolved_results) > 1
        valid_greetings = ["Hola", "Buen día", "Saludos"]
        valid_nouns = ["amigo", "colega"]

        for res in resolved_results:
            assert any(res.startswith(g) for g in valid_greetings), f"Saludo no válido en '{res}'"
            assert any(res.endswith(n) for n in valid_nouns), f"Sujeto no válido en '{res}'"


class TestGracefulShutdownAndPersistence:
    """Pruebas adicionales de resiliencia: Ctrl+C y guardado de estado."""

    @patch("time.sleep", return_value=None)
    def test_graceful_shutdown_saves_exact_state(self, mock_sleep: MagicMock, temp_campaign_dir: Path):
        """Verifica que si runner.interrupted es True, se detiene y persiste."""
        contacts = create_mock_contacts(20)
        config = EngineConfig(batch_size=5)

        sender = DryRunSender(verbose=False)
        runner = CampaignRunner(
            campaign_name="test_shutdown",
            sender=sender,
            config=config,
            state_dir=temp_campaign_dir,
        )

        # Simular interrupción después del envío 3
        original_send = sender.send
        sent_calls = 0

        def send_and_interrupt(phone: str, msg: str) -> bool:
            nonlocal sent_calls
            sent_calls += 1
            res = original_send(phone, msg)
            if sent_calls >= 3:
                runner.interrupted = True
            return res

        sender.send = send_and_interrupt

        sent_count = runner.run(contacts)
        assert sent_count == 3
        assert len(runner.state.sent) == 3

        # Verificar persistencia en disco
        state_file = temp_campaign_dir / "estado_test_shutdown.json"
        assert state_file.exists()
        loaded = CampaignState.load_from_file(state_file, "test_shutdown")
        assert len(loaded.sent) == 3

    def test_normalize_phone_formats(self):
        """Verifica normalización de números con +, espacios, guiones y paréntesis."""
        assert normalize_phone("+52 (55) 1234-5678") == "525512345678"
        assert normalize_phone("  +1-800-555-0199  ") == "18005550199"
        assert normalize_phone("5215512345678") == "5215512345678"
