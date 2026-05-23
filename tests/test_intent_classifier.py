"""Tests para IntentClassifier con OpenAI mockeado."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from services.intent_classifier import IntentClassifier, Intent


def _mock_response(intent: str, confidence: float = 0.9) -> MagicMock:
    msg = MagicMock()
    msg.content = json.dumps({"intent": intent, "confidence": confidence})
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock()
    return client


@pytest.fixture
def classifier(mock_client):
    return IntentClassifier(openai_client=mock_client, model="gpt-4o-mini")


class TestIntentClassifier:
    async def test_create_reminder(self, classifier, mock_client):
        mock_client.chat.completions.create.return_value = _mock_response("create_reminder")
        result = await classifier.classify("Recuérdame a las 10 que llame al dentista")
        assert result == Intent.CREATE_REMINDER

    async def test_create_reminder_with_time(self, classifier, mock_client):
        mock_client.chat.completions.create.return_value = _mock_response("create_reminder")
        result = await classifier.classify("Mañana a las 9 tengo reunión")
        assert result == Intent.CREATE_REMINDER

    async def test_list_reminders(self, classifier, mock_client):
        mock_client.chat.completions.create.return_value = _mock_response("list_reminders")
        result = await classifier.classify("¿Qué recordatorios tengo pendientes?")
        assert result == Intent.LIST_REMINDERS

    async def test_list_reminders_general(self, classifier, mock_client):
        mock_client.chat.completions.create.return_value = _mock_response("list_reminders")
        result = await classifier.classify("qué tengo esta semana")
        assert result == Intent.LIST_REMINDERS

    async def test_query_specific(self, classifier, mock_client):
        mock_client.chat.completions.create.return_value = _mock_response("query_specific")
        result = await classifier.classify("¿Cuándo tengo los análisis?")
        assert result == Intent.QUERY_SPECIFIC

    async def test_query_specific_detail(self, classifier, mock_client):
        mock_client.chat.completions.create.return_value = _mock_response("query_specific")
        result = await classifier.classify("De qué tengo que hacer la foto")
        assert result == Intent.QUERY_SPECIFIC

    async def test_edit_reminder(self, classifier, mock_client):
        mock_client.chat.completions.create.return_value = _mock_response("edit_reminder")
        result = await classifier.classify("Cambia el recordatorio del médico a las 5")
        assert result == Intent.EDIT_REMINDER

    async def test_edit_reminder_postpone(self, classifier, mock_client):
        mock_client.chat.completions.create.return_value = _mock_response("edit_reminder")
        result = await classifier.classify("Pospón el de mañana una hora")
        assert result == Intent.EDIT_REMINDER

    async def test_help(self, classifier, mock_client):
        mock_client.chat.completions.create.return_value = _mock_response("help")
        result = await classifier.classify("¿Qué puedes hacer?")
        assert result == Intent.HELP

    async def test_help_how(self, classifier, mock_client):
        mock_client.chat.completions.create.return_value = _mock_response("help")
        result = await classifier.classify("cómo funciona esto")
        assert result == Intent.HELP

    async def test_general_conversation_greeting(self, classifier, mock_client):
        mock_client.chat.completions.create.return_value = _mock_response("general_conversation")
        result = await classifier.classify("Hola!")
        assert result == Intent.GENERAL_CONVERSATION

    async def test_general_conversation_thanks(self, classifier, mock_client):
        mock_client.chat.completions.create.return_value = _mock_response("general_conversation")
        result = await classifier.classify("Muchas gracias")
        assert result == Intent.GENERAL_CONVERSATION

    async def test_unknown_intent_returns_unknown(self, classifier, mock_client):
        msg = MagicMock()
        msg.content = json.dumps({"intent": "something_new", "confidence": 0.5})
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        mock_client.chat.completions.create.return_value = resp
        result = await classifier.classify("asdfghjkl")
        assert result == Intent.UNKNOWN

    async def test_api_exception_returns_unknown(self, classifier, mock_client):
        mock_client.chat.completions.create.side_effect = Exception("timeout")
        result = await classifier.classify("algo")
        assert result == Intent.UNKNOWN

    async def test_invalid_json_returns_unknown(self, classifier, mock_client):
        msg = MagicMock()
        msg.content = "no es json"
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        mock_client.chat.completions.create.return_value = resp
        result = await classifier.classify("algo")
        assert result == Intent.UNKNOWN
