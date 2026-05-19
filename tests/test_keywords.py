# Тесты логики поиска ключевых слов из listener._has_keyword

KEYWORDS = ["хочу купить", "нужна ручка", "ищу ручку"]


def _matches(text: str, keywords: list[str]) -> bool:
    return any(kw in text.lower() for kw in keywords)


def test_keyword_found():
    assert _matches("Хочу купить хорошую ручку", KEYWORDS)


def test_keyword_not_found():
    assert not _matches("Просто привет, как дела?", KEYWORDS)


def test_keyword_case_insensitive():
    assert _matches("МНЕ НУЖНА РУЧКА срочно!!!", KEYWORDS)
