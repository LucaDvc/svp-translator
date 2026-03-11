# SVP Translator Bot

Automated Russian → English translation bot for System-vector psychology lecture summaries.

Monitors a Telegram channel for new `.docx` files, translates them using Claude Sonnet 4.6 with specialized terminology, runs a QA pass to catch errors, and posts the translated document to another Telegram channel.

## How It Works

```
Russian .docx posted to Telegram channel
        ↓
Bot detects new file, downloads it
        ↓
Text extracted, split into ~5-page chunks
        ↓
Each chunk translated (Claude Sonnet 4.6 + prompt caching)
        ↓
Each chunk QA-reviewed against original (catches untranslated words, meaning errors)
        ↓
Clean .docx assembled with proper formatting
        ↓
Posted to target Telegram channel with caption
```

## Cost

- **API costs:** ~$6–15/month for 6 files/week (with prompt caching)
- **Hosting:** ~€3.30/month on Hetzner Cloud (or free on Oracle Cloud)

## Setup

### 1. Create a Telegram Bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g., "SVP Translator") and username (e.g., `svp_translator_bot`)
4. **Save the bot token** you receive
5. **Add the bot as an admin** to both your source and target channels
   - Open channel → Edit → Administrators → Add Administrator → search for your bot
   - The bot needs "Post Messages" permission on the target channel
   - The bot needs to be able to see messages on the source channel

### 2. Get Channel IDs

Forward any message from each channel to **@userinfobot** or **@getidsbot** on Telegram. You'll get an ID like `-1001234567890`.

### 3. Get an Anthropic API Key

1. Go to https://console.anthropic.com/
2. Create an API key
3. Add some credits ($10 will last you ~1–2 months)

### 4. Configure

```bash
cp config_local.py.template config_local.py
```

Edit `config_local.py` and fill in:

- `TELEGRAM_BOT_TOKEN` — from step 1
- `SOURCE_CHANNEL_ID` — from step 2
- `TARGET_CHANNEL_ID` — from step 2
- `ANTHROPIC_API_KEY` — from step 3

### 5. Deploy

#### Option A: Docker (Recommended)

```bash
docker compose up -d
```

That's it. The bot runs in the background and auto-restarts if it crashes.

To check logs:

```bash
docker compose logs -f
```

To update after changes:

```bash
docker compose up -d --build
```

#### Option B: Run Directly

```bash
pip install -r requirements.txt
python bot.py
```

## Deploying on a VPS (Hetzner) with GitHub Actions

Every push to `main` automatically builds a new Docker image and deploys it to your VPS. Here's how to set it up.

### 1. Create the VPS

1. Create a Hetzner Cloud account
2. Create a **CAX11** server (ARM, €3.29/month) with Ubuntu 24.04
3. Add your SSH public key during server creation

### 2. Prepare the VPS (one-time)

SSH into the server and install Docker:

```bash
curl -fsSL https://get.docker.com | sh
```

Authenticate with GitHub Container Registry so the server can pull your image.
Generate a GitHub personal access token with `read:packages` scope at
`GitHub → Settings → Developer settings → Personal access tokens`, then:

```bash
echo YOUR_GITHUB_TOKEN | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

That's it — the deploy action will handle everything else (creating directories, writing the `.env`, pulling the image).

### 3. Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions**.

Under the **Secrets** tab, add:

| Secret | Value |
|---|---|
| `VPS_HOST` | Your server's IP address |
| `VPS_USER` | `root` (or your SSH user) |
| `VPS_SSH_KEY` | Your SSH private key (contents of `~/.ssh/id_rsa`) |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `SOURCE_CHANNEL_ID` | Channel ID where Russian `.docx` files are posted |
| `TARGET_CHANNEL_ID` | Channel ID where translations are posted |
| `ANTHROPIC_API_KEY` | Your Anthropic API key |

Under the **Variables** tab, add:

| Variable | Default | Description |
|---|---|---|
| `MODEL` | `claude-sonnet-4-6` | Anthropic model to use |
| `CHUNK_SIZE_WORDS` | `1500` | Words per translation chunk |
| `USE_BATCH_API` | `true` | `true` = 50% cheaper, up to 1hr wait; `false` = instant |
| `LOG_LEVEL` | `INFO` | `DEBUG` for troubleshooting |

### 4. Deploy

Push to `main` — the action will build the image, push it to `ghcr.io`, and restart the container on your VPS. Check progress under the **Actions** tab in your repo.

To check logs on the VPS at any time:

```bash
docker logs svp-translator -f
```

## Bot Commands

Send these to the bot in a direct message:

- `/status` — Check if the bot is running and see current settings
- `/translate` — Reply to any `.docx` message with this command to manually trigger translation

## Configuration Options

Edit `config_local.py` to customize:

| Setting            | Default             | Description                                     |
| ------------------ | ------------------- | ----------------------------------------------- |
| `MODEL`            | `claude-sonnet-4-6` | Anthropic model to use                          |
| `CHUNK_SIZE_WORDS` | `1500`              | Words per translation chunk (~5 pages)          |
| `USE_BATCH_API`    | `False`             | Use batch API (50% cheaper, up to 1hr wait)     |
| `BATCH_TIMEOUT`    | `3600`              | Max seconds to wait for batch results           |
| `LOG_LEVEL`        | `INFO`              | Logging verbosity (`DEBUG` for troubleshooting) |

## Customizing the Terminology

The translation and QA prompts are in `config.py` as `TRANSLATION_SYSTEM_PROMPT` and `QA_SYSTEM_PROMPT`. To customize:

1. Copy the prompt to your `config_local.py`
2. Modify as needed
3. Restart the bot: `docker compose restart`

## Troubleshooting

**Bot doesn't detect files:**

- Make sure the bot is an admin in the source channel
- Check that `SOURCE_CHANNEL_ID` is correct (should be negative, like `-1001234567890`)
- Set `LOG_LEVEL = "DEBUG"` in config_local.py and check logs

**Translation quality issues:**

- Adjust `CHUNK_SIZE_WORDS` — smaller chunks (1000) may be more accurate, larger (2000) faster
- Edit the system prompts to add specific terminology

**API errors:**

- Verify your API key is valid: `curl https://api.anthropic.com/v1/messages -H "x-api-key: YOUR_KEY" -H "anthropic-version: 2023-06-01"`
- Check you have credits in your Anthropic account

## File Structure

```
svp-translator/
├── bot.py                    # Telegram bot (entry point)
├── translator.py             # Translation + QA pipeline
├── assembler.py              # .docx reading and writing
├── config.py                 # Default configuration
├── config_local.py.template  # Template for your local config
├── config_local.py           # Your actual config (not in git)
├── requirements.txt          # Python dependencies
├── Dockerfile                # Container build
├── docker-compose.yml        # One-command deployment
└── README.md                 # This file
```
