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
from datetime import datetime

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

    def _format_reminder_times(self, reminder: dict) -> str:
        """Formatea la hora de aviso y, si aplica, la hora real del evento."""
        reminder_time = reminder["reminder_time"]
        event_time = reminder.get("event_time") or reminder_time
        advance_minutes = reminder.get("advance_minutes") or 0

        formatted_reminder = self.time.format_for_display(reminder_time)
        if advance_minutes and event_time != reminder_time:
            formatted_event = self.time.format_for_display(event_time)
            return (
                f"    ⏰ Aviso: {formatted_reminder}\n"
                f"    📅 Evento: {formatted_event}\n"
            )

        return f"    ⏰ {formatted_reminder}\n"

    def _build_reminder_record(
        self,
        task: str,
        reminder_time: datetime,
        event_time: datetime | None = None,
        advance_minutes: int | None = None,
    ) -> dict:
        return {
            "task": task,
            "reminder_time": reminder_time,
            "event_time": event_time or reminder_time,
            "advance_minutes": advance_minutes or 0,
        }

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

    _EDIT_KEYWORDS = (
        "editar", "edita", "edite",
        "modificar", "modifica",
        "reprogramar", "reprograma",
        "cambiar hora", "cambiar la hora", "nueva hora",
        "posponer", "pospón", "adelantar",
    )

    _CANCEL_KEYWORDS = (
        "cancelar", "cancel", "cancela", "olvida", "olvidalo", "da igual",
        "no importa", "salir", "stop",
    )

    _YES_KEYWORDS = (
        "si", "sí", "yes", "quiero", "por favor", "dale", "ok", "vale", "claro",
        "afirmativo", "venga", "anda", "pues si", "pues sí",
    )

    _NO_KEYWORDS = (
        "no", "nope", "no gracias", "paso", "mejor no", "dejalo", "déjalo",
        "ninguna", "ninguno", "sin hora", "no quiero", "no hace falta",
    )

    _PENDING_NOTES_KEYWORDS = (
        "que cosas tengo pendiente", "que tengo pendiente", "que tengo anotado",
        "de que me tengo que acordar", "que tengo que acordarme",
        "que no me tengo que olvidar", "que no debo olvidar",
        "que tengo guardado", "mis notas", "que cosas tengo guardadas",
        "que me habia apuntado", "que me habia anotado", "que tengo apuntado",
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
                "/edit <id> - Cambiar la hora de uno\n"
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
            "/edit <id> - Cambiar la hora de un recordatorio\n"
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
        application.add_handler(CommandHandler("edit", self.cmd_edit))
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
            "/edit <id> - Cambiar la hora de un recordatorio\n"
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
        """Handler del comando /list - muestra recordatorios pendientes y notas sin fecha."""
        user_id = update.effective_user.id
        reminders = await self.db.get_user_reminders(user_id)
        notes = await self.db.get_user_notes(user_id)

        if not reminders and not notes:
            await update.message.reply_text("No tienes recordatorios ni notas pendientes.")
            return

        lines = []

        if notes:
            lines.append("📌 Cosas pendientes (sin fecha):\n")
            for n in notes:
                lines.append(f"[N-{n['id']}] {n['task']}\n")

        if reminders:
            if lines:
                lines.append("")
            lines.append("📋 Recordatorios programados:\n")
            for r in reminders:
                lines.append(f"[{r['id']}] {r['task']}\n{self._format_reminder_times(r)}")

        await update.message.reply_text("\n".join(lines))

    @require_registered
    async def cmd_edit(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handler del comando /edit - cambia la hora de un recordatorio."""
        user_id = update.effective_user.id

        if not context.args:
            # Sin argumentos: mostrar lista para que el usuario elija
            reminders = await self.db.get_user_reminders(user_id)
            if not reminders:
                await update.message.reply_text("No tienes recordatorios pendientes.")
                return
            lines = ["¿Cuál quieres editar? Usa /edit <id>:\n"]
            for r in reminders:
                lines.append(f"[{r['id']}] {r['task']}\n{self._format_reminder_times(r)}")
            await update.message.reply_text("\n".join(lines))
            return

        try:
            reminder_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("El ID debe ser un número.")
            return

        await self._start_edit_flow(reminder_id, user_id, update, context)

    async def _start_edit_flow(
        self,
        reminder_id: int,
        user_id: int,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Inicia el flujo de edición: verifica el recordatorio y pide la nueva hora."""
        reminder = await self.db.get_reminder(reminder_id, user_id)
        if not reminder:
            await update.message.reply_text(
                "No se encontró ese recordatorio o no te pertenece."
            )
            return

        context.user_data["pending_edit_id"] = reminder_id
        await update.message.reply_text(
            f"📝 Recordatorio [{reminder_id}]: {reminder['task']}\n"
            f"{self._format_reminder_times(reminder)}\n"
            "¿A qué nueva hora quieres ponerlo? (escribe \"cancelar\" para salir)"
        )

    async def _handle_pending_edit(
        self,
        reminder_id: int,
        user_message: str,
        user_id: int,
        user_timezone: str | None,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Procesa la nueva hora cuando hay una edición pendiente."""
        normalized = self._normalize_text(user_message)

        # Cancelar edición
        if any(kw in normalized for kw in self._CANCEL_KEYWORDS):
            context.user_data.pop("pending_edit_id", None)
            await update.message.reply_text("Edición cancelada.")
            return

        await update.message.chat.send_action("typing")
        time_context = self.time.get_context_for_llm(user_timezone)
        datetime_iso = await self.openai.parse_time_expression(user_message, time_context)

        if not datetime_iso:
            await update.message.reply_text(
                "No pude entender la hora. Intenta algo como \"a las 15:30\" o \"mañana a las 9\".\n"
                "Escribe \"cancelar\" para salir."
            )
            return

        new_time = self.time.parse_iso(datetime_iso)
        if not new_time:
            await update.message.reply_text(
                "No pude interpretar esa fecha. Intenta de nuevo o escribe \"cancelar\"."
            )
            return

        if not self.time.is_future(new_time):
            await update.message.reply_text(
                "❌ Esa hora ya ha pasado. Indica una hora futura o escribe \"cancelar\"."
            )
            return

        # Obtener el recordatorio para re-programar el scheduler
        reminder = await self.db.get_reminder(reminder_id, user_id)
        if not reminder:
            context.user_data.pop("pending_edit_id", None)
            await update.message.reply_text(
                "El recordatorio ya no existe. Edición cancelada."
            )
            return

        updated = await self.db.update_reminder_time(reminder_id, user_id, new_time)
        if not updated:
            await update.message.reply_text(
                "No se pudo actualizar el recordatorio. Intenta de nuevo."
            )
            return

        # Re-programar en el scheduler
        chat_id = update.effective_chat.id
        self.scheduler.cancel_reminder(reminder_id)
        self.scheduler.schedule_reminder(
            reminder_id=reminder_id,
            chat_id=chat_id,
            task=reminder["task"],
            reminder_time=new_time
        )

        context.user_data.pop("pending_edit_id", None)
        updated_reminder = self._build_reminder_record(reminder["task"], new_time)
        await update.message.reply_text(
            f"✅ Recordatorio actualizado.\n\n"
            f"📝 {reminder['task']}\n"
            f"{self._format_reminder_times(updated_reminder)}"
        )

    async def _handle_no_date_yesno(
        self,
        user_message: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Procesa la respuesta sí/no cuando se pregunta si quiere una hora para el recordatorio."""
        normalized = self._normalize_text(user_message)
        task = context.user_data["pending_no_date_task"]
        original_message = context.user_data.get("pending_no_date_original_message")

        if any(kw in normalized for kw in self._CANCEL_KEYWORDS):
            context.user_data.pop("pending_no_date_task", None)
            context.user_data.pop("pending_no_date_original_message", None)
            await update.message.reply_text("De acuerdo, no crearé ningún recordatorio.")
            return

        if any(normalized == kw or normalized.startswith(kw + " ") or normalized.endswith(" " + kw)
               for kw in self._YES_KEYWORDS):
            context.user_data.pop("pending_no_date_task", None)
            context.user_data.pop("pending_no_date_original_message", None)
            context.user_data["pending_no_date_awaiting_time"] = task
            context.user_data["pending_no_date_awaiting_original_message"] = original_message
            await update.message.reply_text("¿A qué hora quieres que te lo recuerde?")
            return

        if any(normalized == kw or normalized.startswith(kw + " ") or normalized.endswith(" " + kw)
               for kw in self._NO_KEYWORDS):
            context.user_data.pop("pending_no_date_task", None)
            context.user_data.pop("pending_no_date_original_message", None)
            chat_id = update.effective_chat.id
            user_id = update.effective_user.id
            note_id = await self.db.add_note(user_id, chat_id, task)
            await update.message.reply_text(
                f"Anotado. Lo guardaré en tu lista de pendientes.\n\n"
                f"📌 [N-{note_id}] {task}\n\n"
                f"Puedes verlo con /list y borrarlo con /delete N-{note_id}."
            )
            return

        await update.message.reply_text(
            "¿Quieres que te lo recuerde a alguna hora? Responde sí o no.\n"
            "(escribe \"cancelar\" para salir)"
        )

    async def _handle_no_date_time(
        self,
        user_message: str,
        user_id: int,
        user_timezone: str | None,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Procesa la hora cuando el usuario confirma que quiere recordatorio sin fecha original."""
        task = context.user_data["pending_no_date_awaiting_time"]
        original_message = context.user_data.get("pending_no_date_awaiting_original_message")
        normalized = self._normalize_text(user_message)

        if any(kw in normalized for kw in self._CANCEL_KEYWORDS):
            context.user_data.pop("pending_no_date_awaiting_time", None)
            context.user_data.pop("pending_no_date_awaiting_original_message", None)
            await update.message.reply_text("De acuerdo, no crearé ningún recordatorio.")
            return

        await update.message.chat.send_action("typing")
        time_context = self.time.get_context_for_llm(user_timezone)
        datetime_iso = await self.openai.parse_time_expression(user_message, time_context)

        if not datetime_iso:
            await update.message.reply_text(
                "No pude entender la hora. Intenta algo como \"a las 15:30\" o \"mañana a las 9\".\n"
                "Escribe \"cancelar\" para salir."
            )
            return

        new_time = self.time.parse_iso(datetime_iso)
        if not new_time:
            await update.message.reply_text(
                "No pude interpretar esa fecha. Intenta de nuevo o escribe \"cancelar\"."
            )
            return

        if not self.time.is_future(new_time):
            await update.message.reply_text(
                "❌ Esa hora ya ha pasado. Indica una hora futura o escribe \"cancelar\"."
            )
            return

        chat_id = update.effective_chat.id
        reminder_id = await self.db.add_reminder(
            user_id=user_id,
            chat_id=chat_id,
            task=task,
            reminder_time=new_time,
            original_message=original_message,
            event_time=new_time,
            advance_minutes=0
        )

        scheduled = self.scheduler.schedule_reminder(
            reminder_id=reminder_id,
            chat_id=chat_id,
            task=task,
            reminder_time=new_time
        )

        context.user_data.pop("pending_no_date_awaiting_time", None)
        context.user_data.pop("pending_no_date_awaiting_original_message", None)

        if scheduled:
            reminder_record = self._build_reminder_record(task, new_time)
            await update.message.reply_text(
                f"✅ Recordatorio creado.\n\n"
                f"📝 {task}\n"
                f"{self._format_reminder_times(reminder_record)}"
            )
        else:
            await update.message.reply_text(
                "❌ No se pudo programar el recordatorio. La fecha podría ser inválida."
            )

    async def _show_notes(self, user_id: int, update: Update) -> None:
        """Muestra la lista de notas sin fecha del usuario."""
        notes = await self.db.get_user_notes(user_id)
        if not notes:
            await update.message.reply_text(
                "No tienes nada anotado en tu lista de pendientes.\n\n"
                "Puedo guardar cosas que quieras recordar sin fecha, como:\n"
                "- \"Llamar al dentista en febrero\"\n"
                "- \"Renovar el seguro del coche\""
            )
            return
        lines = ["📌 Tus cosas pendientes:\n"]
        for n in notes:
            lines.append(f"[N-{n['id']}] {n['task']}\n")
        lines.append("\nUsa /delete N-<id> para eliminar una.")
        await update.message.reply_text("\n".join(lines))

    async def _detect_edit_intent(
        self,
        normalized: str,
        user_message: str,
        user_id: int,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """
        Detecta si el usuario quiere editar un recordatorio en lenguaje natural.

        Returns:
            True si el mensaje fue manejado como intent de edición.
        """
        if not any(kw in normalized for kw in self._EDIT_KEYWORDS):
            return False

        reminders = await self.db.get_user_reminders(user_id)
        if not reminders:
            await update.message.reply_text(
                "No tienes recordatorios pendientes para editar."
            )
            return True

        await update.message.chat.send_action("typing")
        reminder_id = await self.openai.identify_reminder_to_edit(user_message, reminders)

        if reminder_id is not None:
            # Verificar que el ID pertenece a este usuario
            reminder = await self.db.get_reminder(reminder_id, user_id)
            if reminder:
                await self._start_edit_flow(reminder_id, user_id, update, context)
                return True

        # No se identificó: mostrar lista
        lines = ["No estoy seguro de cuál quieres editar. Aquí están tus recordatorios:\n"]
        for r in reminders:
            lines.append(f"[{r['id']}] {r['task']}\n{self._format_reminder_times(r)}")
        lines.append("Usa /edit <id> para editar uno.")
        await update.message.reply_text("\n".join(lines))
        return True

    @require_registered
    async def cmd_delete(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handler del comando /delete - elimina un recordatorio."""
        user_id = update.effective_user.id

        # Obtener el ID del recordatorio o nota de los argumentos
        if not context.args:
            await update.message.reply_text(
                "Uso: /delete <id> para recordatorios o /delete N-<id> para notas.\n"
                "Usa /list para ver los IDs."
            )
            return

        arg = context.args[0].upper()

        # Detectar si es una nota (formato N-id)
        if arg.startswith("N-"):
            try:
                note_id = int(arg[2:])
            except ValueError:
                await update.message.reply_text("Formato incorrecto. Usa N-<número>, por ejemplo: N-3")
                return
            deleted = await self.db.delete_note(note_id, user_id)
            if deleted:
                await update.message.reply_text(f"Nota [N-{note_id}] eliminada.")
            else:
                await update.message.reply_text(
                    "No se encontró esa nota o no te pertenece."
                )
            return

        # Si no, es un recordatorio con ID numérico
        try:
            reminder_id = int(arg)
        except ValueError:
            await update.message.reply_text(
                "El ID debe ser un número o N-<número> para notas."
            )
            return

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
        notes = await self.db.get_user_notes(user_id)

        if not reminders and not notes:
            await update.message.reply_text("No tienes recordatorios ni notas pendientes.")
            return

        deleted_reminders = await self.db.delete_all_reminders(user_id)
        for r in reminders:
            self.scheduler.cancel_reminder(r["id"])
        deleted_notes = await self.db.delete_all_notes(user_id)

        parts = []
        if deleted_reminders:
            parts.append(f"{deleted_reminders} recordatorio(s)")
        if deleted_notes:
            parts.append(f"{deleted_notes} nota(s)")
        await update.message.reply_text(
            f"✅ Hecho. Se han borrado {' y '.join(parts)}."
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

        # Comprobar si hay una edición pendiente esperando nueva hora
        pending_edit_id = context.user_data.get("pending_edit_id")
        if pending_edit_id is not None:
            await self._handle_pending_edit(
                pending_edit_id, user_message, user_id, user_timezone, update, context
            )
            return

        # Comprobar si estamos esperando sí/no sobre si quiere hora para un recordatorio sin fecha
        if "pending_no_date_task" in context.user_data:
            await self._handle_no_date_yesno(user_message, update, context)
            return

        # Comprobar si estamos esperando la hora tras confirmar que sí quiere recordatorio
        if "pending_no_date_awaiting_time" in context.user_data:
            await self._handle_no_date_time(
                user_message, user_id, user_timezone, update, context
            )
            return

        # Indicador de "escribiendo..."
        await update.message.chat.send_action("typing")

        # Obtener contexto temporal para el LLM (con timezone del usuario)
        time_context = self.time.get_context_for_llm(user_timezone)

        # Detectar mensajes conversacionales antes de llamar a OpenAI
        normalized_message = self._normalize_text(user_message)
        if await self._handle_conversational_message(normalized_message, user, update):
            return

        # Detectar intent de edición en lenguaje natural
        if await self._detect_edit_intent(normalized_message, user_message, user_id, update, context):
            return

        # Detectar preguntas sobre notas/pendientes sin fecha
        if any(kw in normalized_message for kw in self._PENDING_NOTES_KEYWORDS):
            await self._show_notes(user_id, update)
            return

        result = await self.openai.parse_reminder(user_message, time_context)

        if not result.success:
            await update.message.reply_text(f"❌ {result.error_message}")
            return

        # El LLM identificó la tarea pero no hay fecha/hora — preguntar al usuario
        if not result.has_date:
            context.user_data["pending_no_date_task"] = result.task
            context.user_data["pending_no_date_original_message"] = user_message
            await update.message.reply_text(
                f"Entendido: \"{result.task}\"\n\n"
                "¿Quieres que te lo recuerde a alguna hora?"
            )
            return

        # Parsear la fecha devuelta por el LLM
        reminder_time = self.time.parse_iso(result.datetime_iso)
        event_time = (
            self.time.parse_iso(result.event_datetime_iso)
            if result.event_datetime_iso
            else reminder_time
        )
        advance_minutes = result.advance_minutes or 0

        if not reminder_time:
            await update.message.reply_text(
                "❌ Hubo un problema interpretando la fecha. "
                "Por favor, intenta ser más específico."
            )
            return
        if not event_time:
            event_time = reminder_time

        # Verificar que la fecha del aviso esté en el futuro
        if not self.time.is_future(reminder_time):
            context.user_data["pending_no_date_awaiting_time"] = result.task
            context.user_data["pending_no_date_awaiting_original_message"] = user_message
            await update.message.reply_text(
                "La hora de aviso ya ha pasado. ¿A qué hora quieres que te lo recuerde?\n"
                "Por favor, especifica una fecha futura. Escribe \"cancelar\" para salir."
            )
            return

        # Guardar en base de datos
        reminder_id = await self.db.add_reminder(
            user_id=user_id,
            chat_id=chat_id,
            task=result.task,
            reminder_time=reminder_time,
            original_message=user_message,
            event_time=event_time,
            advance_minutes=advance_minutes
        )

        # Programar la notificación
        scheduled = self.scheduler.schedule_reminder(
            reminder_id=reminder_id,
            chat_id=chat_id,
            task=result.task,
            reminder_time=reminder_time
        )

        if scheduled:
            reminder_record = self._build_reminder_record(
                result.task,
                reminder_time,
                event_time,
                advance_minutes,
            )
            await update.message.reply_text(
                f"✅ {result.confirmation_message}\n\n"
                f"📝 {result.task}\n"
                f"{self._format_reminder_times(reminder_record)}"
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
                f"{status} {u['display_name']}\n"
                f"   ID: {u['user_id']}\n"
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
