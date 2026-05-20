from pathlib import Path

_BY_USERNAME: dict[str, str] = {}
_BY_PHONE: dict[str, str] = {}
_last_mtime: float = 0.0

_DEFAULT_PATH = Path(__file__).parent / "data" / "knowledge_base" / "users.txt"


def _normalize_phone(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())


def _reload(file_path: Path, verbose: bool = False) -> None:
    global _BY_USERNAME, _BY_PHONE, _last_mtime
    try:
        mtime = file_path.stat().st_mtime
    except FileNotFoundError:
        if verbose:
            print(f"[user_profile] файл не найден: {file_path}")
        return
    if mtime == _last_mtime:
        return
    by_username: dict[str, str] = {}
    by_phone: dict[str, str] = {}
    try:
        text = file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    for block in [b.strip() for b in text.split("\n\n") if b.strip()]:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        identifier, profile = lines[0], "\n".join(lines[1:])
        if identifier.startswith("@"):
            by_username[identifier[1:].lower()] = profile
        elif identifier.lower().startswith("mobile:"):
            phone = _normalize_phone(identifier.split(":", 1)[1])
            if phone:
                by_phone[phone] = profile
    _BY_USERNAME, _BY_PHONE, _last_mtime = by_username, by_phone, mtime
    if verbose:
        print(f"[user_profile] загружено: {len(_BY_USERNAME)} username, {len(_BY_PHONE)} phone")


def load(path: str | None = None) -> None:
    _reload(Path(path) if path else _DEFAULT_PATH, verbose=True)


def lookup(username: str = "", phone: str = "") -> str:
    _reload(_DEFAULT_PATH)
    if username:
        found = _BY_USERNAME.get(username.lower().lstrip("@"), "")
        if found:
            return found
    if phone:
        found = _BY_PHONE.get(_normalize_phone(phone), "")
        if found:
            return found
    return ""
