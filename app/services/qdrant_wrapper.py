# file: app/services/qdrant_wrapper.py
# Action: Create this new file.

import asyncio
from typing import List, Any, Callable, Coroutine
from qdrant_client import QdrantClient, models
import asyncio
from typing import List, Any, Callable, ParamSpec, TypeVar
P = ParamSpec("P")
T = TypeVar("T")
class QdrantClientWrapper:
    """
    A wrapper around the synchronous QdrantClient to expose a fully async interface.
    This encapsulates all `asyncio.to_thread` calls, cleaning up the main service logic.
    """
    def __init__(self, client: QdrantClient):
        self._client = client

    async def _run_sync(self, func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        """Runs any synchronous client method in a separate thread."""
        return await asyncio.to_thread(func, *args, **kwargs)

    async def recreate_collection(self, **kwargs: Any) -> bool:
        return await self._run_sync(self._client.recreate_collection, **kwargs)

    async def get_collection(self, **kwargs: Any) -> models.CollectionInfo:
        return await self._run_sync(self._client.get_collection, **kwargs)

    async def create_collection(self, **kwargs: Any) -> bool:
        return await self._run_sync(self._client.create_collection, **kwargs)

    async def create_payload_index(self, **kwargs: Any) -> models.UpdateResult:
        return await self._run_sync(self._client.create_payload_index, **kwargs)

    async def upsert(self, **kwargs: Any) -> models.UpdateResult:
        return await self._run_sync(self._client.upsert, **kwargs)

    async def scroll(self, **kwargs: Any) -> tuple[list[models.Record], str | int | None]:
        return await self._run_sync(self._client.scroll, **kwargs)

    async def count(self, **kwargs: Any) -> models.CountResult:
        return await self._run_sync(self._client.count, **kwargs)

    async def search_batch(self, **kwargs: Any) -> List[List[models.ScoredPoint]]:
        return await self._run_sync(self._client.search_batch, **kwargs)

    async def recommend(self, **kwargs: Any) -> List[models.ScoredPoint]:
        return await self._run_sync(self._client.recommend, **kwargs)

    async def search_groups(self, **kwargs: Any) -> models.GroupsResult:
        return await self._run_sync(self._client.search_groups, **kwargs)
    async def has_collection(self, collection_name: str) -> bool:
        try:
            await self.get_collection(collection_name=collection_name)
            return True
        except Exception:
            return False

    async def delete_collection(self, collection_name: str) -> bool:
        return await self._run_sync(self._client.delete_collection, collection_name=collection_name)