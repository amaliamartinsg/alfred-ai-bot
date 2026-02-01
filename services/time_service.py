"""
Servicio de gestión de tiempo y zonas horarias.
Maneja conversiones y obtención de fechas en la zona horaria configurada.
"""
from datetime import datetime
from typing import Optional
import pytz
import logging

logger = logging.getLogger(__name__)


class TimeService:
    """Gestiona operaciones de tiempo con soporte de zonas horarias."""

    def __init__(self, timezone_str: str):
        """
        Inicializa el servicio con la zona horaria especificada.

        Args:
            timezone_str: Zona horaria (ej: 'Europe/Madrid', 'America/Mexico_City')
        """
        try:
            self.timezone = pytz.timezone(timezone_str)
        except pytz.UnknownTimeZoneError:
            logger.warning(f"Zona horaria desconocida: {timezone_str}. Usando UTC.")
            self.timezone = pytz.UTC
        self.timezone_str = timezone_str

    def now(self) -> datetime:
        """Obtiene la fecha/hora actual en la zona horaria configurada."""
        return datetime.now(self.timezone)

    def parse_iso(self, iso_string: str) -> Optional[datetime]:
        """
        Parsea una fecha ISO 8601 y la localiza en la zona horaria configurada.

        Args:
            iso_string: Fecha en formato ISO (ej: '2024-05-20T15:30:00')

        Returns:
            Datetime localizado o None si el formato es inválido.
        """
        try:
            # Intentar parsear con zona horaria incluida
            if '+' in iso_string or 'Z' in iso_string:
                dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
                return dt.astimezone(self.timezone)

            # Parsear sin zona horaria y localizar
            dt = datetime.fromisoformat(iso_string)
            return self.timezone.localize(dt)
        except (ValueError, AttributeError) as e:
            logger.error(f"Error parseando fecha '{iso_string}': {e}")
            return None

    def is_future(self, dt: datetime) -> bool:
        """Verifica si una fecha está en el futuro."""
        now = self.now()
        # Asegurar que ambas fechas tengan zona horaria
        if dt.tzinfo is None:
            dt = self.timezone.localize(dt)
        return dt > now

    def format_for_display(self, dt: datetime) -> str:
        """
        Formatea una fecha para mostrar al usuario de forma legible.

        Args:
            dt: Datetime a formatear.

        Returns:
            Cadena formateada (ej: 'lunes 20 de mayo a las 15:30')
        """
        days = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
        months = [
            'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
            'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'
        ]

        day_name = days[dt.weekday()]
        month_name = months[dt.month - 1]

        return f"{day_name} {dt.day} de {month_name} a las {dt.strftime('%H:%M')}"

    def get_context_for_llm(self, user_timezone: Optional[str] = None) -> str:
        """
        Genera contexto temporal para el prompt del LLM.

        Args:
            user_timezone: Zona horaria del usuario (opcional, usa la default si no se especifica).

        Returns:
            Cadena con la fecha/hora actual para incluir en el prompt.
        """
        tz_str = user_timezone or self.timezone_str
        try:
            tz = pytz.timezone(tz_str)
        except pytz.UnknownTimeZoneError:
            tz = self.timezone
            tz_str = self.timezone_str

        now = datetime.now(tz)
        return (
            f"Fecha y hora actual: {now.strftime('%Y-%m-%d %H:%M:%S')} "
            f"(zona horaria: {tz_str})"
        )
