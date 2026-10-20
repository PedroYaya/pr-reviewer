"""Embeddings wrapper that caches vectors by content hash.

Convention docs and past review comments rarely change between PRs, so most
embedding calls after the first review of a repository are cache hits.
"""

import hashlib
import json
from typing import Protocol

import redis
from langchain_core.embeddings import Embeddings


class KeyValueStore(Protocol):
    def mget(self, keys: list[str]) -> list[bytes | None]: ...

    def mset(self, items: dict[str, bytes], ttl_seconds: int) -> None: ...


class RedisKeyValueStore:
    def __init__(self, client: redis.Redis):
        self._client = client

    def mget(self, keys: list[str]) -> list[bytes | None]:
        return self._client.mget(keys)

    def mset(self, items: dict[str, bytes], ttl_seconds: int) -> None:
        pipeline = self._client.pipeline()
        for key, value in items.items():
            pipeline.set(key, value, ex=ttl_seconds)
        pipeline.execute()


class InMemoryKeyValueStore:
    def __init__(self):
        self.data: dict[str, bytes] = {}

    def mget(self, keys: list[str]) -> list[bytes | None]:
        return [self.data.get(key) for key in keys]

    def mset(self, items: dict[str, bytes], ttl_seconds: int) -> None:
        self.data.update(items)


class CachedEmbeddings(Embeddings):
    def __init__(self, embeddings: Embeddings, store: KeyValueStore, namespace: str, ttl_seconds: int):
        self._embeddings = embeddings
        self._store = store
        self._namespace = namespace
        self._ttl_seconds = ttl_seconds

    def _key(self, text: str) -> str:
        return f"emb:{self._namespace}:{hashlib.sha256(text.encode()).hexdigest()}"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        keys = [self._key(text) for text in texts]
        vectors = [json.loads(raw) if raw is not None else None for raw in self._store.mget(keys)]
        missing = [i for i, vector in enumerate(vectors) if vector is None]
        if missing:
            fresh = self._embeddings.embed_documents([texts[i] for i in missing])
            for i, vector in zip(missing, fresh):
                vectors[i] = vector
            self._store.mset({keys[i]: json.dumps(vectors[i]).encode() for i in missing}, self._ttl_seconds)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
