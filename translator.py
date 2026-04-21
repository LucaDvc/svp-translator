"""
Translator module: handles text chunking, Anthropic API translation, and QA review.
Supports both standard and batch API modes, with prompt caching.
"""

import anthropic
import json
import time
import logging
import re

logger = logging.getLogger(__name__)


def extract_header_info(
    client: anthropic.Anthropic,
    russian_text: str,
    model: str,
) -> dict | None:
    """
    Extract lesson header info (title, date, part) from the beginning of Russian text.
    Returns dict with keys "title", "date", "part", or None if extraction fails.
    """
    # Only send the first ~300 words to keep this cheap
    words = russian_text.split()
    preview = " ".join(words[:300])

    try:
        response = client.messages.create(
            model=model,
            max_tokens=256,
            system=[
                {
                    "type": "text",
                    "text": (
                        "You extract metadata from Russian lecture transcripts about "
                        "System-vector psychology (системно-векторная психология). "
                        "Return ONLY valid JSON, no other text."
                    ),
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Extract the lesson title, date, and part number from this text.\n\n"
                        "The lesson could be:\n"
                        "- A vector lesson, e.g. \"Oral Vector 2\", \"Urethral Vector 1\"\n"
                        "- A themed training, e.g. 'Themed Training \"Female Sexuality\"', "
                        "'Themed Training \"Combinations of Vectors\"'\n"
                        "- An additional/supplementary lesson\n"
                        "- Any other type of lecture\n\n"
                        "Use these vector name translations when applicable:\n"
                        "- звуковой вектор → Auditory Vector\n"
                        "- зрительный вектор → Visual Vector\n"
                        "- кожный вектор → Dermal Vector\n"
                        "- анальный вектор → Anal Vector\n"
                        "- уретральный вектор → Urethral Vector\n"
                        "- оральный вектор → Oral Vector\n"
                        "- мышечный вектор → Muscular Vector\n"
                        "- обонятельный вектор → Olfactory Vector\n"
                        "- тематическое занятие / ТЗ → Themed Training\n\n"
                        "Return JSON with exactly these keys:\n"
                        '- "title": the lesson title in English, e.g. "Urethral Vector 1" '
                        'or \'Themed Training "Female Sexuality"\' or "Additional Lesson 3". '
                        "Include the lesson number if present.\n"
                        '- "date": the lecture date in format "Month day, year", '
                        'e.g. "March 25, 2026"\n'
                        '- "part": "Part 1" or "Part 2" etc.\n'
                        '- "header_paragraphs": integer count of non-empty paragraphs '
                        "at the very start of the text that make up the header block "
                        "(title + date + part lines, before the lecture content begins). "
                        "Typically 2-5.\n\n"
                        f"TEXT:\n{preview}"
                    ),
                }
            ],
        )

        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)

        if all(k in result for k in ("title", "date", "part", "header_paragraphs")):
            logger.info(
                f"Extracted header: {result['title']} | {result['date']} | {result['part']} "
                f"({result['header_paragraphs']} source paragraphs)"
            )
            return result
        else:
            logger.warning(f"Header extraction missing keys: {result}")
            return None

    except Exception as e:
        logger.warning(f"Header extraction failed, skipping header: {e}")
        return None


def strip_source_header(text: str, header_info: dict | None) -> str:
    """Drop the first N non-empty paragraphs (the header) from the source text,
    so they aren't translated and duplicated below the programmatic header."""
    if not header_info:
        return text
    n = header_info.get("header_paragraphs", 0)
    if not isinstance(n, int) or n < 1:
        return text

    lines = text.split("\n")
    non_empty_seen = 0
    idx = 0
    while idx < len(lines) and non_empty_seen < n:
        if lines[idx].strip():
            non_empty_seen += 1
        idx += 1
    # Also consume trailing blank lines immediately after the header
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    return "\n".join(lines[idx:])


def chunk_text(text: str, chunk_size_words: int = 1500) -> list[str]:
    """
    Split text into chunks at paragraph boundaries, respecting approximate word count.
    Each chunk will be roughly chunk_size_words long, but won't break mid-paragraph.
    """
    paragraphs = text.split("\n")
    chunks = []
    current_chunk = []
    current_word_count = 0

    for para in paragraphs:
        para_words = len(para.split())

        # If adding this paragraph would exceed the limit AND we already have content,
        # close the current chunk and start a new one
        if current_word_count + para_words > chunk_size_words and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
            current_word_count = 0

        current_chunk.append(para)
        current_word_count += para_words

    # Don't forget the last chunk
    if current_chunk:
        chunks.append("\n".join(current_chunk))

    # Filter out empty chunks
    chunks = [c.strip() for c in chunks if c.strip()]
    logger.info(f"Split text into {len(chunks)} chunks")
    return chunks


def translate_chunk(
    client: anthropic.Anthropic,
    chunk: str,
    system_prompt: str,
    model: str,
) -> str:
    """Translate a single chunk of Russian text to English using the Anthropic API."""
    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Translate the following Russian text to English. Output ONLY the translation, nothing else.\n\n{chunk}",
            }
        ],
    )

    translated = response.content[0].text

    # Log cache performance
    usage = response.usage
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
    logger.debug(
        f"Translation - Input: {usage.input_tokens}, Output: {usage.output_tokens}, "
        f"Cache read: {cache_read}, Cache creation: {cache_creation}"
    )

    return translated


def qa_review_chunk(
    client: anthropic.Anthropic,
    original: str,
    translation: str,
    system_prompt: str,
    model: str,
) -> str:
    """Run QA review on a translated chunk, comparing against the original."""
    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"ORIGINAL:\n{original}\n\nTRANSLATION:\n{translation}",
            }
        ],
    )

    corrected = response.content[0].text

    usage = response.usage
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    logger.debug(
        f"QA Review - Input: {usage.input_tokens}, Output: {usage.output_tokens}, "
        f"Cache read: {cache_read}"
    )

    return corrected


def translate_and_review(
    text: str,
    anthropic_api_key: str,
    model: str,
    translation_prompt: str,
    qa_prompt: str,
    chunk_size_words: int = 1500,
    use_batch: bool = False,
    batch_timeout: int = 3600,
) -> str:
    """
    Full translation pipeline: chunk → translate → QA review → assemble.

    Args:
        text: Full Russian source text
        anthropic_api_key: API key
        model: Model name (e.g. "claude-sonnet-4-6")
        translation_prompt: System prompt for translation
        qa_prompt: System prompt for QA
        chunk_size_words: Words per chunk
        use_batch: Whether to use batch API (cheaper but slower)
        batch_timeout: Max seconds to wait for batch results

    Returns:
        Complete translated and QA-reviewed English text
    """
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    chunks = chunk_text(text, chunk_size_words)

    if use_batch:
        try:
            return _translate_batch(
                client, chunks, model, translation_prompt, qa_prompt, batch_timeout
            )
        except TimeoutError:
            logger.warning(
                "Batch timed out after %ds, falling back to sequential mode",
                batch_timeout,
            )
            return _translate_sequential(
                client, chunks, model, translation_prompt, qa_prompt
            )
    else:
        return _translate_sequential(
            client, chunks, model, translation_prompt, qa_prompt
        )


def _translate_sequential(
    client: anthropic.Anthropic,
    chunks: list[str],
    model: str,
    translation_prompt: str,
    qa_prompt: str,
) -> str:
    """Translate chunks sequentially (standard API, immediate results)."""
    translated_chunks = []
    total_chunks = len(chunks)

    for i, chunk in enumerate(chunks):
        logger.info(f"Translating chunk {i + 1}/{total_chunks}...")
        translated = translate_chunk(client, chunk, translation_prompt, model)

        logger.info(f"QA reviewing chunk {i + 1}/{total_chunks}...")
        reviewed = qa_review_chunk(client, chunk, translated, qa_prompt, model)

        translated_chunks.append(reviewed)

    return "\n\n".join(translated_chunks)


def _translate_batch(
    client: anthropic.Anthropic,
    chunks: list[str],
    model: str,
    translation_prompt: str,
    qa_prompt: str,
    timeout: int,
) -> str:
    """
    Translate chunks using the Batch API (50% cheaper).
    Step 1: Batch-translate all chunks.
    Step 2: Batch-QA all translations.
    """
    # --- Step 1: Batch translation ---
    logger.info(f"Submitting {len(chunks)} chunks for batch translation...")
    translation_requests = []
    for i, chunk in enumerate(chunks):
        translation_requests.append(
            {
                "custom_id": f"translate-{i}",
                "params": {
                    "model": model,
                    "max_tokens": 8192,
                    "system": [
                        {
                            "type": "text",
                            "text": translation_prompt,
                            "cache_control": {"type": "ephemeral", "ttl": "1h"},
                        }
                    ],
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Translate the following Russian text to English. Output ONLY the translation, nothing else.\n\n{chunk}",
                        }
                    ],
                },
            }
        )

    batch = client.messages.batches.create(requests=translation_requests)
    translations = _wait_for_batch(client, batch.id, timeout)

    # Extract translations in order
    translated_chunks = []
    for i in range(len(chunks)):
        key = f"translate-{i}"
        if key in translations:
            translated_chunks.append(translations[key])
        else:
            logger.error(f"Missing translation for chunk {i}, using empty string")
            translated_chunks.append("")

    # --- Step 2: Batch QA ---
    logger.info(f"Submitting {len(chunks)} chunks for batch QA review...")
    qa_requests = []
    for i, (original, translated) in enumerate(zip(chunks, translated_chunks)):
        qa_requests.append(
            {
                "custom_id": f"qa-{i}",
                "params": {
                    "model": model,
                    "max_tokens": 8192,
                    "system": [
                        {
                            "type": "text",
                            "text": qa_prompt,
                            "cache_control": {"type": "ephemeral", "ttl": "1h"},
                        }
                    ],
                    "messages": [
                        {
                            "role": "user",
                            "content": f"ORIGINAL:\n{original}\n\nTRANSLATION:\n{translated}",
                        }
                    ],
                },
            }
        )

    batch = client.messages.batches.create(requests=qa_requests)
    qa_results = _wait_for_batch(client, batch.id, timeout)

    # Extract QA results in order
    reviewed_chunks = []
    for i in range(len(chunks)):
        key = f"qa-{i}"
        if key in qa_results:
            reviewed_chunks.append(qa_results[key])
        else:
            logger.warning(f"Missing QA for chunk {i}, using unreviewed translation")
            reviewed_chunks.append(translated_chunks[i])

    return "\n\n".join(reviewed_chunks)


def _wait_for_batch(
    client: anthropic.Anthropic,
    batch_id: str,
    timeout: int,
) -> dict[str, str]:
    """Poll for batch completion and return results as {custom_id: text}."""
    start = time.time()
    poll_interval = 10  # seconds

    while time.time() - start < timeout:
        batch = client.messages.batches.retrieve(batch_id)
        logger.debug(f"Batch {batch_id} status: {batch.processing_status}")

        if batch.processing_status == "ended":
            break

        time.sleep(poll_interval)
        # Gradually increase poll interval up to 60s
        poll_interval = min(poll_interval * 1.5, 60)
    else:
        raise TimeoutError(
            f"Batch {batch_id} did not complete within {timeout} seconds"
        )

    # Retrieve results
    results = {}
    for result in client.messages.batches.results(batch_id):
        if result.result.type == "succeeded":
            text = result.result.message.content[0].text
            results[result.custom_id] = text
        else:
            logger.error(
                f"Batch request {result.custom_id} failed: {result.result.type}"
            )

    logger.info(f"Batch {batch_id} completed: {len(results)} successful results")
    return results
