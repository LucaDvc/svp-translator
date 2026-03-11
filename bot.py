"""
Telegram bot: monitors source channel for .docx files, translates them,
and posts the translation to the target channel.
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from telegram import Update, Bot
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

from translator import translate_and_review
from assembler import (
    extract_text_from_docx,
    build_translated_docx,
    generate_output_filename,
)

try:
    import config_local as config
except ImportError:
    import config

logger = logging.getLogger(__name__)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming documents in the source channel."""
    message = update.channel_post or update.message

    if not message:
        message = update.edited_channel_post or update.edited_message

    if not message or not message.document:
        return

    # Only process .docx files
    filename = message.document.file_name or ""
    if not filename.lower().endswith(".docx"):
        logger.debug(f"Skipping non-docx file: {filename}")
        return

    # Only process from the source channel
    chat_id = message.chat.id
    if chat_id != config.SOURCE_CHANNEL_ID:
        logger.debug(f"Skipping file from non-source channel: {chat_id}")
        return

    logger.info(f"New .docx detected: {filename}")

    # Work in a temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # Download the file
            input_path = Path(tmpdir) / filename
            file = await message.document.get_file()
            await file.download_to_drive(str(input_path))
            logger.info(f"Downloaded {filename} ({input_path.stat().st_size} bytes)")

            # Extract text
            russian_text = extract_text_from_docx(input_path)
            if not russian_text.strip():
                logger.warning(f"Empty document: {filename}")
                return

            word_count = len(russian_text.split())
            logger.info(f"Extracted {word_count} words from {filename}")

            # Translate + QA
            logger.info("Starting translation pipeline...")
            translated_text = translate_and_review(
                text=russian_text,
                anthropic_api_key=config.ANTHROPIC_API_KEY,
                model=config.MODEL,
                translation_prompt=config.TRANSLATION_SYSTEM_PROMPT,
                qa_prompt=config.QA_SYSTEM_PROMPT,
                chunk_size_words=config.CHUNK_SIZE_WORDS,
                use_batch=config.USE_BATCH_API,
                batch_timeout=config.BATCH_TIMEOUT,
            )

            # Build output .docx
            output_filename = generate_output_filename(filename)
            output_path = Path(tmpdir) / output_filename
            build_translated_docx(translated_text, output_path, filename)

            # Post to target channel
            logger.info(f"Posting {output_filename} to target channel...")

            # Generate a nice caption from the filename
            caption = _make_caption(output_filename)

            bot: Bot = context.bot
            with open(output_path, "rb") as f:
                await bot.send_document(
                    chat_id=config.TARGET_CHANNEL_ID,
                    document=f,
                    filename=output_filename,
                    caption=caption,
                )

            logger.info(f"Successfully translated and posted: {output_filename}")

        except Exception as e:
            logger.error(f"Error processing {filename}: {e}", exc_info=True)


def _make_caption(filename: str) -> str:
    """Generate a human-readable caption from the output filename."""
    name = Path(filename).stem
    # Replace underscores with spaces, clean up
    pretty = name.replace("_", " ").replace("-", " — ")
    return f"📄 Translation ready: {pretty}"


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple /status command to verify the bot is running."""
    await update.message.reply_text(
        "✅ SVP Translator Bot is running.\n"
        f"Model: {config.MODEL}\n"
        f"Batch mode: {'ON' if config.USE_BATCH_API else 'OFF'}\n"
        f"Chunk size: {config.CHUNK_SIZE_WORDS} words"
    )


async def cmd_translate_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /translate command — reply to a .docx message with /translate to manually
    trigger translation (useful for testing or re-translating).
    """
    message = update.message
    if not message:
        return

    # Check if replying to a document
    reply = message.reply_to_message
    if not reply or not reply.document:
        await message.reply_text("Reply to a .docx file with /translate to translate it.")
        return

    filename = reply.document.file_name or "document.docx"
    if not filename.lower().endswith(".docx"):
        await message.reply_text("That's not a .docx file.")
        return

    await message.reply_text(f"Starting translation of {filename}...")

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            input_path = Path(tmpdir) / filename
            file = await reply.document.get_file()
            await file.download_to_drive(str(input_path))

            russian_text = extract_text_from_docx(input_path)
            translated_text = translate_and_review(
                text=russian_text,
                anthropic_api_key=config.ANTHROPIC_API_KEY,
                model=config.MODEL,
                translation_prompt=config.TRANSLATION_SYSTEM_PROMPT,
                qa_prompt=config.QA_SYSTEM_PROMPT,
                chunk_size_words=config.CHUNK_SIZE_WORDS,
                use_batch=config.USE_BATCH_API,
                batch_timeout=config.BATCH_TIMEOUT,
            )

            output_filename = generate_output_filename(filename)
            output_path = Path(tmpdir) / output_filename
            build_translated_docx(translated_text, output_path, filename)

            caption = _make_caption(output_filename)

            with open(output_path, "rb") as f:
                await message.reply_document(
                    document=f,
                    filename=output_filename,
                    caption=caption,
                )

        except Exception as e:
            await message.reply_text(f"Error: {e}")
            logger.error(f"Manual translate error: {e}", exc_info=True)


def main():
    """Start the bot."""
    # Configure logging
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    )
    # Suppress noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logger.info("Starting SVP Translator Bot...")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Handler for .docx files in the source channel
    app.add_handler(
        MessageHandler(
            filters.Document.ALL & (filters.ChatType.CHANNEL | filters.ChatType.SUPERGROUP | filters.ChatType.GROUP),
            handle_document,
        )
    )

    # Commands (for DM / group interaction with the bot)
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("translate", cmd_translate_file))

    logger.info(
        f"Bot started. Monitoring channel {config.SOURCE_CHANNEL_ID} "
        f"→ posting to {config.TARGET_CHANNEL_ID}"
    )

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
