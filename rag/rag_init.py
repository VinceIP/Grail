#!/usr/bin/env python3
"""
Initialize GRAIL hybrid RAG indexes from curated JSONL chunks.

This script reads pre-defined chunks from:

    ./chunks/rgbds_chunks.jsonl

and builds:

    ./chroma_db/    dense vector index, via Chroma
    ./bm25_index/   keyword/BM25 index, via LlamaIndex BM25Retriever

Run from grail/rag:

    python rag_init.py --reset
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import chromadb
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.vector_stores.chroma import ChromaVectorStore


DEFAULT_COLLECTION_NAME = "grail_rgbds_docs"
DEFAULT_EMBED_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_CHUNKS_FILE = "chunks/rgbds_chunks.jsonl"
DEFAULT_CHROMA_DIR = "chroma_db"
DEFAULT_BM25_DIR = "bm25_index"
DEFAULT_MANIFEST = "rag_manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build GRAIL Chroma + BM25 hybrid RAG indexes from JSONL chunks."
    )

    parser.add_argument(
        "--chunks-file",
        default=DEFAULT_CHUNKS_FILE,
        help=f"JSONL chunk file. Default: {DEFAULT_CHUNKS_FILE}",
    )

    parser.add_argument(
        "--chroma-dir",
        default=DEFAULT_CHROMA_DIR,
        help=f"Chroma DB directory. Default: {DEFAULT_CHROMA_DIR}",
    )

    parser.add_argument(
        "--bm25-dir",
        default=DEFAULT_BM25_DIR,
        help=f"BM25 index directory. Default: {DEFAULT_BM25_DIR}",
    )

    parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION_NAME,
        help=f"Chroma collection name. Default: {DEFAULT_COLLECTION_NAME}",
    )

    parser.add_argument(
        "--embed-model",
        default=DEFAULT_EMBED_MODEL,
        help=f"Hugging Face embedding model. Default: {DEFAULT_EMBED_MODEL}",
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing Chroma/BM25 indexes before rebuilding.",
    )

    return parser.parse_args()


def normalize_metadata_value(value: Any) -> str | int | float | bool | None:
    """
    Chroma metadata must be scalar.

    Lists/dicts are JSON-encoded so they remain inspectable.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def normalize_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool | None]:
    return {key: normalize_metadata_value(value) for key, value in metadata.items()}


def load_nodes(chunks_file: Path) -> list[TextNode]:
    if not chunks_file.exists():
        raise SystemExit(f"Chunks file does not exist: {chunks_file}")

    nodes: list[TextNode] = []
    seen_ids: set[str] = set()

    with chunks_file.open("r", encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, start=1):
            line = raw_line.strip()

            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    f"Invalid JSON on line {line_number} of {chunks_file}: {exc}"
                ) from exc

            chunk_id = obj.get("id")
            text = obj.get("text")
            metadata = obj.get("metadata", {})

            if not isinstance(chunk_id, str) or not chunk_id.strip():
                raise SystemExit(f"Missing or invalid 'id' on line {line_number}")

            if chunk_id in seen_ids:
                raise SystemExit(f"Duplicate chunk id on line {line_number}: {chunk_id}")

            if not isinstance(text, str) or not text.strip():
                raise SystemExit(f"Missing or empty 'text' on line {line_number}: {chunk_id}")

            if not isinstance(metadata, dict):
                raise SystemExit(f"'metadata' must be an object on line {line_number}: {chunk_id}")

            seen_ids.add(chunk_id)

            normalized_metadata = normalize_metadata(metadata)
            normalized_metadata["chunk_id"] = chunk_id

            # Prefixing text with doc context helps both vector and keyword retrieval.
            source_file = str(metadata.get("source_file", "unknown"))
            heading_path = str(metadata.get("heading_path", ""))
            manual_page = str(metadata.get("manual_page", ""))

            contextual_text = (
                f"Source: {source_file}\n"
                f"Manual page: {manual_page}\n"
                f"Heading: {heading_path}\n\n"
                f"{text.strip()}"
            )

            nodes.append(
                TextNode(
                    id_=chunk_id,
                    text=contextual_text,
                    metadata=normalized_metadata,
                )
            )

    if not nodes:
        raise SystemExit(f"No chunks loaded from: {chunks_file}")

    return nodes


def write_manifest(
    manifest_path: Path,
    *,
    chunks_file: Path,
    chroma_dir: Path,
    bm25_dir: Path,
    collection: str,
    embed_model: str,
    node_count: int,
) -> None:
    manifest = {
        "chunks_file": str(chunks_file),
        "chroma_dir": str(chroma_dir),
        "bm25_dir": str(bm25_dir),
        "collection": collection,
        "embed_model": embed_model,
        "node_count": node_count,
    }

    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()

    root = Path(__file__).resolve().parent
    chunks_file = (root / args.chunks_file).resolve()
    chroma_dir = (root / args.chroma_dir).resolve()
    bm25_dir = (root / args.bm25_dir).resolve()
    manifest_path = (root / DEFAULT_MANIFEST).resolve()

    print("GRAIL hybrid RAG init")
    print(f"Chunks file:   {chunks_file}")
    print(f"Chroma dir:    {chroma_dir}")
    print(f"BM25 dir:      {bm25_dir}")
    print(f"Collection:    {args.collection}")
    print(f"Embed model:   {args.embed_model}")
    print()

    if args.reset:
        for path in (chroma_dir, bm25_dir):
            if path.exists():
                print(f"Removing existing index: {path}")
                shutil.rmtree(path)

    nodes = load_nodes(chunks_file)
    print(f"Loaded {len(nodes)} chunks.")

    print("Preparing embedding model...")
    embed_model = HuggingFaceEmbedding(model_name=args.embed_model)

    print("Building Chroma vector index...")
    chroma_client = chromadb.PersistentClient(path=str(chroma_dir))

    if not args.reset:
        try:
            chroma_client.delete_collection(args.collection)
            print(f"Deleted existing Chroma collection: {args.collection}")
        except Exception:
            pass

    chroma_collection = chroma_client.get_or_create_collection(args.collection)
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    VectorStoreIndex(
        nodes,
        storage_context=storage_context,
        embed_model=embed_model,
        show_progress=True,
    )

    print("Building BM25 keyword index...")
    bm25_dir.mkdir(parents=True, exist_ok=True)

    bm25_retriever = BM25Retriever.from_defaults(
        nodes=nodes,
        similarity_top_k=10,
    )
    bm25_retriever.persist(str(bm25_dir))

    write_manifest(
        manifest_path,
        chunks_file=chunks_file,
        chroma_dir=chroma_dir,
        bm25_dir=bm25_dir,
        collection=args.collection,
        embed_model=args.embed_model,
        node_count=len(nodes),
    )

    print()
    print("GRAIL hybrid RAG initialization complete.")
    print(f"Stored vector chunks: {chroma_collection.count()}")
    print(f"Stored BM25 index:    {bm25_dir}")
    print(f"Manifest:             {manifest_path}")


if __name__ == "__main__":
    main()