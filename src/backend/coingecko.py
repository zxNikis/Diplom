import logging
from typing import Any

import httpx

from common.config import get_settings


class CoinGeckoClient:
    def __init__(self) -> None:
        self._settings = get_settings()

    async def close(self) -> None:
        return None

    async def _request_json(self, path: str, params: dict[str, Any]) -> Any:
        last_error: httpx.RequestError | None = None
        proxy_urls = self._settings.proxy_urls or [None]
        for proxy_url in proxy_urls:
            try:
                async with httpx.AsyncClient(
                    base_url=self._settings.coingecko_base_url,
                    timeout=self._settings.coingecko_timeout_seconds,
                    proxy=proxy_url,
                ) as client:
                    response = await client.get(path, params=params)
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError:
                raise
            except httpx.RequestError as exc:
                last_error = exc
                proxy_label = proxy_url or "без прокси"
                logging.warning("CoinGecko недоступен через %s: %s", proxy_label, exc)

        raise httpx.ConnectError("Не удалось подключиться к CoinGecko ни через один прокси") from last_error

    async def get_prices(self, ids: list[str]) -> dict[str, Any]:
        if not ids:
            return {}

        return await self._request_json(
            "/simple/price",
            params={
                "ids": ",".join(ids),
                "vs_currencies": "rub",
                "include_24hr_change": "true",
            },
        )

    async def get_markets(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []

        response = await self._request_json(
            "/coins/markets",
            params={
                "vs_currency": "rub",
                "ids": ",".join(ids),
                "order": "market_cap_desc",
                "sparkline": "false",
                "price_change_percentage": "24h",
                "locale": "ru",
            },
        )
        return response if isinstance(response, list) else []

    async def get_market_chart(self, coin_id: str, days: int = 7) -> list[dict[str, Any]]:
        if not coin_id:
            return []

        response = await self._request_json(
            f"/coins/{coin_id}/market_chart",
            params={
                "vs_currency": "rub",
                "days": str(days),
            },
        )
        prices = response.get("prices", []) if isinstance(response, dict) else []
        points = []
        for item in prices:
            if not isinstance(item, list) or len(item) < 2:
                continue
            points.append({"timestamp_ms": item[0], "price_rub": item[1]})
        return points
