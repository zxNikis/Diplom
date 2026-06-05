import hashlib
import hmac
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

import httpx
from fastapi import APIRouter, HTTPException, Query

from backend.coingecko import CoinGeckoClient
from backend.schemas import (
    CreateOperationRequest,
    CreatePortfolioRequest,
    CreateUserRequest,
    SyncMarketDataRequest,
    WebAppAuthPayload,
    WebAppCreateAlertRequest,
    WebAppDisableAlertRequest,
    WebAppTradeRequest,
)
from common.config import get_settings
from common.db import get_pool
from common.site_auth import verify_site_token
from common.services import (
    add_operation,
    create_portfolio,
    create_price_alert,
    deactivate_price_alert,
    ensure_assets,
    get_asset_by_symbol,
    get_latest_market_price,
    get_portfolio_balance,
    get_or_create_default_portfolio,
    get_user_by_telegram_id,
    list_active_alerts,
    list_assets,
    list_user_portfolios,
    register_user,
    upsert_market_data,
)

router = APIRouter()
settings = get_settings()
logger = logging.getLogger(__name__)
FEATURED_ASSETS = [
    ("BTC", "Bitcoin", "bitcoin"),
    ("ETH", "Ethereum", "ethereum"),
    ("SOL", "Solana", "solana"),
    ("BNB", "BNB", "binancecoin"),
    ("XRP", "XRP", "ripple"),
    ("DOGE", "Dogecoin", "dogecoin"),
    ("ADA", "Cardano", "cardano"),
    ("TON", "Toncoin", "the-open-network"),
    ("TRX", "TRON", "tron"),
    ("LINK", "Chainlink", "chainlink"),
]
FEATURED_MARKET_SYMBOLS = [asset[0] for asset in FEATURED_ASSETS]


def _verify_telegram_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(status_code=401, detail="Нужны данные авторизации Telegram")
    if not settings.bot_token:
        raise HTTPException(status_code=500, detail="Токен Telegram-бота не настроен")

    items = dict(parse_qsl(init_data, keep_blank_values=True))
    incoming_hash = items.pop("hash", None)
    if not incoming_hash:
        raise HTTPException(status_code=401, detail="Некорректные данные Telegram")
    data_check_string = "\n".join(f"{k}={items[k]}" for k in sorted(items))
    secret_key = hashlib.sha256(settings.bot_token.encode("utf-8")).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, incoming_hash):
        raise HTTPException(status_code=401, detail="Подпись Telegram не совпадает")

    raw_user = items.get("user")
    if not raw_user:
        raise HTTPException(status_code=401, detail="В данных Telegram нет пользователя")
    try:
        user = json.loads(raw_user)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=401, detail="Некорректный пользователь Telegram") from exc
    return user


async def _sync_market_data(pool, symbols: list[str] | None = None) -> int:
    await _ensure_featured_assets(pool)
    assets = await list_assets(pool)
    if symbols:
        selected = {s.upper() for s in symbols}
        assets = [asset for asset in assets if asset["symbol"].upper() in selected]

    coingecko_ids = [asset["coingecko_id"] for asset in assets]
    client = CoinGeckoClient()
    try:
        prices = await client.get_prices(coingecko_ids)
    finally:
        await client.close()

    inserted = 0
    for asset in assets:
        quote = prices.get(asset["coingecko_id"])
        if not quote or "rub" not in quote:
            continue
        inserted += 1
        await upsert_market_data(
            pool=pool,
            asset_id=asset["id"],
            price_rub=float(quote["rub"]),
            change_24h=float(quote.get("rub_24h_change")) if quote.get("rub_24h_change") is not None else None,
        )
    return inserted


def _site_auth_secret() -> str:
    return settings.site_auth_secret or settings.bot_token


async def _resolve_webapp_user(pool, init_data: str, site_token: str = "") -> dict:
    if site_token:
        if not _site_auth_secret():
            raise HTTPException(status_code=500, detail="Секрет авторизации сайта не настроен")
        site_user = verify_site_token(site_token, secret=_site_auth_secret())
        telegram_user_id = int(site_user["telegram_user_id"])
        username = site_user.get("username")
        user_id = await register_user(pool, telegram_user_id, username)
        user = await get_user_by_telegram_id(pool, telegram_user_id)
        user["id"] = user_id
        return user

    if settings.webapp_dev_mode and not init_data:
        user_id = await register_user(pool, settings.dev_telegram_user_id, "dev_local")
        user = await get_user_by_telegram_id(pool, settings.dev_telegram_user_id)
        user["id"] = user_id
        return user

    tg_user = _verify_telegram_init_data(init_data)
    telegram_user_id = int(tg_user["id"])
    username = tg_user.get("username")
    user_id = await register_user(pool, telegram_user_id, username)
    user = await get_user_by_telegram_id(pool, telegram_user_id)
    user["id"] = user_id
    return user


def _to_float(value):
    return float(value) if value is not None else None


async def _ensure_featured_assets(pool) -> None:
    await ensure_assets(pool, FEATURED_ASSETS)


async def _get_latest_market_rows(pool, assets: list[dict]) -> dict[int, dict]:
    asset_ids = [int(asset["id"]) for asset in assets]
    if not asset_ids:
        return {}
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (asset_id)
               asset_id,
               price_rub,
               change_24h,
               captured_at
        FROM market_data
        WHERE asset_id = ANY($1::bigint[])
        ORDER BY asset_id, captured_at DESC
        """,
        asset_ids,
    )
    return {int(row["asset_id"]): dict(row) for row in rows}


def _market_items_from_latest_rows(assets: list[dict], latest_rows: dict[int, dict]) -> list[dict]:
    items = []
    for index, asset in enumerate(assets, start=1):
        latest = latest_rows.get(int(asset["id"]))
        if not latest:
            continue
        items.append(
            {
                "id": asset["coingecko_id"],
                "symbol": asset["symbol"],
                "name": asset["name"],
                "image": None,
                "current_price_rub": _to_float(latest.get("price_rub")),
                "price_change_percentage_24h": _to_float(latest.get("change_24h")),
                "high_24h_rub": None,
                "low_24h_rub": None,
                "market_cap_rank": index,
                "last_updated": latest["captured_at"].isoformat() if latest.get("captured_at") else None,
            }
        )
    return items


async def _get_recent_market_points(pool, asset_id: int, limit: int = 169) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT price_rub, captured_at
        FROM market_data
        WHERE asset_id = $1
        ORDER BY captured_at DESC
        LIMIT $2
        """,
        asset_id,
        limit,
    )
    return [
        {"captured_at": row["captured_at"].isoformat(), "price_rub": _to_float(row["price_rub"])}
        for row in reversed(rows)
    ]


def _build_local_chart_points(latest: dict | None, points_count: int = 169) -> list[dict]:
    if not latest or latest.get("price_rub") is None:
        return []

    last_price = float(latest["price_rub"])
    change_24h = float(latest["change_24h"] or 0)
    end_time = latest.get("captured_at") or datetime.now(timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    first_price = last_price / (1 + change_24h / 100) if change_24h > -99 else last_price
    if abs(first_price - last_price) < last_price * 0.003:
        first_price = last_price * 0.985

    points = []
    start_time = end_time - timedelta(days=7)
    for index in range(points_count):
        progress = index / (points_count - 1)
        trend_price = first_price + (last_price - first_price) * progress
        wave = math.sin(index * 0.34) * last_price * 0.004
        price = last_price if index == points_count - 1 else max(0.01, trend_price + wave)
        captured_at = start_time + timedelta(seconds=7 * 24 * 60 * 60 * progress)
        points.append({"captured_at": captured_at.isoformat(), "price_rub": price})
    return points


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/users/register")
async def register(payload: CreateUserRequest) -> dict[str, int]:
    pool = await get_pool()
    user_id = await register_user(pool, payload.telegram_user_id, payload.username)
    return {"user_id": user_id}


@router.post("/portfolios")
async def create_portfolio_endpoint(payload: CreatePortfolioRequest) -> dict[str, int]:
    pool = await get_pool()
    portfolio_id = await create_portfolio(pool, payload.user_id, payload.name)
    return {"portfolio_id": portfolio_id}


@router.get("/users/{user_id}/portfolios")
async def list_portfolios_endpoint(user_id: int) -> dict:
    pool = await get_pool()
    portfolios = await list_user_portfolios(pool, user_id)
    return {"items": portfolios}


@router.post("/operations")
async def add_operation_endpoint(payload: CreateOperationRequest) -> dict[str, int]:
    pool = await get_pool()
    asset = await get_asset_by_symbol(pool, payload.symbol)
    if not asset:
        raise HTTPException(status_code=404, detail="Актив с таким тикером не найден")

    try:
        operation_id = await add_operation(
            pool=pool,
            portfolio_id=payload.portfolio_id,
            asset_id=asset["id"],
            op_type=payload.op_type,
            quantity=payload.quantity,
            price_rub=payload.price_rub,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"operation_id": operation_id}


@router.get("/portfolios/{portfolio_id}/balance")
async def portfolio_balance_endpoint(portfolio_id: int) -> dict:
    pool = await get_pool()
    try:
        return await get_portfolio_balance(pool, portfolio_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/market/sync")
async def sync_market_data_endpoint(payload: SyncMarketDataRequest) -> dict:
    pool = await get_pool()
    inserted = await _sync_market_data(pool, payload.symbols)
    return {"inserted_market_rows": inserted}


@router.post("/app/auth")
async def app_auth(payload: WebAppAuthPayload) -> dict:
    init_data = payload.init_data
    pool = await get_pool()
    await _ensure_featured_assets(pool)
    user = await _resolve_webapp_user(pool, init_data, payload.site_token)
    default_portfolio = await get_or_create_default_portfolio(pool, user["id"])
    return {"user": user, "default_portfolio": default_portfolio}


@router.get("/app/dashboard")
async def app_dashboard(init_data: str = Query(""), site_token: str = Query("")) -> dict:
    pool = await get_pool()
    await _ensure_featured_assets(pool)
    user = await _resolve_webapp_user(pool, init_data, site_token)
    portfolio = await get_or_create_default_portfolio(pool, user["id"])
    balance = await get_portfolio_balance(pool, int(portfolio["id"]))
    alerts = await list_active_alerts(pool, user["id"])
    return {"portfolio": portfolio, "balance": balance, "alerts_count": len(alerts)}


@router.get("/app/market")
async def app_market(init_data: str = Query(""), site_token: str = Query("")) -> dict:
    pool = await get_pool()
    await _ensure_featured_assets(pool)
    await _resolve_webapp_user(pool, init_data, site_token)

    assets = await list_assets(pool)
    assets_by_symbol = {
        asset["symbol"].upper(): asset
        for asset in assets
        if asset["symbol"].upper() in FEATURED_MARKET_SYMBOLS
    }
    ordered_assets = [assets_by_symbol[symbol] for symbol in FEATURED_MARKET_SYMBOLS if symbol in assets_by_symbol]
    if not ordered_assets:
        return {"items": []}

    client = CoinGeckoClient()
    try:
        market_rows = await client.get_markets([asset["coingecko_id"] for asset in ordered_assets])
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        logger.warning("CoinGecko market request failed, using local market_data fallback: %s", exc)
        latest_rows = await _get_latest_market_rows(pool, ordered_assets)
        fallback_items = _market_items_from_latest_rows(ordered_assets, latest_rows)
        if fallback_items:
            return {"items": fallback_items}
        raise HTTPException(status_code=503, detail="Карточки рынка временно недоступны") from exc
    finally:
        await client.close()

    rows_by_id = {row.get("id"): row for row in market_rows if row.get("id")}
    items = []
    for asset in ordered_assets:
        row = rows_by_id.get(asset["coingecko_id"])
        if not row:
            continue
        items.append(
            {
                "id": row.get("id", asset["coingecko_id"]),
                "symbol": asset["symbol"],
                "name": row.get("name") or asset["name"],
                "image": row.get("image"),
                "current_price_rub": _to_float(row.get("current_price")),
                "price_change_percentage_24h": _to_float(row.get("price_change_percentage_24h")),
                "high_24h_rub": _to_float(row.get("high_24h")),
                "low_24h_rub": _to_float(row.get("low_24h")),
                "market_cap_rank": row.get("market_cap_rank"),
                "last_updated": row.get("last_updated"),
            }
        )
    return {"items": items}


@router.get("/app/market/history")
async def app_market_history(
    symbol: str = Query(...),
    init_data: str = Query(""),
    site_token: str = Query(""),
) -> dict:
    pool = await get_pool()
    await _ensure_featured_assets(pool)
    await _resolve_webapp_user(pool, init_data, site_token)
    asset = await get_asset_by_symbol(pool, symbol)
    if not asset:
        raise HTTPException(status_code=404, detail="Актив не найден")

    client = CoinGeckoClient()
    try:
        raw_points = await client.get_market_chart(asset["coingecko_id"], days=7)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        logger.warning(
            "CoinGecko history request failed for %s, using local market_data fallback: %s",
            asset["symbol"],
            exc,
        )
        local_points = await _get_recent_market_points(pool, int(asset["id"]))
        if len(local_points) >= 2:
            return {"symbol": asset["symbol"], "points": local_points}
        latest_rows = await _get_latest_market_rows(pool, [asset])
        local_points = _build_local_chart_points(latest_rows.get(int(asset["id"])))
        if local_points:
            return {"symbol": asset["symbol"], "points": local_points}
        raise HTTPException(status_code=503, detail="История цены временно недоступна") from exc
    finally:
        await client.close()

    points = []
    for point in raw_points:
        timestamp_ms = point.get("timestamp_ms")
        price_rub = point.get("price_rub")
        if timestamp_ms is None or price_rub is None:
            continue
        points.append(
            {
                "captured_at": datetime.fromtimestamp(float(timestamp_ms) / 1000, tz=timezone.utc).isoformat(),
                "price_rub": _to_float(price_rub),
            }
        )
    return {"symbol": asset["symbol"], "points": points}


@router.get("/app/prices")
async def app_prices(symbol: str = Query(...), init_data: str = Query(""), site_token: str = Query("")) -> dict:
    pool = await get_pool()
    await _ensure_featured_assets(pool)
    await _resolve_webapp_user(pool, init_data, site_token)
    asset = await get_asset_by_symbol(pool, symbol)
    if not asset:
        raise HTTPException(status_code=404, detail="Актив не найден")
    latest = await get_latest_market_price(pool, asset["id"])
    if latest is None:
        await _sync_market_data(pool, [asset["symbol"]])
        latest = await get_latest_market_price(pool, asset["id"])
    if latest is None:
        raise HTTPException(status_code=503, detail="Цена временно недоступна")
    return {
        "symbol": asset["symbol"],
        "price_rub": float(latest["price_rub"]),
        "change_24h": float(latest["change_24h"]) if latest["change_24h"] is not None else None,
        "captured_at": latest["captured_at"],
    }


@router.post("/app/trade")
async def app_trade(payload: WebAppTradeRequest) -> dict:
    pool = await get_pool()
    await _ensure_featured_assets(pool)
    user = await _resolve_webapp_user(pool, payload.init_data, payload.site_token)
    portfolio = await get_or_create_default_portfolio(pool, user["id"])
    asset = await get_asset_by_symbol(pool, payload.symbol)
    if not asset:
        raise HTTPException(status_code=404, detail="Актив не найден")

    if payload.price_mode == "manual":
        if payload.price_rub is None:
            raise HTTPException(status_code=400, detail="Для ручного режима нужно указать цену в рублях")
        price_to_use = payload.price_rub
    else:
        latest = await get_latest_market_price(pool, asset["id"])
        if latest is None:
            await _sync_market_data(pool, [asset["symbol"]])
            latest = await get_latest_market_price(pool, asset["id"])
        if latest is None:
            raise HTTPException(status_code=503, detail="Рыночная цена временно недоступна")
        price_to_use = float(latest["price_rub"])

    try:
        operation_id = await add_operation(
            pool,
            int(portfolio["id"]),
            asset["id"],
            payload.op_type,
            payload.quantity,
            price_to_use,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"operation_id": operation_id, "portfolio_id": portfolio["id"], "price_used_rub": price_to_use}


@router.get("/app/alerts")
async def app_list_alerts(init_data: str = Query(""), site_token: str = Query("")) -> dict:
    pool = await get_pool()
    await _ensure_featured_assets(pool)
    user = await _resolve_webapp_user(pool, init_data, site_token)
    items = await list_active_alerts(pool, user["id"])
    return {"items": items}


@router.post("/app/alerts")
async def app_create_alert(payload: WebAppCreateAlertRequest) -> dict:
    pool = await get_pool()
    await _ensure_featured_assets(pool)
    user = await _resolve_webapp_user(pool, payload.init_data, payload.site_token)
    portfolio = await get_or_create_default_portfolio(pool, user["id"])
    asset = await get_asset_by_symbol(pool, payload.symbol)
    if not asset:
        raise HTTPException(status_code=404, detail="Актив не найден")
    alert_id = await create_price_alert(
        pool=pool,
        user_id=user["id"],
        asset_id=asset["id"],
        condition_type=payload.condition_type,
        target_price_rub=payload.target_price_rub,
        portfolio_id=int(portfolio["id"]),
    )
    return {"alert_id": alert_id}


@router.post("/app/alerts/{alert_id}/disable")
async def app_disable_alert(alert_id: int, payload: WebAppDisableAlertRequest) -> dict:
    pool = await get_pool()
    user = await _resolve_webapp_user(pool, payload.init_data, payload.site_token)
    changed = await deactivate_price_alert(pool, user["id"], alert_id)
    return {"disabled": changed}
