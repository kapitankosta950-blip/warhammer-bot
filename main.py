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
import secrets
import sqlite3
import string
from pathlib import Path

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
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", Path(__file__).with_name("database.db")))

# Comma-separated Telegram IDs, e.g. "123456789,987654321".  Keep these IDs
# in the deployment environment instead of committing them to the repository.
ADMIN_USER_IDS = {
    int(value)
    for value in os.environ.get("ADMIN_USER_IDS", "").split(",")
    if value.strip().isdigit()
}
CHANNEL_URL = os.environ.get("TELEGRAM_CHANNEL_URL", "@your_warhammer_channel")

ROLE_PROMPTS = {
    "default": SYSTEM_PROMPT,
    "erebus": (
        "You speak as Erebus of the Word Bearers: honeyed, clever and subtly "
        "manipulative. You frame heresy as a tempting argument, while remaining "
        "a fictional Warhammer 40K role-play assistant."
    ),
    "omnisiah": (
        "You speak as a devout servant of the Omnissiah. Use restrained binary "
        "flourishes and invocations of the Machine Spirit; give especially precise "
        "and useful Warhammer technology analysis."
    ),
    "emperor": (
        "You speak as the Emperor of Mankind from the Golden Throne: majestic, "
        "grave and inspiring, yet still answer the user's Warhammer question clearly."
    ),
    "khorne": "You speak as Khorne: martial, explosive and obsessed with battle, blood and skulls, without encouraging real-world violence.",
    "nurgle": "You speak as Nurgle: warm, decayed and morbidly affectionate, with fictional Warhammer flavour.",
    "tzeentch": "You speak as Tzeentch: cryptic, conspiratorial and fond of layered plans and riddles.",
    "slaanesh": "You speak as Slaanesh: refined, excessive and aesthetic, without sexual content.",
}
PRIMARCHS = {
    "guilliman": "Roboute Guilliman, practical Ultramarine statesman and strategist",
    "dorn": "Rogal Dorn, stoic master of defence and fortification",
    "sanguinius": "Sanguinius, noble and compassionate angel of Baal",
    "vulkan": "Vulkan, humane smith and protector of civilians",
    "horus": "Horus Lupercal, charismatic and tragic Warmaster",
    "magnus": "Magnus the Red, brilliant tragic psyker and scholar",
    "angron": "Angron, furious and bitter gladiator primarch",
    "perturabo": "Perturabo, calculating siege master with a wounded pride",
}

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

# Per-user custom donation state: { user_id: bool }
awaiting_donation: dict[int, bool] = {}

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
            "Використовуй /suggest, щоб надіслати пропозицію.\n"
            "Використовуй /support, якщо хочеш підтримати мене зірочками. 🌟"
        ),
        "clear": "🧹 Пам'ять очищено. Інквізиція була б задоволена.",
        "support_desc": "Задонатити зірочки автору бота на підтримку проекту.",
        "thanks": "🙏 Дякую, бойовий брате! Твоя щедрість живить Астрономікан. Імператор захищає!",
        "overload": "⏳ Модель зараз перевантажена, спробуй через хвилинку!",
        "suggest_text": "💡 Маєш ідею чи відгук? Напиши мені анонімно за цим посиланням:",
        "suggest_btn": "💡 Надіслати пропозицію",
        "ad": "📣 *Реклама:*\nЗробити сайт легко! @Bober5b все зробить швидко та якісно. 😉\n\n",
        "choose_amount": "Обери суму донату (Stars 🌟):",
        "custom_prompt": "✍️ Введи бажану кількість Stars (ціле число від 15 до 1000):",
        "invalid_amount": "❌ Некоректна сума. Будь ласка, введи ціле число від 15 до 1000.",
    },
    "en": {
        "start": (
            "**Ave Imperator!** 🦅\n\n"
            "I'm your Warhammer 40K lore buddy. Ask me anything about the "
            "grimdark universe — factions, characters, tabletop tips, you name it.\n\n"
            "Just type a message and we'll chat.\n"
            "Use /clear to wipe our conversation history.\n"
            "Use /suggest to send suggestions.\n"
            "Use /support if you want to toss some Stars my way. 🌟"
        ),
        "clear": "🧹 Memory wiped. The Inquisition would approve.",
        "support_desc": "Toss Telegram Stars to the dev as a thank-you.",
        "thanks": "🙏 Thank you, battle-brother! Your generosity fuels the Astronomican. The Emperor protects!",
        "overload": "⏳ Model is currently overloaded, please try again in a minute!",
        "suggest_text": "💡 Have an idea or feedback? Send an anonymous message here:",
        "suggest_btn": "💡 Send suggestion",
        "ad": "📣 *Ad:*\nNeed a website? It's easy! @Bober5b will build everything quickly and professionally. 😉\n\n",
        "choose_amount": "Choose a donation amount (Stars 🌟):",
        "custom_prompt": "✍️ Enter the number of Stars you want to donate (between 15 and 1000):",
        "invalid_amount": "❌ Invalid amount. Please enter a whole number between 15 and 1000.",
    },
    "ru": {
        "start": (
            "**Ave Imperator!** 🦅\n\n"
            "Я твой ИИ-помощник по лору Warhammer 40K. Спрашивай меня о чём угодно — "
            "фракциях, персонажах, советах по игре и т.д.\n\n"
            "Просто пиши сообщение, и мы пообщаемся.\n"
            "Используй /clear, чтобы очистить нашу историю.\n"
            "Используй /suggest, чтобы отправить предложение.\n"
            "Используй /support, если хочешь поддержать меня звёздочками. 🌟"
        ),
        "clear": "🧹 Память очищена. Инквизиция одобряет.",
        "support_desc": "Задонатить звёздочки автору бота на поддержку проекта.",
        "thanks": "🙏 Спасибо, боевой брат! Твоя щедрость питает Астрономикан. Император защищает!",
        "overload": "⏳ Модель сейчас перегружена, попробуй через минутку!",
        "suggest_text": "💡 Есть идея или отзыв? Напиши мне анонимно по этой ссылке:",
        "suggest_btn": "💡 Отправить предложение",
        "ad": "📣 *Реклама:*\nСделать сайт легко! @Bober5b всё сделает быстро и качественно. 😉\n\n",
        "choose_amount": "Выбери сумму доната (Stars 🌟):",
        "custom_prompt": "✍️ Введи желаемое количество Stars (целое число от 15 до 1000):",
        "invalid_amount": "❌ Некорректная сумма. Пожалуйста, введи целое число от 15 до 1000.",
    }
}


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------

def _db_connection() -> sqlite3.Connection:
    """Return a short-lived connection; handlers do no long-running DB work."""
    connection = sqlite3.connect(DATABASE_PATH)
    return connection


def init_database() -> None:
    """Create the persistent user and one-time promo-code tables if needed."""
    with _db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                is_premium BOOLEAN NOT NULL DEFAULT FALSE,
                current_role TEXT NOT NULL DEFAULT 'default'
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS promocodes (
                code TEXT PRIMARY KEY,
                is_used BOOLEAN NOT NULL DEFAULT FALSE,
                activated_by INTEGER NULL
            )
            """
        )


def ensure_user(user_id: int) -> None:
    with _db_connection() as connection:
        connection.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))


def get_user_profile(user_id: int) -> tuple[bool, str]:
    ensure_user(user_id)
    with _db_connection() as connection:
        row = connection.execute(
            "SELECT is_premium, current_role FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return bool(row[0]), row[1]


def set_current_role(user_id: int, role: str) -> None:
    ensure_user(user_id)
    with _db_connection() as connection:
        connection.execute("UPDATE users SET current_role = ? WHERE user_id = ?", (role, user_id))


def grant_premium(user_id: int) -> None:
    ensure_user(user_id)
    with _db_connection() as connection:
        connection.execute("UPDATE users SET is_premium = TRUE WHERE user_id = ?", (user_id,))


def redeem_promocode(user_id: int, code: str) -> bool:
    """Atomically redeem a code so it cannot be claimed twice."""
    ensure_user(user_id)
    with _db_connection() as connection:
        result = connection.execute(
            """
            UPDATE promocodes
            SET is_used = TRUE, activated_by = ?
            WHERE code = ? AND is_used = FALSE
            """,
            (user_id, code.upper()),
        )
        if result.rowcount != 1:
            return False
        connection.execute("UPDATE users SET is_premium = TRUE WHERE user_id = ?", (user_id,))
    return True


def generate_promocodes(quantity: int) -> list[str]:
    """Generate and store collision-safe one-time WAHA-PREM-XXXX codes."""
    alphabet = string.ascii_uppercase + string.digits
    codes: list[str] = []
    with _db_connection() as connection:
        while len(codes) < quantity:
            code = "WAHA-PREM-" + "".join(secrets.choice(alphabet) for _ in range(4))
            try:
                connection.execute("INSERT INTO promocodes (code) VALUES (?)", (code,))
            except sqlite3.IntegrityError:
                continue
            codes.append(code)
    return codes


def role_prompt(role: str) -> str:
    if role.startswith("primarch_"):
        primarch = PRIMARCHS.get(role.removeprefix("primarch_"))
        if primarch:
            return (
                f"You role-play as {primarch}. Keep the character's voice, but give "
                "accurate, practical answers about Warhammer 40K lore and gaming."
            )
    return ROLE_PROMPTS.get(role, SYSTEM_PROMPT)


def role_label(role: str) -> str:
    labels = {
        "default": "Дефолтний ШІ-помічник",
        "erebus": "Ереб",
        "omnisiah": "Омнісія",
        "emperor": "Імператор Людства",
        "khorne": "Кхорн",
        "nurgle": "Нургл",
        "tzeentch": "Тзінч",
        "slaanesh": "Слаанеш",
    }
    if role.startswith("primarch_"):
        return PRIMARCHS.get(role.removeprefix("primarch_"), "Примарх").split(",")[0]
    return labels.get(role, "Дефолтний ШІ-помічник")


def pantheon_keyboard(is_premium: bool) -> InlineKeyboardMarkup:
    premium_marker = "" if is_premium else " 🔒"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤖 Дефолтний ШІ-помічник", callback_data="role_default")],
            [InlineKeyboardButton(text=f"🗡 Ереб{premium_marker}", callback_data="role_erebus"),
             InlineKeyboardButton(text=f"⚙️ Омнісія{premium_marker}", callback_data="role_omnisiah")],
            [InlineKeyboardButton(text=f"👑 Імператор Людства{premium_marker}", callback_data="role_emperor")],
            [InlineKeyboardButton(text=f"💀 Боги Хаосу{premium_marker}", callback_data="roles_chaos")],
            [InlineKeyboardButton(text=f"🧬 Примархи{premium_marker}", callback_data="roles_primarchs")],
        ]
    )


def choices_keyboard(kind: str) -> InlineKeyboardMarkup:
    if kind == "chaos":
        rows = [
            [InlineKeyboardButton(text="Кхорн", callback_data="role_khorne"), InlineKeyboardButton(text="Нургл", callback_data="role_nurgle")],
            [InlineKeyboardButton(text="Тзінч", callback_data="role_tzeentch"), InlineKeyboardButton(text="Слаанеш", callback_data="role_slaanesh")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="Гілліман", callback_data="role_primarch_guilliman"), InlineKeyboardButton(text="Дорн", callback_data="role_primarch_dorn")],
            [InlineKeyboardButton(text="Сангвіній", callback_data="role_primarch_sanguinius"), InlineKeyboardButton(text="Вулкан", callback_data="role_primarch_vulkan")],
            [InlineKeyboardButton(text="Хорус", callback_data="role_primarch_horus"), InlineKeyboardButton(text="Магнус", callback_data="role_primarch_magnus")],
            [InlineKeyboardButton(text="Ангрон", callback_data="role_primarch_angron"), InlineKeyboardButton(text="Пертурабо", callback_data="role_primarch_perturabo")],
        ]
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="roles_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Message counter intentionally remains ephemeral: premium status and role are
# persistent, while an occasional channel reminder does not need to survive a restart.
message_counts: dict[int, int] = {}


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

    # Cap history length to avoid unbounded growth (keep last 12 turns for token optimization)
    if len(history) > 12:
        history[:] = history[-12:]

    user_lang = user_languages.get(user_id, "en")
    lang_inst = LANG_INSTRUCTIONS.get(user_lang, LANG_INSTRUCTIONS["en"])
    _, current_role = get_user_profile(user_id)
    full_prompt = f"{role_prompt(current_role)} {lang_inst}"

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
    ensure_user(message.from_user.id)
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

    pantheon_hints = {
        "uk": "⚔️ Обрати роль Пантеону: /pantheon",
        "en": "⚔️ Choose a Pantheon role: /pantheon",
        "ru": "⚔️ Выбрать роль Пантеона: /pantheon",
    }
    welcome_text = f"{STRINGS[selected_lang]['start']}\n\n{pantheon_hints[selected_lang]}"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=STRINGS[selected_lang]["suggest_btn"],
                    url="https://t.me/anonaskbot?start=2g6uwo9"
                )
            ],
            [InlineKeyboardButton(text="⚔️ Пантеон / ролі", callback_data="roles_back")],
        ]
    )
    await callback.message.answer(welcome_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.message(Command("promo"))
async def cmd_promo(message: Message) -> None:
    """Redeem a one-time premium code: /promo WAHA-PREM-XXXX."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Використання: /promo WAHA-PREM-XXXX")
        return

    code = parts[1].strip().upper()
    if redeem_promocode(message.from_user.id, code):
        conversations.pop(message.from_user.id, None)
        await message.answer(
            "✨ Промокод активовано! Преміум і весь Пантеон уже доступні через /pantheon."
        )
    else:
        await message.answer("❌ Цей промокод не існує або вже був використаний.")


@router.message(Command("gencodes"))
async def cmd_gencodes(message: Message) -> None:
    """Admin-only generator. Configure both admins in ADMIN_USER_IDS."""
    if message.from_user.id not in ADMIN_USER_IDS:
        return

    parts = (message.text or "").split(maxsplit=1)
    try:
        quantity = int(parts[1]) if len(parts) == 2 else 0
    except ValueError:
        quantity = 0
    if not 1 <= quantity <= 100:
        await message.answer("Використання: /gencodes [кількість від 1 до 100]")
        return

    codes = generate_promocodes(quantity)
    await message.answer("Нові промокоди:\n<code>" + "\n".join(codes) + "</code>", parse_mode=ParseMode.HTML)


@router.message(Command("pantheon"))
@router.message(Command("role"))
async def cmd_pantheon(message: Message) -> None:
    is_premium, current_role = get_user_profile(message.from_user.id)
    await message.answer(
        f"⚔️ Поточна роль: {role_label(current_role)}\nОберіть голос Пантеону:",
        reply_markup=pantheon_keyboard(is_premium),
    )


@router.callback_query(F.data == "roles_back")
async def callback_roles_back(callback: CallbackQuery) -> None:
    is_premium, current_role = get_user_profile(callback.from_user.id)
    await callback.message.edit_text(
        f"⚔️ Поточна роль: {role_label(current_role)}\nОберіть голос Пантеону:",
        reply_markup=pantheon_keyboard(is_premium),
    )
    await callback.answer()


@router.callback_query(F.data == "roles_chaos")
async def callback_chaos_roles(callback: CallbackQuery) -> None:
    is_premium, _ = get_user_profile(callback.from_user.id)
    if not is_premium:
        await callback.answer("Пантеон доступний у Premium.", show_alert=True)
        return
    await callback.message.edit_text("Оберіть Бога Хаосу:", reply_markup=choices_keyboard("chaos"))
    await callback.answer()


@router.callback_query(F.data == "roles_primarchs")
async def callback_primarch_roles(callback: CallbackQuery) -> None:
    is_premium, _ = get_user_profile(callback.from_user.id)
    if not is_premium:
        await callback.answer("Пантеон доступний у Premium.", show_alert=True)
        return
    await callback.message.edit_text("Оберіть примарха:", reply_markup=choices_keyboard("primarch"))
    await callback.answer()


@router.callback_query(F.data.startswith("role_"))
async def callback_set_role(callback: CallbackQuery) -> None:
    role = callback.data.removeprefix("role_")
    valid_roles = set(ROLE_PROMPTS) | {f"primarch_{name}" for name in PRIMARCHS}
    if role not in valid_roles:
        await callback.answer("Невідома роль.", show_alert=True)
        return

    is_premium, _ = get_user_profile(callback.from_user.id)
    if role != "default" and not is_premium:
        await callback.answer("🔒 Активуйте /promo або підтримайте бота через /support.", show_alert=True)
        return

    set_current_role(callback.from_user.id, role)
    conversations.pop(callback.from_user.id, None)
    await callback.message.answer(f"✅ Активна роль: {role_label(role)}")
    await callback.answer()


@router.message(Command("suggest"))
async def cmd_suggest(message: Message) -> None:
    user_id = message.from_user.id
    lang = user_languages.get(user_id, "en")
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=STRINGS[lang]["suggest_btn"],
                    url="https://t.me/anonaskbot?start=2g6uwo9"
                )
            ]
        ]
    )
    await message.answer(STRINGS[lang]["suggest_text"], reply_markup=keyboard)


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
    # Show donation options keyboard
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="15 🌟", callback_data="donate_15"),
                InlineKeyboardButton(text="20 🌟", callback_data="donate_20"),
                InlineKeyboardButton(text="50 🌟", callback_data="donate_50"),
            ],
            [
                InlineKeyboardButton(text="100 🌟", callback_data="donate_100"),
                InlineKeyboardButton(text="Custom 🌟", callback_data="donate_custom"),
            ]
        ]
    )
    await message.answer(STRINGS[lang]["choose_amount"], reply_markup=keyboard)


@router.callback_query(F.data.startswith("donate_"))
async def callback_select_donation(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    lang = user_languages.get(user_id, "en")
    action = callback.data.split("_")[1]
    
    if action == "custom":
        awaiting_donation[user_id] = True
        await callback.message.answer(STRINGS[lang]["custom_prompt"])
        await callback.answer()
        return
        
    try:
        amount = int(action)
        desc = STRINGS[lang]["support_desc"]
        
        await callback.message.answer_invoice(
            title=SUPPORT_TITLE,
            description=desc,
            payload="support_donation",
            currency="XTR",
            prices=[LabeledPrice(label="Donation", amount=amount)],
        )
    except Exception as exc:
        log.exception("Failed to send invoice via callback")
        await callback.message.answer(f"⚠️ Error: {exc}")
        
    await callback.answer()


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    """Always approve — it's a voluntary donation."""
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    user_id = message.from_user.id
    lang = user_languages.get(user_id, "en")
    grant_premium(user_id)
    await message.answer(STRINGS[lang]["thanks"])
    await message.answer("✨ Premium активовано — реклама вимкнена, Пантеон доступний через /pantheon.")


# ---------------------------------------------------------------------------
# Chat handler (catch-all for text messages)
# ---------------------------------------------------------------------------

@router.message(F.text)
async def handle_chat(message: Message) -> None:
    user_id = message.from_user.id
    user_text = message.text
    ensure_user(user_id)

    # Check if user is in custom donation input state
    if awaiting_donation.get(user_id):
        text = user_text.strip()
        lang = user_languages.get(user_id, "en")
        
        # If user sends a command instead, cancel the donation state and handle it
        if text.startswith("/"):
            awaiting_donation[user_id] = False
            # Let other handlers deal with it
            return

        try:
            amount = int(text)
            if 15 <= amount <= 1000:
                awaiting_donation[user_id] = False
                desc = STRINGS[lang]["support_desc"]
                await message.answer_invoice(
                    title=SUPPORT_TITLE,
                    description=desc,
                    payload="support_donation",
                    currency="XTR",
                    prices=[LabeledPrice(label="Donation", amount=amount)],
                )
                return
            else:
                await message.answer(STRINGS[lang]["invalid_amount"])
                return
        except ValueError:
            await message.answer(STRINGS[lang]["invalid_amount"])
            return

    # Show "typing…" while Gemini thinks
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    reply = await ask_gemini(user_id, user_text)

    is_premium, _ = get_user_profile(user_id)
    if not is_premium:
        message_counts[user_id] = message_counts.get(user_id, 0) + 1
        if message_counts[user_id] % 5 == 0:
            reply += f"\n\n📣 Більше лору та новин — у нашому Telegram-каналі: {CHANNEL_URL}"

    # Telegram messages cap at 4096 chars — split if needed
    for i in range(0, len(reply), 4096):
        await message.answer(reply[i : i + 4096])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def health_check(request: web.Request) -> web.Response:
    return web.Response(text="I am alive and serving the Emperor!")


async def main() -> None:
    init_database()
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
