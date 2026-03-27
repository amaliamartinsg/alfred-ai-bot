"""
Flujo de registro de usuarios mediante ConversationHandler.
Gestiona el proceso de alta de nuevos usuarios con código de invitación.
"""
from telegram import Update
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
import logging

import config
from database import DatabaseManager
from services import CityService

logger = logging.getLogger(__name__)

# Estados de la conversación
WAITING_CODE = 1
WAITING_CITY = 2
WAITING_NAME = 3


class RegistrationHandler:
    """Gestiona el flujo de registro de nuevos usuarios."""

    def __init__(self, db: DatabaseManager, city_service: CityService):
        """
        Inicializa el handler de registro.

        Args:
            db: Gestor de base de datos.
            city_service: Servicio para obtener timezone de ciudades.
        """
        self.db = db
        self.city_service = city_service

    async def start_registration(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Inicia el flujo de registro pidiendo el código de invitación."""
        user_id = update.effective_user.id
        user = update.effective_user
        chat_id = update.effective_chat.id

        # Log de información del mensaje /start
        logger.info("=" * 50)
        logger.info("COMANDO /start RECIBIDO:")
        logger.info(f"  user_id: {user_id}")
        logger.info(f"  chat_id: {chat_id}")
        logger.info(f"  username: @{user.username}")
        logger.info(f"  first_name: {user.first_name}")
        logger.info(f"  last_name: {user.last_name}")
        logger.info(f"  is_bot: {user.is_bot}")
        logger.info(f"  language_code: {user.language_code}")
        logger.info("=" * 50)

        # Si es admin, saludar y mostrar comandos
        if user_id == config.ADMIN_USER_ID:
            await update.message.reply_text(
                f"👋 ¡Hola Admin {user.first_name}!\n\n"
                "🔐 Comandos de administrador:\n"
                "/admin_invite - Generar código de invitación\n"
                "/admin_users - Ver usuarios registrados\n"
                "/admin_revoke <user_id> - Revocar acceso a usuario\n\n"
                "📝 Comandos de usuario:\n"
                "/list - Ver recordatorios pendientes\n"
                "/delete <id> - Eliminar un recordatorio\n"
                "/delete_all - Eliminar todos los recordatorios\n"
                "/help - Ver ayuda\n\n"
                "También puedes escribir directamente un recordatorio como:\n"
                "\"Recuérdame llamar al dentista mañana a las 10\""
            )
            return ConversationHandler.END

        # Verificar si ya está registrado
        if await self.db.is_user_registered(user_id):
            await update.message.reply_text(
                "Ya estás registrado. Puedes empezar a crear recordatorios."
            )
            return ConversationHandler.END

        await update.message.reply_text(
            "¡Bienvenido! Para usar este bot necesitas un código de invitación.\n\n"
            "Por favor, introduce tu código de invitación:"
        )
        return WAITING_CODE

    async def receive_code(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Recibe y valida el código de invitación."""
        code = update.message.text.strip()

        is_valid = await self.db.validate_invitation_code(code)

        if not is_valid:
            await update.message.reply_text(
                "❌ Código inválido o ya utilizado.\n\n"
                "Por favor, introduce un código válido o contacta con el administrador."
            )
            return WAITING_CODE

        # Guardar código válido en contexto
        context.user_data["invitation_code"] = code

        await update.message.reply_text(
            "✅ ¡Código válido!\n\n"
            "Ahora necesito saber tu ubicación para configurar tu zona horaria.\n"
            "¿Desde qué ciudad te conectas? (ej: Madrid, Buenos Aires, México DF)"
        )
        return WAITING_CITY

    async def receive_city(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Recibe la ciudad y obtiene el timezone."""
        city = update.message.text.strip()

        # Obtener timezone de la ciudad
        timezone, normalized_city = await self.city_service.get_timezone_from_city(city)

        if not timezone:
            await update.message.reply_text(
                "❌ No pude reconocer esa ciudad.\n\n"
                "Por favor, intenta con el nombre de una ciudad conocida "
                "(ej: Madrid, Londres, Nueva York, Tokio):"
            )
            return WAITING_CITY

        # Guardar en contexto
        context.user_data["city"] = normalized_city or city
        context.user_data["timezone"] = timezone

        await update.message.reply_text(
            f"✅ Perfecto, tu zona horaria será: {timezone}\n\n"
            "Por último, ¿cómo te gustaría que te llame el bot?\n"
            "Escribe tu nombre o apodo:"
        )
        return WAITING_NAME

    async def receive_name(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Recibe el nombre y completa el registro."""
        display_name = update.message.text.strip()
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        # Validar longitud del nombre
        if len(display_name) < 2 or len(display_name) > 50:
            await update.message.reply_text(
                "El nombre debe tener entre 2 y 50 caracteres. Inténtalo de nuevo:"
            )
            return WAITING_NAME

        # Registrar usuario
        await self.db.register_user(
            user_id=user_id,
            chat_id=chat_id,
            display_name=display_name,
            city=context.user_data["city"],
            timezone=context.user_data["timezone"],
            invitation_code=context.user_data["invitation_code"]
        )

        # Limpiar datos temporales
        context.user_data.clear()

        await update.message.reply_text(
            f"🎉 ¡Registro completado, {display_name}!\n\n"
            "Ahora puedes crear recordatorios escribiendo mensajes como:\n"
            "- \"Recuérdame llamar al dentista mañana a las 10\"\n"
            "- \"Reunión en 30 minutos\"\n\n"
            "Comandos disponibles:\n"
            "/list - Ver tus recordatorios\n"
            "/delete <id> - Eliminar un recordatorio\n"
            "/help - Ver ayuda"
        )
        return ConversationHandler.END

    async def cancel(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Cancela el proceso de registro."""
        context.user_data.clear()
        await update.message.reply_text(
            "Registro cancelado. Usa /start para comenzar de nuevo."
        )
        return ConversationHandler.END

    def get_handler(self) -> ConversationHandler:
        """
        Retorna el ConversationHandler configurado para el registro.

        Returns:
            ConversationHandler listo para registrar en la aplicación.
        """
        return ConversationHandler(
            entry_points=[CommandHandler("start", self.start_registration)],
            states={
                WAITING_CODE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_code)
                ],
                WAITING_CITY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_city)
                ],
                WAITING_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_name)
                ]
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
            name="registration",
            persistent=False
        )
