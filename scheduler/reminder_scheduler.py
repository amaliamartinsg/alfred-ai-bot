"""
Programador de recordatorios usando APScheduler.
Gestiona la programación y ejecución de notificaciones.
"""
from datetime import datetime
from typing import Callable, Awaitable, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import pytz
import logging

logger = logging.getLogger(__name__)


class ReminderScheduler:
    """Gestiona la programación de recordatorios con APScheduler."""

    def __init__(self, timezone: pytz.BaseTzInfo):
        """
        Inicializa el scheduler.

        Args:
            timezone: Zona horaria para programar los trabajos.
        """
        self.timezone = timezone
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        self._notification_callback: Optional[Callable[[int, int, str], Awaitable[None]]] = None

    def set_notification_callback(
        self,
        callback: Callable[[int, int, str], Awaitable[None]]
    ) -> None:
        """
        Configura el callback que se ejecutará al dispararse un recordatorio.

        Args:
            callback: Función async que recibe (reminder_id, chat_id, task).
        """
        self._notification_callback = callback

    def start(self) -> None:
        """Inicia el scheduler."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler iniciado")

    def shutdown(self) -> None:
        """Detiene el scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler detenido")

    def schedule_reminder(
        self,
        reminder_id: int,
        chat_id: int,
        task: str,
        reminder_time: datetime
    ) -> bool:
        """
        Programa un nuevo recordatorio.

        Args:
            reminder_id: ID del recordatorio en la base de datos.
            chat_id: ID del chat de Telegram donde enviar la notificación.
            task: Descripción de la tarea.
            reminder_time: Fecha/hora para la notificación.

        Returns:
            True si se programó correctamente, False si la fecha ya pasó.
        """
        # Verificar que la fecha esté en el futuro
        now = datetime.now(self.timezone)
        if reminder_time.tzinfo is None:
            reminder_time = self.timezone.localize(reminder_time)

        if reminder_time <= now:
            logger.warning(f"Recordatorio {reminder_id} tiene fecha pasada: {reminder_time}")
            return False

        job_id = f"reminder_{reminder_id}"

        # Eliminar job existente si existe (por si se reprograma)
        existing_job = self.scheduler.get_job(job_id)
        if existing_job:
            existing_job.remove()

        # Programar el nuevo job
        self.scheduler.add_job(
            func=self._trigger_notification,
            trigger=DateTrigger(run_date=reminder_time, timezone=self.timezone),
            args=[reminder_id, chat_id, task],
            id=job_id,
            name=f"Recordatorio: {task[:30]}",
            replace_existing=True
        )

        logger.info(
            f"Recordatorio {reminder_id} programado para {reminder_time.isoformat()}"
        )
        return True

    async def _trigger_notification(
        self,
        reminder_id: int,
        chat_id: int,
        task: str
    ) -> None:
        """
        Ejecuta la notificación cuando llega la hora programada.

        Args:
            reminder_id: ID del recordatorio.
            chat_id: ID del chat de Telegram.
            task: Descripción de la tarea.
        """
        logger.info(f"Disparando recordatorio {reminder_id}")

        if self._notification_callback:
            try:
                await self._notification_callback(reminder_id, chat_id, task)
            except Exception as e:
                logger.error(f"Error ejecutando callback de notificación: {e}")
        else:
            logger.warning("No hay callback de notificación configurado")

    def cancel_reminder(self, reminder_id: int) -> bool:
        """
        Cancela un recordatorio programado.

        Args:
            reminder_id: ID del recordatorio a cancelar.

        Returns:
            True si se canceló, False si no existía.
        """
        job_id = f"reminder_{reminder_id}"
        job = self.scheduler.get_job(job_id)

        if job:
            job.remove()
            logger.info(f"Recordatorio {reminder_id} cancelado")
            return True

        return False

    def get_scheduled_count(self) -> int:
        """Obtiene el número de recordatorios programados."""
        return len(self.scheduler.get_jobs())
