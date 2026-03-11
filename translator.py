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
