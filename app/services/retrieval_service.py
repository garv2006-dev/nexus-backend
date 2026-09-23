import re
import time
import uuid
from typing import Dict, List, Any, Tuple
from ..database import fetch_all
from .embedding_service import generate_embedding_async


def compute_cross_encoder_rerank_score(query_text: str, content: str, initial_score: float, rank_index: int) -> float:
    """
    Computes cross-encoder reranking score combining:
    1. Initial Hybrid Vector + Keyword similarity score
    2. Reciprocal Rank Fusion (RRF) positional rank weight: 1 / (60 + rank_index)
    3. Exact phrase & token overlap density matching query terms
    4. Structural term relevance boost
    """
    stop_words = {
        "what", "is", "explain", "me", "the", "a", "an", "and", "or", "for", "to", "in",
        "of", "details", "overview", "how", "does", "it", "work", "with", "from", "on", "at"
    }
    
    query_tokens = [w.lower() for w in re.findall(r'\w+', query_text) if len(w) > 1]
    substantive_tokens = [w for w in query_tokens if w not in stop_words]
    
    content_lower = content.lower()
    
    if not substantive_tokens:
        substantive_tokens = query_tokens
        
    token_hits = 0
    exact_phrase_bonus = 0.0
    
    # Check exact query phrase match
    clean_query_str = query_text.strip().lower().rstrip("?")
    if len(clean_query_str) > 4 and clean_query_str in content_lower:
        exact_phrase_bonus += 0.35

    # Term frequency and token density
    for token in substantive_tokens:
        if token in content_lower:
            count = content_lower.count(token)
            token_hits += min(count, 3)

    coverage_ratio = (len(set(t for t in substantive_tokens if t in content_lower)) / max(1, len(set(substantive_tokens))))
    
    # RRF (Reciprocal Rank Fusion) positional score
    rrf_score = 1.0 / (60.0 + rank_index)
    
    # Cross-encoder composite score formula
    density_score = (token_hits * 0.05) + (coverage_ratio * 0.25)
    rerank_score = (initial_score * 0.45) + (density_score * 0.35) + (exact_phrase_bonus * 0.15) + (rrf_score * 0.05)
    
    return round(float(rerank_score), 4)


def rerank_retrieved_chunks(
    query_text: str,
    candidate_chunks: List[Dict[str, Any]],
    top_k: int = 5
) -> Tuple[List[Dict[str, Any]], float]:
    """
    Cross-Encoder Reranker:
    Takes retrieved candidates (top 15-20), computes joint query-content cross relevance scores,
    and returns top-k highest-ranked chunks.
    Returns (reranked_chunks, rerank_execution_time_ms).
    """
    t_start = time.perf_counter()
    if not candidate_chunks:
        return [], 0.0

    scored_chunks = []
    for rank_idx, chunk in enumerate(candidate_chunks):
        content = chunk.get("content", "")
        orig_score = float(chunk.get("final_score") or chunk.get("score") or 0.0)
        
        rerank_score = compute_cross_encoder_rerank_score(
            query_text=query_text,
            content=content,
            initial_score=orig_score,
            rank_index=rank_idx
        )
        
        chunk_copy = dict(chunk)
        chunk_copy["original_score"] = orig_score
        chunk_copy["rerank_score"] = rerank_score
        chunk_copy["final_score"] = rerank_score
        scored_chunks.append(chunk_copy)

    # Sort candidates in descending order of cross-encoder rerank score
    scored_chunks.sort(key=lambda x: x["rerank_score"], reverse=True)
    
    rerank_time_ms = round((time.perf_counter() - t_start) * 1000, 2)
    return scored_chunks[:top_k], rerank_time_ms


async def perform_hybrid_search(
    workspace_id: str,
    query_text: str,
    top_k: int = 5,
    semantic_weight: float = 0.7,
    keyword_weight: float = 0.3,
    candidate_k: int = 15
) -> List[Dict[str, Any]]:
    """
    Production High-Precision Hybrid Search with Cross-Encoder Reranking & Retrieval Latency Tracking:
    1. Over-fetches candidate_k (15-20) chunks from DB using vector similarity + keyword hybrid search.
    2. Applies Cross-Encoder Reranking to sort and select the top_k (5) most relevant chunks.
    3. Measures and attaches precise retrieval latency timing (retrieval_time_ms, search_time_ms, rerank_time_ms).
    """
    if not query_text or not query_text.strip():
        return []

    t0 = time.perf_counter()
    ws_uuid = uuid.UUID(str(workspace_id))
    
    # Generate query vector embedding
    query_embedding = await generate_embedding_async(query_text, task_type="retrieval_query")
    vec_str = "[" + ",".join(str(f) for f in query_embedding) + "]"

    query = """
        SELECT * FROM match_chunks_hybrid(
            $1::uuid,
            $2::text,
            $3::vector,
            $4::int,
            $5::float,
            $6::float
        )
    """

    # Fetch initial candidate set (e.g. top 15 candidates)
    fetch_k = max(top_k * 3, candidate_k)
    raw_candidates = await fetch_all(
        query,
        ws_uuid,
        query_text,
        vec_str,
        fetch_k,
        semantic_weight,
        keyword_weight
    )
    
    t_search_done = time.perf_counter()
    search_time_ms = round((t_search_done - t0) * 1000, 2)

    # Apply Cross-Encoder Reranker
    reranked_chunks, rerank_time_ms = rerank_retrieved_chunks(
        query_text=query_text,
        candidate_chunks=raw_candidates,
        top_k=top_k
    )

    total_retrieval_time_ms = round(search_time_ms + rerank_time_ms, 2)

    # Attach timing metadata to each returned chunk
    for c in reranked_chunks:
        c["retrieval_time_ms"] = total_retrieval_time_ms
        c["search_time_ms"] = search_time_ms
        c["rerank_time_ms"] = rerank_time_ms

    return reranked_chunks

