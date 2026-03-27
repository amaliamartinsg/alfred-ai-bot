"""
Handlers del bot de Telegram para gestión de recordatorios.
Implementa los comandos y manejo de mensajes.
"""
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
import logging
from functools import wraps
import unicodedata

import config
from database import DatabaseManager
from services import OpenAIService, TimeService
from scheduler import ReminderScheduler

logger = logging.getLogger(__name__)


def require_registered(func):
    """Decorador que verifica si el usuario está registrado."""
    @wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        # Admin siempre tiene acceso
        if user_id == config.ADMIN_USER_ID:
            return await func(self, update, context)

        if not await self.db.is_user_registered(user_id):
            await update.message.reply_text(
                "No estás registrado. Usa /start para comenzar el registro."
            )
            return
        return await func(self, update, context)
    return wrapper


def require_admin(func):
    """Decorador que verifica si el usuario es admin."""
    @wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id != config.ADMIN_USER_ID:
            await update.message.reply_text("No tienes permisos para este comando.")
            return
        return await func(self, update, context)
    return wrapper


class BotHandlers:
    """Gestiona los handlers del bot de Telegram."""

    def __init__(
        self,
        db: DatabaseManager,
        openai_service: OpenAIService,
        time_service: TimeService,
        scheduler: ReminderScheduler
    ):
        """
        Inicializa los handlers con las dependencias necesarias.

        Args:
            db: Gestor de base de datos.
            openai_service: Servicio de OpenAI.
            time_service: Servicio de tiempo.
            scheduler: Programador de recordatorios.
        """
        self.db = db
        self.openai = openai_service
        self.time = time_service
        self.scheduler = scheduler
        self._bot: Bot | None = None

    def set_bot(self, bot: Bot) -> None:
        """Configura la instancia del bot para enviar mensajes proactivos."""
        self._bot = bot

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normaliza texto para comparaciones simples de intencion."""
        normalized = unicodedata.normalize("NFD", text)
        stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        return " ".join(stripped.lower().split())

    _GREETING_KEYWORDS = (
        "hola", "hey", "buenas", "buenos dias", "buenas tardes", "buenas noches",
        "ola", "saludos", "hi", "hello", "que hay", "que pasa", "que es lo que hay",
    )

    _WELLBEING_KEYWORDS = (
        "que tal estas", "como estas", "como te encuentras", "como te va",
        "como andas", "como va todo", "todo bien", "que tal todo", "que tal",
        "como estas hoy", "te encuentras bien", "estas bien",
    )

    _GRATITUDE_KEYWORDS = (
        "gracias", "muchas gracias", "mil gracias", "grac", "te lo agradezco",
        "muy amable",
    )

    _HELP_KEYWORDS = (
        "que puedes hacer", "para que sirves", "que haces", "en que me ayudas",
        "que se puede hacer", "que comandos", "como funciona", "ayuda",
        "como te uso", "como puedo usarte",
    )

    async def _handle_conversational_message(
        self,
        normalized: str,
        user: dict | None,
        update: Update,
    ) -> bool:
        """
        Detecta mensajes conversacionales (saludos, agradecimientos, preguntas de ayuda)
        y responde sin pasar por OpenAI.

        Returns:
            True si el mensaje fue manejado aquí y no debe procesarse como recordatorio.
        """
        name = user["display_name"] if user else "usuario"

        if any(kw in normalized for kw in self._WELLBEING_KEYWORDS):
            await update.message.reply_text(
                f"Estoy muy bien, ¡gracias por preguntar! Pero estaré más feliz ayudándote con lo que necesites.\n\n"
                f"Puedes enviarme recordatorios de cualquier cosa, {name}. Por ejemplo:\n"
                "- \"Recuérdame tomar la medicación a las 21:00\"\n"
                "- \"Llamar a mamá el domingo a mediodía\"\n"
                "- \"Entregar el informe mañana antes de las 9\""
            )
            return True

        if any(kw == normalized or normalized.startswith(kw + " ") or normalized.endswith(" " + kw)
               or (" " + kw + " ") in normalized
               for kw in self._GREETING_KEYWORDS):
            await update.message.reply_text(
                f"Hola {name}. Soy Alfred, tu asistente de recordatorios.\n\n"
                "Puedo ayudarte a no olvidar nada. Solo dime qué tienes que hacer y cuándo, por ejemplo:\n"
                "- \"Recuérdame llamar al médico mañana a las 10\"\n"
                "- \"Sacar la basura en 20 minutos\"\n"
                "- \"Reunión con el equipo el lunes a las 16:00\"\n\n"
                "También puedes usar:\n"
                "/list - Ver tus recordatorios pendientes\n"
                "/delete <id> - Eliminar uno\n"
                "/delete_all - Eliminar todos"
            )
            return True

        if any(kw in normalized for kw in self._GRATITUDE_KEYWORDS):
            await update.message.reply_text("De nada. Cuando quieras, aquí estoy.")
            return True

        if any(kw in normalized for kw in self._HELP_KEYWORDS):
            await update.message.reply_text(self._build_user_help_message(name))
            return True

        return False

    @staticmethod
    def _build_user_help_message(name: str) -> str:
        """Mensaje de ayuda para usuarios normales."""
        return (
            f"Hola {name}. Soy tu asistente de recordatorios.\n\n"
            "Puedes crear recordatorios con lenguaje natural, por ejemplo:\n"
            "- \"Recuerdame llamar al dentista manana a las 10\"\n"
            "- \"Sacar la basura en 30 minutos\"\n"
            "- \"Reunion con el equipo el viernes a las 15:00\"\n\n"
            "Comandos disponibles:\n"
            "/list - Ver recordatorios pendientes\n"
            "/delete <id> - Eliminar un recordatorio\n"
            "/delete_all - Eliminar todos los recordatorios pendientes\n"
            "/help - Ver esta ayuda"
        )

    def register_handlers(self, application: Application) -> None:
        """
        Registra todos los handlers en la aplicación.
        Nota: /start se maneja en RegistrationHandler (ConversationHandler).

        Args:
            application: Instancia de Application de python-telegram-bot.
        """
        # Comandos de usuario
        application.add_handler(CommandHandler("help", self.cmd_help))
        application.add_handler(CommandHandler("list", self.cmd_list))
        application.add_handler(CommandHandler("delete", self.cmd_delete))
        application.add_handler(CommandHandler("delete_all", self.cmd_delete_all))

        # Comandos de admin
        application.add_handler(CommandHandler("admin_invite", self.cmd_admin_invite))
        application.add_handler(CommandHandler("admin_users", self.cmd_admin_users))
        application.add_handler(CommandHandler("admin_revoke", self.cmd_admin_revoke))

        # Mensajes de texto (procesados como recordatorios)
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        logger.info("Handlers registrados correctamente")

    @require_registered
    async def cmd_help(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handler del comando /help."""
        user_id = update.effective_user.id
        user = await self.db.get_user(user_id)
        name = user["display_name"] if user else "usuario"

        help_message = (
            f"¡Hola {name}! Soy tu asistente de recordatorios.\n\n"
            "Simplemente escríbeme lo que necesitas recordar y cuándo, por ejemplo:\n"
            "- \"Recuérdame llamar al dentista mañana a las 10\"\n"
            "- \"Sacar la basura en 30 minutos\"\n"
            "- \"Reunión con el equipo el viernes a las 15:00\"\n\n"
            "Comandos disponibles:\n"
            "/list - Ver recordatorios pendientes\n"
            "/delete <id> - Eliminar un recordatorio\n"
            "/delete_all - Eliminar todos los recordatorios pendientes\n"
            "/help - Ver esta ayuda"
        )

        # Mostrar comandos admin si es admin
        if user_id == config.ADMIN_USER_ID:
            help_message += (
                "\n\n🔐 Comandos de admin:\n"
                "/admin_invite - Generar código de invitación\n"
                "/admin_users - Ver usuarios registrados\n"
                "/admin_revoke <user_id> - Revocar acceso a usuario"
            )

        await update.message.reply_text(help_message)

    @require_registered
    async def cmd_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handler del comando /list - muestra recordatorios pendientes."""
        user_id = update.effective_user.id
        reminders = await self.db.get_user_reminders(user_id)

        if not reminders:
            await update.message.reply_text("No tienes recordatorios pendientes.")
            return

        lines = ["📋 Tus recordatorios pendientes:\n"]
        for r in reminders:
            formatted_time = self.time.format_for_display(r["reminder_time"])
            lines.append(f"[{r['id']}] {r['task']}\n    ⏰ {formatted_time}\n")

        await update.message.reply_text("\n".join(lines))

    @require_registered
    async def cmd_delete(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handler del comando /delete - elimina un recordatorio."""
        user_id = update.effective_user.id

        # Obtener el ID del recordatorio de los argumentos
        if not context.args:
            await update.message.reply_text(
                "Uso: /delete <id>\n"
                "Usa /list para ver los IDs de tus recordatorios."
            )
            return

        try:
            reminder_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("El ID debe ser un número.")
            return

        # Intentar eliminar
        deleted = await self.db.delete_reminder(reminder_id, user_id)

        if deleted:
            self.scheduler.cancel_reminder(reminder_id)
            await update.message.reply_text(f"Recordatorio [{reminder_id}] eliminado.")
        else:
            await update.message.reply_text(
                "No se encontró ese recordatorio o no te pertenece."
            )

    @require_registered
    async def cmd_delete_all(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handler del comando /delete_all - elimina todos los recordatorios del usuario."""
        user_id = update.effective_user.id

        reminders = await self.db.get_user_reminders(user_id)
        if not reminders:
            await update.message.reply_text("No tienes recordatorios pendientes.")
            return

        deleted = await self.db.delete_all_reminders(user_id)
        for r in reminders:
            self.scheduler.cancel_reminder(r["id"])
        await update.message.reply_text(
            f"✅ Hecho. Se han borrado todos tus recordatorios ({deleted})."
        )

    @require_registered
    async def handle_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handler para mensajes de texto - procesa como recordatorio."""
        user_message = update.message.text
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        # Log de información del mensaje
        user = update.effective_user
        logger.info("=" * 50)
        logger.info("MENSAJE RECIBIDO:")
        logger.info(f"  user_id: {user_id}")
        logger.info(f"  chat_id: {chat_id}")
        logger.info(f"  username: @{user.username}")
        logger.info(f"  first_name: {user.first_name}")
        logger.info(f"  last_name: {user.last_name}")
        logger.info(f"  is_bot: {user.is_bot}")
        logger.info(f"  language_code: {user.language_code}")
        logger.info(f"  message_id: {update.message.message_id}")
        logger.info(f"  date: {update.message.date}")
        logger.info(f"  text: {user_message}")
        logger.info("=" * 50)

        # Indicador de "escribiendo..."
        await update.message.chat.send_action("typing")

        # Obtener timezone del usuario
        user = await self.db.get_user(user_id)
        user_timezone = user["timezone"] if user else None

        # Obtener contexto temporal para el LLM (con timezone del usuario)
        time_context = self.time.get_context_for_llm(user_timezone)

        # Detectar mensajes conversacionales antes de llamar a OpenAI
        normalized_message = self._normalize_text(user_message)
        if await self._handle_conversational_message(normalized_message, user, update):
            return

        result = await self.openai.parse_reminder(user_message, time_context)

        if not result.success:
            await update.message.reply_text(f"❌ {result.error_message}")
            return

        # Parsear la fecha devuelta por el LLM
        reminder_time = self.time.parse_iso(result.datetime_iso)

        if not reminder_time:
            await update.message.reply_text(
                "❌ Hubo un problema interpretando la fecha. "
                "Por favor, intenta ser más específico."
            )
            return

        # Verificar que la fecha esté en el futuro
        if not self.time.is_future(reminder_time):
            await update.message.reply_text(
                "❌ La fecha indicada ya ha pasado. "
                "Por favor, especifica una fecha futura."
            )
            return

        # Guardar en base de datos
        reminder_id = await self.db.add_reminder(
            user_id=user_id,
            chat_id=chat_id,
            task=result.task,
            reminder_time=reminder_time
        )

        # Programar la notificación
        scheduled = self.scheduler.schedule_reminder(
            reminder_id=reminder_id,
            chat_id=chat_id,
            task=result.task,
            reminder_time=reminder_time
        )

        if scheduled:
            formatted_time = self.time.format_for_display(reminder_time)
            await update.message.reply_text(
                f"✅ {result.confirmation_message}\n\n"
                f"📝 {result.task}\n"
                f"⏰ {formatted_time}"
            )
        else:
            await update.message.reply_text(
                "❌ No se pudo programar el recordatorio. "
                "La fecha podría ser inválida."
            )

    # ============ Comandos de Admin ============

    @require_admin
    async def cmd_admin_invite(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Genera un código de invitación."""
        code = await self.db.create_invitation_code()
        await update.message.reply_text(
            f"🎟️ Nuevo código de invitación:\n\n"
            f"`{code}`\n\n"
            "Comparte este código con el usuario que quieras invitar.",
            parse_mode="Markdown"
        )

    @require_admin
    async def cmd_admin_users(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Lista todos los usuarios registrados."""
        users = await self.db.get_all_users()

        if not users:
            await update.message.reply_text("No hay usuarios registrados.")
            return

        lines = ["👥 Usuarios registrados:\n"]
        for u in users:
            status = "✅" if u["is_active"] else "❌"
            lines.append(
                f"{status} {u['display_name']} ({u['user_id']})\n"
                f"   📍 {u['city']} ({u['timezone']})\n"
            )

        await update.message.reply_text("\n".join(lines))

    @require_admin
    async def cmd_admin_revoke(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Revoca el acceso a un usuario."""
        if not context.args:
            await update.message.reply_text(
                "Uso: /admin_revoke <user_id>\n"
                "Usa /admin_users para ver los IDs."
            )
            return

        try:
            target_user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("El user_id debe ser un número.")
            return

        if target_user_id == config.ADMIN_USER_ID:
            await update.message.reply_text("No puedes revocarte a ti mismo.")
            return

        revoked = await self.db.deactivate_user(target_user_id)

        if revoked:
            await update.message.reply_text(f"✅ Usuario {target_user_id} desactivado.")
        else:
            await update.message.reply_text("No se encontró ese usuario.")

    async def send_notification(
        self,
        reminder_id: int,
        chat_id: int,
        task: str
    ) -> None:
        """
        Envía una notificación proactiva cuando llega la hora del recordatorio.

        Args:
            reminder_id: ID del recordatorio.
            chat_id: ID del chat donde enviar.
            task: Descripción de la tarea.
        """
        if not self._bot:
            logger.error("Bot no configurado para enviar notificaciones")
            return

        try:
            # Generar mensaje creativo con el LLM
            notification_message = await self.openai.generate_notification_message(task)

            await self._bot.send_message(
                chat_id=chat_id,
                text=f"🔔 {notification_message}"
            )

            # Marcar como notificado en la base de datos
            await self.db.mark_as_notified(reminder_id)

            logger.info(f"Notificación enviada para recordatorio {reminder_id}")

        except Exception as e:
            logger.error(f"Error enviando notificación {reminder_id}: {e}")
