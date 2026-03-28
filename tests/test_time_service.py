"""Tests para TimeService."""
import pytest
from datetime import datetime
import pytz

from services.time_service import TimeService


class TestTimeServiceInit:
    def test_valid_timezone(self):
        svc = TimeService("Europe/Madrid")
        assert svc.timezone == pytz.timezone("Europe/Madrid")
        assert svc.timezone_str == "Europe/Madrid"

    def test_invalid_timezone_falls_back_to_utc(self):
        svc = TimeService("Zona/Inexistente")
        assert svc.timezone == pytz.UTC

    def test_utc_timezone(self):
        svc = TimeService("UTC")
        assert svc.timezone == pytz.UTC


class TestTimeServiceNow:
    def test_now_is_aware(self):
        svc = TimeService("Europe/Madrid")
        now = svc.now()
        assert now.tzinfo is not None

    def test_now_uses_configured_timezone(self):
        svc = TimeService("America/New_York")
        now = svc.now()
        # El offset de New York debe ser -5 o -4 (según DST)
        offset_hours = now.utcoffset().total_seconds() / 3600
        assert -6 <= offset_hours <= -4


class TestTimeServiceParseIso:
    def test_parse_naive_datetime(self):
        svc = TimeService("Europe/Madrid")
        result = svc.parse_iso("2025-06-15T10:30:00")
        assert result is not None
        assert result.tzinfo is not None
        assert result.hour == 10
        assert result.minute == 30

    def test_parse_datetime_with_utc_offset(self):
        svc = TimeService("Europe/Madrid")
        result = svc.parse_iso("2025-06-15T10:30:00+00:00")
        assert result is not None
        assert result.tzinfo is not None

    def test_parse_datetime_with_z(self):
        svc = TimeService("Europe/Madrid")
        result = svc.parse_iso("2025-06-15T10:30:00Z")
        assert result is not None
        assert result.tzinfo is not None

    def test_parse_invalid_returns_none(self):
        svc = TimeService("Europe/Madrid")
        result = svc.parse_iso("esto-no-es-una-fecha")
        assert result is None

    def test_parse_empty_string_returns_none(self):
        svc = TimeService("Europe/Madrid")
        result = svc.parse_iso("")
        assert result is None


class TestTimeServiceIsFuture:
    def test_future_date_returns_true(self):
        svc = TimeService("Europe/Madrid")
        tz = pytz.timezone("Europe/Madrid")
        future = datetime(2099, 1, 1, 12, 0, 0, tzinfo=tz)
        assert svc.is_future(future) is True

    def test_past_date_returns_false(self):
        svc = TimeService("Europe/Madrid")
        tz = pytz.timezone("Europe/Madrid")
        past = datetime(2000, 1, 1, 12, 0, 0, tzinfo=tz)
        assert svc.is_future(past) is False

    def test_naive_datetime_is_localized(self):
        svc = TimeService("Europe/Madrid")
        future_naive = datetime(2099, 1, 1, 12, 0, 0)
        assert svc.is_future(future_naive) is True


class TestTimeServiceFormatForDisplay:
    def test_format_known_date(self):
        svc = TimeService("Europe/Madrid")
        tz = pytz.timezone("Europe/Madrid")
        # 2025-03-31 es lunes
        dt = datetime(2025, 3, 31, 15, 30, tzinfo=tz)
        result = svc.format_for_display(dt)
        assert "lunes" in result
        assert "31" in result
        assert "marzo" in result
        assert "15:30" in result

    def test_format_includes_all_parts(self):
        svc = TimeService("UTC")
        dt = datetime(2025, 12, 25, 9, 0, tzinfo=pytz.UTC)
        result = svc.format_for_display(dt)
        assert "25" in result
        assert "diciembre" in result
        assert "09:00" in result

    @pytest.mark.parametrize("month_num,month_name", [
        (1, "enero"), (2, "febrero"), (3, "marzo"), (4, "abril"),
        (5, "mayo"), (6, "junio"), (7, "julio"), (8, "agosto"),
        (9, "septiembre"), (10, "octubre"), (11, "noviembre"), (12, "diciembre"),
    ])
    def test_all_months_in_spanish(self, month_num, month_name):
        svc = TimeService("UTC")
        dt = datetime(2025, month_num, 1, 10, 0, tzinfo=pytz.UTC)
        result = svc.format_for_display(dt)
        assert month_name in result


class TestTimeServiceGetContextForLlm:
    def test_returns_string_with_date_and_timezone(self):
        svc = TimeService("Europe/Madrid")
        ctx = svc.get_context_for_llm()
        assert "Europe/Madrid" in ctx
        assert "Fecha y hora actual:" in ctx

    def test_uses_provided_timezone(self):
        svc = TimeService("Europe/Madrid")
        ctx = svc.get_context_for_llm("America/Mexico_City")
        assert "America/Mexico_City" in ctx

    def test_invalid_user_timezone_falls_back_to_default(self):
        svc = TimeService("Europe/Madrid")
        ctx = svc.get_context_for_llm("Zona/Invalida")
        assert "Europe/Madrid" in ctx
