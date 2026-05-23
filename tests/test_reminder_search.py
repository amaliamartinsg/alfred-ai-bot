"""Tests para reminder_search."""
from datetime import datetime

from services.reminder_search import search_user_reminders, _tokenize, _score


SAMPLE_REMINDERS = [
    {"id": 1, "task": "Hacerme unos análisis médicos", "reminder_time": datetime(2099, 10, 1, 0, 0), "event_time": datetime(2099, 10, 1, 0, 0), "advance_minutes": 0},
    {"id": 2, "task": "Hacer una foto del contador de la luz", "reminder_time": datetime(2099, 5, 23, 10, 0), "event_time": datetime(2099, 5, 23, 10, 0), "advance_minutes": 0},
    {"id": 3, "task": "Llamar al fontanero", "reminder_time": datetime(2099, 6, 1, 9, 0), "event_time": datetime(2099, 6, 1, 9, 0), "advance_minutes": 0},
]

SAMPLE_NOTES = [
    {"id": 1, "task": "Renovar el seguro del coche"},
    {"id": 2, "task": "Comprar leche y pan"},
]


class TestTokenize:
    def test_removes_stopwords(self):
        tokens = _tokenize("que tengo que hacer hoy")
        assert "que" not in tokens
        assert "tengo" not in tokens
        assert "hoy" not in tokens

    def test_normalizes_accents(self):
        tokens = _tokenize("análisis médicos")
        assert "analisis" in tokens
        assert "medicos" in tokens

    def test_filters_short_words(self):
        tokens = _tokenize("un es la")
        assert not any(len(t) <= 2 for t in tokens)

    def test_lowercases(self):
        tokens = _tokenize("Llamar Fontanero")
        assert "llamar" in tokens
        assert "fontanero" in tokens


class TestScore:
    def test_perfect_match(self):
        s = _score({"analisis", "medicos"}, {"analisis", "medicos"})
        assert s == 1.0

    def test_partial_match(self):
        s = _score({"analisis"}, {"analisis", "medicos"})
        assert 0 < s < 1

    def test_no_match(self):
        s = _score({"perro"}, {"gato", "pez"})
        assert s == 0.0

    def test_empty_query(self):
        assert _score(set(), {"algo"}) == 0.0


class TestSearchUserReminders:
    def test_finds_analisis(self):
        results = search_user_reminders("cuándo tengo los análisis", SAMPLE_REMINDERS, [])
        assert len(results) >= 1
        assert results[0]["task"] == "Hacerme unos análisis médicos"
        assert results[0]["kind"] == "reminder"

    def test_finds_foto_contador(self):
        results = search_user_reminders("de qué tengo que hacer la foto", SAMPLE_REMINDERS, [])
        assert len(results) >= 1
        assert "foto" in results[0]["task"].lower()

    def test_finds_note(self):
        results = search_user_reminders("seguro del coche", [], SAMPLE_NOTES)
        assert len(results) >= 1
        assert results[0]["kind"] == "note"

    def test_returns_empty_when_no_match(self):
        results = search_user_reminders("pizza hawaiana", SAMPLE_REMINDERS, SAMPLE_NOTES)
        assert results == []

    def test_respects_top_k(self):
        results = search_user_reminders("hacer", SAMPLE_REMINDERS, SAMPLE_NOTES, top_k=1)
        assert len(results) <= 1

    def test_respects_min_score(self):
        results = search_user_reminders("análisis", SAMPLE_REMINDERS, [], min_score=0.99)
        # score({"analisis"}, {"hacerme","analisis","medicos"}) = 1/3 < 0.99
        assert results == []

    def test_sorted_by_score_desc(self):
        results = search_user_reminders("hacer foto", SAMPLE_REMINDERS, [], top_k=3)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_empty_query_returns_empty(self):
        results = search_user_reminders("", SAMPLE_REMINDERS, SAMPLE_NOTES)
        assert results == []

    def test_duplicate_detection_threshold(self):
        results = search_user_reminders(
            "Hacerme análisis médicos", SAMPLE_REMINDERS, [], top_k=1, min_score=0.7
        )
        assert len(results) == 1
        assert results[0]["id"] == 1
