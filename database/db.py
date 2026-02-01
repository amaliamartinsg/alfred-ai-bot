"""
Gestor de base de datos SQLite para persistencia de recordatorios.
Usa aiosqlite para operaciones asíncronas compatibles con asyncio.
"""
import aiosqlite
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Gestiona la conexión y operaciones con SQLite."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Inicializa la conexión y crea las tablas si no existen."""
        self._connection = await aiosqlite.connect(self.db_path)
        await self._create_tables()
        logger.info("Base de datos inicializada correctamente")

    async def _create_tables(self) -> None:
        """Crea las tablas si no existen."""
        # Tabla de recordatorios
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                task TEXT NOT NULL,
                reminder_time TEXT NOT NULL,
                created_at TEXT NOT NULL,
                notified INTEGER DEFAULT 0
            )
        """)
        await self._connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_reminder_time
            ON reminders(reminder_time) WHERE notified = 0
        """)

        # Tabla de códigos de invitación
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS invitation_codes (
                code TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                used_by INTEGER,
                used_at TEXT
            )
        """)

        # Tabla de usuarios registrados
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                city TEXT NOT NULL,
                timezone TEXT NOT NULL,
                invitation_code TEXT NOT NULL,
                registered_at TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (invitation_code) REFERENCES invitation_codes(code)
            )
        """)

        await self._connection.commit()

    async def add_reminder(
        self,
        user_id: int,
        chat_id: int,
        task: str,
        reminder_time: datetime
    ) -> int:
        """
        Añade un nuevo recordatorio a la base de datos.

        Returns:
            ID del recordatorio creado.
        """
        cursor = await self._connection.execute(
            """
            INSERT INTO reminders (user_id, chat_id, task, reminder_time, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                chat_id,
                task,
                reminder_time.isoformat(),
                datetime.now().isoformat()
            )
        )
        await self._connection.commit()
        reminder_id = cursor.lastrowid
        logger.info(f"Recordatorio {reminder_id} creado para usuario {user_id}")
        return reminder_id

    async def get_pending_reminders(self) -> list[dict]:
        """
        Obtiene todos los recordatorios pendientes (no notificados).

        Returns:
            Lista de diccionarios con los datos de cada recordatorio.
        """
        cursor = await self._connection.execute(
            """
            SELECT id, user_id, chat_id, task, reminder_time
            FROM reminders
            WHERE notified = 0
            ORDER BY reminder_time ASC
            """
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "user_id": row[1],
                "chat_id": row[2],
                "task": row[3],
                "reminder_time": datetime.fromisoformat(row[4])
            }
            for row in rows
        ]

    async def get_user_reminders(self, user_id: int) -> list[dict]:
        """
        Obtiene los recordatorios pendientes de un usuario específico.

        Args:
            user_id: ID del usuario de Telegram.

        Returns:
            Lista de recordatorios del usuario.
        """
        cursor = await self._connection.execute(
            """
            SELECT id, task, reminder_time
            FROM reminders
            WHERE user_id = ? AND notified = 0
            ORDER BY reminder_time ASC
            """,
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "task": row[1],
                "reminder_time": datetime.fromisoformat(row[2])
            }
            for row in rows
        ]

    async def mark_as_notified(self, reminder_id: int) -> None:
        """Marca un recordatorio como notificado."""
        await self._connection.execute(
            "UPDATE reminders SET notified = 1 WHERE id = ?",
            (reminder_id,)
        )
        await self._connection.commit()
        logger.info(f"Recordatorio {reminder_id} marcado como notificado")

    async def delete_reminder(self, reminder_id: int, user_id: int) -> bool:
        """
        Elimina un recordatorio si pertenece al usuario.

        Returns:
            True si se eliminó, False si no existía o no pertenecía al usuario.
        """
        cursor = await self._connection.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?",
            (reminder_id, user_id)
        )
        await self._connection.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info(f"Recordatorio {reminder_id} eliminado")
        return deleted

    # ============ Métodos de códigos de invitación ============

    async def create_invitation_code(self) -> str:
        """
        Genera un código de invitación único.

        Returns:
            Código de invitación generado.
        """
        import secrets
        code = secrets.token_urlsafe(8)  # Código de 11 caracteres aprox

        await self._connection.execute(
            "INSERT INTO invitation_codes (code, created_at) VALUES (?, ?)",
            (code, datetime.now().isoformat())
        )
        await self._connection.commit()
        logger.info(f"Código de invitación creado: {code}")
        return code

    async def validate_invitation_code(self, code: str) -> bool:
        """
        Verifica si un código de invitación es válido y no ha sido usado.

        Args:
            code: Código a validar.

        Returns:
            True si el código es válido y disponible.
        """
        cursor = await self._connection.execute(
            "SELECT used_by FROM invitation_codes WHERE code = ?",
            (code,)
        )
        row = await cursor.fetchone()

        if not row:
            return False  # Código no existe

        return row[0] is None  # True si no ha sido usado

    async def mark_code_as_used(self, code: str, user_id: int) -> None:
        """Marca un código como usado por un usuario."""
        await self._connection.execute(
            "UPDATE invitation_codes SET used_by = ?, used_at = ? WHERE code = ?",
            (user_id, datetime.now().isoformat(), code)
        )
        await self._connection.commit()

    # ============ Métodos de usuarios ============

    async def register_user(
        self,
        user_id: int,
        chat_id: int,
        display_name: str,
        city: str,
        timezone: str,
        invitation_code: str
    ) -> None:
        """
        Registra un nuevo usuario en el sistema.

        Args:
            user_id: ID de Telegram del usuario.
            chat_id: ID del chat.
            display_name: Nombre preferido del usuario.
            city: Ciudad del usuario.
            timezone: Zona horaria calculada.
            invitation_code: Código de invitación usado.
        """
        await self._connection.execute(
            """
            INSERT INTO users (user_id, chat_id, display_name, city, timezone, invitation_code, registered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, chat_id, display_name, city, timezone, invitation_code, datetime.now().isoformat())
        )
        await self._connection.commit()
        await self.mark_code_as_used(invitation_code, user_id)
        logger.info(f"Usuario {user_id} registrado como '{display_name}'")

    async def get_user(self, user_id: int) -> Optional[dict]:
        """
        Obtiene los datos de un usuario.

        Args:
            user_id: ID de Telegram del usuario.

        Returns:
            Diccionario con datos del usuario o None si no existe.
        """
        cursor = await self._connection.execute(
            """
            SELECT user_id, chat_id, display_name, city, timezone, registered_at, is_active
            FROM users WHERE user_id = ?
            """,
            (user_id,)
        )
        row = await cursor.fetchone()

        if not row:
            return None

        return {
            "user_id": row[0],
            "chat_id": row[1],
            "display_name": row[2],
            "city": row[3],
            "timezone": row[4],
            "registered_at": row[5],
            "is_active": bool(row[6])
        }

    async def is_user_registered(self, user_id: int) -> bool:
        """Verifica si un usuario está registrado y activo."""
        user = await self.get_user(user_id)
        return user is not None and user["is_active"]

    async def get_all_users(self) -> list[dict]:
        """Obtiene todos los usuarios registrados (para admin)."""
        cursor = await self._connection.execute(
            """
            SELECT user_id, display_name, city, timezone, registered_at, is_active
            FROM users ORDER BY registered_at DESC
            """
        )
        rows = await cursor.fetchall()
        return [
            {
                "user_id": row[0],
                "display_name": row[1],
                "city": row[2],
                "timezone": row[3],
                "registered_at": row[4],
                "is_active": bool(row[5])
            }
            for row in rows
        ]

    async def deactivate_user(self, user_id: int) -> bool:
        """
        Desactiva un usuario.

        Returns:
            True si se desactivó, False si no existía.
        """
        cursor = await self._connection.execute(
            "UPDATE users SET is_active = 0 WHERE user_id = ?",
            (user_id,)
        )
        await self._connection.commit()
        deactivated = cursor.rowcount > 0
        if deactivated:
            logger.info(f"Usuario {user_id} desactivado")
        return deactivated

    async def close(self) -> None:
        """Cierra la conexión a la base de datos."""
        if self._connection:
            await self._connection.close()
            logger.info("Conexión a base de datos cerrada")
