import io
import re
from typing import List, Dict, Any
from pypdf import PdfReader
import docx


def clean_text_formatting(text: str) -> str:
    """
    Normalizes extracted PDF/document text formatting.
    Collapses single-word vertical linebreaks and fragmented text blocks into clean, continuous sentences and paragraphs.
    Preserves lists and bullet points.
    """
    if not text or not text.strip():
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = [line.strip() for line in text.split("\n") if line.strip()]

    blocks = []
    current_block = []

    for line in raw_lines:
        is_bullet = bool(re.match(r'^(?:[●•\-\*]|\d+[\.\)])\s*', line)) or line in ["●", "•", "-", "*"]
        if is_bullet:
            if current_block:
                blocks.append(" ".join(current_block))
                current_block = []
            current_block.append(line)
        else:
            current_block.append(line)

    if current_block:
        blocks.append(" ".join(current_block))

    final_lines = []
    i = 0
    while i < len(blocks):
        b = blocks[i].strip()
        if b in ["●", "•", "-", "*"] and i + 1 < len(blocks):
            final_lines.append(f"• {blocks[i+1].strip()}")
            i += 2
        else:
            if b.startswith("●") or b.startswith("•"):
                b = "• " + b.lstrip("●•").strip()
            final_lines.append(b)
            i += 1

    res = "\n\n".join(final_lines)
    res = re.sub(r'[ \t]+', ' ', res)
    res = re.sub(r'\s+([,\.\?\!:])', r'\1', res)
    return res.strip()


def extract_text_from_file(file_bytes: bytes, file_name: str) -> List[Dict[str, Any]]:
    """
    Extracts text from PDF, DOC, DOCX, or TXT files.
    Returns a list of dicts with keys: {'page_number': int, 'text': str}
    """
    ext = file_name.split(".")[-1].lower()
    pages = []

    if ext == "pdf":
        reader = PdfReader(io.BytesIO(file_bytes))
        for idx, page in enumerate(reader.pages):
            raw_text = page.extract_text() or ""
            cleaned_text = clean_text_formatting(raw_text)
            if cleaned_text:
                pages.append({"page_number": idx + 1, "text": cleaned_text})
    elif ext in ["doc", "docx"]:
        try:
            doc = docx.Document(io.BytesIO(file_bytes))
            full_text = []
            for p in doc.paragraphs:
                if p.text.strip():
                    full_text.append(p.text.strip())
            
            raw_content = "\n\n".join(full_text)
            cleaned_content = clean_text_formatting(raw_content)
            page_size = 2000
            total_pages = max(1, (len(cleaned_content) + page_size - 1) // page_size)
            for page_num in range(1, total_pages + 1):
                start = (page_num - 1) * page_size
                end = page_num * page_size
                page_str = cleaned_content[start:end]
                if page_str.strip():
                    pages.append({"page_number": page_num, "text": page_str.strip()})
        except Exception:
            text_str = file_bytes.decode("utf-8", errors="ignore")
            cleaned_text = clean_text_formatting(text_str)
            pages.append({"page_number": 1, "text": cleaned_text})
    else:
        text_str = file_bytes.decode("utf-8", errors="ignore")
        cleaned_text = clean_text_formatting(text_str)
        pages.append({"page_number": 1, "text": cleaned_text})

    if not pages:
        pages.append({"page_number": 1, "text": ""})

    return pages


def chunk_extracted_pages(
    pages: List[Dict[str, Any]],
    target_chunk_chars: int = 1800,  # ~400-450 tokens (optimized for precision & token cost)
    overlap_chars: int = 300         # ~75 tokens overlap
) -> List[Dict[str, Any]]:
    """
    Paragraph-aware semantic text chunker.
    Splits text across natural paragraph breaks (\n\n) while respecting page boundaries.
    """
    chunks = []
    chunk_idx = 0

    for page_info in pages:
        page_num = page_info["page_number"]
        page_text = page_info["text"]

        if not page_text.strip():
            continue

        # Split into paragraphs
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', page_text) if p.strip()]

        current_chunk = ""

        for para in paragraphs:
            if len(current_chunk) + len(para) + 2 <= target_chunk_chars:
                current_chunk += ("\n\n" if current_chunk else "") + para
            else:
                if current_chunk:
                    chunks.append({
                        "chunk_index": chunk_idx,
                        "page_number": page_num,
                        "content": current_chunk.strip()
                    })
                    chunk_idx += 1
                    # Keep overlap from end of current_chunk
                    overlap_start = max(0, len(current_chunk) - overlap_chars)
                    current_chunk = current_chunk[overlap_start:].strip() + "\n\n" + para
                else:
                    # Paragraph is longer than target_chunk_chars -> force break by sentences
                    sentences = re.split(r'(?<=[.!?])\s+', para)
                    sub_chunk = ""
                    for s in sentences:
                        if len(sub_chunk) + len(s) + 1 <= target_chunk_chars:
                            sub_chunk += (" " if sub_chunk else "") + s
                        else:
                            if sub_chunk:
                                chunks.append({
                                    "chunk_index": chunk_idx,
                                    "page_number": page_num,
                                    "content": sub_chunk.strip()
                                })
                                chunk_idx += 1
                                sub_chunk = s
                            else:
                                # Giant string with no whitespace
                                chunks.append({
                                    "chunk_index": chunk_idx,
                                    "page_number": page_num,
                                    "content": s[:target_chunk_chars]
                                })
                                chunk_idx += 1
                                sub_chunk = ""
                    if sub_chunk:
                        current_chunk = sub_chunk

        if current_chunk.strip():
            chunks.append({
                "chunk_index": chunk_idx,
                "page_number": page_num,
                "content": current_chunk.strip()
            })
            chunk_idx += 1

    return chunks
