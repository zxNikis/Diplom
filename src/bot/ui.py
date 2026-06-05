from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class PortfolioStates(StatesGroup):
    waiting_name = State()


class TradeStates(StatesGroup):
    waiting_portfolio_id = State()
    waiting_symbol = State()
    waiting_quantity = State()
    waiting_price = State()


class AlertStates(StatesGroup):
    waiting_symbol = State()
    waiting_condition = State()
    waiting_target_price = State()


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Создать портфель", callback_data="menu:create_portfolio"),
                InlineKeyboardButton(text="Портфели", callback_data="menu:list_portfolios"),
            ],
            [
                InlineKeyboardButton(text="Покупка", callback_data="menu:buy"),
                InlineKeyboardButton(text="Продажа", callback_data="menu:sell"),
            ],
            [
                InlineKeyboardButton(text="Создать уведомление", callback_data="menu:add_alert"),
                InlineKeyboardButton(text="Уведомления", callback_data="menu:list_alerts"),
            ],
            [
                InlineKeyboardButton(text="Обновить цены", callback_data="menu:sync_market"),
                InlineKeyboardButton(text="Помощь", callback_data="menu:help"),
            ],
        ]
    )


def alert_condition_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Цена выше", callback_data="alert_cond:gt"),
                InlineKeyboardButton(text="Цена ниже", callback_data="alert_cond:lt"),
            ]
        ]
    )
