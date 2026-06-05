from typing import Optional

from pydantic import BaseModel, Field


class CreateUserRequest(BaseModel):
    telegram_user_id: int
    username: Optional[str] = None


class CreatePortfolioRequest(BaseModel):
    user_id: int
    name: str = Field(min_length=1, max_length=120)


class CreateOperationRequest(BaseModel):
    portfolio_id: int
    symbol: str = Field(min_length=2, max_length=15)
    op_type: str = Field(pattern="^(buy|sell)$")
    quantity: float = Field(gt=0)
    price_rub: float = Field(gt=0)


class SyncMarketDataRequest(BaseModel):
    symbols: Optional[list[str]] = None


class WebAppAuthPayload(BaseModel):
    init_data: str = ""
    site_token: str = ""


class WebAppTradeRequest(BaseModel):
    init_data: str = ""
    site_token: str = ""
    symbol: str = Field(min_length=2, max_length=15)
    op_type: str = Field(pattern="^(buy|sell)$")
    quantity: float = Field(gt=0)
    price_mode: str = Field(default="market", pattern="^(market|manual)$")
    price_rub: Optional[float] = Field(default=None, gt=0)


class WebAppPriceQuery(BaseModel):
    symbol: str = Field(min_length=2, max_length=15)


class WebAppCreateAlertRequest(BaseModel):
    init_data: str = ""
    site_token: str = ""
    symbol: str = Field(min_length=2, max_length=15)
    condition_type: str = Field(pattern="^(gt|lt)$")
    target_price_rub: float = Field(gt=0)


class WebAppDisableAlertRequest(BaseModel):
    init_data: str = ""
    site_token: str = ""
