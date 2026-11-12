# Poem Bot — Telegram Poetry Channel Manager

A small runnable first deployment of the **Poem Bot**, focused on preparing and managing poetry posts. It is not a general chatbot. Drafts are stored in SQLite and cannot be published until an authorized owner explicitly approves them.

## Run it

Requires Python 3.11+.

1. Create a Telegram bot with [@BotFather](https://t.me/BotFather), add it as an administrator to the destination channel, and grant permission to post.
2. Obtain your numeric Telegram user ID and configure `OWNER_IDS`.
3. Set up and launch:

```bash
cd poem_agent
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: TELEGRAM_BOT_TOKEN, OWNER_IDS, TARGET_CHANNEL
python -m poem_agent.main
```

The bot uses long polling; do not run two instances with the same token. `DATA_DIR` contains the SQLite database and should be backed up.

## Owner workflow

- `/start` or `/help` — instructions
- `/draft poem text` — create a pending draft
- Send poem text directly in the private chat — create a pending draft
- `/pending` — show outstanding drafts
- Tap **Approve & publish** to publish to the configured destination, or **Reject** to discard
- `/schedule YYYY-MM-DD HH:MM | poem text` — create a scheduled draft; it still requires approval before it can be scheduled for publication
- `/analyze poem text` — local heuristic classification preview

Only configured owner IDs can create, approve, reject, or schedule posts. The callback also verifies the approving Telegram user. A pending or rejected draft is never in the publication queue. The bot must have channel posting rights or delivery will fail and be recorded.

## Current scope and honest limitations

This version gives you a runnable, approval-gated publishing workflow with SQLite persistence, audit events, draft scheduling, and basic Burmese/English heuristic analysis. It does **not yet** collect channel history, use MTProto, call an AI model, search or validate image licenses, or provide channel analytics. Telegram bots cannot read arbitrary channel history; source collection needs explicit access and an optional authorized MTProto client. Those integrations should be added behind their own adapters rather than represented as already working.

The `AI_API_KEY` settings are reserved for later integration; current `/analyze` is explicitly heuristic and does not send poem text to an AI service.

## Tests

From the `poem_agent` directory:

```bash
pytest -q
```

Publication safety is covered by tests ensuring pending and rejected drafts cannot enter the publish queue. Run first in a private test channel before using a production channel.
