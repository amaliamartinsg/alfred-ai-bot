"""Tests para la validación de configuración."""
import pytest
from unittest.mock import patch


class TestValidateConfig:
    def test_all_vars_present_passes(self):
        env = {
            "TELEGRAM_TOKEN": "tok123",
            "OPENAI_API_KEY": "sk-abc",
            "ADMIN_USER_ID": "12345",
        }
        with patch.dict("os.environ", env, clear=False):
            import importlib
            import config
            importlib.reload(config)
            config.validate_config()  # no debe lanzar

    def test_missing_telegram_token_raises(self):
        env = {"OPENAI_API_KEY": "sk-abc", "ADMIN_USER_ID": "12345"}
        with patch.dict("os.environ", env, clear=True):
            import importlib
            import config
            importlib.reload(config)
            with pytest.raises(ValueError, match="TELEGRAM_TOKEN"):
                config.validate_config()

    def test_missing_openai_key_raises(self):
        env = {"TELEGRAM_TOKEN": "tok123", "ADMIN_USER_ID": "12345"}
        with patch.dict("os.environ", env, clear=True):
            import importlib
            import config
            importlib.reload(config)
            with pytest.raises(ValueError, match="OPENAI_API_KEY"):
                config.validate_config()

    def test_missing_admin_user_id_raises(self):
        env = {"TELEGRAM_TOKEN": "tok123", "OPENAI_API_KEY": "sk-abc"}
        with patch.dict("os.environ", env, clear=True):
            import importlib
            import config
            importlib.reload(config)
            with pytest.raises(ValueError, match="ADMIN_USER_ID"):
                config.validate_config()

    def test_error_message_lists_all_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            import importlib
            import config
            importlib.reload(config)
            with pytest.raises(ValueError) as exc_info:
                config.validate_config()
            msg = str(exc_info.value)
            assert "TELEGRAM_TOKEN" in msg
            assert "OPENAI_API_KEY" in msg
            assert "ADMIN_USER_ID" in msg

    def test_default_timezone_is_europe_madrid(self):
        env = {
            "TELEGRAM_TOKEN": "tok",
            "OPENAI_API_KEY": "key",
            "ADMIN_USER_ID": "1",
        }
        with patch.dict("os.environ", env, clear=True):
            import importlib
            import config
            importlib.reload(config)
            assert config.DFT_TIMEZONE == "Europe/Madrid"

    def test_custom_timezone_is_loaded(self):
        env = {
            "TELEGRAM_TOKEN": "tok",
            "OPENAI_API_KEY": "key",
            "ADMIN_USER_ID": "1",
            "DFT_TIMEZONE": "America/Mexico_City",
        }
        with patch.dict("os.environ", env, clear=True):
            import importlib
            import config
            importlib.reload(config)
            assert config.DFT_TIMEZONE == "America/Mexico_City"
