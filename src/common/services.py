from datetime import datetime
from typing import Any, Optional

import asyncpg


async def register_user(pool: asyncpg.Pool, telegram_user_id: int, username: Optional[str]) -> int:
    row = await pool.fetchrow(
        """
        INSERT INTO app_user (telegram_user_id, username)
        VALUES ($1, $2)
        ON CONFLICT (telegram_user_id)
        DO UPDATE SET username = EXCLUDED.username
        RETURNING id
        """,
        telegram_user_id,
        username,
    )
    return row["id"]


async def get_user_by_telegram_id(pool: asyncpg.Pool, telegram_user_id: int) -> Optional[dict[str, Any]]:
    row = await pool.fetchrow(
        """
        SELECT id, telegram_user_id, username, created_at
        FROM app_user
        WHERE telegram_user_id = $1
        """,
        telegram_user_id,
    )
    return dict(row) if row else None


async def create_portfolio(pool: asyncpg.Pool, user_id: int, name: str) -> int:
    row = await pool.fetchrow(
        """
        INSERT INTO portfolio (user_id, name)
        VALUES ($1, $2)
        RETURNING id
        """,
        user_id,
        name,
    )
    return row["id"]


async def get_or_create_default_portfolio(pool: asyncpg.Pool, user_id: int) -> dict[str, Any]:
    existing = await pool.fetchrow(
        """
        SELECT id, user_id, name, total_value_rub, created_at
        FROM portfolio
        WHERE user_id = $1
        ORDER BY created_at ASC
        LIMIT 1
        """,
        user_id,
    )
    if existing:
        return dict(existing)

    created = await pool.fetchrow(
        """
        INSERT INTO portfolio (user_id, name)
        VALUES ($1, $2)
        RETURNING id, user_id, name, total_value_rub, created_at
        """,
        user_id,
        "Основной",
    )
    return dict(created)


async def list_user_portfolios(pool: asyncpg.Pool, user_id: int) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT id, name, total_value_rub, created_at
        FROM portfolio
        WHERE user_id = $1
        ORDER BY created_at DESC
        """,
        user_id,
    )
    return [dict(row) for row in rows]


async def get_asset_by_symbol(pool: asyncpg.Pool, symbol: str) -> Optional[dict[str, Any]]:
    row = await pool.fetchrow(
        """
        SELECT id, symbol, name, coingecko_id
        FROM crypto_asset
        WHERE upper(symbol) = upper($1)
          AND is_active = TRUE
        """,
        symbol,
    )
    return dict(row) if row else None


async def ensure_assets(pool: asyncpg.Pool, assets: list[tuple[str, str, str]]) -> None:
    await pool.executemany(
        """
        INSERT INTO crypto_asset (symbol, name, coingecko_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (symbol)
        DO UPDATE SET
            name = EXCLUDED.name,
            coingecko_id = EXCLUDED.coingecko_id,
            is_active = TRUE
        """,
        assets,
    )


async def add_operation(
    pool: asyncpg.Pool,
    portfolio_id: int,
    asset_id: int,
    op_type: str,
    quantity: float,
    price_rub: float,
) -> int:
    row = await pool.fetchrow(
        """
        INSERT INTO "operation" (portfolio_id, asset_id, op_type, quantity, price_rub)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        portfolio_id,
        asset_id,
        op_type,
        quantity,
        price_rub,
    )
    return row["id"]


async def get_portfolio_balance(pool: asyncpg.Pool, portfolio_id: int) -> dict[str, Any]:
    summary = await pool.fetchrow(
        """
        SELECT p.id, p.name, p.total_value_rub
        FROM portfolio p
        WHERE p.id = $1
        """,
        portfolio_id,
    )
    if not summary:
        raise ValueError("Портфель не найден")

    positions = await pool.fetch(
        """
        SELECT ca.symbol, pe.quantity, pe.avg_buy_price_rub, pe.realized_pnl_rub
        FROM position_entry pe
        JOIN crypto_asset ca ON ca.id = pe.asset_id
        WHERE pe.portfolio_id = $1 AND pe.quantity > 0
        ORDER BY ca.symbol
        """,
        portfolio_id,
    )
    result = dict(summary)
    result["positions"] = [dict(row) for row in positions]
    return result


async def upsert_market_data(
    pool: asyncpg.Pool,
    asset_id: int,
    price_rub: float,
    change_24h: Optional[float],
    source: str = "coingecko",
) -> int:
    row = await pool.fetchrow(
        """
        INSERT INTO market_data (asset_id, price_rub, change_24h, source)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        asset_id,
        price_rub,
        change_24h,
        source,
    )
    return row["id"]


async def list_assets(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT id, symbol, name, coingecko_id
        FROM crypto_asset
        WHERE is_active = TRUE
        ORDER BY symbol
        """
    )
    return [dict(row) for row in rows]


async def get_latest_market_price(pool: asyncpg.Pool, asset_id: int) -> Optional[dict[str, Any]]:
    row = await pool.fetchrow(
        """
        SELECT price_rub, change_24h, captured_at
        FROM market_data
        WHERE asset_id = $1
        ORDER BY captured_at DESC
        LIMIT 1
        """,
        asset_id,
    )
    return dict(row) if row else None


async def create_price_alert(
    pool: asyncpg.Pool,
    user_id: int,
    asset_id: int,
    condition_type: str,
    target_price_rub: float,
    portfolio_id: Optional[int] = None,
) -> int:
    row = await pool.fetchrow(
        """
        INSERT INTO price_alert (user_id, portfolio_id, asset_id, condition_type, target_price_rub)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        user_id,
        portfolio_id,
        asset_id,
        condition_type,
        target_price_rub,
    )
    return row["id"]


async def list_active_alerts(pool: asyncpg.Pool, user_id: int) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT a.id,
               ca.symbol,
               a.condition_type,
               a.target_price_rub,
               a.portfolio_id,
               a.created_at
        FROM price_alert a
        JOIN crypto_asset ca ON ca.id = a.asset_id
        WHERE a.user_id = $1
          AND a.is_active = TRUE
        ORDER BY a.created_at DESC
        """,
        user_id,
    )
    return [dict(row) for row in rows]


async def deactivate_price_alert(pool: asyncpg.Pool, user_id: int, alert_id: int) -> bool:
    row = await pool.fetchrow(
        """
        UPDATE price_alert
        SET is_active = FALSE
        WHERE id = $1
          AND user_id = $2
          AND is_active = TRUE
        RETURNING id
        """,
        alert_id,
        user_id,
    )
    return row is not None


async def get_triggered_alerts(
    pool: asyncpg.Pool,
    since: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    base_query = """
        SELECT a.id,
               a.triggered_at,
               a.target_price_rub,
               a.condition_type,
               au.telegram_user_id,
               ca.symbol,
               md.price_rub AS current_price_rub
        FROM price_alert a
        JOIN app_user au ON au.id = a.user_id
        JOIN crypto_asset ca ON ca.id = a.asset_id
        LEFT JOIN LATERAL (
            SELECT m.price_rub
            FROM market_data m
            WHERE m.asset_id = a.asset_id
            ORDER BY m.captured_at DESC
            LIMIT 1
        ) md ON TRUE
        WHERE a.is_active = FALSE
          AND a.triggered_at IS NOT NULL
    """
    if since:
        rows = await pool.fetch(
            base_query + """
              AND a.triggered_at >= $1
            ORDER BY a.triggered_at DESC
            """,
            since,
        )
    else:
        rows = await pool.fetch(
            base_query + """
            ORDER BY a.triggered_at DESC
            LIMIT 100
            """
        )

    return [dict(row) for row in rows]
