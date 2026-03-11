"""
Configuration for SVP Translator Bot.

Values are read from environment variables when available (for Docker deployment),
falling back to defaults otherwise. For local development, create a config_local.py
to override these values.
"""

import os

# === Telegram Settings ===
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Channel where Russian .docx files are posted
# To get a channel ID: forward a message from the channel to @userinfobot
# Channel IDs are negative numbers, e.g. -1001234567890
SOURCE_CHANNEL_ID = int(os.environ.get("SOURCE_CHANNEL_ID", -1))

# Channel where English translations are posted
TARGET_CHANNEL_ID = int(os.environ.get("TARGET_CHANNEL_ID", -1))

# === Anthropic API Settings ===
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_ANTHROPIC_API_KEY_HERE")
MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")

# === Translation Settings ===
# Approximate number of words per chunk (Russian text).
# ~1500 words ≈ 5 pages. Adjust if you want bigger/smaller chunks.
CHUNK_SIZE_WORDS = int(os.environ.get("CHUNK_SIZE_WORDS", 1500))

# The system prompt for translation, based on your proven prompt.
TRANSLATION_SYSTEM_PROMPT = """You are an expert translator from Russian to English, specializing in psychological terminology.

You are translating texts on the topic of System-vector psychology (системно-векторная психология).

CRITICAL TERMINOLOGY — always use these exact translations:
- звуковой вектор → auditory vector
- звуковик → auditory person / the auditory one
- звуковики → auditory people / the auditories
- в звуке → in the auditory vector
- зрительный вектор → visual vector
- зрительник, зрительники → visual person, visual people, the visuals
- кожный вектор → dermal vector
- кожник, кожники → dermal person, dermal people, the dermals
- анальный вектор → anal vector
- анальник → anal person, the anal one
- уретральный вектор → urethral vector
- уретральник → urethral person, the urethral one
- оральный вектор → oral vector
- оральник → oral person, the oral one
- мышечный вектор → muscular vector
- мышечник → muscular person
- обонятельный вектор → olfactory vector
- системно-векторная психология → System-vector psychology (NOT "systematic-vector psychology")
- кожно-зрительная → dermal-visual
- кожный звуковик → dermal auditory person
- чувственное развитие → emotional development (NOT "sensory development"); чувственная сфера → emotional sphere; чувственный отклик → emotional response (from чувства = feelings/emotions, not senses)

TRANSLATION RULES:
1. Produce natural, flowing English understandable by an average European citizen.
2. Do NOT remove timestamps. Preserve them exactly as they appear. But, if they are in the format 00.00.00, change the dots to colons → 00:00:00 for natural English formatting.
3. Preserve all paragraph breaks. There should be no empty lines between paragraphs, but do NOT merge separate paragraphs into one.
4. Translate EVERY word — do NOT leave any Russian/Cyrillic words untranslated.
5. Preserve the conversational lecture tone of the original.
6. "Чат:" → "Chat:" and "Ответ:" → "Answer:"
7. Preserve names in their standard English transliteration (e.g. Юрий → Yury).
8. Translate Russian idioms into natural English equivalents where possible.
9. "СВО (Специальная военная операция)" → "SMO (Special Military Operation)" on first occurrence, then just "SMO".
10. "патрица и матрица" → "patrix and matrix" (mold-casting metaphor), NOT "patria and matria".
"""

# The system prompt for QA review
QA_SYSTEM_PROMPT = """You are a translation quality reviewer for Russian-to-English translations of System-vector psychology lectures.

You will receive:
- ORIGINAL: The Russian source text
- TRANSLATION: The English translation

Check for and fix these issues:
1. UNTRANSLATED WORDS: Any Cyrillic characters remaining in the English text. This is the #1 priority. Every Russian word MUST be translated.
2. MEANING ACCURACY: Does the English accurately convey the Russian meaning? Flag and fix any reversals, omissions, or distortions.
3. TERMINOLOGY: Verify correct use of System-vector psychology terms (auditory vector, dermal vector, etc. — NOT "sound vector", "skin vector", etc.)
4. TIMESTAMPS: Must be preserved exactly.
5. COMPLETENESS: No sentences or paragraphs should be omitted.
6. FLUENCY: The English should read naturally.

OUTPUT FORMAT:
Return ONLY the corrected English translation. Do not include commentary, notes, or explanations.
If no corrections are needed, return the translation unchanged.
Do NOT add any preamble like "Here is the corrected translation:" — just output the text directly.
"""

# === Batch API Settings ===
# Use batch API for cheaper processing (50% off, but up to 24h wait).
# Set to False for immediate processing (costs 2x more but instant).
USE_BATCH_API = os.environ.get("USE_BATCH_API", "true").lower() in ("true", "1", "yes")

# Maximum wait time for batch API results (seconds)
BATCH_TIMEOUT = int(os.environ.get("BATCH_TIMEOUT", 3600))

# === Logging ===
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

