BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS app_user (
    id BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL UNIQUE,
    username TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crypto_asset (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    coingecko_id TEXT NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO crypto_asset (symbol, name, coingecko_id)
VALUES
    ('BTC', 'Bitcoin', 'bitcoin'),
    ('ETH', 'Ethereum', 'ethereum'),
    ('SOL', 'Solana', 'solana'),
    ('BNB', 'BNB', 'binancecoin'),
    ('XRP', 'XRP', 'ripple'),
    ('DOGE', 'Dogecoin', 'dogecoin'),
    ('ADA', 'Cardano', 'cardano'),
    ('TON', 'Toncoin', 'the-open-network'),
    ('TRX', 'TRON', 'tron'),
    ('LINK', 'Chainlink', 'chainlink')
ON CONFLICT (symbol) DO NOTHING;

CREATE TABLE IF NOT EXISTS portfolio (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    total_value_rub NUMERIC(24, 8) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS position_entry (
    id BIGSERIAL PRIMARY KEY,
    portfolio_id BIGINT NOT NULL REFERENCES portfolio(id) ON DELETE CASCADE,
    asset_id BIGINT NOT NULL REFERENCES crypto_asset(id) ON DELETE RESTRICT,
    quantity NUMERIC(24, 12) NOT NULL DEFAULT 0,
    avg_buy_price_rub NUMERIC(24, 8) NOT NULL DEFAULT 0,
    realized_pnl_rub NUMERIC(24, 8) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (portfolio_id, asset_id),
    CHECK (quantity >= 0),
    CHECK (avg_buy_price_rub >= 0)
);

CREATE TABLE IF NOT EXISTS market_data (
    id BIGSERIAL PRIMARY KEY,
    asset_id BIGINT NOT NULL REFERENCES crypto_asset(id) ON DELETE CASCADE,
    price_rub NUMERIC(24, 8) NOT NULL,
    change_24h NUMERIC(10, 4),
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source TEXT NOT NULL DEFAULT 'coingecko',
    CHECK (price_rub > 0)
);

CREATE INDEX IF NOT EXISTS idx_market_data_asset_captured_at
    ON market_data (asset_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS "operation" (
    id BIGSERIAL PRIMARY KEY,
    portfolio_id BIGINT NOT NULL REFERENCES portfolio(id) ON DELETE CASCADE,
    asset_id BIGINT NOT NULL REFERENCES crypto_asset(id) ON DELETE RESTRICT,
    op_type TEXT NOT NULL CHECK (op_type IN ('buy', 'sell')),
    quantity NUMERIC(24, 12) NOT NULL CHECK (quantity > 0),
    price_rub NUMERIC(24, 8) NOT NULL CHECK (price_rub > 0),
    deal_amount_rub NUMERIC(24, 8) GENERATED ALWAYS AS (quantity * price_rub) STORED,
    commission_rate NUMERIC(5, 4) NOT NULL DEFAULT 0.007 CHECK (commission_rate = 0.007),
    fee_amount_rub NUMERIC(24, 8) GENERATED ALWAYS AS ((quantity * price_rub) * commission_rate) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_operation_portfolio_asset
    ON "operation" (portfolio_id, asset_id, created_at DESC);

CREATE TABLE IF NOT EXISTS price_alert (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    portfolio_id BIGINT REFERENCES portfolio(id) ON DELETE CASCADE,
    asset_id BIGINT NOT NULL REFERENCES crypto_asset(id) ON DELETE CASCADE,
    condition_type TEXT NOT NULL CHECK (condition_type IN ('gt', 'lt')),
    target_price_rub NUMERIC(24, 8) NOT NULL CHECK (target_price_rub > 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    triggered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_price_alert_active_asset
    ON price_alert (asset_id)
    WHERE is_active = TRUE;

CREATE OR REPLACE FUNCTION fn_recalculate_portfolio_total(p_portfolio_id BIGINT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE portfolio p
    SET total_value_rub = COALESCE((
        SELECT SUM(pe.quantity * md.price_rub)
        FROM position_entry pe
        JOIN LATERAL (
            SELECT m.price_rub
            FROM market_data m
            WHERE m.asset_id = pe.asset_id
            ORDER BY m.captured_at DESC
            LIMIT 1
        ) md ON TRUE
        WHERE pe.portfolio_id = p.id
          AND pe.quantity > 0
    ), 0)
    WHERE p.id = p_portfolio_id;
END;
$$;

CREATE OR REPLACE FUNCTION fn_check_price_alerts(p_asset_id BIGINT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_latest_price NUMERIC(24, 8);
BEGIN
    SELECT m.price_rub
    INTO v_latest_price
    FROM market_data m
    WHERE m.asset_id = p_asset_id
    ORDER BY m.captured_at DESC
    LIMIT 1;

    IF v_latest_price IS NULL THEN
        RETURN;
    END IF;

    UPDATE price_alert a
    SET is_active = FALSE,
        triggered_at = NOW()
    WHERE a.asset_id = p_asset_id
      AND a.is_active = TRUE
      AND (
          (a.condition_type = 'gt' AND v_latest_price > a.target_price_rub)
          OR
          (a.condition_type = 'lt' AND v_latest_price < a.target_price_rub)
      );
END;
$$;

CREATE OR REPLACE FUNCTION fn_apply_operation_to_position()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_position position_entry%ROWTYPE;
    v_existing_cost NUMERIC(24, 8);
    v_new_avg NUMERIC(24, 8);
    v_realized_delta NUMERIC(24, 8);
BEGIN
    SELECT *
    INTO v_position
    FROM position_entry
    WHERE portfolio_id = NEW.portfolio_id
      AND asset_id = NEW.asset_id
    FOR UPDATE;

    IF NOT FOUND THEN
        INSERT INTO position_entry (
            portfolio_id,
            asset_id,
            quantity,
            avg_buy_price_rub,
            realized_pnl_rub
        )
        VALUES (
            NEW.portfolio_id,
            NEW.asset_id,
            0,
            0,
            0
        )
        RETURNING *
        INTO v_position;
    END IF;

    IF NEW.op_type = 'buy' THEN
        v_existing_cost := v_position.quantity * v_position.avg_buy_price_rub;
        v_new_avg := (v_existing_cost + NEW.deal_amount_rub + NEW.fee_amount_rub)
                     / (v_position.quantity + NEW.quantity);

        UPDATE position_entry
        SET quantity = v_position.quantity + NEW.quantity,
            avg_buy_price_rub = v_new_avg,
            updated_at = NOW()
        WHERE id = v_position.id;
    ELSE
        IF v_position.quantity < NEW.quantity THEN
            RAISE EXCEPTION
                'Количество продажи (%) превышает текущий остаток (%) для portfolio_id=% asset_id=%',
                NEW.quantity, v_position.quantity, NEW.portfolio_id, NEW.asset_id;
        END IF;

        v_realized_delta := (NEW.deal_amount_rub - NEW.fee_amount_rub)
                            - (NEW.quantity * v_position.avg_buy_price_rub);

        UPDATE position_entry
        SET quantity = v_position.quantity - NEW.quantity,
            avg_buy_price_rub = CASE
                WHEN (v_position.quantity - NEW.quantity) = 0 THEN 0
                ELSE v_position.avg_buy_price_rub
            END,
            realized_pnl_rub = v_position.realized_pnl_rub + v_realized_delta,
            updated_at = NOW()
        WHERE id = v_position.id;
    END IF;

    PERFORM fn_recalculate_portfolio_total(NEW.portfolio_id);
    PERFORM fn_check_price_alerts(NEW.asset_id);

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION fn_handle_market_data_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_portfolio_id BIGINT;
BEGIN
    FOR v_portfolio_id IN
        SELECT DISTINCT pe.portfolio_id
        FROM position_entry pe
        WHERE pe.asset_id = NEW.asset_id
          AND pe.quantity > 0
    LOOP
        PERFORM fn_recalculate_portfolio_total(v_portfolio_id);
    END LOOP;

    PERFORM fn_check_price_alerts(NEW.asset_id);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_operation_after_insert ON "operation";
CREATE TRIGGER trg_operation_after_insert
AFTER INSERT ON "operation"
FOR EACH ROW
EXECUTE FUNCTION fn_apply_operation_to_position();

DROP TRIGGER IF EXISTS trg_market_data_after_insert ON market_data;
CREATE TRIGGER trg_market_data_after_insert
AFTER INSERT ON market_data
FOR EACH ROW
EXECUTE FUNCTION fn_handle_market_data_insert();

COMMIT;
