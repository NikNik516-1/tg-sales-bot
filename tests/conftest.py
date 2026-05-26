import os
import sys

# Set required env vars before any project module is imported
os.environ.setdefault("TG_API_ID", "12345")
os.environ.setdefault("TG_API_HASH", "testhash000000000000000000000000")
os.environ.setdefault("TG_SESSION_STRING", "testsession")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("ADMIN_TG_ID", "12345")
os.environ.setdefault("KEYWORDS", "хочу купить,нужна ручка,ищу ручку")
os.environ.setdefault("MONITORED_CHATS", "-100123,-100456")

# Make shared/ and bot/ importable
ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "bot"))
