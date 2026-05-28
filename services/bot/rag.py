import time
import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from config import CHROMA_HOST, CHROMA_PORT

_collection = None
_ef = DefaultEmbeddingFunction()


def _connect(retries: int = 10, delay: float = 3.0):
    global _collection
    for attempt in range(retries):
        try:
            client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT, ssl=False)
            client.heartbeat()
            _collection = client.get_or_create_collection("sales_knowledge", embedding_function=_ef)
            print(f"[RAG] Подключено к ChromaDB, документов: {_collection.count()}")
            return
        except Exception as e:
            print(f"[RAG] Ожидание ChromaDB ({attempt + 1}/{retries}): {e}")
            time.sleep(delay)
    raise RuntimeError("Не удалось подключиться к ChromaDB")


def init():
    _connect()


def search(query: str, n_results: int = 20) -> list[str]:
    global _collection
    if _collection is None:
        return []
    actual = min(n_results, _collection.count())
    if actual == 0:
        return []
    try:
        results = _collection.query(query_texts=[query], n_results=actual)
        docs = results.get("documents", [[]])[0]
        return [d for d in docs if d]
    except Exception as e:
        print(f"[RAG] Ошибка поиска: {e}, переподключаемся")
        try:
            _connect(retries=2, delay=1.0)
            actual = min(n_results, _collection.count())
            results = _collection.query(query_texts=[query], n_results=actual)
            docs = results.get("documents", [[]])[0]
            return [d for d in docs if d]
        except Exception as e2:
            print(f"[RAG] Повторная ошибка: {e2}")
            return []
