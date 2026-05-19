# Тесты форматирования временной метки из admin_server.dashboard


def _format_ts(raw_ts: str) -> str:
    if not raw_ts:
        return ""
    return raw_ts[8:10] + "." + raw_ts[5:7] + " " + raw_ts[11:16]


def test_timestamp_formatting():
    assert _format_ts("2024-01-15T14:30:00") == "15.01 14:30"


def test_timestamp_empty():
    assert _format_ts("") == ""
