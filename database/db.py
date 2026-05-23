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
                original_message TEXT,
                reminder_time TEXT NOT NULL,
                event_time TEXT,
                advance_minutes INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                notified INTEGER DEFAULT 0
            )
        """)
        await self._ensure_column("reminders", "original_message", "TEXT")
        await self._ensure_column("reminders", "event_time", "TEXT")
        await self._ensure_column("reminders", "advance_minutes", "INTEGER DEFAULT 0")
        await self._ensure_column("reminders", "completed_at", "TEXT")
        await self._ensure_column("reminders", "recurrence", "TEXT")
        await self._connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_reminder_time
            ON reminders(reminder_time) WHERE notified = 0
        """)

        # Tabla de notas sin fecha (recordatorios informativos sin hora de aviso)
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                task TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
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

    async def _ensure_column(self, table: str, column: str, definition: str) -> None:
        """Añade una columna si la base de datos existente aún no la tiene."""
        cursor = await self._connection.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in await cursor.fetchall()}
        if column not in columns:
            await self._connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    async def add_reminder(
        self,
        user_id: int,
        chat_id: int,
        task: str,
        reminder_time: datetime,
        original_message: Optional[str] = None,
        event_time: Optional[datetime] = None,
        advance_minutes: int = 0,
        recurrence: Optional[str] = None,
    ) -> int:
        """
        Añade un nuevo recordatorio a la base de datos.

        Returns:
            ID del recordatorio creado.
        """
        cursor = await self._connection.execute(
            """
            INSERT INTO reminders (
                user_id, chat_id, task, original_message, reminder_time,
                event_time, advance_minutes, recurrence, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                chat_id,
                task,
                original_message,
                reminder_time.isoformat(),
                (event_time or reminder_time).isoformat(),
                advance_minutes,
                recurrence,
                datetime.now().isoformat(),
            )
        )
        await self._connection.commit()
        reminder_id = cursor.lastrowid
        logger.info(f"Recordatorio {reminder_id} creado para usuario {user_id}")
        return reminder_id

    async def get_pending_reminders(self) -> list[dict]:
        """
        Obtiene todos los recordatorios pendientes (no notificados) y recurrentes.

        Returns:
            Lista de diccionarios con los datos de cada recordatorio.
        """
        cursor = await self._connection.execute(
            """
            SELECT id, user_id, chat_id, task, original_message, reminder_time,
                   event_time, advance_minutes, recurrence
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
                "original_message": row[4],
                "reminder_time": datetime.fromisoformat(row[5]),
                "event_time": datetime.fromisoformat(row[6]) if row[6] else datetime.fromisoformat(row[5]),
                "advance_minutes": row[7] or 0,
                "recurrence": row[8],
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
            SELECT id, task, original_message, reminder_time, event_time, advance_minutes, recurrence
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
                "original_message": row[2],
                "reminder_time": datetime.fromisoformat(row[3]),
                "event_time": datetime.fromisoformat(row[4]) if row[4] else datetime.fromisoformat(row[3]),
                "advance_minutes": row[5] or 0,
                "recurrence": row[6],
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

    async def mark_as_completed(self, reminder_id: int) -> None:
        """Marca un recordatorio como completado por el usuario."""
        await self._connection.execute(
            "UPDATE reminders SET notified = 1, completed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), reminder_id)
        )
        await self._connection.commit()
        logger.info(f"Recordatorio {reminder_id} marcado como completado")

    async def get_user_reminders_in_range(
        self,
        user_id: int,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """Obtiene recordatorios pendientes de un usuario en un rango de fechas."""
        cursor = await self._connection.execute(
            """
            SELECT id, task, original_message, reminder_time, event_time, advance_minutes, recurrence
            FROM reminders
            WHERE user_id = ? AND notified = 0
              AND reminder_time >= ? AND reminder_time <= ?
            ORDER BY reminder_time ASC
            """,
            (user_id, start.isoformat(), end.isoformat()),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "task": row[1],
                "original_message": row[2],
                "reminder_time": datetime.fromisoformat(row[3]),
                "event_time": datetime.fromisoformat(row[4]) if row[4] else datetime.fromisoformat(row[3]),
                "advance_minutes": row[5] or 0,
                "recurrence": row[6],
            }
            for row in rows
        ]

    async def delete_all_reminders(self, user_id: int) -> int:
        """
        Elimina todos los recordatorios pendientes de un usuario.

        Returns:
            Número de recordatorios eliminados.
        """
        cursor = await self._connection.execute(
            "DELETE FROM reminders WHERE user_id = ? AND notified = 0",
            (user_id,)
        )
        await self._connection.commit()
        count = cursor.rowcount
        if count:
            logger.info(f"Eliminados {count} recordatorios del usuario {user_id}")
        return count

    async def get_reminder(self, reminder_id: int, user_id: int) -> Optional[dict]:
        """
        Obtiene un recordatorio específico si pertenece al usuario.

        Returns:
            Diccionario con los datos o None si no existe/no pertenece.
        """
        cursor = await self._connection.execute(
            """
            SELECT id, task, original_message, reminder_time, event_time, advance_minutes, recurrence
            FROM reminders
            WHERE id = ? AND user_id = ? AND notified = 0
            """,
            (reminder_id, user_id)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "task": row[1],
            "original_message": row[2],
            "reminder_time": datetime.fromisoformat(row[3]),
            "event_time": datetime.fromisoformat(row[4]) if row[4] else datetime.fromisoformat(row[3]),
            "advance_minutes": row[5] or 0,
            "recurrence": row[6],
        }

    async def update_reminder_time(
        self,
        reminder_id: int,
        user_id: int,
        new_time: datetime
    ) -> bool:
        """
        Actualiza la hora de un recordatorio si pertenece al usuario.

        Returns:
            True si se actualizó, False si no existía o no pertenecía al usuario.
        """
        cursor = await self._connection.execute(
            """
            UPDATE reminders SET reminder_time = ?, event_time = ?, advance_minutes = 0
            WHERE id = ? AND user_id = ? AND notified = 0
            """,
            (new_time.isoformat(), new_time.isoformat(), reminder_id, user_id)
        )
        await self._connection.commit()
        updated = cursor.rowcount > 0
        if updated:
            logger.info(f"Recordatorio {reminder_id} reprogramado a {new_time.isoformat()}")
        return updated

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

    # ============ Métodos de notas sin fecha ============

    async def add_note(self, user_id: int, chat_id: int, task: str) -> int:
        """
        Añade una nota sin fecha de recordatorio.

        Returns:
            ID de la nota creada.
        """
        cursor = await self._connection.execute(
            """
            INSERT INTO notes (user_id, chat_id, task, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, chat_id, task, datetime.now().isoformat())
        )
        await self._connection.commit()
        note_id = cursor.lastrowid
        logger.info(f"Nota {note_id} creada para usuario {user_id}")
        return note_id

    async def get_user_notes(self, user_id: int) -> list[dict]:
        """
        Obtiene todas las notas sin fecha de un usuario.

        Returns:
            Lista de diccionarios con id y task.
        """
        cursor = await self._connection.execute(
            """
            SELECT id, task, created_at
            FROM notes
            WHERE user_id = ?
            ORDER BY created_at ASC
            """,
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [{"id": row[0], "task": row[1], "created_at": row[2]} for row in rows]

    async def delete_note(self, note_id: int, user_id: int) -> bool:
        """
        Elimina una nota si pertenece al usuario.

        Returns:
            True si se eliminó, False si no existía o no pertenecía al usuario.
        """
        cursor = await self._connection.execute(
            "DELETE FROM notes WHERE id = ? AND user_id = ?",
            (note_id, user_id)
        )
        await self._connection.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info(f"Nota {note_id} eliminada")
        return deleted

    async def delete_all_notes(self, user_id: int) -> int:
        """
        Elimina todas las notas de un usuario.

        Returns:
            Número de notas eliminadas.
        """
        cursor = await self._connection.execute(
            "DELETE FROM notes WHERE user_id = ?",
            (user_id,)
        )
        await self._connection.commit()
        count = cursor.rowcount
        if count:
            logger.info(f"Eliminadas {count} notas del usuario {user_id}")
        return count

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
