import time
import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from config import CHROMA_HOST, CHROMA_PORT, OPENAI_API_KEY

_collection = None


def _connect(retries: int = 10, delay: float = 3.0):
    global _collection
    ef = OpenAIEmbeddingFunction(api_key=OPENAI_API_KEY, model_name="text-embedding-3-small")
    for attempt in range(retries):
        try:
            client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT, ssl=False)
            client.heartbeat()
            _collection = client.get_or_create_collection("sales_knowledge", embedding_function=ef)
            print(f"[RAG] Подключено к ChromaDB, документов: {_collection.count()}")
            return
        except Exception as e:
            print(f"[RAG] Ожидание ChromaDB ({attempt + 1}/{retries}): {e}")
            time.sleep(delay)
    raise RuntimeError("Не удалось подключиться к ChromaDB")


def init():
    _connect()


def search(query: str, n_results: int = 3) -> list[str]:
    if _collection is None:
        return []
    try:
        results = _collection.query(query_texts=[query], n_results=n_results)
        docs = results.get("documents", [[]])[0]
        return [d for d in docs if d]
    except Exception as e:
        print(f"[RAG] Ошибка поиска: {e}")
        return []
