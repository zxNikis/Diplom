import ast
import asyncio
import contextlib
import sys
import unittest
from pathlib import Path

from fastapi import HTTPException


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from common.site_auth import create_site_token, verify_site_token  # noqa: E402
import bot.main as bot_main  # noqa: E402


class StaticContractTests(unittest.TestCase):
    def test_python_sources_parse_without_writing_pyc(self):
        for path in SRC_ROOT.rglob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_site_token_roundtrip_and_signature_check(self):
        token = create_site_token(
            telegram_user_id=12345,
            username="demo_user",
            secret="test-secret",
            ttl_days=1,
        )

        payload = verify_site_token(token, secret="test-secret")
        self.assertEqual(payload["telegram_user_id"], 12345)
        self.assertEqual(payload["username"], "demo_user")

        with self.assertRaises(HTTPException) as exc_info:
            verify_site_token(token, secret="wrong-secret")
        self.assertEqual(exc_info.exception.status_code, 401)

    def test_commission_documentation_matches_schema(self):
        schema = (PROJECT_ROOT / "db" / "001_init_schema.sql").read_text(encoding="utf-8")
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("DEFAULT 0.007", schema)
        self.assertIn("0,7%", readme)
        self.assertNotIn("18%", readme)

    def test_start_handler_resolves_message_identity_before_site_url_use(self):
        source = (SRC_ROOT / "bot" / "main.py").read_text(encoding="utf-8")
        start_index = source.index("async def cmd_start")
        identity_index = source.index("telegram_user_id, username = _message_identity(message)", start_index)
        site_keyboard_index = source.index("_site_link_keyboard(telegram_user_id, username)", start_index)

        self.assertLess(identity_index, site_keyboard_index)


class BotNotifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_alert_notifier_sends_triggered_alert_message(self):
        sent_messages = []
        send_event = asyncio.Event()

        async def fake_sync_market_data_once():
            return 1

        async def fake_init_pool():
            return object()

        async def fake_get_triggered_alerts(pool, since=None):
            return [
                {
                    "id": 9001,
                    "telegram_user_id": 12345,
                    "symbol": "BTC",
                    "condition_type": "gt",
                    "target_price_rub": 1,
                    "current_price_rub": 2,
                }
            ]

        class FakeBot:
            async def send_message(self, chat_id, text):
                sent_messages.append((chat_id, text))
                send_event.set()

        original_sync = bot_main._sync_market_data_once
        original_init_pool = bot_main.init_pool
        original_get_triggered_alerts = bot_main.get_triggered_alerts
        bot_main._sync_market_data_once = fake_sync_market_data_once
        bot_main.init_pool = fake_init_pool
        bot_main.get_triggered_alerts = fake_get_triggered_alerts
        stop_event = asyncio.Event()
        task = asyncio.create_task(bot_main._alerts_notifier_loop(FakeBot(), stop_event))
        try:
            await asyncio.wait_for(send_event.wait(), timeout=2)
        finally:
            stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            bot_main._sync_market_data_once = original_sync
            bot_main.init_pool = original_init_pool
            bot_main.get_triggered_alerts = original_get_triggered_alerts

        self.assertEqual(sent_messages[0][0], 12345)
        self.assertIn("Сработало ценовое уведомление", sent_messages[0][1])
        self.assertIn("BTC", sent_messages[0][1])
        self.assertIn("Текущая цена", sent_messages[0][1])


if __name__ == "__main__":
    unittest.main()
