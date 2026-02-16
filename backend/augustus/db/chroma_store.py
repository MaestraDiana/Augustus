"""ChromaDB storage interface for Augustus."""

import logging
from pathlib import Path
from typing import Any

import chromadb
from chromadb import Collection
from chromadb.api.client import SharedSystemClient

logger = logging.getLogger(__name__)

# Vector collections for semantic search
COLLECTIONS = [
    "session_transcripts",
    "close_reports",
    "annotations",
    "emergent_observations",
]


class ChromaStore:
    """ChromaDB interface for vector-indexed semantic search."""

    def __init__(self, data_dir: Path) -> None:
        """Initialize ChromaDB client and collections.

        Args:
            data_dir: Directory for ChromaDB persistent storage
        """
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=str(data_dir))
        self.collections: dict[str, Collection] = {}
        self._init_collections()
        logger.info(f"ChromaDB store initialized at {data_dir}")

    def refresh(self) -> None:
        """Re-create the ChromaDB client to pick up data written by other processes.

        ChromaDB's PersistentClient caches HNSW indexes in memory. When another
        OS process (e.g. the Augustus backend) writes new documents, a long-lived
        client (e.g. the MCP server) won't see them until it re-opens the database.
        Call this before query operations in multi-process scenarios.
        """
        SharedSystemClient.clear_system_cache()
        self.client = chromadb.PersistentClient(path=str(self.data_dir))
        self.collections.clear()
        self._init_collections()
        logger.debug("ChromaDB client refreshed")

    def _init_collections(self) -> None:
        """Create or get all required collections."""
        for name in COLLECTIONS:
            self.collections[name] = self.client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
        logger.debug(f"Initialized {len(COLLECTIONS)} ChromaDB collections")

    def add_document(
        self,
        collection: str,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add or update a document in a collection.

        Args:
            collection: Collection name
            doc_id: Unique document identifier
            text: Document text content
            metadata: Optional metadata dictionary
        """
        if collection not in self.collections:
            raise ValueError(f"Unknown collection: {collection}")

        coll = self.collections[collection]
        coll.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata or {}],
        )
        logger.debug(f"Stored document {doc_id} in {collection}")

    def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 5,
        where_filter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Query a collection by semantic similarity.

        Args:
            collection: Collection name
            query_text: Query text
            n_results: Number of results to return
            where_filter: Optional metadata filter

        Returns:
            Query results dictionary
        """
        if collection not in self.collections:
            raise ValueError(f"Unknown collection: {collection}")

        coll = self.collections[collection]
        kwargs: dict[str, Any] = {
            "query_texts": [query_text],
            "n_results": n_results,
        }
        if where_filter:
            kwargs["where"] = where_filter

        return coll.query(**kwargs)

    def delete(self, collection: str, doc_id: str) -> None:
        """Delete a document from a collection.

        Args:
            collection: Collection name
            doc_id: Document identifier to delete
        """
        if collection not in self.collections:
            raise ValueError(f"Unknown collection: {collection}")

        coll = self.collections[collection]
        coll.delete(ids=[doc_id])
        logger.debug(f"Deleted document {doc_id} from {collection}")

    def delete_by_filter(self, collection: str, where_filter: dict[str, Any]) -> None:
        """Delete documents matching a metadata filter.

        Args:
            collection: Collection name
            where_filter: Metadata filter for documents to delete
        """
        if collection not in self.collections:
            raise ValueError(f"Unknown collection: {collection}")

        coll = self.collections[collection]
        coll.delete(where=where_filter)
        logger.debug(f"Deleted documents from {collection} matching filter")
