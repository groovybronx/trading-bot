// --- DOM Element References ---
export const statusValue = document.getElementById('status-value');
export const strategyTypeValueSpan = document.getElementById('strategy-type-value');
export const symbolValue = document.getElementById('symbol-value');
export const timeframeValue = document.getElementById('timeframe-value');
export const balanceValue = document.getElementById('balance-value');
export const quantityValue = document.getElementById('quantity-value');
export const priceValue = document.getElementById('current-price');
export const positionValue = document.getElementById('position-value');
export const quoteAssetLabel = document.getElementById('quote-asset-label');
export const baseAssetLabel = document.getElementById('base-asset-label');
export const symbolPriceLabel = document.getElementById('symbol-price-label');
export const logOutput = document.getElementById('log-output');
export const startBotBtn = document.getElementById('start-bot-btn');
export const stopBotBtn = document.getElementById('stop-bot-btn');
export const saveParamsBtn = document.getElementById('save-params-btn');
export const paramSaveStatus = document.getElementById('param-save-status');

// --- Session Management DOM Elements ---
export const sessionSelector = document.getElementById('session-selector');
export const newSessionBtn = document.getElementById('new-session-btn');
export const deleteSessionBtn = document.getElementById('delete-session-btn');
export const sessionStatusIndicator = document.getElementById('session-status-indicator');
export const historySessionIdSpan = document.getElementById('history-session-id'); // Span in history title

// --- Parameter Inputs ---
export const strategySelector = document.getElementById('param-strategy-type');
export const swingParamsDiv = document.getElementById('swing-params');
export const scalpingOrderBookParamsDiv = document.getElementById('scalping-params'); // Points to the SCALPING (Order Book) specific params div
export const scalping2SpecificParamsDiv = document.getElementById('scalping2-specific-params'); // Div pour params spécifiques Scalping2 (Indicateurs)
export const timeframeRelevance = document.getElementById('timeframe-relevance');

// Common Params (Risk/Capital/Exit) - Utilisés par toutes les stratégies
export const paramRisk = document.getElementById('param-risk');
export const paramCapitalAllocation = document.getElementById('param-capital-allocation');
export const paramSl = document.getElementById('param-sl');
export const paramTp1 = document.getElementById('param-tp1');
export const paramTp2 = document.getElementById('param-tp2');
export const paramTrailing = document.getElementById('param-trailing');
export const paramTimeStop = document.getElementById('param-time-stop');
export const paramOrderCooldown = document.getElementById('param-order-cooldown'); // Moved to common

// SWING Params
export const paramTimeframe = document.getElementById('param-timeframe');
export const paramEmaShort = document.getElementById('param-ema-short');
export const paramEmaLong = document.getElementById('param-ema-long');
export const paramEmaFilter = document.getElementById('param-ema-filter');
export const paramRsiPeriod = document.getElementById('param-rsi-period');
export const paramRsiOb = document.getElementById('param-rsi-ob');
export const paramRsiOs = document.getElementById('param-rsi-os');
export const paramVolumeAvg = document.getElementById('param-volume-avg');
export const paramUseEmaFilter = document.getElementById('param-use-ema-filter');
export const paramUseVolume = document.getElementById('param-use-volume');

// SCALPING (Order Book) Specific Params
export const paramScalpingOrderType = document.getElementById('param-scalping-order-type');
export const paramScalpingLimitTif = document.getElementById('param-scalping-limit-tif');
export const paramScalpingLimitTimeout = document.getElementById('param-scalping-limit-timeout');
export const paramScalpingDepthLevels = document.getElementById('param-scalping-depth-levels');
export const paramScalpingDepthSpeed = document.getElementById('param-scalping-depth-speed');
export const paramScalpingSpreadThreshold = document.getElementById('param-scalping-spread-threshold');
export const paramScalpingImbalanceThreshold = document.getElementById('param-scalping-imbalance-threshold');

// SCALPING 2 (Indicators) Specific Params
export const paramSupertrendAtr = document.getElementById('param-supertrend-atr');
export const paramSupertrendMult = document.getElementById('param-supertrend-mult');
export const paramRsiPeriodScalp = document.getElementById('param-rsi-period-scalp');
export const paramStochK = document.getElementById('param-stoch-k');
export const paramStochD = document.getElementById('param-stoch-d');
export const paramStochSmooth = document.getElementById('param-stoch-smooth');
export const paramBbPeriod = document.getElementById('param-bb-period');
export const paramBbStd = document.getElementById('param-bb-std');
export const paramVolMa = document.getElementById('param-vol-ma'); // Volume MA pour Scalping2

// --- Statistiques ---
export const statRoi = document.getElementById('stat-roi');
export const statWinrate = document.getElementById('stat-winrate');
export const statWins = document.getElementById('stat-wins');
export const statLosses = document.getElementById('stat-losses');
export const statTotal = document.getElementById('stat-total');
export const statAvgPnl = document.getElementById('stat-avg-pnl');

// --- Signals ---
export const signalsOutput = document.getElementById("signals-output");

// --- DataTables ---
// Note: DataTables is initialized using a jQuery selector. We store the ID.
export const orderHistoryTableId = '#order-history-table';
