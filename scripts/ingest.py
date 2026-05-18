"""
Загружает файлы из data/knowledge_base/ в ChromaDB.
Запускать ПОСЛЕ docker-compose up (когда ChromaDB уже работает).

  python scripts/ingest.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8000"))
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "knowledge_base")

client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
ef = OpenAIEmbeddingFunction(api_key=OPENAI_API_KEY, model_name="text-embedding-3-small")
collection = client.get_or_create_collection("sales_knowledge", embedding_function=ef)

documents, ids = [], []
chunk_size = 600

for filename in sorted(os.listdir(DATA_DIR)):
    if not filename.endswith(".txt"):
        continue
    path = os.path.join(DATA_DIR, filename)
    with open(path, encoding="utf-8") as f:
        content = f.read()
    chunks = [content[i : i + chunk_size].strip() for i in range(0, len(content), chunk_size)]
    for k, chunk in enumerate(chunks):
        if chunk:
            documents.append(chunk)
            ids.append(f"{filename}_{k}")
    print(f"  {filename}: {len(chunks)} фрагментов")

if documents:
    collection.upsert(documents=documents, ids=ids)
    print(f"\nГотово: {len(documents)} фрагментов загружено в ChromaDB.")
else:
    print("Нет .txt файлов в data/knowledge_base/")
