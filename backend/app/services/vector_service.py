import hashlib
import math
from typing import Any

from app.core.config import settings


EMBEDDING_DIM = 384


def simple_embedding(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    clean = "".join(str(text or "").split()).lower()
    if not clean:
        return vector
    tokens: list[str] = []
    for size in (2, 3, 4):
        tokens.extend(clean[index : index + size] for index in range(max(0, len(clean) - size + 1)))
    if not tokens:
        tokens = [clean]
    for token in tokens:
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIM
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _collection():
    try:
        import chromadb  # type: ignore
    except Exception:
        return None
    settings.chroma_root.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(settings.chroma_root))
    return client.get_or_create_collection(name=settings.chroma_collection)


def chroma_available() -> bool:
    return _collection() is not None


def upsert_knowledge_chunk(chroma_id: str, content: str, metadata: dict[str, Any]) -> bool:
    collection = _collection()
    if collection is None:
        return False
    clean_metadata = {key: ("" if value is None else value) for key, value in metadata.items()}
    collection.upsert(
        ids=[chroma_id],
        documents=[content],
        embeddings=[simple_embedding(content)],
        metadatas=[clean_metadata],
    )
    return True


def delete_knowledge_chunks(chroma_ids: list[str]) -> None:
    collection = _collection()
    if collection is None or not chroma_ids:
        return
    collection.delete(ids=chroma_ids)


def query_knowledge(question: str, where: dict[str, Any] | None = None, limit: int = 12) -> list[dict[str, Any]]:
    collection = _collection()
    if collection is None:
        return []
    result = collection.query(
        query_embeddings=[simple_embedding(question)],
        n_results=limit,
        where=where or None,
        include=["documents", "metadatas", "distances"],
    )
    rows: list[dict[str, Any]] = []
    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    for index, chroma_id in enumerate(ids):
        distance = float(distances[index] if index < len(distances) else 1.0)
        rows.append(
            {
                "chroma_id": chroma_id,
                "content": documents[index] if index < len(documents) else "",
                "metadata": metadatas[index] if index < len(metadatas) else {},
                "score": max(0.0, 1.0 - distance),
            }
        )
    return rows
