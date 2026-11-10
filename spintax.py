"""
spintax.py - Generador dinámico de mensajes con soporte de Spintax,
inyección de variables de contacto y cláusula obligatoria de Opt-Out.
"""

from __future__ import annotations

import random
import re
from typing import List, Optional

from models import Contact

DEFAULT_GREETINGS = [
    "¡Hola {nombre}!",
    "Buen día {nombre}, ¿cómo estás?",
    "Hola {nombre}, qué gusto saludarte.",
    "Estimado/a {nombre}, espero te encuentres muy bien.",
    "¡Hola {nombre}! Esperamos que estés teniendo una excelente semana.",
]

DEFAULT_BODIES = [
    "Te escribimos para compartirte nuestras promociones y beneficios especiales de este mes.",
    "Queremos comentarte las novedades exclusivas que tenemos preparadas para ti en esta campaña.",
    "Nos comunicamos para hacerte llegar oportunidades y descuentos diseñados especialmente para ti.",
    "Te compartimos información importante sobre nuestras promociones vigentes por tiempo limitado.",
]

DEFAULT_CLOSINGS = [
    "Quedamos muy atentos a cualquier duda o consulta.",
    "Cualquier duda que tengas, aquí estamos a la orden.",
    "Que tengas un excelente día. Saludos cordiales.",
    "¡Esperamos poder atenderte pronto!",
]

OPT_OUT_NOTE = "Responde BAJA para no recibir más avisos."


def resolve_spintax(text: str) -> str:
    """
    Resuelve recursivamente patrones Spintax con sintaxis `{opción1|opción2|opción3}`.
    Solo procesa bloques con delimitador '|' para preservar variables como {nombre}.
    """
    pattern = re.compile(r"\{([^{}]+?\|[^{}]+?)\}")
    while True:
        match = pattern.search(text)
        if not match:
            break
        options = match.group(1).split("|")
        chosen = random.choice(options)
        text = text[: match.start()] + chosen + text[match.end() :]
    return text


class SpintaxMessageGenerator:
    """
    Generador modular de mensajes dinámicos con variabilidad en
    saludo, cuerpo y despedida, más nota obligatoria de opt-out.
    """

    def __init__(
        self,
        greetings: Optional[List[str]] = None,
        bodies: Optional[List[str]] = None,
        closings: Optional[List[str]] = None,
        opt_out_note: str = OPT_OUT_NOTE,
        custom_template: Optional[str] = None,
    ):
        self.greetings = greetings or DEFAULT_GREETINGS
        self.bodies = bodies or DEFAULT_BODIES
        self.closings = closings or DEFAULT_CLOSINGS
        self.opt_out_note = opt_out_note.strip()
        self.custom_template = custom_template

    def build_message(self, contact: Contact) -> str:
        """
        Construye el mensaje personalizado para un contacto, aplicando:
        1. Selección aleatoria de componentes o plantilla spintax personalizada.
        2. Inyección de nombre y campos adicionales.
        3. Adición mandatoria de la nota de opt-out.
        """
        name = contact.name.strip() if contact.name else "amigo/a"

        if self.custom_template:
            base_text = resolve_spintax(self.custom_template)
            variables = {"nombre": name, "telefono": contact.phone, **contact.extra}
            formatted = base_text.format(**variables)
        else:
            greeting_template = random.choice(self.greetings)
            body_template = random.choice(self.bodies)
            closing_template = random.choice(self.closings)

            # Inyectar nombre en plantillas y resolver spintax interno
            greeting = resolve_spintax(greeting_template).replace("{nombre}", name)
            body = resolve_spintax(body_template).replace("{nombre}", name)
            closing = resolve_spintax(closing_template).replace("{nombre}", name)

            parts = [greeting, body, closing]
            formatted = "\n\n".join(parts)

        # Garantizar que la nota de opt-out esté siempre presente al final
        if self.opt_out_note and self.opt_out_note not in formatted:
            final_message = f"{formatted}\n\n---\n{self.opt_out_note}"
        else:
            final_message = formatted

        return final_message.strip()
