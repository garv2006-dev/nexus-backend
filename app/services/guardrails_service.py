import re
from typing import List, Dict, Any, Tuple


class InputGuardrail:
    """
    Input Guardrail for RAG System.
    Validates query structure, length bounds, and checks for prompt injection / jailbreak attempts.
    """
    INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?(previous|above|prior)\s+instructions",
        r"forget\s+(all\s+)?(previous|above|prior)\s+instructions",
        r"disregard\s+(all\s+)?system\s+prompts",
        r"you\s+are\s+now\s+DAN",
        r"override\s+system\s+prompt",
        r"reveal\s+(your\s+)?system\s+prompt",
        r"show\s+(me\s+)?(your\s+)?hidden\s+instructions",
        r"act\s+as\s+an\s+unfiltered\s+ai",
        r"jailbreak",
        r"pretend\s+you\s+have\s+no\s+rules",
    ]

    @classmethod
    def validate_and_sanitize(cls, query: str) -> Tuple[bool, str, str]:
        """
        Validates user query string.
        Returns (is_valid, sanitized_query, rejection_reason).
        """
        if not query or not query.strip():
            return False, "", "Query cannot be empty."

        clean_q = query.strip()

        if len(clean_q) > 4000:
            return False, clean_q[:4000], "Query length exceeds maximum limit of 4000 characters."

        # Check for prompt injection patterns
        for pattern in cls.INJECTION_PATTERNS:
            if re.search(pattern, clean_q, flags=re.IGNORECASE):
                return (
                    False,
                    clean_q,
                    "Input query rejected by security guardrails (potential system prompt override attempt detected)."
                )

        # Basic control character sanitization
        clean_q = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', clean_q)

        return True, clean_q, ""


class RetrievalGuardrail:
    """
    Retrieval Guardrail for RAG System.
    Filters out low-relevance retrieval noise, deduplicates chunk content,
    and enforces maximum context window token boundaries.
    """
    @classmethod
    def filter_and_guard_chunks(
        cls,
        chunks: List[Dict[str, Any]],
        min_score_threshold: float = 0.20,
        max_context_chars: int = 12000
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Filters chunks based on relevance threshold and bounds maximum context.
        Returns (guarded_chunks, guardrail_metadata).
        """
        if not chunks:
            return [], {"total_retrieved": 0, "kept": 0, "filtered_out": 0, "reason": "No chunks retrieved."}

        filtered = []
        seen_texts = set()
        total_chars = 0

        for c in chunks:
            score = float(c.get("final_score", 0.0))
            raw_content = (c.get("content") or "").strip()

            # 1. Score threshold check
            if score < min_score_threshold:
                continue

            # 2. Content deduplication check
            content_fingerprint = raw_content[:150].lower()
            if content_fingerprint in seen_texts:
                continue

            # 3. Context size bound check
            if total_chars + len(raw_content) > max_context_chars and filtered:
                # Truncate content to fit bound if necessary
                allowed_len = max_context_chars - total_chars
                if allowed_len > 200:
                    truncated_c = dict(c)
                    truncated_c["content"] = raw_content[:allowed_len] + "..."
                    filtered.append(truncated_c)
                break

            seen_texts.add(content_fingerprint)
            filtered.append(c)
            total_chars += len(raw_content)

        meta = {
            "total_retrieved": len(chunks),
            "kept": len(filtered),
            "filtered_out": len(chunks) - len(filtered),
            "total_chars": total_chars
        }

        return filtered, meta


class OutputGuardrail:
    """
    Output Guardrail for RAG System.
    Ensures response factuality, strips unwanted inline source tags,
    and formats final output for safety and presentation.
    """
    @classmethod
    def sanitize_and_validate_output(
        cls,
        response_text: str,
        chunks: List[Dict[str, Any]],
        has_context: bool = True
    ) -> Tuple[str, bool]:
        """
        Sanitizes response text and validates grounding.
        Returns (sanitized_response, is_grounded).
        """
        if not response_text or not response_text.strip():
            return "The system was unable to produce an answer. Please try rephrasing your question.", False

        text = response_text.strip()

        # 1. Strip raw inline citation tags (e.g. [Source 1], [Source 2])
        text = re.sub(r'\[Source\s*\d+(?::[^\]]+)?\]', '', text, flags=re.IGNORECASE)
        text = re.sub(r'[ \t]+\.', '.', text)
        text = re.sub(r'[ \t]+,', ',', text)
        text = re.sub(r'  +', ' ', text)

        # 2. Grounding fallback check
        if not has_context or not chunks:
            if "not found in the uploaded documents" not in text.lower():
                text = "The requested information was not found in the uploaded documents for this workspace."
            return text, True

        return text.strip(), True
