import uuid
from typing import Dict, List, Any
from ..database import fetch_all
from .embedding_service import generate_embedding_async


async def perform_hybrid_search(
    workspace_id: str,
    query_text: str,
    top_k: int = 5,
    semantic_weight: float = 0.7,
    keyword_weight: float = 0.3
) -> List[Dict[str, Any]]:
    """
    Executes multi-tenant hybrid search (vector similarity + full-text keyword search)
    using the Supabase stored procedure `match_chunks_hybrid`.
    Enforces strict workspace authorization filtering (`workspace_id = current_workspace_id`).
    Non-blocking async vector embedding generation.
    """
    if not query_text or not query_text.strip():
        return []

    ws_uuid = uuid.UUID(str(workspace_id))
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

    results = await fetch_all(
        query,
        ws_uuid,
        query_text,
        vec_str,
        top_k,
        semantic_weight,
        keyword_weight
    )

    return results
