"""Tests de integración para DatabaseManager usando SQLite en memoria."""
import pytest
import pytest_asyncio
from datetime import datetime
import pytz

from database.db import DatabaseManager


@pytest_asyncio.fixture
async def db():
    """Base de datos en memoria para cada test."""
    manager = DatabaseManager(":memory:")
    await manager.initialize()
    yield manager
    await manager.close()


# ── Recordatorios ─────────────────────────────────────────────────────────────

class TestAddAndGetReminders:
    async def test_add_reminder_returns_id(self, db):
        reminder_time = datetime(2099, 6, 15, 10, 30, tzinfo=pytz.UTC)
        reminder_id = await db.add_reminder(1, 100, "Llamar al médico", reminder_time)
        assert isinstance(reminder_id, int)
        assert reminder_id > 0

    async def test_get_pending_reminders_empty(self, db):
        result = await db.get_pending_reminders()
        assert result == []

    async def test_get_pending_reminders_returns_added(self, db):
        reminder_time = datetime(2099, 6, 15, 10, 30, tzinfo=pytz.UTC)
        await db.add_reminder(1, 100, "Comprar leche", reminder_time)
        result = await db.get_pending_reminders()
        assert len(result) == 1
        assert result[0]["task"] == "Comprar leche"
        assert result[0]["user_id"] == 1

    async def test_get_pending_reminders_ordered_by_time(self, db):
        t1 = datetime(2099, 1, 1, tzinfo=pytz.UTC)
        t2 = datetime(2099, 6, 1, tzinfo=pytz.UTC)
        await db.add_reminder(1, 100, "Segundo", t2)
        await db.add_reminder(1, 100, "Primero", t1)
        result = await db.get_pending_reminders()
        assert result[0]["task"] == "Primero"
        assert result[1]["task"] == "Segundo"

    async def test_get_user_reminders_only_own(self, db):
        t = datetime(2099, 1, 1, tzinfo=pytz.UTC)
        await db.add_reminder(1, 100, "User1 reminder", t)
        await db.add_reminder(2, 200, "User2 reminder", t)
        result = await db.get_user_reminders(1)
        assert len(result) == 1
        assert result[0]["task"] == "User1 reminder"


class TestMarkAsNotified:
    async def test_mark_as_notified_removes_from_pending(self, db):
        t = datetime(2099, 1, 1, tzinfo=pytz.UTC)
        rid = await db.add_reminder(1, 100, "Tarea", t)
        await db.mark_as_notified(rid)
        result = await db.get_pending_reminders()
        assert result == []

    async def test_mark_as_notified_only_affects_one(self, db):
        t = datetime(2099, 1, 1, tzinfo=pytz.UTC)
        rid1 = await db.add_reminder(1, 100, "Tarea 1", t)
        await db.add_reminder(1, 100, "Tarea 2", t)
        await db.mark_as_notified(rid1)
        result = await db.get_pending_reminders()
        assert len(result) == 1
        assert result[0]["task"] == "Tarea 2"


class TestDeleteReminder:
    async def test_delete_own_reminder_returns_true(self, db):
        t = datetime(2099, 1, 1, tzinfo=pytz.UTC)
        rid = await db.add_reminder(1, 100, "Borrar esto", t)
        deleted = await db.delete_reminder(rid, user_id=1)
        assert deleted is True
        assert await db.get_user_reminders(1) == []

    async def test_delete_other_user_reminder_returns_false(self, db):
        t = datetime(2099, 1, 1, tzinfo=pytz.UTC)
        rid = await db.add_reminder(1, 100, "No tuyo", t)
        deleted = await db.delete_reminder(rid, user_id=2)
        assert deleted is False
        assert len(await db.get_user_reminders(1)) == 1

    async def test_delete_nonexistent_reminder_returns_false(self, db):
        deleted = await db.delete_reminder(9999, user_id=1)
        assert deleted is False


class TestDeleteAllReminders:
    async def test_delete_all_returns_count(self, db):
        t = datetime(2099, 1, 1, tzinfo=pytz.UTC)
        await db.add_reminder(1, 100, "A", t)
        await db.add_reminder(1, 100, "B", t)
        count = await db.delete_all_reminders(user_id=1)
        assert count == 2

    async def test_delete_all_only_affects_own_user(self, db):
        t = datetime(2099, 1, 1, tzinfo=pytz.UTC)
        await db.add_reminder(1, 100, "User1", t)
        await db.add_reminder(2, 200, "User2", t)
        await db.delete_all_reminders(user_id=1)
        assert len(await db.get_user_reminders(2)) == 1

    async def test_delete_all_when_none_returns_zero(self, db):
        count = await db.delete_all_reminders(user_id=1)
        assert count == 0


# ── Códigos de invitación ──────────────────────────────────────────────────────

class TestInvitationCodes:
    async def test_create_invitation_code_returns_string(self, db):
        code = await db.create_invitation_code()
        assert isinstance(code, str)
        assert len(code) > 0

    async def test_created_code_is_valid(self, db):
        code = await db.create_invitation_code()
        valid = await db.validate_invitation_code(code)
        assert valid is True

    async def test_invalid_code_returns_false(self, db):
        valid = await db.validate_invitation_code("codigo-falso")
        assert valid is False

    async def test_used_code_is_invalid(self, db):
        code = await db.create_invitation_code()
        await db.mark_code_as_used(code, user_id=42)
        valid = await db.validate_invitation_code(code)
        assert valid is False

    async def test_each_code_is_unique(self, db):
        codes = [await db.create_invitation_code() for _ in range(5)]
        assert len(set(codes)) == 5


# ── Usuarios ───────────────────────────────────────────────────────────────────

class TestUsers:
    async def _register_user(self, db, user_id=1, chat_id=100):
        code = await db.create_invitation_code()
        await db.register_user(
            user_id=user_id,
            chat_id=chat_id,
            display_name="Pepe",
            city="Madrid",
            timezone="Europe/Madrid",
            invitation_code=code,
        )
        return code

    async def test_register_and_get_user(self, db):
        await self._register_user(db)
        user = await db.get_user(1)
        assert user is not None
        assert user["display_name"] == "Pepe"
        assert user["city"] == "Madrid"
        assert user["timezone"] == "Europe/Madrid"
        assert user["is_active"] is True

    async def test_get_nonexistent_user_returns_none(self, db):
        user = await db.get_user(9999)
        assert user is None

    async def test_is_user_registered_true(self, db):
        await self._register_user(db)
        assert await db.is_user_registered(1) is True

    async def test_is_user_registered_false_for_unknown(self, db):
        assert await db.is_user_registered(9999) is False

    async def test_register_marks_invitation_code_as_used(self, db):
        code = await self._register_user(db)
        valid = await db.validate_invitation_code(code)
        assert valid is False

    async def test_deactivate_user_returns_true(self, db):
        await self._register_user(db)
        result = await db.deactivate_user(1)
        assert result is True
        assert await db.is_user_registered(1) is False

    async def test_deactivate_nonexistent_user_returns_false(self, db):
        result = await db.deactivate_user(9999)
        assert result is False

    async def test_get_all_users(self, db):
        await self._register_user(db, user_id=1, chat_id=100)
        await self._register_user(db, user_id=2, chat_id=200)
        users = await db.get_all_users()
        assert len(users) == 2
