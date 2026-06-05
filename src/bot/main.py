import asyncio
import contextlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command
from aiogram.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from backend.coingecko import CoinGeckoClient
from common.config import get_settings
from common.db import close_pool, init_pool
from common.site_auth import create_site_token
from common.services import (
    get_asset_by_symbol,
    get_latest_market_price,
    get_or_create_default_portfolio,
    get_portfolio_balance,
    get_triggered_alerts,
    list_assets,
    register_user,
    upsert_market_data,
)

logging.basicConfig(level=logging.INFO)
settings = get_settings()
dp = Dispatcher()


def _rub(value: object) -> str:
    return f"{float(value or 0):,.2f} руб.".replace(",", " ")


async def _ensure_user_by_telegram(telegram_user_id: int, username: Optional[str]) -> int:
    pool = await init_pool()
    return await register_user(pool, telegram_user_id, username)


async def _ensure_user_message(message: Message) -> int:
    username = message.from_user.username if message.from_user else None
    telegram_user_id = message.from_user.id if message.from_user else message.chat.id
    return await _ensure_user_by_telegram(telegram_user_id, username)


async def _sync_market_data_once() -> int:
    pool = await init_pool()
    assets = await list_assets(pool)
    if not assets:
        return 0

    client = CoinGeckoClient()
    try:
        prices = await client.get_prices([a["coingecko_id"] for a in assets])
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            logging.warning("CoinGecko временно ограничил частоту запросов при фоновой синхронизации.")
            return 0
        raise
    finally:
        await client.close()

    inserted = 0
    for asset in assets:
        quote = prices.get(asset["coingecko_id"])
        if not quote or "rub" not in quote:
            continue
        await upsert_market_data(
            pool=pool,
            asset_id=asset["id"],
            price_rub=float(quote["rub"]),
            change_24h=float(quote.get("rub_24h_change")) if quote.get("rub_24h_change") is not None else None,
            source="coingecko",
        )
        inserted += 1
    return inserted


async def _resolve_market_price(symbol: str) -> Optional[float]:
    pool = await init_pool()
    asset = await get_asset_by_symbol(pool, symbol)
    if not asset:
        return None
    latest = await get_latest_market_price(pool, asset["id"])
    if latest is None:
        client = CoinGeckoClient()
        try:
            payload = await client.get_prices([asset["coingecko_id"]])
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                logging.warning("CoinGecko временно ограничил частоту запросов при проверке цены.")
                return None
            raise
        finally:
            await client.close()
        quote = payload.get(asset["coingecko_id"], {})
        if "rub" in quote:
            await upsert_market_data(
                pool=pool,
                asset_id=asset["id"],
                price_rub=float(quote["rub"]),
                change_24h=float(quote.get("rub_24h_change")) if quote.get("rub_24h_change") is not None else None,
                source="coingecko",
            )
            latest = await get_latest_market_price(pool, asset["id"])
    if latest is None:
        return None
    return float(latest["price_rub"])


def _launcher_keyboard() -> InlineKeyboardMarkup:
    url = settings.webapp_url.strip()
    site_url = settings.site_url.strip()
    buttons = []
    if not url.startswith("https://") or "your-public-domain" in url:
        if site_url.startswith("https://") and "your-public-domain" not in site_url:
            buttons.append([InlineKeyboardButton(text="Открыть сайт", url=site_url)])
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть приложение", web_app=WebAppInfo(url=url))]
        ]
    )


def _site_auth_secret() -> str:
    return settings.site_auth_secret or settings.bot_token


def _message_identity(message: Message) -> tuple[int, Optional[str]]:
    username = message.from_user.username if message.from_user else None
    telegram_user_id = message.from_user.id if message.from_user else message.chat.id
    return int(telegram_user_id), username


def _build_site_url(telegram_user_id: int, username: Optional[str]) -> str:
    base_url = settings.site_url.strip()
    token = create_site_token(
        telegram_user_id=telegram_user_id,
        username=username,
        secret=_site_auth_secret(),
        ttl_days=settings.site_token_ttl_days,
    )
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}token={token}"


def _site_link_keyboard(telegram_user_id: int, username: Optional[str]) -> InlineKeyboardMarkup:
    if not settings.site_url.strip().startswith("https://"):
        return InlineKeyboardMarkup(inline_keyboard=[])
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть сайт", url=_build_site_url(telegram_user_id, username))]]
    )


async def _alerts_notifier_loop(bot: Bot, stop_event: asyncio.Event) -> None:
    known_ids: set[int] = set()
    while not stop_event.is_set():
        try:
            await _sync_market_data_once()
            recent = datetime.now(timezone.utc) - timedelta(minutes=20)
            triggered = await get_triggered_alerts(await init_pool(), since=recent)
            for item in triggered:
                if item["id"] in known_ids:
                    continue
                known_ids.add(item["id"])
                cond = "выше" if item["condition_type"] == "gt" else "ниже"
                text = (
                    "Сработало ценовое уведомление\n"
                    f"{item['symbol']}: цена {cond} {_rub(item['target_price_rub'])}\n"
                    f"Текущая цена: {_rub(item.get('current_price_rub'))}"
                )
                await bot.send_message(chat_id=item["telegram_user_id"], text=text)
        except Exception as exc:
            logging.exception("Ошибка цикла уведомлений: %s", exc)
            await asyncio.sleep(max(30, settings.bot_market_sync_interval_seconds))
            continue
        await asyncio.sleep(max(30, settings.bot_market_sync_interval_seconds))


async def _create_working_bot() -> Bot:
    proxy_urls = settings.proxy_urls or [None]
    last_error: Exception | None = None
    for proxy_url in proxy_urls:
        bot_session = AiohttpSession(proxy=proxy_url) if proxy_url else None
        bot = Bot(token=settings.bot_token, session=bot_session)
        try:
            await bot.get_me()
            proxy_label = proxy_url or "без прокси"
            logging.info("Telegram-бот запущен через подключение: %s", proxy_label)
            return bot
        except Exception as exc:
            last_error = exc
            proxy_label = proxy_url or "без прокси"
            logging.warning("Не удалось подключить Telegram-бота через %s: %s", proxy_label, exc)
            await bot.session.close()
    raise RuntimeError("Не удалось подключиться к Telegram ни через один прокси") from last_error


@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    user_id = await _ensure_user_message(message)
    default_portfolio = await get_or_create_default_portfolio(await init_pool(), user_id)
    telegram_user_id, username = _message_identity(message)
    url = settings.webapp_url.strip()
    if not url.startswith("https://") or "your-public-domain" in url:
        await message.answer(
            "Бот мониторинга криптовалютного портфеля готов.\n"
            f"ID пользователя: {user_id}\n"
            f"Основной портфель: {default_portfolio['name']} (id={default_portfolio['id']})\n\n"
            "Ссылка на WebApp пока не настроена. Быстрая проверка цены доступна сообщением вида: 1 btc",
        )
        return

    await message.answer(
        "Бот мониторинга криптовалютного портфеля готов.\n"
        f"ID пользователя: {user_id}\n"
        f"Основной портфель: {default_portfolio['name']} (id={default_portfolio['id']})\n\n"
        "Откройте приложение кнопкой ниже.",
        reply_markup=_launcher_keyboard(),
    )


@dp.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await _ensure_user_message(message)
    await message.answer("Открыть приложение:", reply_markup=_launcher_keyboard())


@dp.message(Command("site"))
async def cmd_site(message: Message) -> None:
    await _ensure_user_message(message)
    telegram_user_id, username = _message_identity(message)
    if not settings.site_url.strip() or "your-public-domain" in settings.site_url:
        await message.answer("Ссылка на сайт пока не настроена.")
        return
    site_url = _build_site_url(telegram_user_id, username)
    keyboard = _site_link_keyboard(telegram_user_id, username)
    await message.answer(
        "Альтернативный вход на сайт. Ссылка персональная и открывает тот же портфель.",
        reply_markup=keyboard if keyboard.inline_keyboard else None,
    )
    if not keyboard.inline_keyboard:
        await message.answer(site_url)


@dp.message(Command("balance"))
async def cmd_balance(message: Message) -> None:
    user_id = await _ensure_user_message(message)
    portfolio = await get_or_create_default_portfolio(await init_pool(), user_id)
    try:
        balance = await get_portfolio_balance(await init_pool(), int(portfolio["id"]))
    except ValueError:
        await message.answer("Портфель не найден.")
        return
    lines = [
        f"Портфель: {balance['name']} (id={balance['id']})",
        f"Общая стоимость: {_rub(balance['total_value_rub'])}",
        "Позиции:",
    ]
    for pos in balance["positions"]:
        lines.append(
            f"- {pos['symbol']}: количество={pos['quantity']}, "
            f"средняя цена={_rub(pos['avg_buy_price_rub'])}, "
            f"результат={_rub(pos['realized_pnl_rub'])}"
        )
    if not balance["positions"]:
        lines.append("- открытых позиций нет")
    await message.answer("\n".join(lines), reply_markup=_launcher_keyboard())


@dp.message(F.text)
async def fallback(message: Message) -> None:
    await _ensure_user_message(message)
    text = (message.text or "").strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s+([a-z]{2,10})", text)
    if match:
        amount = float(match.group(1))
        symbol = match.group(2).upper()
        price = await _resolve_market_price(symbol)
        if price is None:
            await message.answer(f"Не удалось найти цену для тикера: {symbol}", reply_markup=_launcher_keyboard())
            return
        total = amount * price
        await message.answer(
            f"{amount:g} {symbol} = {_rub(total)}\n1 {symbol} = {_rub(price)}",
            reply_markup=_launcher_keyboard(),
        )
        return
    await message.answer("Используйте /menu или /start. Формат быстрой проверки цены: 1 btc", reply_markup=_launcher_keyboard())


async def main() -> None:
    if not settings.bot_token:
        raise RuntimeError("Токен Telegram-бота не заполнен")
    await init_pool()
    bot = await _create_working_bot()
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="menu", description="Открыть WebApp"),
            BotCommand(command="site", description="Получить ссылку на сайт"),
            BotCommand(command="balance", description="Показать портфель"),
        ]
    )

    stop_event = asyncio.Event()
    notifier_task = asyncio.create_task(_alerts_notifier_loop(bot, stop_event))
    try:
        await dp.start_polling(bot)
    finally:
        stop_event.set()
        notifier_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await notifier_task
        await bot.session.close()
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
