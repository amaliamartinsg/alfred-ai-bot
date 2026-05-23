"""
Handlers del bot de Telegram para gestión de recordatorios.
Implementa los comandos y manejo de mensajes.
"""
from datetime import timedelta

from telegram import Update, Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import logging
from functools import wraps
import unicodedata
from datetime import datetime

import config
from database import DatabaseManager
from services import OpenAIService, TimeService, IntentClassifier, Intent, search_user_reminders
from scheduler import ReminderScheduler

logger = logging.getLogger(__name__)


def require_registered(func):
    """Decorador que verifica si el usuario está registrado."""
    @wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

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
        scheduler: ReminderScheduler,
        intent_classifier: IntentClassifier | None = None,
    ):
        self.db = db
        self.openai = openai_service
        self.time = time_service
        self.scheduler = scheduler
        self.intent_classifier = intent_classifier
        self._bot: Bot | None = None

    def set_bot(self, bot: Bot) -> None:
        """Configura la instancia del bot para enviar mensajes proactivos."""
        self._bot = bot

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = unicodedata.normalize("NFD", text)
        stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        return " ".join(stripped.lower().split())

    def _format_reminder_times(self, reminder: dict) -> str:
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
        "gracias", "muchas gracias", "mil gracias", "te lo agradezco",
        "muy amable", "genial", "perfecto", "perfe", "estupendo", "fenomenal",
        "guay", "chévere", "que bien", "muy bien", "bien hecho",
        "excelente", "increible", "increíble", "fantastico", "fantástico",
        "ok", "vale", "de acuerdo", "entendido", "claro que si",
    )

    # Palabras que indican petición explícita de recordatorio
    _CREATE_REMINDER_KEYWORDS = (
        "recuerdame", "recuerda", "recuérdame", "recuérdate",
        "apunta", "apuntame", "apúntame",
        "anota", "anotame", "anótame",
        "avisa", "avisame", "avísame",
        "programa", "agenda", "crea",
        "pon un recordatorio", "ponme un recordatorio",
        "añade un recordatorio", "nuevo recordatorio",
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

    _LIST_REMINDERS_KEYWORDS = (
        "que recordatorios tengo", "mis recordatorios", "recordatorios pendientes",
        "que tengo programado", "que tengo esta semana", "que tengo hoy",
        "cuales son mis recordatorios", "ver mis recordatorios",
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
            True si el mensaje fue manejado aquí.
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
        return (
            f"Hola {name}. Soy tu asistente de recordatorios.\n\n"
            "Puedes crear recordatorios con lenguaje natural, por ejemplo:\n"
            "- \"Recuerdame llamar al dentista manana a las 10\"\n"
            "- \"Sacar la basura en 30 minutos\"\n"
            "- \"Reunion con el equipo el viernes a las 15:00\"\n"
            "- \"Todos los lunes a las 9 ir al gym\" (recurrente)\n\n"
            "También puedes preguntarme sobre recordatorios existentes:\n"
            "- \"¿Cuándo tengo los análisis?\"\n"
            "- \"¿Qué tengo esta semana?\"\n\n"
            "Comandos disponibles:\n"
            "/list - Ver recordatorios pendientes\n"
            "/today - Ver recordatorios de hoy\n"
            "/week - Ver recordatorios de esta semana\n"
            "/edit <id> - Cambiar la hora de un recordatorio\n"
            "/delete <id> - Eliminar un recordatorio\n"
            "/delete_all - Eliminar todos los recordatorios pendientes\n"
            "/help - Ver esta ayuda"
        )

    def register_handlers(self, application: Application) -> None:
        """Registra todos los handlers en la aplicación."""
        application.add_handler(CommandHandler("help", self.cmd_help))
        application.add_handler(CommandHandler("list", self.cmd_list))
        application.add_handler(CommandHandler("today", self.cmd_today))
        application.add_handler(CommandHandler("week", self.cmd_week))
        application.add_handler(CommandHandler("edit", self.cmd_edit))
        application.add_handler(CommandHandler("delete", self.cmd_delete))
        application.add_handler(CommandHandler("delete_all", self.cmd_delete_all))

        application.add_handler(CommandHandler("admin_invite", self.cmd_admin_invite))
        application.add_handler(CommandHandler("admin_users", self.cmd_admin_users))
        application.add_handler(CommandHandler("admin_revoke", self.cmd_admin_revoke))

        application.add_handler(
            CallbackQueryHandler(self.handle_callback, pattern=r"^(del_|snooze_|done_|confirm_|dup_)")
        )

        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        logger.info("Handlers registrados correctamente")

    @require_registered
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        user = await self.db.get_user(user_id)
        name = user["display_name"] if user else "usuario"

        help_message = (
            f"¡Hola {name}! Soy tu asistente de recordatorios.\n\n"
            "Simplemente escríbeme lo que necesitas recordar y cuándo, por ejemplo:\n"
            "- \"Recuérdame llamar al dentista mañana a las 10\"\n"
            "- \"Sacar la basura en 30 minutos\"\n"
            "- \"Reunión con el equipo el viernes a las 15:00\"\n"
            "- \"Todos los lunes a las 9 ir al gym\"\n\n"
            "También puedes preguntarme sobre lo que ya tienes:\n"
            "- \"¿Cuándo tengo los análisis?\"\n"
            "- \"¿Qué recordatorios tengo pendientes?\"\n\n"
            "Comandos disponibles:\n"
            "/list - Ver recordatorios pendientes\n"
            "/today - Ver recordatorios de hoy\n"
            "/week - Ver recordatorios de esta semana\n"
            "/edit <id> - Cambiar la hora de un recordatorio\n"
            "/delete <id> - Eliminar un recordatorio\n"
            "/delete_all - Eliminar todos los recordatorios pendientes\n"
            "/help - Ver esta ayuda"
        )

        if user_id == config.ADMIN_USER_ID:
            help_message += (
                "\n\n🔐 Comandos de admin:\n"
                "/admin_invite - Generar código de invitación\n"
                "/admin_users - Ver usuarios registrados\n"
                "/admin_revoke <user_id> - Revocar acceso a usuario"
            )

        await update.message.reply_text(help_message)

    @require_registered
    async def cmd_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler del comando /list - muestra recordatorios pendientes y notas sin fecha."""
        user_id = update.effective_user.id
        await self._send_list(user_id, update)

    async def _send_list(self, user_id: int, update: Update) -> None:
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
                recurrence_badge = " 🔁" if r.get("recurrence") else ""
                lines.append(
                    f"[{r['id']}] {r['task']}{recurrence_badge}\n"
                    f"{self._format_reminder_times(r)}"
                )

        await update.message.reply_text("\n".join(lines))

    @require_registered
    async def cmd_today(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Muestra recordatorios de hoy."""
        user_id = update.effective_user.id
        user = await self.db.get_user(user_id)
        user_timezone = user["timezone"] if user else None
        await self._send_range_list(user_id, user_timezone, update, days=0, label="hoy")

    @require_registered
    async def cmd_week(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Muestra recordatorios de los próximos 7 días."""
        user_id = update.effective_user.id
        user = await self.db.get_user(user_id)
        user_timezone = user["timezone"] if user else None
        await self._send_range_list(user_id, user_timezone, update, days=7, label="los próximos 7 días")

    async def _send_range_list(
        self,
        user_id: int,
        user_timezone: str | None,
        update: Update,
        days: int,
        label: str,
    ) -> None:
        import pytz
        tz_str = user_timezone or self.time.timezone_str
        try:
            tz = pytz.timezone(tz_str)
        except Exception:
            tz = self.time.timezone

        now = datetime.now(tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=0) if days == 0 else (
            start + timedelta(days=days)
        )
        reminders = await self.db.get_user_reminders_in_range(user_id, start, end)

        if not reminders:
            await update.message.reply_text(f"No tienes recordatorios para {label}.")
            return

        lines = [f"📋 Recordatorios para {label}:\n"]
        for r in reminders:
            recurrence_badge = " 🔁" if r.get("recurrence") else ""
            lines.append(
                f"[{r['id']}] {r['task']}{recurrence_badge}\n"
                f"{self._format_reminder_times(r)}"
            )
        await update.message.reply_text("\n".join(lines))

    @require_registered
    async def cmd_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id

        if not context.args:
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
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
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
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        normalized = self._normalize_text(user_message)

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

        reminder = await self.db.get_reminder(reminder_id, user_id)
        if not reminder:
            context.user_data.pop("pending_edit_id", None)
            await update.message.reply_text("El recordatorio ya no existe. Edición cancelada.")
            return

        updated = await self.db.update_reminder_time(reminder_id, user_id, new_time)
        if not updated:
            await update.message.reply_text(
                "No se pudo actualizar el recordatorio. Intenta de nuevo."
            )
            return

        chat_id = update.effective_chat.id
        self.scheduler.cancel_reminder(reminder_id)
        self.scheduler.schedule_reminder(
            reminder_id=reminder_id,
            chat_id=chat_id,
            task=reminder["task"],
            reminder_time=new_time,
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
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
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
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
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
            advance_minutes=0,
        )

        scheduled = self.scheduler.schedule_reminder(
            reminder_id=reminder_id,
            chat_id=chat_id,
            task=task,
            reminder_time=new_time,
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
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
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
            reminder = await self.db.get_reminder(reminder_id, user_id)
            if reminder:
                await self._start_edit_flow(reminder_id, user_id, update, context)
                return True

        lines = ["No estoy seguro de cuál quieres editar. Aquí están tus recordatorios:\n"]
        for r in reminders:
            lines.append(f"[{r['id']}] {r['task']}\n{self._format_reminder_times(r)}")
        lines.append("Usa /edit <id> para editar uno.")
        await update.message.reply_text("\n".join(lines))
        return True

    async def _handle_query_specific(
        self,
        user_message: str,
        user_id: int,
        update: Update,
    ) -> None:
        """Responde a preguntas sobre un recordatorio concreto ya existente."""
        reminders = await self.db.get_user_reminders(user_id)
        notes = await self.db.get_user_notes(user_id)
        results = search_user_reminders(user_message, reminders, notes)

        if not results:
            await update.message.reply_text(
                "No encuentro ningún recordatorio sobre eso. "
                "Usa /list para ver todos los que tienes."
            )
            return

        if len(results) == 1:
            r = results[0]
            if r["kind"] == "note":
                await update.message.reply_text(
                    f"Tienes pendiente: \"{r['task']}\"\n"
                    "(sin fecha de aviso — guardado como nota)"
                )
            else:
                await update.message.reply_text(
                    f"Tienes \"{r['task']}\"\n"
                    f"{self._format_reminder_times(r)}"
                )
            return

        # Varios candidatos
        lines = ["Tengo varios que podrían ser:\n"]
        for r in results:
            if r["kind"] == "note":
                lines.append(f"• \"{r['task']}\" (sin fecha)\n")
            else:
                lines.append(f"• \"{r['task']}\"\n{self._format_reminder_times(r)}")
        await update.message.reply_text("\n".join(lines))

    @require_registered
    async def cmd_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id

        if not context.args:
            # Mostrar lista con botones inline de borrado
            reminders = await self.db.get_user_reminders(user_id)
            notes = await self.db.get_user_notes(user_id)

            if not reminders and not notes:
                await update.message.reply_text("No tienes recordatorios ni notas pendientes.")
                return

            lines = ["¿Qué quieres borrar?\n"]
            keyboard = []

            if notes:
                lines.append("📌 Notas sin fecha:")
                for n in notes:
                    lines.append(f"  [N-{n['id']}] {n['task']}")
                    keyboard.append([InlineKeyboardButton(
                        f"🗑️ [N-{n['id']}] {n['task'][:40]}",
                        callback_data=f"del_note_{n['id']}"
                    )])

            if reminders:
                lines.append("\n📋 Recordatorios programados:")
                for r in reminders:
                    formatted = self.time.format_for_display(r["reminder_time"])
                    lines.append(f"  [{r['id']}] {r['task']} — {formatted}")
                    keyboard.append([InlineKeyboardButton(
                        f"🗑️ [{r['id']}] {r['task'][:40]}",
                        callback_data=f"del_reminder_{r['id']}"
                    )])

            await update.message.reply_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        arg = context.args[0].upper()

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
                await update.message.reply_text("No se encontró esa nota o no te pertenece.")
            return

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
    async def cmd_delete_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    async def handle_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Gestiona todos los callbacks de botones inline."""
        query = update.callback_query
        await query.answer()
        data = query.data
        user_id = update.effective_user.id

        # Borrar nota
        if data.startswith("del_note_"):
            note_id = int(data.split("_")[-1])
            deleted = await self.db.delete_note(note_id, user_id)
            if deleted:
                await query.edit_message_text(f"✅ Nota [N-{note_id}] eliminada.")
            else:
                await query.edit_message_text("No se encontró esa nota.")
            return

        # Borrar recordatorio
        if data.startswith("del_reminder_"):
            reminder_id = int(data.split("_")[-1])
            deleted = await self.db.delete_reminder(reminder_id, user_id)
            if deleted:
                self.scheduler.cancel_reminder(reminder_id)
                await query.edit_message_text(f"✅ Recordatorio [{reminder_id}] eliminado.")
            else:
                await query.edit_message_text("No se encontró ese recordatorio.")
            return

        # Snooze: snooze_{minutos}_{reminder_id}
        if data.startswith("snooze_"):
            parts = data.split("_")
            minutes = int(parts[1])
            reminder_id = int(parts[2])
            chat_id = update.effective_chat.id
            # Recuperar la tarea del mensaje original o de la BD
            original_text = update.callback_query.message.text or ""
            # Extraemos la línea después de "🔔 " como task aproximada
            task_line = next(
                (line for line in original_text.splitlines() if line and not line.startswith("🔔")),
                None,
            )
            task = task_line.strip() if task_line else "Recordatorio"
            new_time = datetime.now(self.time.timezone) + timedelta(minutes=minutes)

            new_id = await self.db.add_reminder(
                user_id=user_id,
                chat_id=chat_id,
                task=task,
                reminder_time=new_time,
                event_time=new_time,
                advance_minutes=0,
            )
            self.scheduler.schedule_reminder(
                reminder_id=new_id,
                chat_id=chat_id,
                task=task,
                reminder_time=new_time,
            )
            label = f"{minutes} min" if minutes < 60 else f"{minutes // 60} h" if minutes < 1440 else "1 día"
            await query.edit_message_text(
                f"⏰ Pospuesto {label}. Te recuerdo a las {new_time.strftime('%H:%M')}."
            )
            return

        # Marcar como hecho
        if data.startswith("done_"):
            reminder_id = int(data.split("_")[-1])
            await self.db.mark_as_completed(reminder_id)
            await query.edit_message_text("✅ ¡Hecho! Marcado como completado.")
            return

        # Confirmar creación de recordatorio
        if data == "confirm_reminder":
            pending = context.user_data.pop("pending_confirm_reminder", None)
            if not pending:
                await query.edit_message_text("No hay recordatorio pendiente de confirmar.")
                return
            await self._save_and_schedule_reminder(pending, update, context, from_callback=True)
            return

        # Editar (en flujo de confirmación)
        if data == "confirm_edit_reminder":
            pending = context.user_data.get("pending_confirm_reminder")
            if not pending:
                await query.edit_message_text("No hay recordatorio pendiente.")
                return
            context.user_data["pending_edit_after_confirm"] = True
            await query.edit_message_text(
                "¿Qué quieres cambiar? Escribe la nueva tarea o la nueva hora."
            )
            return

        # Cancelar creación de recordatorio
        if data == "cancel_reminder":
            context.user_data.pop("pending_confirm_reminder", None)
            await query.edit_message_text("❌ Recordatorio cancelado.")
            return

        # Duplicado: crear nuevo
        if data == "dup_new":
            pending = context.user_data.pop("pending_dup_reminder", None)
            if not pending:
                await query.edit_message_text("No hay recordatorio pendiente.")
                return
            await self._save_and_schedule_reminder(pending, update, context, from_callback=True)
            return

        # Duplicado: cancelar
        if data == "dup_cancel":
            context.user_data.pop("pending_dup_reminder", None)
            await query.edit_message_text("De acuerdo, no creo nada nuevo.")
            return

    async def _save_and_schedule_reminder(
        self,
        pending: dict,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        from_callback: bool = False,
    ) -> None:
        """Guarda en BD y programa el recordatorio. Usado tanto desde handle_message como desde callbacks."""
        user_id = pending["user_id"]
        chat_id = pending["chat_id"]
        recurrence = pending.get("recurrence")

        reminder_id = await self.db.add_reminder(
            user_id=user_id,
            chat_id=chat_id,
            task=pending["task"],
            reminder_time=pending["reminder_time"],
            original_message=pending.get("original_message"),
            event_time=pending["event_time"],
            advance_minutes=pending["advance_minutes"],
            recurrence=recurrence,
        )

        scheduled = self.scheduler.schedule_reminder(
            reminder_id=reminder_id,
            chat_id=chat_id,
            task=pending["task"],
            reminder_time=pending["reminder_time"],
            recurrence=recurrence,
        )

        reminder_record = self._build_reminder_record(
            pending["task"],
            pending["reminder_time"],
            pending["event_time"],
            pending["advance_minutes"],
        )
        text = (
            f"✅ {pending['confirmation_message']}\n\n"
            f"📝 {pending['task']}\n"
            f"{self._format_reminder_times(reminder_record)}"
        )
        if not scheduled:
            text = "❌ No se pudo programar el recordatorio. La fecha podría ser inválida."

        if from_callback:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)

    @require_registered
    async def handle_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handler para mensajes de texto - procesa como recordatorio."""
        user_message = update.message.text
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        tg_user = update.effective_user
        logger.info("=" * 50)
        logger.info("MENSAJE RECIBIDO:")
        logger.info("  user_id: %s", user_id)
        logger.info("  chat_id: %s", chat_id)
        logger.info("  username: @%s", tg_user.username)
        logger.info("  text: %s", user_message)
        logger.info("=" * 50)

        await update.message.chat.send_action("typing")

        user = await self.db.get_user(user_id)
        user_timezone = user["timezone"] if user else None

        # Estados de conversación pendientes
        pending_edit_id = context.user_data.get("pending_edit_id")
        if pending_edit_id is not None:
            await self._handle_pending_edit(
                pending_edit_id, user_message, user_id, user_timezone, update, context
            )
            return

        if "pending_no_date_task" in context.user_data:
            await self._handle_no_date_yesno(user_message, update, context)
            return

        if "pending_no_date_awaiting_time" in context.user_data:
            await self._handle_no_date_time(
                user_message, user_id, user_timezone, update, context
            )
            return

        await update.message.chat.send_action("typing")
        time_context = self.time.get_context_for_llm(user_timezone)
        normalized_message = self._normalize_text(user_message)

        # — Clasificación de intención —
        intent = Intent.UNKNOWN
        if self.intent_classifier is not None:
            intent = await self.intent_classifier.classify(user_message)
            logger.info("Intent detectado: %s para '%s'", intent, user_message[:60])

        # Conversational fast-path (no hace falta ir a OpenAI)
        if intent == Intent.GENERAL_CONVERSATION:
            if not await self._handle_conversational_message(normalized_message, user, update):
                # Intent claramente conversacional pero sin keyword específica — respuesta corta
                await update.message.reply_text("De nada. Cuando quieras, aquí estoy.")
            return

        if intent == Intent.UNKNOWN:
            if await self._handle_conversational_message(normalized_message, user, update):
                return

        if intent == Intent.HELP or (intent == Intent.UNKNOWN and
                                     any(kw in normalized_message for kw in self._HELP_KEYWORDS)):
            name = user["display_name"] if user else "usuario"
            await update.message.reply_text(self._build_user_help_message(name))
            return

        if intent == Intent.LIST_REMINDERS or (intent == Intent.UNKNOWN and
                                               any(kw in normalized_message for kw in self._LIST_REMINDERS_KEYWORDS)):
            await self._send_list(user_id, update)
            return

        if intent == Intent.QUERY_SPECIFIC:
            await self._handle_query_specific(user_message, user_id, update)
            return

        if intent == Intent.EDIT_REMINDER or await self._detect_edit_intent(
            normalized_message, user_message, user_id, update, context
        ):
            if intent == Intent.EDIT_REMINDER:
                await self._detect_edit_intent(
                    normalized_message, user_message, user_id, update, context
                )
            return

        # Detectar preguntas sobre notas/pendientes sin fecha
        if any(kw in normalized_message for kw in self._PENDING_NOTES_KEYWORDS):
            await self._show_notes(user_id, update)
            return

        # Para intent UNKNOWN: solo parsear si hay señal explícita de creación
        if intent == Intent.UNKNOWN and not any(
            kw in normalized_message for kw in self._CREATE_REMINDER_KEYWORDS
        ):
            await update.message.reply_text(
                "No te entiendo muy bien. Si quieres crear un recordatorio, dime algo como:\n"
                "\"Recuérdame mañana a las 10 que llame al fontanero\"."
            )
            return

        # Crear recordatorio
        result = await self.openai.parse_reminder(user_message, time_context)

        if not result.success:
            logger.warning(
                "Parse failure | user_id=%s | message=%r | error=%s",
                user_id, user_message, result.error_message,
            )
            await update.message.reply_text(
                "❌ No he podido entender el recordatorio. ¿Puedes reformularlo?\n\n"
                "Por ejemplo: \"Recuérdame mañana a las 10 que llame al fontanero\"."
            )
            return

        if not result.has_date:
            context.user_data["pending_no_date_task"] = result.task
            context.user_data["pending_no_date_original_message"] = user_message
            await update.message.reply_text(
                f"Entendido: \"{result.task}\"\n\n"
                "¿Quieres que te lo recuerde a alguna hora?"
            )
            return

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

        if not self.time.is_future(reminder_time):
            context.user_data["pending_no_date_awaiting_time"] = result.task
            context.user_data["pending_no_date_awaiting_original_message"] = user_message
            await update.message.reply_text(
                "La hora de aviso ya ha pasado. ¿A qué hora quieres que te lo recuerde?\n"
                "Por favor, especifica una fecha futura. Escribe \"cancelar\" para salir."
            )
            return

        pending = {
            "user_id": user_id,
            "chat_id": chat_id,
            "task": result.task,
            "reminder_time": reminder_time,
            "event_time": event_time,
            "advance_minutes": advance_minutes,
            "recurrence": result.recurrence,
            "original_message": user_message,
            "confirmation_message": result.confirmation_message,
        }

        # — Detección de duplicados (Cambio 7) —
        reminders = await self.db.get_user_reminders(user_id)
        notes = await self.db.get_user_notes(user_id)
        dupes = search_user_reminders(result.task, reminders, notes, top_k=1, min_score=0.7)
        if dupes:
            dupe = dupes[0]
            if dupe["kind"] == "reminder":
                dupe_text = (
                    f"⚠️ Ya tienes \"{dupe['task']}\"\n"
                    f"{self._format_reminder_times(dupe)}\n"
                    "¿Qué prefieres?"
                )
            else:
                dupe_text = (
                    f"⚠️ Ya tienes pendiente \"{dupe['task']}\" (sin fecha).\n"
                    "¿Qué prefieres?"
                )
            context.user_data["pending_dup_reminder"] = pending
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("➕ Crear otro nuevo", callback_data="dup_new"),
                    InlineKeyboardButton("❌ Cancelar", callback_data="dup_cancel"),
                ]
            ])
            await update.message.reply_text(dupe_text, reply_markup=keyboard)
            return

        # — Confirmación previa (Cambio 4) —
        if config.CONFIRMATION_REQUIRED:
            formatted_time = self.time.format_for_display(reminder_time)
            context.user_data["pending_confirm_reminder"] = pending
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Confirmar", callback_data="confirm_reminder"),
                    InlineKeyboardButton("✏️ Editar", callback_data="confirm_edit_reminder"),
                    InlineKeyboardButton("❌ Cancelar", callback_data="cancel_reminder"),
                ]
            ])
            await update.message.reply_text(
                f"📝 Voy a programar:\n"
                f"  Tarea: {result.task}\n"
                f"  Fecha: {formatted_time}\n",
                reply_markup=keyboard,
            )
            return

        await self._save_and_schedule_reminder(pending, update, context)

    # ============ Comandos de Admin ============

    @require_admin
    async def cmd_admin_invite(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        code = await self.db.create_invitation_code()
        await update.message.reply_text(
            f"🎟️ Nuevo código de invitación:\n\n"
            f"`{code}`\n\n"
            "Comparte este código con el usuario que quieras invitar.",
            parse_mode="Markdown",
        )

    @require_admin
    async def cmd_admin_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    async def cmd_admin_revoke(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        task: str,
    ) -> None:
        """Envía una notificación proactiva con botones de snooze."""
        if not self._bot:
            logger.error("Bot no configurado para enviar notificaciones")
            return

        try:
            notification_message = await self.openai.generate_notification_message(task)

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Hecho", callback_data=f"done_{reminder_id}"),
                    InlineKeyboardButton("⏰ +10 min", callback_data=f"snooze_10_{reminder_id}"),
                    InlineKeyboardButton("⏰ +1 h", callback_data=f"snooze_60_{reminder_id}"),
                    InlineKeyboardButton("⏰ +1 día", callback_data=f"snooze_1440_{reminder_id}"),
                ]
            ])

            # Guardamos la tarea en user_data no disponible aquí; usamos application context
            # El callback de snooze recuperará la tarea de la BD si es necesario
            await self._bot.send_message(
                chat_id=chat_id,
                text=f"🔔 {notification_message}",
                reply_markup=keyboard,
            )

            await self.db.mark_as_notified(reminder_id)
            logger.info("Notificación enviada para recordatorio %s", reminder_id)

        except Exception as e:
            logger.error("Error enviando notificación %s: %s", reminder_id, e)
