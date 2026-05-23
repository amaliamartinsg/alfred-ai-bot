"""
Búsqueda semántica ligera de recordatorios por keywords.
No usa embeddings: tokenización + stopwords en español.
"""
import unicodedata
import re

_STOPWORDS = {
    "a", "al", "ante", "bajo", "con", "contra", "de", "del", "desde",
    "durante", "el", "en", "entre", "es", "esa", "ese", "esta", "este",
    "fue", "hacerme", "hacia", "hasta", "la", "las", "le", "les", "lo",
    "los", "me", "mi", "mis", "muy", "no", "o", "para", "pero", "por",
    "que", "se", "sin", "sobre", "su", "sus", "te", "tiene", "tienen",
    "tras", "tu", "tus", "un", "una", "uno", "unos", "unas", "y", "ya",
    "yo", "tengo", "tienes", "tenemos", "hay", "hoy", "mañana", "ayer",
    "recordatorio", "recordar", "recuerdame", "acordarme", "avisarme",
}


def _normalize(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text)
    no_accents = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return no_accents.lower()


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", _normalize(text))
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _score(query_tokens: set[str], task_tokens: set[str]) -> float:
    if not query_tokens or not task_tokens:
        return 0.0
    intersection = query_tokens & task_tokens
    return len(intersection) / max(len(query_tokens), len(task_tokens))


def search_user_reminders(
    query: str,
    reminders: list[dict],
    notes: list[dict],
    top_k: int = 3,
    min_score: float = 0.2,
) -> list[dict]:
    """
    Busca recordatorios y notas por keywords relevantes a la query.

    Args:
        query: Pregunta o fragmento del usuario.
        reminders: Lista de dicts con al menos {"id", "task", "reminder_time"}.
        notes: Lista de dicts con al menos {"id", "task"}.
        top_k: Máximo de resultados a devolver.
        min_score: Umbral mínimo de similitud para incluir resultado.

    Returns:
        Lista de dicts enriquecidos con "score" y "kind" ("reminder" | "note"),
        ordenados por score descendente.
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    candidates = []
    for r in reminders:
        score = _score(query_tokens, _tokenize(r["task"]))
        if score >= min_score:
            candidates.append({**r, "score": score, "kind": "reminder"})
    for n in notes:
        score = _score(query_tokens, _tokenize(n["task"]))
        if score >= min_score:
            candidates.append({**n, "score": score, "kind": "note"})

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_k]
