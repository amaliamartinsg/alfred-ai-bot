"""Tests para OpenAIService con OpenAI mockeado."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.openai_service import OpenAIService, ReminderParseResult


def _make_mock_response(content: str) -> MagicMock:
    """Crea un objeto respuesta falso con la estructura de la API de OpenAI."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.fixture
def mock_openai_client():
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock()
    return client


@pytest.fixture
def svc(mock_openai_client):
    service = OpenAIService.__new__(OpenAIService)
    service.client = mock_openai_client
    service.model = "gpt-4o-mini"
    service.max_tokens = 200
    return service


# ── parse_reminder ─────────────────────────────────────────────────────────────

class TestParseReminder:
    async def test_successful_parse(self, svc, mock_openai_client):
        payload = {
            "tarea": "Llamar al médico",
            "fecha_iso": "2099-06-15T10:30:00",
            "confirmacion_creativa": "¡Genial! Te recuerdo el lunes.",
        }
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response(json.dumps(payload))
        )
        result = await svc.parse_reminder("Llama al médico el lunes", "hoy es viernes")
        assert result.success is True
        assert result.task == "Llamar al médico"
        assert result.datetime_iso == "2099-06-15T10:30:00"
        assert "Genial" in result.confirmation_message

    async def test_missing_fecha_iso_returns_failure(self, svc, mock_openai_client):
        payload = {"tarea": "Algo", "fecha_iso": None, "confirmacion_creativa": ""}
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response(json.dumps(payload))
        )
        result = await svc.parse_reminder("Hazme un recordatorio", "ahora")
        assert result.success is False
        assert result.error_message is not None

    async def test_invalid_json_returns_failure(self, svc, mock_openai_client):
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response("esto no es json {{{")
        )
        result = await svc.parse_reminder("algo", "contexto")
        assert result.success is False
        assert "entender" in result.error_message.lower()

    async def test_api_exception_returns_failure(self, svc, mock_openai_client):
        mock_openai_client.chat.completions.create.side_effect = Exception("timeout")
        result = await svc.parse_reminder("algo", "contexto")
        assert result.success is False
        assert result.error_message is not None

    async def test_missing_tarea_uses_default(self, svc, mock_openai_client):
        payload = {"fecha_iso": "2099-01-01T09:00:00", "confirmacion_creativa": "Ok"}
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response(json.dumps(payload))
        )
        result = await svc.parse_reminder("recuérdame algo mañana", "hoy")
        assert result.task == "Recordatorio"

    async def test_result_is_dataclass(self, svc, mock_openai_client):
        payload = {
            "tarea": "Tarea",
            "fecha_iso": "2099-01-01T09:00:00",
            "confirmacion_creativa": "Ok",
        }
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response(json.dumps(payload))
        )
        result = await svc.parse_reminder("algo", "contexto")
        assert isinstance(result, ReminderParseResult)


# ── generate_notification_message ─────────────────────────────────────────────

class TestGenerateNotificationMessage:
    async def test_returns_generated_message(self, svc, mock_openai_client):
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response("¡No olvides llamar al médico!")
        )
        msg = await svc.generate_notification_message("Llamar al médico")
        assert msg == "¡No olvides llamar al médico!"

    async def test_strips_whitespace(self, svc, mock_openai_client):
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response("  mensaje con espacios  ")
        )
        msg = await svc.generate_notification_message("tarea")
        assert msg == "mensaje con espacios"

    async def test_api_exception_returns_fallback(self, svc, mock_openai_client):
        mock_openai_client.chat.completions.create.side_effect = Exception("error")
        msg = await svc.generate_notification_message("Comprar pan")
        assert "Comprar pan" in msg
