from pathlib import Path

_BY_USERNAME: dict[str, str] = {}
_BY_PHONE: dict[str, str] = {}

_DEFAULT_PATH = Path(__file__).parent / "data" / "knowledge_base" / "users.txt"


def _normalize_phone(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())


def load(path: str | None = None) -> None:
    file_path = Path(path) if path else _DEFAULT_PATH
    try:
        text = file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"[user_profile] файл не найден: {file_path}")
        return

    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        identifier, profile = lines[0], "\n".join(lines[1:])
        if identifier.startswith("@"):
            _BY_USERNAME[identifier[1:].lower()] = profile
        elif identifier.lower().startswith("mobile:"):
            phone = _normalize_phone(identifier.split(":", 1)[1])
            if phone:
                _BY_PHONE[phone] = profile

    print(f"[user_profile] загружено: {len(_BY_USERNAME)} username, {len(_BY_PHONE)} phone")


def lookup(username: str = "", phone: str = "") -> str:
    if username:
        found = _BY_USERNAME.get(username.lower().lstrip("@"), "")
        if found:
            return found
    if phone:
        found = _BY_PHONE.get(_normalize_phone(phone), "")
        if found:
            return found
    return ""
