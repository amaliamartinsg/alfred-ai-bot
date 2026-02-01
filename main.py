"""
Bot de Telegram para gestión inteligente de recordatorios.
Punto de entrada principal que inicializa y coordina todos los componentes.
"""
import logging
import sys
import pytz
from telegram.ext import Application

import config
from database import DatabaseManager
from services import OpenAIService, TimeService, CityService
from scheduler import ReminderScheduler
from bot import BotHandlers, RegistrationHandler

# Configuración de logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Variables globales para los servicios (necesarias para post_init)
db: DatabaseManager = None
scheduler: ReminderScheduler = None
handlers: BotHandlers = None


async def post_init(application: Application) -> None:
    """
    Callback que se ejecuta después de que la aplicación se inicializa.
    Aquí inicializamos la BD y cargamos los recordatorios pendientes.
    """
    global db, scheduler, handlers

    # Inicializar base de datos
    await db.initialize()

    # Configurar bot en handlers para mensajes proactivos
    handlers.set_bot(application.bot)

    # Cargar recordatorios pendientes desde la base de datos
    reminders = await db.get_pending_reminders()
    loaded = 0

    for reminder in reminders:
        scheduled = scheduler.schedule_reminder(
            reminder_id=reminder["id"],
            chat_id=reminder["chat_id"],
            task=reminder["task"],
            reminder_time=reminder["reminder_time"]
        )
        if scheduled:
            loaded += 1
        else:
            await db.mark_as_notified(reminder["id"])
            logger.warning(
                f"Recordatorio {reminder['id']} tenía fecha pasada y fue marcado como perdido"
            )

    logger.info(f"Cargados {loaded} recordatorios pendientes desde la base de datos")


async def post_shutdown(application: Application) -> None:
    """Callback que se ejecuta al cerrar la aplicación."""
    global db, scheduler

    logger.info("Cerrando bot...")
    if scheduler:
        scheduler.shutdown()
    if db:
        await db.close()
    logger.info("Bot cerrado correctamente")


def main() -> None:
    """Función principal que inicializa y ejecuta el bot."""
    global db, scheduler, handlers

    logger.info("Iniciando bot de recordatorios...")

    # Validar configuración
    try:
        config.validate_config()
    except ValueError as e:
        logger.error(f"Error de configuración: {e}")
        sys.exit(1)

    # Inicializar servicios síncronos
    time_service = TimeService(config.DFT_TIMEZONE)
    timezone = pytz.timezone(config.DFT_TIMEZONE)

    openai_service = OpenAIService(
        api_key=config.OPENAI_API_KEY,
        model=config.OPENAI_MODEL,
        max_tokens=config.OPENAI_MAX_TOKENS
    )

    city_service = CityService(
        openai_client=openai_service.client,
        model=config.OPENAI_MODEL
    )

    # Crear instancia de base de datos (se inicializará en post_init)
    db = DatabaseManager(config.DATABASE_PATH)

    scheduler = ReminderScheduler(timezone)

    # Crear handlers
    handlers = BotHandlers(
        db=db,
        openai_service=openai_service,
        time_service=time_service,
        scheduler=scheduler
    )

    # Crear handler de registro
    registration_handler = RegistrationHandler(
        db=db,
        city_service=city_service
    )

    # Configurar callback de notificaciones
    scheduler.set_notification_callback(handlers.send_notification)

    # Crear aplicación de Telegram con callbacks
    application = (
        Application.builder()
        .token(config.TELEGRAM_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Registrar ConversationHandler de registro PRIMERO (tiene prioridad)
    application.add_handler(registration_handler.get_handler())

    # Registrar handlers normales
    handlers.register_handlers(application)

    # Iniciar scheduler
    scheduler.start()

    # Iniciar el bot (esto bloquea hasta que se cierre)
    logger.info("Bot iniciado. Esperando mensajes...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
