"""Create or reuse a token-aware, persistent Chroma vector store."""

import hashlib
from itertools import islice
from pathlib import Path
from typing import cast

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Embeddable, EmbeddingFunction
from chromadb.errors import NotFoundError
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from transformers import AutoTokenizer

from xml_parser import iter_records

DEFAULT_XML_PATH = Path(__file__).resolve().parents[2] / "data" / "CA Code - Revenue and Taxation Code.xml"
DEFAULT_STORE_PATH = DEFAULT_XML_PATH.parent / "chroma"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_TOKEN_LIMIT = 256
COLLECTION_NAME = "ca_revenue_taxation"
INDEX_VERSION = 1


def create_vector_store(
    xml_path: str | Path = DEFAULT_XML_PATH,
    *,
    chunk_size: int = 240,
    batch_size: int = 100,
    store_path: str | Path = DEFAULT_STORE_PATH,
    rebuild: bool = False,
) -> tuple[ClientAPI, Collection]:
    """Reuse matching saved embeddings, or build them from XML.

    Token budgets include citation text and special tokens. Source/settings
    changes require rebuild=True, which replaces the old collection. The XML
    must remain available for fingerprint verification. Inference runs locally;
    model files may download on first use. Failed imports remove partial indexes.
    """
    path = Path(xml_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(path)
    if not 0 < chunk_size <= MODEL_TOKEN_LIMIT:
        raise ValueError(f"chunk_size must be between 1 and {MODEL_TOKEN_LIMIT}")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    with path.open("rb") as source:
        fingerprint = hashlib.file_digest(source, "sha256").hexdigest()
    metadata = {
        "source_sha256": fingerprint,
        "embedding_model": MODEL_NAME,
        "chunk_size": chunk_size,
        "index_version": INDEX_VERSION,
        "normalized_embeddings": True,
    }
    embedding_function = SentenceTransformerEmbeddingFunction(
        model_name=MODEL_NAME, device="cpu", normalize_embeddings=True
    )
    client = chromadb.PersistentClient(path=str(Path(store_path).expanduser().resolve()))
    # Chroma's broader protocol includes images; this collection accepts text only.
    embedder = cast(EmbeddingFunction[Embeddable], embedding_function)
    try:
        existing = client.get_collection(COLLECTION_NAME, embedding_function=embedder)
    except NotFoundError:
        existing = None
    if existing is not None:
        if not rebuild:
            saved = existing.metadata or {}
            if any(saved.get(key) != value for key, value in metadata.items()):
                raise ValueError("Source or index settings changed. Run with --rebuild.")
            count = existing.count()
            if not saved.get("complete") or not count or saved.get("record_count") != count:
                raise ValueError("Saved index is incomplete. Run with --rebuild.")
            return client, existing
        client.delete_collection(COLLECTION_NAME)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

    def count_tokens(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=True, truncation=False))

    collection = client.create_collection(
        name=COLLECTION_NAME, embedding_function=embedder,
        metadata={**metadata, "complete": False},
    )
    try:
        records = iter_records(path, chunk_size=chunk_size, length_function=count_tokens)
        effective_batch_size = min(batch_size, client.get_max_batch_size())
        added = 0
        while batch := list(islice(records, effective_batch_size)):
            documents = [record["document"] for record in batch]
            if any(count_tokens(document) > chunk_size for document in documents):
                raise ValueError("Parser emitted a chunk exceeding the token budget")
            collection.add(
                ids=[record["id"] for record in batch], documents=documents,
                metadatas=[record["metadata"] for record in batch],
            )
            added += len(batch)
        if not added:
            raise ValueError(f"No sections were found in {path}")
        if collection.count() != added:
            raise RuntimeError("Collection record count does not match the parsed chunks")
        collection.modify(metadata={**metadata, "complete": True, "record_count": added})
    except Exception:
        client.delete_collection(collection.name)
        raise
    return client, collection
