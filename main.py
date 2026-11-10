"""
main.py - Interfaz CLI para el envío manual esporádico por lotes en WhatsApp Web.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from campaign_runner import CampaignRunner, load_contacts_from_file
from models import EngineConfig
from sender import DryRunSender, PlaywrightWhatsAppSender
from spintax import SpintaxMessageGenerator


def setup_interactive_session(user_data_dir: str) -> None:
    """
    Abre una ventana de navegador dedicada para que el usuario pueda
    iniciar sesión en WhatsApp Web (escaneando el código QR) con calma.
    La sesión se guarda permanentemente en user_data_dir.
    """
    print("\n=======================================================")
    print("      CONFIGURACIÓN INICIAL DE SESIÓN DE WHATSAPP      ")
    print("=======================================================")
    print(f"[*] Directorio de sesión: {Path(user_data_dir).resolve()}")
    print("[*] Abriendo navegador...")
    
    sender = PlaywrightWhatsAppSender(
        user_data_dir=user_data_dir,
        headless=False,
        sync_delay=2.0,
    )
    sender.initialize()

    print("\n-------------------------------------------------------")
    print("   INSTRUCCIONES PARA VINCULAR TU WHATSAPP:")
    print("   1. En tu celular, abre WhatsApp.")
    print("   2. Toca en Menú (tres puntos) o Configuración.")
    print("   3. Selecciona 'Dispositivos vinculados' > 'Vincular un dispositivo'.")
    print("   4. Escanea el código QR que ves en la pantalla del navegador.")
    print("-------------------------------------------------------")
    input("\n>> Presiona [ENTER] una vez que tus chats hayan cargado por completo para guardar la sesión: ")

    sender.close()
    print("\n[✓] ¡Sesión vinculada y guardada exitosamente!")
    print(f"[✓] Las cookies y credenciales han quedado en: {user_data_dir}")
    print("[✓] Ya puedes ejecutar tus campañas sin necesidad de escanear el QR nuevamente.\n")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CLI para campañas de mensajería por lotes en WhatsApp Web (Uso Esporádico Anti-Ban)."
    )

    parser.add_argument(
        "--setup-session",
        "--login",
        action="store_true",
        help="Abre el navegador para escanear el código QR y guardar la sesión de WhatsApp Web.",
    )
    parser.add_argument(
        "--campaign",
        "-c",
        required=False,
        default=None,
        help="Identificador único de la campaña (ej. 'promo_marzo', 'reactivacion').",
    )
    parser.add_argument(
        "--input",
        "-i",
        required=False,
        default=None,
        type=str,
        help="Ruta al archivo de contactos en formato CSV o JSON (ej. contactos.csv).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Modo simulación: no abre navegador ni despacha mensajes a WhatsApp Web.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Tamaño de cada lote de contactos (por defecto: 20).",
    )
    parser.add_argument(
        "--hard-stop",
        type=int,
        default=120,
        help="Límite máximo de mensajes permitidos para esta corrida (por defecto: 120).",
    )
    parser.add_argument(
        "--user-data-dir",
        type=str,
        default="./whatsapp_session",
        help="Directorio local para persistir la sesión y cookies del navegador.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Ejecuta el navegador en segundo plano sin ventana gráfica.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Modo rápido para pruebas: minimiza las pausas a fracciones de segundo.",
    )
    parser.add_argument(
        "--template",
        type=str,
        default=None,
        help="Plantilla de texto directa con sintaxis Spintax {opc1|opc2} y variable {nombre}.",
    )
    parser.add_argument(
        "--template-file",
        type=str,
        default=None,
        help="Ruta a un archivo de texto (.txt) que contiene el mensaje/plantilla Spintax.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    # Si se pide únicamente vincular sesión
    if args.setup_session:
        setup_interactive_session(args.user_data_dir)
        sys.exit(0)

    # Validar argumentos obligatorios para campaña
    if not args.campaign:
        print("[ERROR] Debes especificar el nombre de la campaña con --campaign (ej. --campaign 'promo_mes')")
        print("        O si deseas vincular tu cuenta primero, ejecuta: python main.py --setup-session")
        sys.exit(1)

    if not args.input:
        print("[ERROR] Debes especificar el archivo de contactos con --input (ej. --input contactos.csv)")
        sys.exit(1)

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"[ERROR] El archivo de contactos no existe: {input_path}")
        sys.exit(1)

    # Cargar plantilla personalizada si se indicó archivo o texto directo
    custom_template = None
    if args.template_file:
        template_file_path = Path(args.template_file).resolve()
        if not template_file_path.exists():
            print(f"[ERROR] El archivo de plantilla no existe: {template_file_path}")
            sys.exit(1)
        with open(template_file_path, "r", encoding="utf-8") as tf:
            custom_template = tf.read().strip()
    elif args.template:
        custom_template = args.template

    print("\n=======================================================")
    print("   WHATSAPP BATCH MESSAGING TOOL - ANTI-SPIKE ENGINE   ")
    print("=======================================================")
    print(f"[*] Campaña:        {args.campaign}")
    print(f"[*] Archivo fuente: {input_path.name}")
    print(f"[*] Modo de envío:  {'DRY-RUN (Simulación)' if args.dry_run else 'PRODUCCIÓN (WhatsApp Web)'}")
    print(f"[*] Tamaño de lote: {args.batch_size} contactos")
    print(f"[*] Límite sesión:  {args.hard_stop} mensajes")
    if custom_template:
        print("[*] Plantilla:      Personalizada (cargada)")
    else:
        print("[*] Plantilla:      Spintax dinámica predeterminada")
    print("=======================================================\n")

    # Configurar motor Anti-Ban
    config = EngineConfig(
        batch_size=args.batch_size,
        hard_stop_limit=args.hard_stop,
        user_data_dir=args.user_data_dir,
    )

    # Modo rápido para tests manuales
    if args.fast:
        print("[!] ATENCIÓN: Flag '--fast' activo. Se omiten pausas largas anti-ban para propósitos de prueba.")
        config.warmup_min_delay = 0.2
        config.warmup_max_delay = 0.5
        config.standard_min_delay = 0.1
        config.standard_max_delay = 0.3
        config.cooldown_min_seconds = 1.0
        config.cooldown_max_seconds = 2.0
        config.initial_sync_delay = 1.0

    # Inicializar generador Spintax
    generator = SpintaxMessageGenerator(custom_template=custom_template)

    # Cargar contactos
    try:
        contacts = load_contacts_from_file(input_path)
    except Exception as e:
        print(f"[ERROR] Fallo al leer contactos: {e}")
        sys.exit(1)

    # Inyección del sender
    if args.dry_run:
        sender = DryRunSender()
    else:
        sender = PlaywrightWhatsAppSender(
            user_data_dir=args.user_data_dir,
            headless=args.headless,
            sync_delay=config.initial_sync_delay,
        )

    # Inicializar y correr campaña
    runner = CampaignRunner(
        campaign_name=args.campaign,
        sender=sender,
        config=config,
        generator=generator,
    )

    sent_count = runner.run(contacts)
    print(f"[✓] Proceso finalizado. Total procesados exitosamente en esta corrida: {sent_count}")


if __name__ == "__main__":
    main()
