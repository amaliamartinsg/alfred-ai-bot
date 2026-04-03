"""
Servicio de conexión con OpenAI para procesamiento de lenguaje natural.
Optimizado para consumo mínimo de tokens usando prompts cortos y directos.
"""
import json
from typing import Optional
from dataclasses import dataclass
from openai import AsyncOpenAI
import logging

logger = logging.getLogger(__name__)


@dataclass
class ReminderParseResult:
    """Resultado del parseo de un recordatorio."""
    task: str
    datetime_iso: str
    confirmation_message: str
    success: bool = True
    has_date: bool = True
    error_message: Optional[str] = None


class OpenAIService:
    """Gestiona las llamadas a la API de OpenAI."""

    # Prompt de sistema optimizado para mínimo consumo de tokens
    SYSTEM_PROMPT_PARSE = """Eres un asistente que extrae recordatorios de mensajes.
Responde SOLO con JSON válido, sin texto adicional.
Formato: {"tarea": "descripción corta", "fecha_iso": "YYYY-MM-DDTHH:MM:SS", "confirmacion_creativa": "mensaje breve y amigable"}
Si no puedes determinar la fecha/hora, usa fecha_iso: null."""

    SYSTEM_PROMPT_NOTIFICATION = """Genera un mensaje breve y amigable para recordar una tarea.
Responde SOLO con el mensaje, sin comillas ni formato extra. Máximo 100 caracteres."""

    SYSTEM_PROMPT_IDENTIFY_REMINDER = """Eres un asistente que identifica qué recordatorio quiere editar el usuario.
Se te da una lista de recordatorios (con ID, tarea y hora) y un mensaje del usuario.
Responde SOLO con JSON válido: {"id": <número_id>} o {"id": null} si no puedes identificarlo claramente."""

    SYSTEM_PROMPT_PARSE_TIME = """Eres un asistente que extrae una fecha u hora de un mensaje.
Responde SOLO con JSON válido: {"fecha_iso": "YYYY-MM-DDTHH:MM:SS"} o {"fecha_iso": null} si no hay fecha/hora."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", max_tokens: int = 200):
        """
        Inicializa el servicio de OpenAI.

        Args:
            api_key: Clave de API de OpenAI.
            model: Modelo a utilizar.
            max_tokens: Máximo de tokens en la respuesta.
        """
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    async def parse_reminder(
        self,
        user_message: str,
        time_context: str
    ) -> ReminderParseResult:
        """
        Procesa un mensaje del usuario para extraer tarea y fecha.

        Args:
            user_message: Mensaje del usuario en lenguaje natural.
            time_context: Contexto de fecha/hora actual.

        Returns:
            ReminderParseResult con los datos extraídos o error.
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=0.3,  # Baja temperatura para respuestas consistentes
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT_PARSE},
                    {"role": "user", "content": f"{time_context}\nMensaje: {user_message}"}
                ]
            )

            content = response.choices[0].message.content.strip()
            logger.debug(f"Respuesta OpenAI: {content}")

            # Parsear JSON de la respuesta
            data = json.loads(content)

            # Validar que tenemos los campos necesarios
            if not data.get("fecha_iso"):
                task = data.get("tarea", "").strip()
                if task:
                    # Hay tarea pero sin fecha: el handler preguntará al usuario
                    return ReminderParseResult(
                        task=task,
                        datetime_iso="",
                        confirmation_message="",
                        success=True,
                        has_date=False,
                    )
                return ReminderParseResult(
                    task="",
                    datetime_iso="",
                    confirmation_message="",
                    success=False,
                    error_message="No pude determinar cuándo quieres el recordatorio. "
                                  "Por favor, especifica la fecha u hora."
                )

            return ReminderParseResult(
                task=data.get("tarea", "Recordatorio"),
                datetime_iso=data["fecha_iso"],
                confirmation_message=data.get(
                    "confirmacion_creativa",
                    "Recordatorio programado correctamente."
                )
            )

        except json.JSONDecodeError as e:
            logger.error(f"Error parseando JSON de OpenAI: {e}")
            return ReminderParseResult(
                task="",
                datetime_iso="",
                confirmation_message="",
                success=False,
                error_message="No pude entender bien tu mensaje. "
                              "Intenta de nuevo con más detalle."
            )
        except Exception as e:
            logger.error(f"Error en llamada a OpenAI: {e}")
            return ReminderParseResult(
                task="",
                datetime_iso="",
                confirmation_message="",
                success=False,
                error_message="Hubo un problema procesando tu mensaje. "
                              "Inténtalo de nuevo en unos segundos."
            )

    async def identify_reminder_to_edit(
        self,
        user_message: str,
        reminders: list[dict]
    ) -> Optional[int]:
        """
        Identifica qué recordatorio de la lista quiere editar el usuario.

        Args:
            user_message: Mensaje del usuario en lenguaje natural.
            reminders: Lista de recordatorios con 'id', 'task' y 'reminder_time'.

        Returns:
            ID del recordatorio identificado o None si no se puede determinar.
        """
        reminders_text = "\n".join(
            [f"[{r['id']}] {r['task']} — {r['reminder_time']}" for r in reminders]
        )
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=30,
                temperature=0.1,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT_IDENTIFY_REMINDER},
                    {
                        "role": "user",
                        "content": (
                            f"Recordatorios:\n{reminders_text}\n\n"
                            f"Mensaje del usuario: {user_message}"
                        )
                    }
                ]
            )
            content = response.choices[0].message.content.strip()
            data = json.loads(content)
            result = data.get("id")
            return int(result) if result is not None else None
        except Exception as e:
            logger.error(f"Error identificando recordatorio a editar: {e}")
            return None

    async def parse_time_expression(
        self,
        user_message: str,
        time_context: str
    ) -> Optional[str]:
        """
        Extrae únicamente una fecha/hora de un mensaje del usuario.

        Args:
            user_message: Mensaje con la nueva hora.
            time_context: Contexto de fecha/hora actual.

        Returns:
            Fecha en formato ISO 8601 o None si no se puede determinar.
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=40,
                temperature=0.1,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT_PARSE_TIME},
                    {"role": "user", "content": f"{time_context}\nMensaje: {user_message}"}
                ]
            )
            content = response.choices[0].message.content.strip()
            data = json.loads(content)
            return data.get("fecha_iso")
        except Exception as e:
            logger.error(f"Error parseando expresión de tiempo: {e}")
            return None

    async def generate_notification_message(self, task: str) -> str:
        """
        Genera un mensaje de notificación creativo para un recordatorio.

        Args:
            task: Descripción de la tarea a recordar.

        Returns:
            Mensaje de notificación generado por el LLM.
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=60,  # Notificaciones cortas
                temperature=0.8,  # Mayor creatividad para variedad
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT_NOTIFICATION},
                    {"role": "user", "content": f"Tarea: {task}"}
                ]
            )

            message = response.choices[0].message.content.strip()
            return message

        except Exception as e:
            logger.error(f"Error generando notificación: {e}")
            # Fallback a mensaje genérico
            return f"¡Recuerda: {task}!"
