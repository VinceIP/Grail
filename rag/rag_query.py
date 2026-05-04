#!/usr/bin/env python3
"""
Query GRAIL hybrid RAG indexes.

This is a retrieval tool, not a chat tool.

It combines:
- Chroma vector retrieval
- BM25 keyword retrieval
- reciprocal-rank fusion

Run from grail/rag:

    python rag_query.py "LD A,[HL+]"
    python rag_query.py "rgbfix checksum validation"
    python rag_query.py "$FF47 BGP palette register"
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path
from typing import Iterable

import chromadb
from llama_index.core import VectorStoreIndex
from llama_index.core.schema import NodeWithScore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.vector_stores.chroma import ChromaVectorStore


DEFAULT_MANIFEST = "rag_manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search GRAIL hybrid RAG indexes and return evidence chunks."
    )

    parser.add_argument(
        "query",
        help="Search query.",
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Final number of chunks to return. Default: 5",
    )

    parser.add_argument(
        "--vector-k",
        type=int,
        default=8,
        help="Number of vector results to retrieve before fusion. Default: 8",
    )

    parser.add_argument(
        "--bm25-k",
        type=int,
        default=8,
        help="Number of BM25 results to retrieve before fusion. Default: 8",
    )

    parser.add_argument(
        "--mode",
        choices=["hybrid", "vector", "bm25"],
        default="hybrid",
        help="Retrieval mode. Default: hybrid",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of formatted text.",
    )

    parser.add_argument(
        "--max-chars",
        type=int,
        default=1800,
        help="Max characters per returned chunk excerpt. Default: 1800",
    )

    return parser.parse_args()


def load_manifest(root: Path) -> dict:
    manifest_path = root / DEFAULT_MANIFEST

    if not manifest_path.exists():
        raise SystemExit(
            f"Missing {manifest_path}. Run `python rag_init.py --reset` first."
        )

    return json.loads(manifest_path.read_text(encoding="utf-8"))


def get_node_id(result: NodeWithScore) -> str:
    return result.node.node_id


def reciprocal_rank_fusion(
    ranked_lists: Iterable[list[NodeWithScore]],
    *,
    k: int = 60,
) -> list[NodeWithScore]:
    """
    Fuse multiple ranked result lists using reciprocal-rank fusion.

    Score contribution = 1 / (k + rank).

    This favors items that appear near the top of either BM25 or vector retrieval,
    and strongly favors items that appear in both.
    """
    fused_scores: dict[str, float] = {}
    best_result: dict[str, NodeWithScore] = {}

    for ranked_list in ranked_lists:
        for rank, result in enumerate(ranked_list, start=1):
            node_id = get_node_id(result)
            fused_scores[node_id] = fused_scores.get(node_id, 0.0) + (1.0 / (k + rank))

            if node_id not in best_result:
                best_result[node_id] = result

    fused: list[NodeWithScore] = []

    for node_id, result in best_result.items():
        result.score = fused_scores[node_id]
        fused.append(result)

    fused.sort(key=lambda r: r.score or 0.0, reverse=True)
    return fused


def compact_metadata(metadata: dict) -> dict:
    wanted_keys = [
        "chunk_id",
        "source_file",
        "manual_page",
        "tool",
        "section",
        "heading_path",
        "chunk_type",
        "keywords",
    ]

    return {key: metadata.get(key) for key in wanted_keys if key in metadata}


def format_result(index: int, result: NodeWithScore, *, max_chars: int) -> str:
    node = result.node
    metadata = compact_metadata(node.metadata or {})
    text = node.get_content(metadata_mode="none").strip()

    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n[...]"

    source_file = metadata.get("source_file", "unknown")
    heading = metadata.get("heading_path", "")
    manual_page = metadata.get("manual_page", "")
    chunk_id = metadata.get("chunk_id", node.node_id)

    return (
        f"\n--- RESULT {index} ---\n"
        f"score: {result.score}\n"
        f"chunk_id: {chunk_id}\n"
        f"source_file: {source_file}\n"
        f"manual_page: {manual_page}\n"
        f"heading: {heading}\n"
        f"metadata: {json.dumps(metadata, ensure_ascii=False)}\n\n"
        f"{text}\n"
    )


def result_to_json(result: NodeWithScore, *, max_chars: int) -> dict:
    node = result.node
    text = node.get_content(metadata_mode="none").strip()

    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n[...]"

    return {
        "score": result.score,
        "node_id": node.node_id,
        "metadata": compact_metadata(node.metadata or {}),
        "text": text,
    }


def load_vector_results(
    *,
    query: str,
    chroma_dir: Path,
    collection_name: str,
    embed_model_name: str,
    top_k: int,
) -> list[NodeWithScore]:
    embed_model = HuggingFaceEmbedding(model_name=embed_model_name)

    chroma_client = chromadb.PersistentClient(path=str(chroma_dir))
    chroma_collection = chroma_client.get_collection(collection_name)

    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    vector_index = VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        embed_model=embed_model,
    )

    vector_retriever = vector_index.as_retriever(similarity_top_k=top_k)
    return vector_retriever.retrieve(query)


def load_bm25_results(
    *,
    query: str,
    bm25_dir: Path,
    top_k: int,
) -> list[NodeWithScore]:
    # Do not pass similarity_top_k into from_persist_dir; some versions pass it
    # down to bm25s.BM25.load(), which raises:
    # TypeError: BM25.__init__() got an unexpected keyword argument 'similarity_top_k'
    bm25_retriever = BM25Retriever.from_persist_dir(str(bm25_dir))
    bm25_retriever.similarity_top_k = top_k
    return bm25_retriever.retrieve(query)


def main() -> None:
    # Optional: keep harmless Hugging Face warnings from cluttering CLI output.
    warnings.filterwarnings(
        "ignore",
        message=".*resume_download.*",
        category=FutureWarning,
    )

    args = parse_args()

    root = Path(__file__).resolve().parent
    manifest = load_manifest(root)

    chroma_dir = Path(manifest["chroma_dir"])
    bm25_dir = Path(manifest["bm25_dir"])
    collection_name = manifest["collection"]
    embed_model_name = manifest["embed_model"]

    vector_results: list[NodeWithScore] = []
    bm25_results: list[NodeWithScore] = []

    if args.mode in {"hybrid", "vector"}:
        vector_results = load_vector_results(
            query=args.query,
            chroma_dir=chroma_dir,
            collection_name=collection_name,
            embed_model_name=embed_model_name,
            top_k=args.vector_k,
        )

    if args.mode in {"hybrid", "bm25"}:
        bm25_results = load_bm25_results(
            query=args.query,
            bm25_dir=bm25_dir,
            top_k=args.bm25_k,
        )

    if args.mode == "vector":
        final_results = vector_results[: args.top_k]
    elif args.mode == "bm25":
        final_results = bm25_results[: args.top_k]
    else:
        final_results = reciprocal_rank_fusion(
            [bm25_results, vector_results],
        )[: args.top_k]

    if args.json:
        payload = {
            "query": args.query,
            "mode": args.mode,
            "top_k": args.top_k,
            "results": [
                result_to_json(result, max_chars=args.max_chars)
                for result in final_results
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    print(f"Query: {args.query}")
    print(f"Mode: {args.mode}")
    print(f"Results: {len(final_results)}")

    for i, result in enumerate(final_results, start=1):
        print(format_result(i, result, max_chars=args.max_chars))


if __name__ == "__main__":
    main()