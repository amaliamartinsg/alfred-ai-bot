"""
Servicio para mapear ciudades a zonas horarias usando OpenAI.
"""
import json
from openai import AsyncOpenAI
import logging

logger = logging.getLogger(__name__)


class CityService:
    """Servicio para obtener timezone a partir de una ciudad."""

    SYSTEM_PROMPT = """Eres un asistente que determina zonas horarias.
Dada una ciudad, responde SOLO con JSON válido: {"timezone": "Region/Ciudad", "ciudad_normalizada": "Nombre Oficial"}
Usa formato de zona horaria IANA (ej: Europe/Madrid, America/New_York).
Si no reconoces la ciudad, responde: {"timezone": null, "error": "Ciudad no reconocida"}"""

    def __init__(self, openai_client: AsyncOpenAI, model: str = "gpt-4o-mini"):
        """
        Inicializa el servicio.

        Args:
            openai_client: Cliente de OpenAI ya configurado.
            model: Modelo a utilizar.
        """
        self.client = openai_client
        self.model = model

    async def get_timezone_from_city(self, city: str) -> tuple[str | None, str | None]:
        """
        Obtiene la zona horaria de una ciudad.

        Args:
            city: Nombre de la ciudad introducido por el usuario.

        Returns:
            Tupla (timezone, ciudad_normalizada) o (None, None) si no se reconoce.
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=100,
                temperature=0,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": f"Ciudad: {city}"}
                ]
            )

            content = response.choices[0].message.content.strip()
            logger.debug(f"Respuesta timezone: {content}")

            data = json.loads(content)

            if not data.get("timezone"):
                return None, None

            return data["timezone"], data.get("ciudad_normalizada", city)

        except json.JSONDecodeError as e:
            logger.error(f"Error parseando JSON de timezone: {e}")
            return None, None
        except Exception as e:
            logger.error(f"Error obteniendo timezone: {e}")
            return None, None
