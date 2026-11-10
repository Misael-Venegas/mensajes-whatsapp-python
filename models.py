"""
models.py - Modelos de datos para el motor de campañas de WhatsApp.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


def normalize_phone(phone: str) -> str:
    """
    Normaliza el número telefónico extrayendo solo dígitos.
    Remueve signos +, guiones, espacios y paréntesis.
    """
    cleaned = re.sub(r"[^\d]", "", str(phone))
    return cleaned


@dataclass
class Contact:
    """Representa un contacto destinatario de la campaña."""

    phone: str
    name: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def clean_phone(self) -> str:
        return normalize_phone(self.phone)


@dataclass
class EngineConfig:
    """Configuración del motor Anti-Ban / Anti-Spike y límites de ejecución."""

    warmup_threshold: int = 5  # Primeros 5 mensajes en modo calentamiento
    warmup_min_delay: float = 35.0  # Segundos min pausa inicial
    warmup_max_delay: float = 65.0  # Segundos max pausa inicial
    standard_min_delay: float = 20.0  # Segundos min pausa regular
    standard_max_delay: float = 45.0  # Segundos max pausa regular
    batch_size: int = 20  # Tamaño del lote por defecto
    cooldown_min_seconds: float = 25.0 * 60.0  # 25 minutos (1500 seg)
    cooldown_max_seconds: float = 40.0 * 60.0  # 40 minutos (2400 seg)
    hard_stop_limit: int = 120  # Límite máximo de mensajes por ejecución
    initial_sync_delay: float = 15.0  # Pausa inicial para sincronización de WhatsApp Web
    user_data_dir: str = "./whatsapp_session"  # Ruta de sesión persistente de Playwright


@dataclass
class CampaignState:
    """
    Control de persistencia de estado por campaña.
    Permite reanudación idempotente de envíos.
    """

    campaign_name: str
    sent: List[str] = field(default_factory=list)
    failed: Dict[str, str] = field(default_factory=dict)
    last_updated: Optional[str] = None

    def is_sent(self, phone: str) -> bool:
        norm = normalize_phone(phone)
        return norm in self.sent_set

    @property
    def sent_set(self) -> Set[str]:
        return set(self.sent)

    def mark_sent(self, phone: str) -> None:
        norm = normalize_phone(phone)
        if norm not in self.sent:
            self.sent.append(norm)
        self.failed.pop(norm, None)
        self.last_updated = datetime.now().isoformat()

    def mark_failed(self, phone: str, reason: str) -> None:
        norm = normalize_phone(phone)
        self.failed[norm] = reason
        self.last_updated = datetime.now().isoformat()

    def save_to_file(self, filepath: Path) -> None:
        data = {
            "campaign_name": self.campaign_name,
            "total_sent": len(self.sent),
            "sent": self.sent,
            "failed": self.failed,
            "last_updated": self.last_updated or datetime.now().isoformat(),
        }
        filepath.parent.mkdir(parents=True, exist_ok=True)
        # Escritura atómica vía archivo temporal para prevenir corrupción si se interrumpe
        tmp_file = filepath.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_file.replace(filepath)

    @classmethod
    def load_from_file(cls, filepath: Path, campaign_name: str) -> CampaignState:
        if not filepath.exists():
            return cls(campaign_name=campaign_name)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(
                campaign_name=data.get("campaign_name", campaign_name),
                sent=data.get("sent", []),
                failed=data.get("failed", {}),
                last_updated=data.get("last_updated"),
            )
        except Exception:
            return cls(campaign_name=campaign_name)

