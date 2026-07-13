"""
Warhammer 40K Lore Companion — Telegram Bot
Uses aiogram v3 + Google Gemini (google-genai SDK).

Environment variables:
    TELEGRAM_BOT_TOKEN  — token from @BotFather
    GEMINI_API_KEY      — Google AI Studio / Gemini API key
"""

import os
import asyncio
import logging
import random

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    LabeledPrice,
    PreCheckoutQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode

from google import genai
from google.genai import types as genai_types
from aiohttp import web

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = "gemini-3.1-flash-lite"

SYSTEM_PROMPT = (
    "You are an authentic, adaptive AI collaborator with a touch of wit. "
    "You talk to the user naturally, like a close friend, without formal BS. "
    "You are deeply knowledgeable about Warhammer 40k lore and gaming. "
    "Keep the tone grounded, casual, and supportive."
)

SUPPORT_TITLE = "Support the Author ⚔️"
SUPPORT_DESCRIPTION = (
    "Toss 50 Telegram Stars to the dev as a thank-you for keeping "
    "the Emperor's light burning. Totally optional!"
)
SUPPORT_STARS = 50

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
)
log = logging.getLogger("warhammer_bot")

# ---------------------------------------------------------------------------
# Gemini client  (google-genai SDK)
# ---------------------------------------------------------------------------

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Per-user conversation history: { user_id: [Content, ...] }
conversations: dict[int, list] = {}

# Per-user language preference: { user_id: 'uk' | 'en' | 'ru' }
user_languages: dict[int, str] = {}

# Localized response instructions for Gemini system prompt
LANG_INSTRUCTIONS = {
    "uk": "Always reply in Ukrainian.",
    "en": "Always reply in English.",
    "ru": "Always reply in Russian.",
}

# Localized strings
STRINGS = {
    "uk": {
        "start": (
            "**Ave Imperator!** 🦅\n\n"
            "Я твій ШІ-помічник з лору Warhammer 40K. Запитуй мене про що завгодно — "
            "фракції, персонажі, поради до гри тощо.\n\n"
            "Просто пиши повідомлення і ми поспілкуємось.\n"
            "Використовуй /clear, щоб стерти нашу історію.\n"
            "Використовуй /support, якщо хочеш підтримати мене зірочками. 🌟"
        ),
        "clear": "🧹 Пам'ять очищено. Інквізиція була б задоволена.",
        "support_desc": "Задонатити 50 зірочок автору бота на підтримку проекту. Абсолютно добровільно!",
        "thanks": "🙏 Дякую, бойовий брате! Твоя щедрість живить Астрономікан. Імператор захищає!",
        "overload": "⏳ Модель зараз перевантажена, спробуй через хвилинку!",
    },
    "en": {
        "start": (
            "**Ave Imperator!** 🦅\n\n"
            "I'm your Warhammer 40K lore buddy. Ask me anything about the "
            "grimdark universe — factions, characters, tabletop tips, you name it.\n\n"
            "Just type a message and we'll chat.\n"
            "Use /clear to wipe our conversation history.\n"
            "Use /support if you want to toss some Stars my way. 🌟"
        ),
        "clear": "🧹 Memory wiped. The Inquisition would approve.",
        "support_desc": "Toss 50 Telegram Stars to the dev as a thank-you. Totally optional!",
        "thanks": "🙏 Thank you, battle-brother! Your generosity fuels the Astronomican. The Emperor protects!",
        "overload": "⏳ Model is currently overloaded, please try again in a minute!",
    },
    "ru": {
        "start": (
            "**Ave Imperator!** 🦅\n\n"
            "Я твой ИИ-помощник по лору Warhammer 40K. Спрашивай меня о чём угодно — "
            "фракциях, персонажах, советах по игре и т.д.\n\n"
            "Просто пиши сообщение, и мы пообщаемся.\n"
            "Используй /clear, чтобы очистить нашу историю.\n"
            "Используй /support, если хочешь поддержать меня звёздочками. 🌟"
        ),
        "clear": "🧹 Память очищена. Инквизиция одобряет.",
        "support_desc": "Задонатить 50 звёздочек автору бота на поддержку проекта. Абсолютно добровольно!",
        "thanks": "🙏 Спасибо, боевой брат! Твоя щедрость питает Астрономикан. Император защищает!",
        "overload": "⏳ Модель сейчас перегружена, попробуй через минутку!",
    }
}


async def ask_gemini(user_id: int, user_text: str) -> str:
    """Send user_text to Gemini, maintaining per-user history."""

    history = conversations.setdefault(user_id, [])

    # Append the new user turn
    history.append(
        genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=user_text)],
        )
    )

    # Cap history length to avoid unbounded growth (keep last 40 turns)
    if len(history) > 40:
        history[:] = history[-40:]

    user_lang = user_languages.get(user_id, "en")
    lang_inst = LANG_INSTRUCTIONS.get(user_lang, LANG_INSTRUCTIONS["en"])
    full_prompt = f"{SYSTEM_PROMPT} {lang_inst}"

    # Retry up to 3 times with exponential backoff on 503 (overload)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = await asyncio.to_thread(
                gemini_client.models.generate_content,
                model=GEMINI_MODEL,
                contents=history,
                config=genai_types.GenerateContentConfig(
                    system_instruction=full_prompt,
                    temperature=0.9,
                    max_output_tokens=1024,
                ),
            )

            assistant_text = response.text or "*(the Warp swallowed my response — try again)*"

            # Store assistant reply in history
            history.append(
                genai_types.Content(
                    role="model",
                    parts=[genai_types.Part(text=assistant_text)],
                )
            )

            return assistant_text

        except Exception as exc:
            is_overload = "503" in str(exc) or "UNAVAILABLE" in str(exc)
            if is_overload and attempt < max_retries - 1:
                wait = (2 ** attempt) + random.uniform(0, 1)
                log.warning(
                    "Gemini 503 for user %s, retrying in %.1fs (attempt %d/%d)",
                    user_id, wait, attempt + 1, max_retries,
                )
                await asyncio.sleep(wait)
                continue

            log.exception("Gemini API error for user %s", user_id)
            # Don't persist the failed user turn
            history.pop()
            if is_overload:
                return STRINGS[user_lang]["overload"]
            return f"⚠️ Something went wrong on the cogitator side:\n`{exc}`"

# ---------------------------------------------------------------------------
# Bot & Router
# ---------------------------------------------------------------------------

bot = Bot(token=TELEGRAM_BOT_TOKEN)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇺🇦 Українська", callback_data="lang_uk"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en"),
            ],
            [
                InlineKeyboardButton(text="🇷🇺 російська", callback_data="lang_ru"),
            ]
        ]
    )
    await message.answer(
        "Choose your language / Оберіть мову / Выберите язык:",
        reply_markup=keyboard
    )


@router.callback_query(F.data.startswith("lang_"))
async def callback_select_lang(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    selected_lang = callback.data.split("_")[1]
    user_languages[user_id] = selected_lang

    # Clear history on language switch so the bot starts fresh in that language
    conversations.pop(user_id, None)

    welcome_text = STRINGS[selected_lang]["start"]
    await callback.message.answer(welcome_text, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.message(Command("clear"))
async def cmd_clear(message: Message) -> None:
    user_id = message.from_user.id
    conversations.pop(user_id, None)
    lang = user_languages.get(user_id, "en")
    await message.answer(STRINGS[lang]["clear"])


# ---------------------------------------------------------------------------
# /support — Telegram Stars invoice (XTR)
# ---------------------------------------------------------------------------

@router.message(Command("support"))
async def cmd_support(message: Message) -> None:
    user_id = message.from_user.id
    lang = user_languages.get(user_id, "en")
    desc = STRINGS[lang]["support_desc"]
    
    await message.answer_invoice(
        title=SUPPORT_TITLE,
        description=desc,
        payload="support_donation",
        currency="XTR",
        prices=[LabeledPrice(label="Donation", amount=SUPPORT_STARS)],
    )


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    """Always approve — it's a voluntary donation."""
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    user_id = message.from_user.id
    lang = user_languages.get(user_id, "en")
    await message.answer(STRINGS[lang]["thanks"])


# ---------------------------------------------------------------------------
# Chat handler (catch-all for text messages)
# ---------------------------------------------------------------------------

@router.message(F.text)
async def handle_chat(message: Message) -> None:
    user_id = message.from_user.id
    user_text = message.text

    # Show "typing…" while Gemini thinks
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    reply = await ask_gemini(user_id, user_text)

    # Telegram messages cap at 4096 chars — split if needed
    for i in range(0, len(reply), 4096):
        await message.answer(reply[i : i + 4096])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def health_check(request: web.Request) -> web.Response:
    return web.Response(text="I am alive and serving the Emperor!")


async def main() -> None:
    dp = Dispatcher()
    dp.include_router(router)

    # Start a background web server for Render's health checks (keeps the bot awake)
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Web server started on port %s", port)

    log.info("Bot starting — For the Emperor!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
