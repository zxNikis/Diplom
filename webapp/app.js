const tg = window.Telegram?.WebApp;
const SITE_TOKEN_STORAGE_KEY = "cryptoPortfolioSiteToken";
if (tg) {
  tg.ready();
  tg.expand();
  tg.setHeaderColor("#08111f");
  tg.setBackgroundColor("#08111f");
}

const VIEW_TITLES = {
  home: "Главная",
  operation: "Операция",
  market: "Рынок",
  alerts: "Алерты",
};

const SUPPORTED_ASSETS = [
  { symbol: "BTC", name: "Bitcoin" },
  { symbol: "ETH", name: "Ethereum" },
  { symbol: "SOL", name: "Solana" },
  { symbol: "BNB", name: "BNB" },
  { symbol: "XRP", name: "XRP" },
  { symbol: "DOGE", name: "Dogecoin" },
  { symbol: "ADA", name: "Cardano" },
  { symbol: "TON", name: "Toncoin" },
  { symbol: "TRX", name: "TRON" },
  { symbol: "LINK", name: "Chainlink" },
];

const SYMBOLS = SUPPORTED_ASSETS.map((asset) => asset.symbol);
const SELL_PERCENT_SHORTCUTS = [25, 50, 75, 100];

function isSiteMode() {
  return window.location.pathname.startsWith("/site");
}

function getInitialSiteToken() {
  if (!isSiteMode()) {
    return "";
  }
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token") || localStorage.getItem(SITE_TOKEN_STORAGE_KEY) || "";
  if (params.has("token")) {
    if (token) {
      localStorage.setItem(SITE_TOKEN_STORAGE_KEY, token);
    }
    params.delete("token");
    const nextSearch = params.toString();
    const nextUrl = `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ""}${window.location.hash}`;
    window.history.replaceState({}, "", nextUrl);
  }
  return token;
}

const moneyFormatter = new Intl.NumberFormat("ru-RU", {
  style: "currency",
  currency: "RUB",
  maximumFractionDigits: 2,
});

const compactMoneyFormatter = new Intl.NumberFormat("ru-RU", {
  style: "currency",
  currency: "RUB",
  notation: "compact",
  maximumFractionDigits: 2,
});

const numberFormatter = new Intl.NumberFormat("ru-RU", {
  maximumFractionDigits: 8,
});

const percentFormatter = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const dateFormatter = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

const state = {
  initData: tg?.initData || "",
  siteMode: isSiteMode(),
  siteToken: getInitialSiteToken(),
  activeView: "home",
  session: null,
  dashboard: null,
  marketItems: [],
  marketHistory: {},
  historyLoading: {},
  alerts: [],
  selectedSymbol: "BTC",
  selectedChartSymbol: "BTC",
  opType: "buy",
  priceMode: "market",
  loading: {
    bootstrap: false,
    dashboard: false,
    market: false,
    alerts: false,
    trade: false,
    priceSync: false,
    alertAction: false,
  },
  marketQuery: "",
  tradeQuantity: "",
  tradeManualPrice: "",
  alertCondition: "gt",
  alertTarget: "",
  tradeResult: null,
  fatalError: "",
  marketError: "",
  historyError: "",
  allowDevAuth: new URLSearchParams(window.location.search).get("dev") === "1",
};

const appRoot = document.getElementById("app");
const toastHost = document.getElementById("toastHost");

window.handleCoinImageError = function handleCoinImageError(img, symbol) {
  const fallback = document.createElement("span");
  fallback.textContent = symbol.slice(0, 2);
  const wrapper = img.parentElement;
  wrapper.classList.add("asset-logo-fallback");
  wrapper.replaceChildren(fallback);
};

function isLocalDebug() {
  return ["localhost", "127.0.0.1"].includes(window.location.hostname);
}

function reqInitData() {
  if (!state.initData && !isLocalDebug() && !state.allowDevAuth) {
    throw new Error("Откройте мини-приложение через Telegram: /start -> Открыть приложение.");
  }
  return state.initData;
}

function reqAuthParams() {
  if (state.siteMode) {
    if (!state.siteToken) {
      throw new Error("Откройте сайт по персональной ссылке из Telegram-бота: команда /site.");
    }
    return { site_token: state.siteToken };
  }
  return { init_data: reqInitData() };
}

function reqAuthPayload() {
  if (state.siteMode) {
    if (!state.siteToken) {
      throw new Error("Откройте сайт по персональной ссылке из Telegram-бота: команда /site.");
    }
    return { site_token: state.siteToken };
  }
  return { init_data: reqInitData() };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatMoney(value, compact = false) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }
  return (compact ? compactMoneyFormatter : moneyFormatter).format(Number(value));
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }
  return numberFormatter.format(Number(value));
}

function normalizeDecimalInput(value) {
  return String(value ?? "")
    .trim()
    .replace(",", ".")
    .replace(/\s+/g, "");
}

function parseDecimalInput(value) {
  const normalized = normalizeDecimalInput(value);
  if (!normalized || normalized === "." || normalized === "-") {
    return null;
  }
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatInputDecimal(value, maxFractionDigits = 12) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "";
  }
  const fixed = Number(value).toFixed(maxFractionDigits);
  return fixed.replace(/\.?0+$/, "");
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }
  const numeric = Number(value);
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${percentFormatter.format(numeric)}%`;
}

function formatDate(value) {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "—";
  }
  return dateFormatter.format(parsed);
}

function formatChartPrice(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }
  const numeric = Number(value);
  if (Math.abs(numeric) >= 1_000_000) {
    return `${(numeric / 1_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} млн`;
  }
  if (Math.abs(numeric) >= 1_000) {
    return `${(numeric / 1_000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} тыс.`;
  }
  return numeric.toLocaleString("ru-RU", { maximumFractionDigits: 0 });
}

function formatChartTime(value) {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
  }).format(parsed);
}

async function readErrorMessage(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const payload = await response.json();
    if (typeof payload?.detail === "string") {
      return payload.detail;
    }
    return "Сервер вернул ошибку";
  }
  const text = (await response.text()).trim();
  return text || `Ошибка запроса (${response.status})`;
}

async function apiGet(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return response.json();
}

async function apiPost(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return response.json();
}

function setLoading(key, value) {
  state.loading[key] = value;
  render();
}

function showToast(type, message) {
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  const text = document.createElement("div");
  text.className = "toast-text";
  text.textContent = message;
  toast.appendChild(text);
  toastHost.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("toast-visible"));
  window.setTimeout(() => {
    toast.classList.remove("toast-visible");
    toast.addEventListener("transitionend", () => toast.remove(), { once: true });
  }, 3200);
}

function buildQuery(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    search.set(key, value ?? "");
  });
  return search.toString();
}

function getSelectedMarketItem() {
  return state.marketItems.find((item) => item.symbol === state.selectedSymbol) || null;
}

function getMarketItemBySymbol(symbol) {
  return state.marketItems.find((item) => item.symbol === symbol) || null;
}

function getPositionBySymbol(symbol) {
  return state.dashboard?.balance?.positions?.find((item) => item.symbol === symbol) || null;
}

function getSelectedPosition() {
  return getPositionBySymbol(state.selectedSymbol);
}

function getLatestMarketUpdate() {
  const timestamps = state.marketItems
    .map((item) => item.last_updated)
    .filter(Boolean)
    .map((value) => new Date(value).getTime())
    .filter((value) => !Number.isNaN(value));
  if (!timestamps.length) {
    return null;
  }
  return new Date(Math.max(...timestamps)).toISOString();
}

function getEstimatedTradeValue() {
  const quantity = parseDecimalInput(state.tradeQuantity);
  if (!quantity || quantity <= 0) {
    return null;
  }
  if (state.priceMode === "manual") {
    const manualPrice = parseDecimalInput(state.tradeManualPrice);
    return manualPrice > 0 ? manualPrice * quantity : null;
  }
  const marketItem = getSelectedMarketItem();
  return marketItem?.current_price_rub ? marketItem.current_price_rub * quantity : null;
}

function getTradePriceValue() {
  if (state.priceMode === "manual") {
    return parseDecimalInput(state.tradeManualPrice);
  }
  return getSelectedMarketItem()?.current_price_rub ?? null;
}

function refreshTradeEstimate() {
  const priceNode = document.getElementById("tradeCurrentPrice");
  const totalNode = document.getElementById("tradeEstimatedTotal");
  if (priceNode) {
    priceNode.textContent = formatMoney(getTradePriceValue());
  }
  if (totalNode) {
    totalNode.textContent = formatMoney(getEstimatedTradeValue());
  }
}

function openTrade(symbol, opType) {
  state.activeView = "operation";
  state.selectedSymbol = symbol;
  state.opType = opType;
  state.tradeQuantity = "";
  state.tradeManualPrice = "";
  state.tradeResult = null;
  render();
}

function getFilteredMarketItems() {
  const query = state.marketQuery.trim().toLowerCase();
  if (!query) {
    return state.marketItems;
  }
  return state.marketItems.filter((item) => {
    return item.symbol.toLowerCase().includes(query) || item.name.toLowerCase().includes(query);
  });
}

function createSkeletonCards(count, className = "skeleton-card") {
  return Array.from({ length: count }, () => `<div class="${className}"></div>`).join("");
}

function renderMetric(label, value) {
  return `
    <div class="metric-card">
      <span class="metric-label">${label}</span>
      <strong class="metric-value">${value}</strong>
    </div>
  `;
}

function getHistoryPoints(symbol) {
  const history = state.marketHistory[symbol];
  return Array.isArray(history?.points) ? history.points : [];
}

function getChartStats(points) {
  const prices = points
    .map((point) => Number(point.price_rub))
    .filter((value) => Number.isFinite(value));
  if (!prices.length) {
    return null;
  }
  const first = prices[0];
  const last = prices[prices.length - 1];
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const delta = last - first;
  const deltaPercent = first ? (delta / first) * 100 : 0;
  return { first, last, min, max, delta, deltaPercent };
}

function buildSmoothPath(coords) {
  if (!coords.length) {
    return "";
  }
  if (coords.length < 2) {
    const [x, y] = coords[0];
    return `M ${x} ${y}`;
  }
  const path = [`M ${coords[0][0]} ${coords[0][1]}`];
  for (let index = 0; index < coords.length - 1; index += 1) {
    const [x0, y0] = coords[index];
    const [x1, y1] = coords[index + 1];
    const controlDistance = (x1 - x0) * 0.42;
    path.push(`C ${x0 + controlDistance} ${y0}, ${x1 - controlDistance} ${y1}, ${x1} ${y1}`);
  }
  return path.join(" ");
}

function buildPriceChartSvg(symbol, variant = "large") {
  const points = getHistoryPoints(symbol);
  const stats = getChartStats(points);
  const isLarge = variant === "large";

  if (!stats || points.length < 2) {
    return `
      <div class="${isLarge ? "chart-empty" : "sparkline-empty"}">
        ${state.historyLoading[symbol] ? "История цены загружается" : "Нет данных для графика"}
      </div>
    `;
  }

  const viewWidth = isLarge ? 420 : 160;
  const viewHeight = isLarge ? 260 : 58;
  const plotLeft = isLarge ? 18 : 4;
  const plotTop = isLarge ? 18 : 6;
  const plotRight = isLarge ? 348 : 156;
  const plotBottom = isLarge ? 210 : 52;
  const chartWidth = plotRight - plotLeft;
  const chartHeight = plotBottom - plotTop;
  const gradientId = `marketChartFill-${symbol}-${variant}`;
  const min = stats.min;
  const max = stats.max;
  const pad = Math.max((max - min) * 0.12, max * 0.002, 1);
  const minY = min - pad;
  const maxY = max + pad;
  const range = maxY - minY || Math.max(maxY * 0.01, 1);
  const coords = points.map((point, index) => {
    const price = Number(point.price_rub);
    const x = plotLeft + (index * chartWidth) / (points.length - 1);
    const y = plotTop + chartHeight - ((price - minY) / range) * chartHeight;
    return [Number(x.toFixed(2)), Number(y.toFixed(2))];
  });
  const trendClass = stats.delta >= 0 ? "chart-positive" : "chart-negative";
  const linePath = buildSmoothPath(coords);
  const fillPath = `${linePath} L ${coords[coords.length - 1][0]} ${plotBottom} L ${coords[0][0]} ${plotBottom} Z`;
  const lastPoint = coords[coords.length - 1];
  const axisTicks = Array.from({ length: 5 }, (_, index) => {
    const ratio = index / 4;
    const value = maxY - ratio * range;
    const y = plotTop + ratio * chartHeight;
    return { value, y: Number(y.toFixed(2)) };
  });
  const timeIndexes = [0, Math.floor((points.length - 1) / 2), points.length - 1];
  const timeTicks = timeIndexes.map((pointIndex) => ({
    label: formatChartTime(points[pointIndex]?.captured_at),
    x: Number((plotLeft + (pointIndex * chartWidth) / (points.length - 1)).toFixed(2)),
  }));

  if (!isLarge) {
    return `
      <svg class="chart-svg sparkline-svg ${trendClass}" viewBox="0 0 ${viewWidth} ${viewHeight}" role="img" aria-label="График цены ${escapeHtml(symbol)}">
        <path class="sparkline-line" d="${linePath}"></path>
        <circle class="sparkline-dot" cx="${lastPoint[0]}" cy="${lastPoint[1]}" r="2.4"></circle>
      </svg>
    `;
  }

  return `
    <svg class="chart-svg ${isLarge ? "chart-svg-large" : "sparkline-svg"} ${trendClass}" viewBox="0 0 ${viewWidth} ${viewHeight}" role="img" aria-label="График цены ${escapeHtml(symbol)}">
      <defs>
        <linearGradient id="${gradientId}" x1="0" x2="0" y1="0" y2="1">
          <stop class="chart-fill-stop-strong" offset="0%" />
          <stop class="chart-fill-stop-soft" offset="72%" />
          <stop class="chart-fill-stop-zero" offset="100%" />
        </linearGradient>
      </defs>
      <rect class="chart-plot-bg" x="${plotLeft}" y="${plotTop}" width="${chartWidth}" height="${chartHeight}" rx="14"></rect>
      ${axisTicks.map((tick) => `
        <line class="chart-grid-line" x1="${plotLeft}" y1="${tick.y}" x2="${plotRight}" y2="${tick.y}" />
        <text class="chart-axis-price" x="${viewWidth - 8}" y="${tick.y + 4}">${escapeHtml(formatChartPrice(tick.value))}</text>
      `).join("")}
      ${timeTicks.map((tick, index) => `
        <text class="chart-axis-time chart-axis-time-${index}" x="${tick.x}" y="${viewHeight - 12}">${escapeHtml(tick.label)}</text>
      `).join("")}
      <clipPath id="chartClip-${symbol}">
        <rect x="${plotLeft}" y="${plotTop}" width="${chartWidth}" height="${chartHeight}" rx="14"></rect>
      </clipPath>
      <g clip-path="url(#chartClip-${symbol})">
        <path class="chart-fill" d="${fillPath}" fill="url(#${gradientId})"></path>
        <path class="chart-line" d="${linePath}"></path>
      </g>
      <circle class="chart-end-dot" cx="${lastPoint[0]}" cy="${lastPoint[1]}" r="${isLarge ? 4.6 : 2.6}"></circle>
      <rect class="chart-last-price-pill" x="${plotRight + 8}" y="${Math.max(plotTop + 4, Math.min(plotBottom - 22, lastPoint[1] - 12))}" width="58" height="24" rx="12"></rect>
      <text class="chart-last-price-text" x="${plotRight + 37}" y="${Math.max(plotTop + 20, Math.min(plotBottom - 6, lastPoint[1] + 4))}">${escapeHtml(formatChartPrice(stats.last))}</text>
    </svg>
  `;
}

function renderMarketChartPanel() {
  const symbol = state.selectedChartSymbol;
  const item = getMarketItemBySymbol(symbol) || state.marketItems[0] || null;
  const points = getHistoryPoints(symbol);
  const stats = getChartStats(points);
  const deltaClass = stats?.delta > 0 ? "trend-positive" : stats?.delta < 0 ? "trend-negative" : "trend-neutral";
  const chartSymbols = SYMBOLS.slice(0, 5);
  const firstDate = points.length ? formatDate(points[0].captured_at) : "—";
  const lastDate = points.length ? formatDate(points[points.length - 1].captured_at) : "—";

  return `
    <section class="chart-panel">
      <div class="chart-panel-head">
        <div>
          <h3>Динамика цены ${escapeHtml(symbol)}</h3>
          <p class="chart-period">${escapeHtml(firstDate)} - ${escapeHtml(lastDate)}</p>
        </div>
        <div class="chart-price-block">
          <span>Текущая цена</span>
          <strong>${formatMoney(item?.current_price_rub || stats?.last)}</strong>
        </div>
      </div>

      <div class="chart-summary ${deltaClass}">
        <span>Изменение за период</span>
        <strong>${stats ? `${formatMoney(stats.delta, true)} · ${formatPercent(stats.deltaPercent)}` : "—"}</strong>
      </div>

      <div class="chart-stage">
        ${buildPriceChartSvg(symbol, "large")}
      </div>

      <div class="chart-chip-row">
        ${chartSymbols.map((chartSymbol) => `
          <button
            type="button"
            class="chip ${symbol === chartSymbol ? "chip-active" : ""}"
            data-action="set-chart-symbol"
            data-symbol="${chartSymbol}"
          >
            ${chartSymbol}
          </button>
        `).join("")}
      </div>
    </section>
  `;
}

function renderSymbolChips(context) {
  return `
    <div class="chip-row">
      ${SYMBOLS.map((symbol) => {
        const active = state.selectedSymbol === symbol ? "chip-active" : "";
        return `
          <button
            type="button"
            class="chip ${active}"
            data-action="set-symbol"
            data-context="${context}"
            data-symbol="${symbol}"
          >
            ${symbol}
          </button>
        `;
      }).join("")}
    </div>
  `;
}

function renderAssetLogo(symbol, compact = false) {
  const item = getMarketItemBySymbol(symbol);
  const sizeClass = compact ? "asset-logo-compact" : "";
  const imageMarkup = item?.image
    ? `<img src="${escapeHtml(item.image)}" alt="${escapeHtml(symbol)}" loading="lazy" onerror="window.handleCoinImageError(this, '${escapeHtml(symbol)}')" />`
    : `<span>${escapeHtml(symbol.slice(0, 2))}</span>`;

  return `<div class="asset-logo ${sizeClass} ${item?.image ? "" : "asset-logo-fallback"}">${imageMarkup}</div>`;
}

function renderMarketCard(item, featured = false) {
  const changeClass =
    item.price_change_percentage_24h > 0
      ? "trend-positive"
      : item.price_change_percentage_24h < 0
        ? "trend-negative"
        : "trend-neutral";
  return `
    <article class="market-card ${featured ? "market-card-featured" : ""}">
      <div class="market-card-head">
        <div class="asset-meta">
          ${renderAssetLogo(item.symbol)}
          <div>
            <strong>${escapeHtml(item.symbol)}</strong>
            <span>${escapeHtml(item.name)}</span>
          </div>
        </div>
        <div class="rank-badge">#${item.market_cap_rank ?? "—"}</div>
      </div>
      <div class="market-price">${formatMoney(item.current_price_rub)}</div>
      <div class="market-subline">
        <span class="${changeClass}">${formatPercent(item.price_change_percentage_24h)}</span>
        <span>24ч диапазон ${formatMoney(item.low_24h_rub, true)} - ${formatMoney(item.high_24h_rub, true)}</span>
      </div>
      <div class="market-footer">
        <span>Обновлено ${formatDate(item.last_updated)}</span>
        <button type="button" class="mini-btn" data-action="set-chart-symbol" data-symbol="${escapeHtml(item.symbol)}">График</button>
      </div>
    </article>
  `;
}

function renderHomeView() {
  const dashboard = state.dashboard?.balance;
  const latestUpdate = getLatestMarketUpdate();
  const marketShowcase = state.loading.market && !state.marketItems.length
    ? createSkeletonCards(4, "skeleton-card skeleton-market")
    : state.marketItems.length
      ? state.marketItems.map((item) => renderMarketCard(item, true)).join("")
      : `
        <div class="empty-card">
          <strong>Карточки рынка пока недоступны</strong>
          <p>${escapeHtml(state.marketError || "Повторите обновление, когда CoinGecko ответит.")}</p>
          <button type="button" class="secondary-btn" data-action="reload-market">Повторить</button>
        </div>
      `;

  const positionsMarkup = state.loading.dashboard && !dashboard
    ? createSkeletonCards(3)
    : dashboard?.positions?.length
      ? dashboard.positions.map((item) => {
          const pnlClass =
            Number(item.realized_pnl_rub) > 0
              ? "trend-positive"
              : Number(item.realized_pnl_rub) < 0
                ? "trend-negative"
                : "trend-neutral";
          return `
            <article class="position-card">
              <div class="position-top">
                <div class="asset-meta">
                  ${renderAssetLogo(item.symbol, true)}
                  <div>
                    <strong>${escapeHtml(item.symbol)}</strong>
                    <span>${formatNumber(item.quantity)} мон.</span>
                  </div>
                </div>
                <div class="position-pill">${formatMoney(item.avg_buy_price_rub)}</div>
              </div>
              <div class="position-grid">
                <div>
                  <span>Средняя цена</span>
                  <strong>${formatMoney(item.avg_buy_price_rub)}</strong>
                </div>
                <div>
                  <span>Результат</span>
                  <strong class="${pnlClass}">${formatMoney(item.realized_pnl_rub)}</strong>
                </div>
              </div>
              <div class="position-actions">
                <button type="button" class="mini-btn" data-action="position-buy" data-symbol="${escapeHtml(item.symbol)}">Купить</button>
                <button type="button" class="mini-btn mini-btn-danger" data-action="position-sell" data-symbol="${escapeHtml(item.symbol)}">Продать</button>
              </div>
            </article>
          `;
        }).join("")
      : `
        <div class="empty-card">
          <strong>Портфель пока пустой</strong>
          <p>Сделайте первую покупку, чтобы позиции появились на главной.</p>
          <button type="button" class="secondary-btn" data-action="quick-buy">Купить актив</button>
        </div>
      `;

  return `
    <section class="view-section ${state.activeView === "home" ? "view-active" : ""}">
      <article class="hero-card">
        <div class="hero-copy">
          <span class="eyebrow">Портфель в Telegram</span>
          ${state.siteMode ? '<span class="site-mode-badge">Режим сайта</span>' : ""}
          <h2>${escapeHtml(state.session?.default_portfolio?.name || "Основной портфель")}</h2>
          <p>Мини-терминал для просмотра позиций, операций и ценовых алертов в одном экране.</p>
        </div>
        <div class="hero-value">${formatMoney(dashboard?.total_value_rub)}</div>
        <div class="metrics-grid">
          ${renderMetric("Позиций", dashboard?.positions?.length ?? 0)}
          ${renderMetric("Активных алертов", state.alerts.length || state.dashboard?.alerts_count || 0)}
          ${renderMetric("Последнее обновление", latestUpdate ? formatDate(latestUpdate) : "—")}
        </div>
        <div class="quick-actions">
          <button type="button" class="primary-btn" data-action="quick-buy">Купить</button>
          <button type="button" class="secondary-btn" data-action="quick-alert">Создать алерт</button>
          <button
            type="button"
            class="ghost-btn"
            data-action="sync-market"
            ${state.loading.priceSync ? "disabled" : ""}
          >
            ${state.loading.priceSync ? "Обновляем..." : "Обновить цены"}
          </button>
        </div>
      </article>

      <section class="panel">
        <div class="panel-head">
          <div>
            <span class="section-kicker">Витрина рынка</span>
            <h3>Главные монеты</h3>
          </div>
          <button type="button" class="ghost-btn ghost-btn-small" data-action="set-view" data-view="market">Все</button>
        </div>
        <div class="market-showcase">${marketShowcase}</div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <span class="section-kicker">Позиции</span>
            <h3>Открытые активы</h3>
          </div>
        </div>
        <div class="position-list">${positionsMarkup}</div>
      </section>
    </section>
  `;
}

function renderOperationView() {
  const marketItem = getSelectedMarketItem();
  const selectedPosition = getSelectedPosition();
  const estimate = getEstimatedTradeValue();
  const hasSellPosition = Number(selectedPosition?.quantity || 0) > 0;
  const tradeButtonDisabled = state.loading.trade || (state.opType === "sell" && !hasSellPosition);
  const tradeButtonLabel = state.loading.trade ? "Сохраняем..." : state.opType === "buy" ? "Подтвердить покупку" : "Подтвердить продажу";
  const sellShortcuts = state.opType === "sell"
    ? `
      <div class="field-block">
        <label>Быстрая продажа</label>
        <div class="percent-row">
          ${SELL_PERCENT_SHORTCUTS.map((percent) => `
            <button
              type="button"
              class="percent-btn"
              data-action="set-sell-percent"
              data-percent="${percent}"
              ${hasSellPosition ? "" : "disabled"}
            >
              ${percent}%
            </button>
          `).join("")}
        </div>
        <p class="helper-text">${hasSellPosition ? `Доступно ${formatNumber(selectedPosition.quantity)} ${escapeHtml(state.selectedSymbol)}` : "По этой монете нет открытой позиции для продажи."}</p>
      </div>
    `
    : "";

  return `
    <section class="view-section ${state.activeView === "operation" ? "view-active" : ""}">
      <section class="panel">
        <div class="panel-head">
          <div>
            <span class="section-kicker">Сделка</span>
            <h3>Новая операция</h3>
          </div>
        </div>

        <div class="segmented">
          <button type="button" class="segment ${state.opType === "buy" ? "segment-active" : ""}" data-action="set-op-type" data-op-type="buy">Покупка</button>
          <button type="button" class="segment ${state.opType === "sell" ? "segment-active" : ""}" data-action="set-op-type" data-op-type="sell">Продажа</button>
        </div>

        <div class="field-block">
          <label>Монета</label>
          ${renderSymbolChips("operation")}
        </div>

        <div class="field-block">
          <label>Режим цены</label>
          <div class="segmented segmented-small">
            <button type="button" class="segment ${state.priceMode === "market" ? "segment-active" : ""}" data-action="set-price-mode" data-price-mode="market">Рыночная</button>
            <button type="button" class="segment ${state.priceMode === "manual" ? "segment-active" : ""}" data-action="set-price-mode" data-price-mode="manual">Ручная</button>
          </div>
        </div>

        <div class="form-grid">
          <label class="field">
            <span>Количество</span>
            <input name="tradeQuantity" type="text" inputmode="decimal" autocomplete="off" placeholder="0,010000" value="${escapeHtml(state.tradeQuantity)}" />
          </label>
          <label class="field ${state.priceMode === "manual" ? "" : "field-disabled"}">
            <span>Цена в рублях</span>
            <input
              name="tradeManualPrice"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="${state.priceMode === "manual" ? "Укажите цену" : "Используется рынок"}"
              value="${escapeHtml(state.tradeManualPrice)}"
              ${state.priceMode === "manual" ? "" : "disabled"}
            />
          </label>
        </div>

        ${sellShortcuts}

        <div class="estimate-card">
          <div>
            <span class="section-kicker">Расчет до сохранения</span>
            <h4>${escapeHtml(state.selectedSymbol)} · ${state.opType === "buy" ? "Покупка" : "Продажа"}</h4>
          </div>
          <div class="estimate-grid">
            <div>
              <span>Текущая цена</span>
              <strong id="tradeCurrentPrice">${formatMoney(getTradePriceValue())}</strong>
            </div>
            <div>
              <span>Примерная сумма</span>
              <strong id="tradeEstimatedTotal">${formatMoney(estimate)}</strong>
            </div>
          </div>
          <p class="helper-text">
            ${state.priceMode === "market"
              ? "Рыночная цена подставляется из последней карточки CoinGecko и фиксируется сервером при сохранении."
              : "В ручном режиме операция сохранится по вашей цене без запроса рыночной котировки."}
          </p>
        </div>

        <button type="button" class="primary-btn" data-action="submit-trade" ${tradeButtonDisabled ? "disabled" : ""}>${tradeButtonLabel}</button>

        ${state.tradeResult
          ? `
            <div class="status-card status-${state.tradeResult.type}">
              <strong>${state.tradeResult.type === "success" ? "Операция выполнена" : "Не удалось сохранить операцию"}</strong>
              <p>${escapeHtml(state.tradeResult.message)}</p>
            </div>
          `
          : ""}
      </section>
    </section>
  `;
}

function renderMarketView() {
  const filteredItems = getFilteredMarketItems();
  const content = state.loading.market && !state.marketItems.length
    ? createSkeletonCards(4)
    : filteredItems.length
      ? filteredItems.map((item) => renderMarketCard(item)).join("")
      : `
        <div class="empty-card">
          <strong>${state.marketItems.length ? "Ничего не найдено" : "Рынок пока пуст"}</strong>
          <p>${escapeHtml(state.marketItems.length ? "Измените запрос поиска по тикеру." : state.marketError || "Повторите загрузку рынка позже.")}</p>
          <button type="button" class="secondary-btn" data-action="reload-market">Обновить рынок</button>
        </div>
      `;

  return `
    <section class="view-section ${state.activeView === "market" ? "view-active" : ""}">
      ${renderMarketChartPanel()}

      <section class="panel">
        <div class="panel-head">
          <div>
            <span class="section-kicker">Рынок</span>
            <h3>Карточки топ-10 монет</h3>
          </div>
          <button type="button" class="ghost-btn ghost-btn-small" data-action="reload-market" ${state.loading.market ? "disabled" : ""}>
            ${state.loading.market ? "Загрузка..." : "Обновить"}
          </button>
        </div>
        <label class="field">
          <span>Поиск по тикеру</span>
          <input name="marketQuery" type="search" placeholder="Например, ETH" value="${escapeHtml(state.marketQuery)}" />
        </label>
      </section>

      <section class="market-grid">${content}</section>
    </section>
  `;
}

function renderAlertsView() {
  const alertsMarkup = state.loading.alerts && !state.alerts.length
    ? createSkeletonCards(3)
    : state.alerts.length
      ? state.alerts.map((item) => {
          const condText = item.condition_type === "gt" ? "Цена выше" : "Цена ниже";
          return `
            <article class="alert-card">
              <div class="alert-card-head">
                <div>
                  <strong>${escapeHtml(item.symbol)}</strong>
                  <span>${condText}</span>
                </div>
                <div class="rank-badge">${formatMoney(item.target_price_rub, true)}</div>
              </div>
              <p>Бот пришлет сообщение в Telegram, когда цель будет достигнута.</p>
              <div class="alert-card-footer">
                <span>Создан ${formatDate(item.created_at)}</span>
                <button
                  type="button"
                  class="danger-btn"
                  data-action="disable-alert"
                  data-alert-id="${item.id}"
                  ${state.loading.alertAction ? "disabled" : ""}
                >
                  Отключить
                </button>
              </div>
            </article>
          `;
        }).join("")
      : `
        <div class="empty-card">
          <strong>Алертов пока нет</strong>
          <p>Создайте первое уведомление и бот отправит сообщение в Telegram.</p>
        </div>
      `;

  return `
    <section class="view-section ${state.activeView === "alerts" ? "view-active" : ""}">
      <section class="panel">
        <div class="panel-head">
          <div>
            <span class="section-kicker">Алерты</span>
            <h3>Новый ценовой сигнал</h3>
          </div>
        </div>

        <div class="field-block">
          <label>Монета</label>
          ${renderSymbolChips("alerts")}
        </div>

        <div class="form-grid">
          <label class="field">
            <span>Условие</span>
            <select name="alertCondition">
              <option value="gt" ${state.alertCondition === "gt" ? "selected" : ""}>Цена выше</option>
              <option value="lt" ${state.alertCondition === "lt" ? "selected" : ""}>Цена ниже</option>
            </select>
          </label>
          <label class="field">
            <span>Целевая цена</span>
            <input name="alertTarget" type="text" inputmode="decimal" autocomplete="off" placeholder="Например, 300000" value="${escapeHtml(state.alertTarget)}" />
          </label>
        </div>

        <p class="helper-text">Уведомление сохранится для ${escapeHtml(state.selectedSymbol)} и останется активным, пока вы его не отключите или пока оно не сработает.</p>
        <button type="button" class="primary-btn" data-action="create-alert" ${state.loading.alertAction ? "disabled" : ""}>
          ${state.loading.alertAction ? "Сохраняем..." : "Создать алерт"}
        </button>
      </section>

      <section class="alert-list">${alertsMarkup}</section>
    </section>
  `;
}

function renderFatalState() {
  return `
    <section class="fatal-state">
      <span class="eyebrow">Ошибка авторизации</span>
      <h2>Мини-приложение не удалось открыть</h2>
      <p>${escapeHtml(state.fatalError)}</p>
    </section>
  `;
}

function render() {
  if (!appRoot) {
    return;
  }

  const activeElement = document.activeElement;
  const focusState =
    activeElement instanceof HTMLInputElement || activeElement instanceof HTMLSelectElement
      ? {
          name: activeElement.name,
          selectionStart: activeElement instanceof HTMLInputElement ? activeElement.selectionStart : null,
          selectionEnd: activeElement instanceof HTMLInputElement ? activeElement.selectionEnd : null,
        }
      : null;

  if (state.fatalError) {
    appRoot.innerHTML = renderFatalState();
    return;
  }

  appRoot.innerHTML = `
    <div class="app-frame">
      <main class="app-content">
        ${renderHomeView()}
        ${renderOperationView()}
        ${renderMarketView()}
        ${renderAlertsView()}
      </main>

      <nav class="bottom-nav" aria-label="Навигация">
        ${Object.entries(VIEW_TITLES).map(([key, label]) => {
          const active = state.activeView === key ? "nav-item-active" : "";
          return `
            <button type="button" class="nav-item ${active}" data-action="set-view" data-view="${key}">
              <span>${label}</span>
            </button>
          `;
        }).join("")}
      </nav>
    </div>
  `;

  if (focusState?.name) {
    const nextField = appRoot.querySelector(`[name="${focusState.name}"]`);
    if (nextField instanceof HTMLInputElement || nextField instanceof HTMLSelectElement) {
      nextField.focus();
      if (
        nextField instanceof HTMLInputElement &&
        focusState.selectionStart !== null &&
        focusState.selectionEnd !== null
      ) {
        nextField.setSelectionRange(focusState.selectionStart, focusState.selectionEnd);
      }
    }
  }
}

async function loadDashboard() {
  setLoading("dashboard", true);
  try {
    state.dashboard = await apiGet(`/app/dashboard?${buildQuery(reqAuthParams())}`);
  } finally {
    setLoading("dashboard", false);
  }
}

async function loadMarket() {
  setLoading("market", true);
  try {
    const response = await apiGet(`/app/market?${buildQuery(reqAuthParams())}`);
    state.marketItems = Array.isArray(response.items) ? response.items : [];
    if (!state.marketItems.some((item) => item.symbol === state.selectedChartSymbol)) {
      state.selectedChartSymbol = state.marketItems[0]?.symbol || "BTC";
    }
    state.marketError = "";
    const prioritySymbols = Array.from(new Set([state.selectedChartSymbol, "BTC", "ETH", "SOL", "BNB"]));
    await Promise.allSettled(prioritySymbols.map((symbol) => loadMarketHistory(symbol)));
  } catch (error) {
    state.marketItems = state.marketItems || [];
    state.marketError = error.message;
    showToast("warning", `Рынок недоступен: ${error.message}`);
  } finally {
    setLoading("market", false);
  }
}

async function loadMarketHistory(symbol, force = false) {
  if (!symbol) {
    return;
  }
  if (!force && getHistoryPoints(symbol).length) {
    return;
  }
  if (state.historyLoading[symbol]) {
    return;
  }

  state.historyLoading[symbol] = true;
  render();
  try {
    const response = await apiGet(`/app/market/history?${buildQuery({ symbol, ...reqAuthParams() })}`);
    state.marketHistory[symbol] = {
      points: Array.isArray(response.points) ? response.points : [],
      error: "",
    };
    state.historyError = "";
  } catch (error) {
    state.marketHistory[symbol] = {
      points: getHistoryPoints(symbol),
      error: error.message,
    };
    state.historyError = error.message;
  } finally {
    delete state.historyLoading[symbol];
    render();
  }
}

async function loadAlerts() {
  setLoading("alerts", true);
  try {
    const response = await apiGet(`/app/alerts?${buildQuery(reqAuthParams())}`);
    state.alerts = Array.isArray(response.items) ? response.items : [];
  } finally {
    setLoading("alerts", false);
  }
}

async function syncMarketData() {
  if (state.loading.priceSync) {
    return;
  }
  setLoading("priceSync", true);
  try {
    await apiPost("/market/sync", { symbols: null });
    showToast("success", "Цены обновлены и портфель пересчитан.");
    await Promise.allSettled([loadDashboard(), loadMarket(), loadAlerts()]);
  } catch (error) {
    showToast("error", `Не удалось обновить цены: ${error.message}`);
  } finally {
    setLoading("priceSync", false);
  }
}

async function submitTrade() {
  const quantity = parseDecimalInput(state.tradeQuantity);
  if (!quantity || quantity <= 0) {
    showToast("warning", "Укажите количество монет больше нуля.");
    return;
  }

  const selectedPosition = getSelectedPosition();
  if (state.opType === "sell") {
    const availableQuantity = Number(selectedPosition?.quantity || 0);
    if (!availableQuantity) {
      showToast("warning", "Для продажи выберите монету с открытой позицией.");
      return;
    }
    if (quantity > availableQuantity) {
      showToast("warning", `Можно продать не больше ${formatNumber(availableQuantity)} ${state.selectedSymbol}.`);
      return;
    }
  }

  let priceRub = null;
  if (state.priceMode === "manual") {
    priceRub = parseDecimalInput(state.tradeManualPrice);
    if (!priceRub || priceRub <= 0) {
      showToast("warning", "Для ручного режима укажите цену в рублях.");
      return;
    }
  }

  setLoading("trade", true);
  try {
    const response = await apiPost("/app/trade", {
      ...reqAuthPayload(),
      symbol: state.selectedSymbol,
      op_type: state.opType,
      quantity,
      price_mode: state.priceMode,
      price_rub: priceRub,
    });
    state.tradeQuantity = "";
    state.tradeManualPrice = "";
    state.tradeResult = {
      type: "success",
      message: `Операция #${response.operation_id} сохранена по цене ${formatMoney(response.price_used_rub)}.`,
    };
    showToast("success", "Операция сохранена.");
    await Promise.allSettled([loadDashboard(), loadAlerts()]);
  } catch (error) {
    state.tradeResult = {
      type: "error",
      message: error.message,
    };
    showToast("error", `Ошибка операции: ${error.message}`);
  } finally {
    setLoading("trade", false);
  }
}

async function createAlert() {
  const targetPrice = parseDecimalInput(state.alertTarget);
  if (!targetPrice || targetPrice <= 0) {
    showToast("warning", "Укажите целевую цену больше нуля.");
    return;
  }

  setLoading("alertAction", true);
  try {
    const response = await apiPost("/app/alerts", {
      ...reqAuthPayload(),
      symbol: state.selectedSymbol,
      condition_type: state.alertCondition,
      target_price_rub: targetPrice,
    });
    state.alertTarget = "";
    showToast("success", `Алерт #${response.alert_id} создан.`);
    await Promise.allSettled([loadAlerts(), loadDashboard()]);
  } catch (error) {
    showToast("error", `Не удалось создать алерт: ${error.message}`);
  } finally {
    setLoading("alertAction", false);
  }
}

async function disableAlert(alertId) {
  setLoading("alertAction", true);
  try {
    await apiPost(`/app/alerts/${alertId}/disable`, reqAuthPayload());
    showToast("success", "Алерт отключен.");
    await Promise.allSettled([loadAlerts(), loadDashboard()]);
  } catch (error) {
    showToast("error", `Не удалось отключить алерт: ${error.message}`);
  } finally {
    setLoading("alertAction", false);
  }
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) {
    return;
  }

  const action = target.dataset.action;
  switch (action) {
    case "set-view":
      state.activeView = target.dataset.view;
      render();
      break;
    case "set-op-type":
      state.opType = target.dataset.opType;
      render();
      break;
    case "set-price-mode":
      state.priceMode = target.dataset.priceMode;
      render();
      break;
    case "set-symbol":
      state.selectedSymbol = target.dataset.symbol;
      state.tradeResult = null;
      render();
      break;
    case "set-chart-symbol":
      state.selectedChartSymbol = target.dataset.symbol;
      render();
      await loadMarketHistory(state.selectedChartSymbol);
      break;
    case "quick-buy":
      openTrade(state.selectedSymbol, "buy");
      break;
    case "position-buy":
      openTrade(target.dataset.symbol, "buy");
      break;
    case "position-sell":
      openTrade(target.dataset.symbol, "sell");
      break;
    case "quick-alert":
      state.activeView = "alerts";
      render();
      break;
    case "set-sell-percent": {
      const position = getSelectedPosition();
      const quantity = Number(position?.quantity || 0);
      const percent = Number(target.dataset.percent);
      if (quantity > 0 && percent > 0) {
        state.tradeQuantity = formatInputDecimal((quantity * percent) / 100);
        state.tradeResult = null;
        render();
      }
      break;
    }
    case "sync-market":
      await syncMarketData();
      break;
    case "reload-market":
      await loadMarket();
      break;
    case "submit-trade":
      await submitTrade();
      break;
    case "create-alert":
      await createAlert();
      break;
    case "disable-alert":
      await disableAlert(Number(target.dataset.alertId));
      break;
    default:
      break;
  }
});

document.addEventListener("input", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) {
    return;
  }

  let shouldRender = false;
  switch (target.name) {
    case "marketQuery":
      state.marketQuery = target.value;
      shouldRender = true;
      break;
    case "tradeQuantity":
      state.tradeQuantity = target.value;
      refreshTradeEstimate();
      break;
    case "tradeManualPrice":
      state.tradeManualPrice = target.value;
      refreshTradeEstimate();
      break;
    case "alertTarget":
      state.alertTarget = target.value;
      break;
    case "alertCondition":
      state.alertCondition = target.value;
      shouldRender = true;
      break;
    default:
      return;
  }
  if (shouldRender) {
    render();
  }
});

document.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLSelectElement) || target.name !== "alertCondition") {
    return;
  }
  state.alertCondition = target.value;
  render();
});

async function bootstrap() {
  render();
  setLoading("bootstrap", true);
  try {
    state.session = await apiPost("/app/auth", reqAuthPayload());
    await Promise.allSettled([loadDashboard(), loadMarket(), loadAlerts()]);
  } catch (error) {
    state.fatalError = error.message;
  } finally {
    setLoading("bootstrap", false);
  }
}

bootstrap();
