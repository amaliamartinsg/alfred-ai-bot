"""Tests para OpenAIService con OpenAI mockeado."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

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
    def test_parse_prompt_preserves_non_temporal_details(self):
        prompt = OpenAIService.SYSTEM_PROMPT_PARSE.lower()
        assert "conserva todos los detalles" in prompt
        assert "lugar" in prompt
        assert "contexto" in prompt

    def test_parse_prompt_supports_advance_notice(self):
        prompt = OpenAIService.SYSTEM_PROMPT_PARSE.lower()
        assert "fecha_evento_iso" in prompt
        assert "preaviso_minutos" in prompt
        assert "2 horas antes" in prompt

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

    async def test_parse_advance_notice(self, svc, mock_openai_client):
        payload = {
            "tarea": "Médico",
            "fecha_iso": "2099-06-15T18:00:00",
            "fecha_evento_iso": "2099-06-15T20:00:00",
            "preaviso_minutos": 120,
            "confirmacion_creativa": "Te aviso dos horas antes.",
        }
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response(json.dumps(payload))
        )

        result = await svc.parse_reminder(
            "recuérdame dos horas antes que tengo médico mañana a las 8",
            "hoy es viernes",
        )

        assert result.datetime_iso == "2099-06-15T18:00:00"
        assert result.event_datetime_iso == "2099-06-15T20:00:00"
        assert result.advance_minutes == 120

    async def test_parse_advance_notice_accepts_string_minutes(self, svc, mock_openai_client):
        payload = {
            "tarea": "Médico",
            "fecha_iso": "2099-06-15T18:00:00",
            "fecha_evento_iso": "2099-06-15T20:00:00",
            "preaviso_minutos": "120",
            "confirmacion_creativa": "Te aviso dos horas antes.",
        }
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response(json.dumps(payload))
        )

        result = await svc.parse_reminder("algo", "hoy")

        assert result.advance_minutes == 120

    async def test_missing_fecha_iso_returns_success_without_date(self, svc, mock_openai_client):
        payload = {"tarea": "Algo", "fecha_iso": None, "confirmacion_creativa": ""}
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response(json.dumps(payload))
        )
        result = await svc.parse_reminder("Hazme un recordatorio", "ahora")
        assert result.success is True
        assert result.has_date is False
        assert result.task == "Algo"

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


# ── identify_reminder_to_edit ──────────────────────────────────────────────────

REMINDERS_SAMPLE = [
    {"id": 1, "task": "Llamar al médico", "reminder_time": "2099-06-01T10:00:00"},
    {"id": 2, "task": "Comprar leche", "reminder_time": "2099-06-02T11:00:00"},
]


class TestIdentifyReminderToEdit:
    async def test_returns_identified_id(self, svc, mock_openai_client):
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response('{"id": 1}')
        )
        result = await svc.identify_reminder_to_edit("edita el del médico", REMINDERS_SAMPLE)
        assert result == 1

    async def test_returns_none_when_not_identified(self, svc, mock_openai_client):
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response('{"id": null}')
        )
        result = await svc.identify_reminder_to_edit("no sé cuál", REMINDERS_SAMPLE)
        assert result is None

    async def test_api_exception_returns_none(self, svc, mock_openai_client):
        mock_openai_client.chat.completions.create.side_effect = Exception("error")
        result = await svc.identify_reminder_to_edit("editar algo", REMINDERS_SAMPLE)
        assert result is None

    async def test_invalid_json_returns_none(self, svc, mock_openai_client):
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response("no es json")
        )
        result = await svc.identify_reminder_to_edit("editar algo", REMINDERS_SAMPLE)
        assert result is None


# ── parse_time_expression ──────────────────────────────────────────────────────

class TestParseTimeExpression:
    async def test_returns_iso_string(self, svc, mock_openai_client):
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response('{"fecha_iso": "2099-06-15T15:30:00"}')
        )
        result = await svc.parse_time_expression("a las 15:30", "hoy es viernes")
        assert result == "2099-06-15T15:30:00"

    async def test_returns_none_when_no_time(self, svc, mock_openai_client):
        mock_openai_client.chat.completions.create.return_value = (
            _make_mock_response('{"fecha_iso": null}')
        )
        result = await svc.parse_time_expression("hola qué tal", "hoy")
        assert result is None

    async def test_api_exception_returns_none(self, svc, mock_openai_client):
        mock_openai_client.chat.completions.create.side_effect = Exception("error")
        result = await svc.parse_time_expression("a las 10", "hoy")
        assert result is None
