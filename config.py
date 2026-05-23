"""
Configuración central del bot de recordatorios.
Carga las variables de entorno y define constantes.
"""
import os
from dotenv import load_dotenv

_env_file = os.getenv("ENV_FILE", ".env")
load_dotenv(_env_file)

# Tokens y claves API
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Configuración de zona horaria
DFT_TIMEZONE = os.getenv("DFT_TIMEZONE", "Europe/Madrid")

# Administrador del bot (user_id de Telegram)
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

# Configuración de base de datos
DATABASE_PATH = os.path.join(os.path.dirname(__file__), "data","reminders.db")

# Configuración OpenAI
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_MAX_TOKENS = 200

# Confirmación previa al guardar recordatorio (False por defecto para no romper UX existente)
CONFIRMATION_REQUIRED = os.getenv("CONFIRMATION_REQUIRED", "false").lower() == "true"

# Validación de configuración requerida
def validate_config():
    """Valida que las variables de entorno requeridas estén configuradas."""
    missing = []
    if not TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")

    if not ADMIN_USER_ID:
        missing.append("ADMIN_USER_ID")

    if missing:
        raise ValueError(f"Variables de entorno faltantes: {', '.join(missing)}")
