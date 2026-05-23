"""
Clasificador de intención para mensajes del usuario.
Determina si el mensaje es un recordatorio nuevo, una consulta, ayuda, etc.
"""
import json
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    CREATE_REMINDER = "create_reminder"
    LIST_REMINDERS = "list_reminders"
    QUERY_SPECIFIC = "query_specific"
    EDIT_REMINDER = "edit_reminder"
    DELETE_REMINDER = "delete_reminder"
    HELP = "help"
    GENERAL_CONVERSATION = "general_conversation"
    UNKNOWN = "unknown"


_SYSTEM_PROMPT = """Clasifica la intención del mensaje del usuario en una de estas categorías:
- create_reminder: quiere crear un recordatorio nuevo (incluye "recuérdame", "apúntame", mensajes con fecha/hora futura)
- list_reminders: pregunta qué recordatorios tiene pendientes en general ("qué tengo pendiente", "mis recordatorios")
- query_specific: pregunta sobre un recordatorio concreto ya existente ("cuándo tengo X", "de qué era Y", "a qué hora es Z")
- edit_reminder: quiere cambiar/editar/reprogramar un recordatorio existente
- delete_reminder: quiere borrar/cancelar un recordatorio existente
- help: pregunta qué puede hacer el bot ("qué puedes hacer", "cómo funciona", "ayuda")
- general_conversation: saludo, agradecimiento, charla sin relación con recordatorios
- unknown: no se puede determinar la intención

Responde SOLO con JSON válido: {"intent": "<categoría>", "confidence": <0.0-1.0>}"""


class IntentClassifier:
    """Clasifica la intención del mensaje usando OpenAI."""

    def __init__(self, openai_client, model: str = "gpt-4o-mini"):
        self.client = openai_client
        self.model = model

    async def classify(self, message: str) -> Intent:
        """
        Clasifica la intención del mensaje.

        Returns:
            Intent detectado (UNKNOWN si falla la llamada).
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=30,
                temperature=0.1,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
            )
            content = response.choices[0].message.content.strip()
            data = json.loads(content)
            intent_str = data.get("intent", "unknown")
            try:
                return Intent(intent_str)
            except ValueError:
                logger.warning("Intent desconocido recibido: %s", intent_str)
                return Intent.UNKNOWN
        except Exception as e:
            logger.error("Error clasificando intención: %s", e)
            return Intent.UNKNOWN
