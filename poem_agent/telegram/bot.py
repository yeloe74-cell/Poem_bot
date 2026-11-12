"""Telegram polling bot with owner-only draft approval and publishing."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from poem_agent.config.settings import Settings
from poem_agent.poetry.poem_analyzer import analyze_poem
from poem_agent.security.owner_auth import is_owner
from poem_agent.storage.database import Database

logger = logging.getLogger(__name__)


class PoemTelegramBot:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database

    async def owner_guard(self, update: Update) -> bool:
        user = update.effective_user
        if not is_owner(self.settings, user.id if user else None):
            if update.effective_message:
                await update.effective_message.reply_text("ဒီ bot ကို ပိုင်ရှင်သာ စီမံနိုင်ပါတယ်။")
            return False
        return True

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.owner_guard(update):
            return
        await update.effective_message.reply_text(
            "Poem Bot အဆင်သင့်ပါပြီ။\n/draft ကဗျာစာသား — အတည်ပြုရန် draft ပြုလုပ်မည်။\n"
            "/pending — စောင့်နေသော draft များ\n/schedule YYYY-MM-DD HH:MM | ကဗျာစာသား\n"
            "စာသားတစ်ခု ပို့လိုက်ပါကလည်း အတည်ပြုရန် draft အဖြစ်သိမ်းပါမည်။\n"
            "ထုတ်ဝေခြင်းသည် ပိုင်ရှင်က Approve နှိပ်ပြီးမှသာ ဖြစ်ပါမည်။"
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.start(update, context)

    async def draft(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.owner_guard(update):
            return
        text = " ".join(context.args).strip()
        if not text:
            await update.effective_message.reply_text("အသုံးပြုပုံ: /draft ကဗျာစာသား")
            return
        await self.create_draft_reply(update, text)

    async def schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.owner_guard(update):
            return
        raw = " ".join(context.args)
        try:
            date_text, poem = raw.split("|", 1)
            scheduled = datetime.strptime(date_text.strip(), "%Y-%m-%d %H:%M").astimezone().isoformat(timespec="seconds")
            draft_id = self.database.create_draft(poem, scheduled_at=scheduled)
        except (ValueError, TypeError):
            await update.effective_message.reply_text(
                "အသုံးပြုပုံ: /schedule 2026-12-01 09:00 | ကဗျာစာသား\n"
                "အချိန်သည် bot server ရဲ့ local timezone အတိုင်းဖြစ်ပါတယ်။"
            )
            return
        await self.send_draft_card(update, draft_id, scheduled)

    async def pending(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.owner_guard(update):
            return
        drafts = self.database.pending_drafts()
        if not drafts:
            await update.effective_message.reply_text("Асуудалгүй: pending draft алга.")
            return
        for item in drafts:
            await self.send_draft_card(update, item["id"], item.get("scheduled_at"))

    async def analyze(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.owner_guard(update):
            return
        text = " ".join(context.args).strip()
        if not text:
            await update.effective_message.reply_text("အသုံးပြုပုံ: /analyze ကဗျာစာသား")
            return
        result = analyze_poem(text)
        await update.effective_message.reply_text(
            f"အမျိုးအစား: {result['category']}\nခံစားချက်: {result['emotion']}\n"
            f"ဘာသာ: {result['language']}\nအရည်အသွေးခန့်မှန်း: {result['quality_score']}/100\n"
            f"{result['note']}"
        )

    async def create_draft_reply(self, update: Update, poem: str) -> None:
        try:
            draft_id = self.database.create_draft(poem)
        except ValueError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        await self.send_draft_card(update, draft_id)

    async def send_draft_card(self, update: Update, draft_id: str,
                              scheduled_at: str | None = None) -> None:
        draft = self.database.get_draft(draft_id)
        if not draft:
            return
        body = draft["poem"]
        if draft.get("author"):
            body += f"\n\n— {draft['author']}"
        body = body[:3800]
        info = f"\n\nDraft: {draft_id}\nအတည်ပြုရန် review လုပ်ပါ။"
        if scheduled_at:
            info += f"\nစီစဉ်ထားချိန်: {scheduled_at} (အတည်ပြုပြီးမှ ထုတ်ဝေမည်)"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve & publish", callback_data=f"approve:{draft_id}"),
            InlineKeyboardButton("🗑 Reject", callback_data=f"reject:{draft_id}"),
        ]])
        await update.effective_message.reply_text(body + info, reply_markup=keyboard)

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        if not is_owner(self.settings, query.from_user.id):
            await query.answer("ပိုင်ရှင်သာ အတည်ပြုနိုင်ပါတယ်။", show_alert=True)
            return
        await query.answer()
        try:
            action, draft_id = (query.data or "").split(":", 1)
        except ValueError:
            return
        draft = self.database.get_draft(draft_id)
        if not draft or draft["status"] != "pending":
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("ဒီ draft ကို ယခင်က ဆုံးဖြတ်ပြီးပါပြီ သို့မဟုတ် မတွေ့ပါ။")
            return
        if action == "reject":
            changed = self.database.reject(draft_id, query.from_user.id)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("Draft ကို ပယ်ဖျက်ပြီးပါပြီ။" if changed else "အခြေအနေပြောင်းလဲသွားပါတယ်။")
            return
        if action != "approve":
            return
        changed = self.database.approve(draft_id, query.from_user.id)
        await query.edit_message_reply_markup(reply_markup=None)
        if not changed:
            await query.message.reply_text("အတည်ပြုမှု မအောင်မြင်ပါ။")
            return
        if draft.get("scheduled_at"):
            await query.message.reply_text("အတည်ပြုပြီးပါပြီ။ သတ်မှတ်ချိန်ရောက်မှ channel သို့တင်ပါမယ်။")
            return
        await self.publish_one(context.application, draft_id)

    async def publish_one(self, application: Application, draft_id: str) -> bool:
        draft = self.database.get_draft(draft_id)
        if not draft or draft["status"] != "approved":
            return False
        text = draft["poem"].strip()
        if draft.get("author"):
            text += f"\n\n— {draft['author']}"
        if draft.get("source"):
            text += f"\n\nSource: {draft['source']}"
        try:
            message = await application.bot.send_message(
                chat_id=self.settings.telegram.target_channel,
                text=text[:4096],
                disable_web_page_preview=True,
            )
            self.database.mark_published(draft_id, message.message_id)
            logger.info("Published approved draft %s to configured channel", draft_id)
            return True
        except Exception as exc:
            logger.exception("Publishing draft %s failed", draft_id)
            self.database.mark_failed(draft_id, str(exc))
            for owner_id in self.settings.telegram.owner_ids:
                try:
                    await application.bot.send_message(chat_id=owner_id, text=f"Draft {draft_id} တင်မရပါ: {exc}")
                except Exception:
                    logger.exception("Could not notify owner about failed publish")
            return False

    async def plain_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.owner_guard(update):
            return
        if update.effective_chat and update.effective_chat.type != ChatType.PRIVATE:
            return
        message = update.effective_message
        if message and message.text:
            await self.create_draft_reply(update, message.text)

    async def scheduled_worker(self, application: Application) -> None:
        while True:
            try:
                for draft in self.database.due_approved():
                    await self.publish_one(application, draft["id"])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduled publication scan failed")
            await asyncio.sleep(15)


def create_application(settings: Settings) -> Application:
    database = Database(settings.database_path)
    database.initialize()
    service = PoemTelegramBot(settings, database)

    async def post_init(application: Application) -> None:
        application.create_task(service.scheduled_worker(application), name="approved-schedule-worker")
        logger.info("Bot initialized; owner approval required for every draft")

    app = (Application.builder().token(settings.telegram.bot_token)
           .connect_timeout(settings.telegram.polling_timeout)
           .read_timeout(settings.telegram.polling_timeout)
           .write_timeout(settings.telegram.polling_timeout)
           .post_init(post_init).build())
    app.add_handler(CommandHandler("start", service.start))
    app.add_handler(CommandHandler("help", service.help))
    app.add_handler(CommandHandler("draft", service.draft))
    app.add_handler(CommandHandler("schedule", service.schedule))
    app.add_handler(CommandHandler("pending", service.pending))
    app.add_handler(CommandHandler("analyze", service.analyze))
    app.add_handler(CallbackQueryHandler(service.callback, pattern=r"^(approve|reject):"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, service.plain_text))
    return app
