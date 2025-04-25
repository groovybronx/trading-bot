import * as DOM from './domElements.js';
import { formatNumber, formatTimestamp } from './utils.js';
import * as API from './apiService.js'; // Import API service to fetch metrics
// Import sessionManager functions when available
// import { fetchAndDisplaySessions } from './sessionManager.js';

let lastKnownState = null; // Stocke le dernier état reçu pour référence interne
let orderHistoryTable = null; // Instance DataTables
let metricsPollingInterval = null; // Pour stocker l'ID de l'intervalle de polling des métriques

/**
 * Initializes the DataTables instance for the order history table.
 */
function initializeOrderHistoryTable() {
    try {
        if (!orderHistoryTable && typeof $ !== 'undefined' && $.fn.dataTable) {
            orderHistoryTable = $(DOM.orderHistoryTableId).DataTable({
                paging: false,
                searching: false,
                info: false,
                order: [[0, 'desc']], // Trier par Date/Heure (colonne 0) descendant
                language: {
                    emptyTable: "Aucun ordre dans l'historique pour cette session.",
                    zeroRecords: "Aucun enregistrement correspondant trouvé"
                },
                // Responsive might be useful: responsive: true,
                // Specify columns if needed for specific rendering/types
                // columns: [ { type: 'date' }, null, null, null, null, null, null, null, null, null, null, null ]
            });
            console.log("DataTables initialized successfully.");
        } else if (orderHistoryTable) {
             console.log("DataTables already initialized.");
        } else {
            console.error("jQuery or DataTables not available for initialization.");
            appendLog("Erreur: Impossible d'initialiser la table d'historique (jQuery/DataTables manquant).", "error");
        }
    } catch (e) {
        console.error("Error initializing DataTables:", e);
        appendLog("Erreur initialisation table historique.", "error");
    }
}

/**
 * Updates the main UI elements based on the bot state.
 * @param {object} state - The state object received from the backend.
 */
function updateUI(state) {
    if (!state) {
        console.warn("updateUI called with null or undefined state");
        return;
    }
    lastKnownState = state; // Store the latest valid state

    // Update Bot Status section
    if (DOM.statusValue) DOM.statusValue.textContent = state.status || 'Inconnu';
    if (DOM.statusValue) DOM.statusValue.className = `status-${(state.status || 'unknown').toLowerCase().replace(/\s+/g, '-')}`;
    if (DOM.strategyTypeValueSpan && state.config) DOM.strategyTypeValueSpan.textContent = state.config?.STRATEGY_TYPE || 'N/A';
    if (DOM.symbolValue) DOM.symbolValue.textContent = state.symbol || 'N/A';
    if (DOM.timeframeValue) DOM.timeframeValue.textContent = state.timeframe || 'N/A';
    if (DOM.quoteAssetLabel) DOM.quoteAssetLabel.textContent = state.quote_asset || 'USDT';
    if (DOM.baseAssetLabel) DOM.baseAssetLabel.textContent = state.base_asset || 'N/A';
    if (DOM.symbolPriceLabel) DOM.symbolPriceLabel.textContent = state.symbol ? `${state.symbol} / ${state.quote_asset || 'USDT'}` : 'N/A';
    if (DOM.balanceValue) DOM.balanceValue.textContent = formatNumber(state.available_balance, 2);
    if (DOM.quantityValue) DOM.quantityValue.textContent = formatNumber(state.symbol_quantity, 8);

    // Update Position Status and Entry Details
    if (DOM.positionValue) {
        if (state.in_position && state.entry_details) {
            const entryPrice = formatNumber(state.entry_details.avg_price, 2);
            const entryQty = formatNumber(state.entry_details.quantity, 8);
            const side = state.entry_details.side || 'N/A';
            const slPrice = state.entry_details.sl_price ? formatNumber(state.entry_details.sl_price, 8) : 'N/A';
            const tp1Price = state.entry_details.tp1_price ? formatNumber(state.entry_details.tp1_price, 8) : 'N/A';
            const tp2Price = state.entry_details.tp2_price ? formatNumber(state.entry_details.tp2_price, 8) : 'N/A';

            DOM.positionValue.innerHTML = `Oui (${side} @ ${entryPrice}, Qté: ${entryQty})<br>SL: ${slPrice}, TP1: ${tp1Price}, TP2: ${tp2Price}`;
            DOM.positionValue.className = 'status-running';
        } else {
            DOM.positionValue.textContent = 'Aucune';
            DOM.positionValue.className = '';
        }
    }

    // Update Control Buttons state
    if (DOM.startBotBtn) DOM.startBotBtn.disabled = state.status === 'RUNNING' || state.status === 'STARTING' || state.status === 'STOPPING';
    if (DOM.stopBotBtn) DOM.stopBotBtn.disabled = state.status !== 'RUNNING';

    // Update Parameter Inputs only if config is present
    if (state.config) {
        const currentStrategy = state.config.STRATEGY_TYPE || 'SWING';
        if (DOM.strategySelector) {
            // Only update selector value if it differs, to avoid triggering change event unnecessarily
            if (DOM.strategySelector.value !== currentStrategy) {
                 DOM.strategySelector.value = currentStrategy;
            }
            updateParameterVisibility(currentStrategy); // Manage visibility
        }
        // Fill parameters based on the state's config
        fillParameters(state.config, currentStrategy);

        // Update Capital Allocation display in Stats section
        const capitalAllocationPercent = (parseFloat(state.config.CAPITAL_ALLOCATION) * 100).toFixed(2);
        // Assuming there's a DOM element for Capital Allocation in the stats section
        // If not, we might need to add one or integrate this into updateStatsDisplay
        // For now, let's add it to the existing stats list if the element exists
        const capitalAllocStat = document.getElementById('stat-capital-allocation'); // Need to add this ID in index.html
        if (capitalAllocStat) {
             capitalAllocStat.textContent = `${capitalAllocationPercent}%`;
        }
    } else {
        console.warn("State received without config object. Cannot update parameters.");
    }

    // Update Price Display
    updatePriceDisplay(state.latest_book_ticker);

    // Update active session indicator if session ID changes in state
    // This check might be better handled where the state update is received (e.g., WebSocket handler)
    // and then call the appropriate session manager function.
    // if (state.active_session_id !== undefined && state.active_session_id !== currentSessionId) {
    //     console.log("Active session ID changed via status update, refreshing sessions list.");
    //     // TODO: Replace with call to sessionManager.fetchAndDisplaySessions() when available
    //     // fetchAndDisplaySessions(); // Refresh list and selection
    // }
}

/**
 * Fills the parameter input fields based on the provided configuration.
 * @param {object} config - The configuration object from the bot state.
 * @param {string} strategyToFill - The strategy type ('SWING', 'SCALPING', 'SCALPING2') to fill parameters for.
 */
function fillParameters(config, strategyToFill) {
    if (!config) {
        console.warn("fillParameters called without config object.");
        return;
    }

    // Helper function to convert backend fractions to frontend percentages
    const toPercent = (value) => (value !== null && value !== undefined && !isNaN(parseFloat(value))) ? (parseFloat(value) * 100).toString() : '';

    // Common Params (Risk/Capital/Exit/Cooldown) - ALWAYS FILLED
    if (DOM.paramRisk) DOM.paramRisk.value = toPercent(config.RISK_PER_TRADE);
    if (DOM.paramCapitalAllocation) DOM.paramCapitalAllocation.value = toPercent(config.CAPITAL_ALLOCATION);
    if (DOM.paramSl) DOM.paramSl.value = toPercent(config.STOP_LOSS_PERCENTAGE);
    if (DOM.paramTp1) DOM.paramTp1.value = toPercent(config.TAKE_PROFIT_1_PERCENTAGE);
    if (DOM.paramTp2) DOM.paramTp2.value = toPercent(config.TAKE_PROFIT_2_PERCENTAGE);
    if (DOM.paramTrailing) DOM.paramTrailing.value = toPercent(config.TRAILING_STOP_PERCENTAGE);
    if (DOM.paramTimeStop) DOM.paramTimeStop.value = config.TIME_STOP_MINUTES ?? '';
    if (DOM.paramOrderCooldown) DOM.paramOrderCooldown.value = config.ORDER_COOLDOWN_MS ?? '';

    // SWING Params - Fill ONLY if SWING is the strategy to fill
    if (strategyToFill === 'SWING') {
        if (DOM.paramTimeframe) DOM.paramTimeframe.value = config.TIMEFRAME || '1m';
        if (DOM.paramEmaShort) DOM.paramEmaShort.value = config.EMA_SHORT_PERIOD ?? '';
        if (DOM.paramEmaLong) DOM.paramEmaLong.value = config.EMA_LONG_PERIOD ?? '';
        if (DOM.paramEmaFilter) DOM.paramEmaFilter.value = config.EMA_FILTER_PERIOD ?? '';
        if (DOM.paramRsiPeriod) DOM.paramRsiPeriod.value = config.RSI_PERIOD ?? '';
        if (DOM.paramRsiOb) DOM.paramRsiOb.value = config.RSI_OVERBOUGHT ?? '';
        if (DOM.paramRsiOs) DOM.paramRsiOs.value = config.RSI_OVERSOLD ?? '';
        if (DOM.paramVolumeAvg) DOM.paramVolumeAvg.value = config.VOLUME_AVG_PERIOD ?? '';
        if (DOM.paramUseEmaFilter) DOM.paramUseEmaFilter.checked = config.USE_EMA_FILTER ?? false;
        if (DOM.paramUseVolume) DOM.paramUseVolume.checked = config.USE_VOLUME_CONFIRMATION ?? false;
    }

    // SCALPING (Order Book) Specific Params - Fill ONLY if SCALPING is the strategy to fill
    if (strategyToFill === 'SCALPING') {
        if(DOM.paramScalpingOrderType) DOM.paramScalpingOrderType.value = config.SCALPING_ORDER_TYPE || 'MARKET';
        if(DOM.paramScalpingLimitTif) DOM.paramScalpingLimitTif.value = config.SCALPING_LIMIT_TIF || 'GTC';
        if(DOM.paramScalpingLimitTimeout) DOM.paramScalpingLimitTimeout.value = config.SCALPING_LIMIT_ORDER_TIMEOUT_MS ?? '';
        if(DOM.paramScalpingDepthLevels) DOM.paramScalpingDepthLevels.value = config.SCALPING_DEPTH_LEVELS || '5';
        if(DOM.paramScalpingDepthSpeed) DOM.paramScalpingDepthSpeed.value = config.SCALPING_DEPTH_SPEED || '1000ms';
        if(DOM.paramScalpingSpreadThreshold) DOM.paramScalpingSpreadThreshold.value = config.SCALPING_SPREAD_THRESHOLD ?? '';
        if(DOM.paramScalpingImbalanceThreshold) DOM.paramScalpingImbalanceThreshold.value = config.SCALPING_IMBALANCE_THRESHOLD ?? '';
    }

    // SCALPING 2 (Indicators) Specific Params - Fill ONLY if SCALPING2 is the strategy to fill
    if (strategyToFill === 'SCALPING2') {
        if (DOM.paramTimeframe) DOM.paramTimeframe.value = config.TIMEFRAME || '1m'; // Timeframe relevant too
        if (DOM.paramSupertrendAtr) DOM.paramSupertrendAtr.value = config.SUPERTREND_ATR_PERIOD ?? '';
        if (DOM.paramSupertrendMult) DOM.paramSupertrendMult.value = config.SUPERTREND_ATR_MULTIPLIER ?? '';
        if (DOM.paramRsiPeriodScalp) DOM.paramRsiPeriodScalp.value = config.SCALPING_RSI_PERIOD ?? '';
        if (DOM.paramStochK) DOM.paramStochK.value = config.STOCH_K_PERIOD ?? '';
        if (DOM.paramStochD) DOM.paramStochD.value = config.STOCH_D_PERIOD ?? '';
        if (DOM.paramStochSmooth) DOM.paramStochSmooth.value = config.STOCH_SMOOTH ?? '';
        if (DOM.paramBbPeriod) DOM.paramBbPeriod.value = config.BB_PERIOD ?? '';
        if (DOM.paramBbStd) DOM.paramBbStd.value = config.BB_STD ?? '';
        if (DOM.paramVolMa) DOM.paramVolMa.value = config.VOLUME_MA_PERIOD ?? '';
    }
}

/**
 * Updates the order history table using DataTables API.
 * @param {Array<object>} history - Array of order objects.
 */
function updateOrderHistory(history) {
    if (!orderHistoryTable) {
        console.error("DataTables instance for order history not initialized!");
        // Attempt to initialize if not already done
        initializeOrderHistoryTable();
        if (!orderHistoryTable) { // Check again after attempt
             appendLog("Impossible de mettre à jour l'historique : table non initialisée.", "error");
             return;
        }
    }

    // Prepare data for DataTables (array of arrays)
    const dataSet = (!Array.isArray(history) || history.length === 0) ? [] : history.map(order => {
        // --- Formatting logic ---
        const performancePctValue = order.performance_pct;
        let performancePctText = '-';
        let perfClass = '';
        if (performancePctValue !== null && performancePctValue !== undefined) {
            if (typeof performancePctValue === 'string' && performancePctValue.includes('%')) {
                performancePctText = performancePctValue;
                const numericPerf = parseFloat(performancePctValue.replace('%', ''));
                if (!isNaN(numericPerf)) {
                    perfClass = numericPerf >= 0 ? 'perf-positive' : 'perf-negative';
                }
            } else {
                const numericPerf = parseFloat(performancePctValue);
                if (!isNaN(numericPerf)) {
                    performancePctText = `${formatNumber(numericPerf * 100, 2)}%`;
                    perfClass = numericPerf >= 0 ? 'perf-positive' : 'perf-negative';
                }
            }
        }
        const performanceCell = `<span class="${perfClass}">${performancePctText}</span>`;

        let avgPrice = order.price;
        const executedQtyNum = parseFloat(order.executedQty || 0);
        const cummQuoteQtyNum = parseFloat(order.cummulativeQuoteQty || 0);

        if ((!avgPrice || parseFloat(avgPrice) === 0) && cummQuoteQtyNum > 0 && executedQtyNum > 0) {
            avgPrice = cummQuoteQtyNum / executedQtyNum;
        }
        const priceOrValueText = formatNumber(avgPrice, 4);

        let quoteValue = '-';
        if (!isNaN(cummQuoteQtyNum) && cummQuoteQtyNum > 0) {
            quoteValue = formatNumber(cummQuoteQtyNum, 2);
        } else if (!isNaN(executedQtyNum) && !isNaN(avgPrice)) {
            quoteValue = formatNumber(executedQtyNum * avgPrice, 2);
        }

        const sideClass = order.side === 'BUY' ? 'side-buy' : (order.side === 'SELL' ? 'side-sell' : '');
        const sideCell = `<span class="${sideClass}">${order.side || 'N/A'}</span>`;
        // --- End formatting logic ---

        // Return array for DataTables row
        return [
            formatTimestamp(order.timestamp), // Col 0: Date/Time
            order.symbol || 'N/A',            // Col 1: Symbol
            order.strategy || '-',            // Col 2: Strategy
            sideCell,                         // Col 3: Side (with class)
            order.type || 'N/A',              // Col 4: Type
            formatNumber(order.origQty, 8),   // Col 5: Qty Requested
            formatNumber(order.executedQty, 8),// Col 6: Qty Executed
            priceOrValueText,                 // Col 7: Price / Value
            quoteValue,                       // Col 8: Value (quote)
            order.status || 'N/A',            // Col 9: Status
            performanceCell,                  // Col 10: Performance (with class)
            order.orderId || 'N/A'            // Col 11: Order ID
        ];
    });

    // Update DataTables
    orderHistoryTable.clear();
    orderHistoryTable.rows.add(dataSet);
    orderHistoryTable.draw();
}

/**
 * Updates the visibility of strategy-specific parameter sections.
 * @param {string} selectedStrategy - The strategy selected ('SWING', 'SCALPING', 'SCALPING2').
 */
function updateParameterVisibility(selectedStrategy) {
    // Hide all specific sections by default
    if (DOM.swingParamsDiv) DOM.swingParamsDiv.style.display = 'none';
    if (DOM.scalpingOrderBookParamsDiv) DOM.scalpingOrderBookParamsDiv.style.display = 'none';
    if (DOM.scalping2SpecificParamsDiv) DOM.scalping2SpecificParamsDiv.style.display = 'none';

    // Re-enable Timeframe by default and clear relevance note
    if (DOM.paramTimeframe) DOM.paramTimeframe.disabled = false;
    if (DOM.timeframeRelevance) DOM.timeframeRelevance.textContent = '';

    // Show the relevant section and adjust Timeframe/note
    if (selectedStrategy === 'SWING') {
        if (DOM.swingParamsDiv) DOM.swingParamsDiv.style.display = 'block';
        if (DOM.timeframeRelevance) DOM.timeframeRelevance.textContent = '(Pertinent pour SWING)';
    } else if (selectedStrategy === 'SCALPING') {
        if (DOM.scalpingOrderBookParamsDiv) DOM.scalpingOrderBookParamsDiv.style.display = 'block';
        if (DOM.paramTimeframe) DOM.paramTimeframe.disabled = true; // Disable Timeframe
        if (DOM.timeframeRelevance) DOM.timeframeRelevance.textContent = '(Non pertinent pour SCALPING)';
    } else if (selectedStrategy === 'SCALPING2') {
        if (DOM.scalping2SpecificParamsDiv) DOM.scalping2SpecificParamsDiv.style.display = 'block';
        // Timeframe remains enabled
        if (DOM.timeframeRelevance) DOM.timeframeRelevance.textContent = '(Pertinent pour SCALPING2)';
    }
    // The 'general-params' section (containing common params) always remains visible
}

/**
 * Appends a message to the log output area.
 * @param {string} message - The message to log.
 * @param {string} [level='log'] - The log level ('log', 'info', 'warn', 'error').
 */
function appendLog(message, level = 'log') {
    if (!DOM.logOutput) {
        console.error("logOutput element not found!");
        return;
    }
    const logEntry = document.createElement('div');
    logEntry.textContent = message;
    logEntry.className = `log-entry log-${level}`; // Use CSS classes for styling
    DOM.logOutput.appendChild(logEntry);
    // Auto-scroll to the bottom
    DOM.logOutput.scrollTop = DOM.logOutput.scrollHeight;
}

/**
 * Updates the current price display based on ticker data.
 * @param {object|null} tickerData - The ticker data object (e.g., { b: 'bid', a: 'ask', c: 'last' }).
 */
function updatePriceDisplay(tickerData) {
    let displayPrice = 'N/A';
    if (tickerData && tickerData.b && tickerData.a) { // Use best bid/ask if available
        try {
            const bid = parseFloat(tickerData.b);
            const ask = parseFloat(tickerData.a);
            if (!isNaN(bid) && !isNaN(ask) && ask > 0) {
                const midPrice = (bid + ask) / 2;
                displayPrice = formatNumber(midPrice); // Format with default decimals
            } else if (!isNaN(bid)) {
                displayPrice = formatNumber(bid); // Fallback to bid
            } else if (!isNaN(ask)) {
                displayPrice = formatNumber(ask); // Fallback to ask
            }
        } catch (e) {
            console.error("Error parsing ticker bid/ask price:", e, tickerData);
            displayPrice = "Erreur";
        }
    } else if (tickerData && tickerData.c) { // Fallback to last price 'c'
        try {
            const lastPrice = parseFloat(tickerData.c);
            if (!isNaN(lastPrice)) {
                displayPrice = formatNumber(lastPrice); // Format with default decimals
            }
        } catch (e) {
            console.error("Error parsing ticker last price:", e, tickerData);
            displayPrice = "Erreur";
        }
    }

    if (DOM.priceValue) {
        DOM.priceValue.textContent = displayPrice;
    } else {
        console.warn("Element with ID 'current-price' not found for price update.");
    }
}

/**
 * Displays a trading signal event in the signals table.
 * @param {object} event - The signal event object from the backend.
 */
function displaySignalEvent(event) {
    const container = DOM.signalsOutput; // Use imported element
    if (!container) return;

    let table = container.querySelector("table.signals-table");
    // Create table if it doesn't exist
    if (!table) {
        table = document.createElement("table");
        table.className = "signals-table"; // Add class for styling
        table.innerHTML = `<thead><tr><th>Heure</th><th>Type</th><th>Direction</th><th>Validé</th><th>Raison</th><th>Prix</th></tr></thead><tbody></tbody>`;
        container.innerHTML = ""; // Clear container before adding table
        container.appendChild(table);
    }

    const tbody = table.querySelector("tbody");
    if (!tbody) return; // Should not happen if table was created

    const timestamp = new Date().toLocaleTimeString(); // Use current time for display
    const row = document.createElement("tr");

    // Populate row cells
    row.innerHTML = `
        <td>${timestamp}</td>
        <td>${event.signal_type ? event.signal_type.toUpperCase() : "-"}</td>
        <td>${event.direction ? event.direction.toUpperCase() : "-"}</td>
        <td>${event.valid ? "✅" : "❌"}</td>
        <td>${event.reason || "-"}</td>
        <td>${event.price !== undefined ? formatNumber(event.price, 2) : "-"}</td>
    `;

    // Insert new row at the top
    tbody.insertBefore(row, tbody.firstChild);

    // Limit the number of rows displayed
    const maxSignalRows = 5; // Keep only the 5 most recent signals
    while (tbody.rows.length > maxSignalRows) {
        tbody.deleteRow(tbody.rows.length - 1); // Remove the oldest row
    }
}

/**
 * Updates the statistics display area.
 * @param {object|null} stats - The statistics object or null to clear.
 */
function updateStatsDisplay(stats) {
    if (!stats) {
        // Clear stats display
        if (DOM.statRoi) DOM.statRoi.textContent = 'N/A';
        if (DOM.statWinrate) DOM.statWinrate.textContent = 'N/A';
        if (DOM.statWins) DOM.statWins.textContent = 'N/A';
        if (DOM.statLosses) DOM.statLosses.textContent = 'N/A';
        if (DOM.statTotal) DOM.statTotal.textContent = 'N/A';
        if (DOM.statAvgPnl) DOM.statAvgPnl.textContent = 'N/A';
        return;
    }

    // Update stats display using formatted values from backend or format here
    if (DOM.statRoi) DOM.statRoi.textContent = (stats.roi !== undefined && stats.roi !== null) ? `${formatNumber(stats.roi, 2)}%` : 'N/A';
    if (DOM.statWinrate) DOM.statWinrate.textContent = (stats.winrate !== undefined && stats.winrate !== null) ? `${formatNumber(stats.winrate, 2)}%` : 'N/A';
    if (DOM.statWins) DOM.statWins.textContent = stats.wins ?? 'N/A';
    if (DOM.statLosses) DOM.statLosses.textContent = stats.losses ?? 'N/A';
    if (DOM.statTotal) DOM.statTotal.textContent = stats.total_trades ?? 'N/A';
    if (DOM.statAvgPnl) DOM.statAvgPnl.textContent = (stats.avg_pnl !== undefined && stats.avg_pnl !== null) ? `${formatNumber(stats.avg_pnl, 2)}%` : 'N/A';
}

/**
 * Updates the parameter save status message.
 * @param {string} message - The message to display.
 * @param {'saving'|'success'|'error'|''} statusType - The type of status for styling.
 */
function updateParamSaveStatus(message, statusType) {
    if (DOM.paramSaveStatus) {
        DOM.paramSaveStatus.textContent = message;
        DOM.paramSaveStatus.className = `status-${statusType}`; // Assumes CSS classes like status-saving, status-success, status-error
    }
    if (DOM.saveParamsBtn) {
        DOM.saveParamsBtn.disabled = (statusType === 'saving');
    }
    // Clear message after a delay
    if (statusType === 'success' || statusType === 'error') {
        setTimeout(() => {
            if (DOM.paramSaveStatus) {
                DOM.paramSaveStatus.textContent = '';
                DOM.paramSaveStatus.className = '';
            }
        }, 5000); // Clear after 5 seconds
    }
}

/**
 * Gets the currently selected strategy from the dropdown.
 * @returns {string|null} The selected strategy value or null if selector doesn't exist.
 */
function getSelectedStrategy() {
    return DOM.strategySelector ? DOM.strategySelector.value : null;
}

/**
 * Gets the last known state received from the backend.
 * Used for re-filling parameters when strategy changes.
 * @returns {object | null}
 */
function getLastKnownState() {
    return lastKnownState;
}

/**
 * Starts the periodic polling for monitoring metrics.
 */
function startMetricsPolling() {
    // Clear any existing interval first
    if (metricsPollingInterval) {
        clearInterval(metricsPollingInterval);
    }
    // Fetch metrics immediately on start
    fetchAndDisplayMetrics();
    // Set up interval for periodic fetching
    metricsPollingInterval = setInterval(fetchAndDisplayMetrics, 5000); // Poll every 5 seconds
    console.log("Started metrics polling.");
}

/**
 * Stops the periodic polling for monitoring metrics.
 */
function stopMetricsPolling() {
    if (metricsPollingInterval) {
        clearInterval(metricsPollingInterval);
        metricsPollingInterval = null;
        console.log("Stopped metrics polling.");
    }
}

/**
 * Fetches metrics from the API and updates the relevant UI sections.
 */
async function fetchAndDisplayMetrics() {
    try {
        const metrics = await API.fetchMetrics();
        if (metrics) {
            // Update Performance Metrics (from /api/metrics -> metrics.performance)
            if (metrics.performance) {
                 const perf = metrics.performance;
                 const winRateElement = document.getElementById('stat-winrate'); // Already exists
                 const totalTradesElement = document.getElementById('stat-total'); // Already exists
                 const profitFactorElement = document.getElementById('stat-profit-factor'); // Need to add this ID
                 const maxDrawdownElement = document.getElementById('stat-max-drawdown'); // Need to add this ID
                 const avgTradeDurationElement = document.getElementById('stat-avg-trade-duration'); // Need to add this ID
                 const bestTradeElement = document.getElementById('stat-best-trade'); // Need to add this ID
                 const worstTradeElement = document.getElementById('stat-worst-trade'); // Need to add this ID
                 const avgProfitPerTradeElement = document.getElementById('stat-avg-profit-per-trade'); // Need to add this ID
                 const sharpeRatioElement = document.getElementById('stat-sharpe-ratio'); // Need to add this ID

                 if (winRateElement) winRateElement.textContent = (perf.win_rate !== undefined && perf.win_rate !== null) ? `${formatNumber(perf.win_rate * 100, 2)}%` : 'N/A';
                 if (totalTradesElement) totalTradesElement.textContent = perf.total_trades ?? 'N/A';
                 // Ajoutez les lignes suivantes pour mettre à jour les autres éléments de performance
                 if (profitFactorElement) profitFactorElement.textContent = (perf.profit_factor !== undefined && perf.profit_factor !== null) ? formatNumber(perf.profit_factor, 2) : 'N/A';
                 if (maxDrawdownElement) maxDrawdownElement.textContent = (perf.max_drawdown !== undefined && perf.max_drawdown !== null) ? `${formatNumber(perf.max_drawdown * 100, 2)}%` : 'N/A'; // Assuming drawdown is a fraction
                 if (avgTradeDurationElement) avgTradeDurationElement.textContent = (perf.avg_trade_duration !== undefined && perf.avg_trade_duration !== null) ? `${formatNumber(perf.avg_trade_duration / 60, 1)} min` : 'N/A'; // Assuming duration is in seconds
                 if (bestTradeElement) bestTradeElement.textContent = (perf.best_trade !== undefined && perf.best_trade !== null) ? `${formatNumber(perf.best_trade * 100, 2)}%` : 'N/A'; // Assuming trade results are fractions
                 if (worstTradeElement) worstTradeElement.textContent = (perf.worst_trade !== undefined && perf.worst_trade !== null) ? `${formatNumber(perf.worst_trade * 100, 2)}%` : 'N/A'; // Assuming trade results are fractions
                 if (avgProfitPerTradeElement) avgProfitPerTradeElement.textContent = (perf.avg_profit_per_trade !== undefined && perf.avg_profit_per_trade !== null) ? `${formatNumber(perf.avg_profit_per_trade * 100, 2)}%` : 'N/A'; // Assuming profit is a fraction
                 if (sharpeRatioElement) sharpeRatioElement.textContent = (perf.sharpe_ratio !== undefined && perf.sharpe_ratio !== null) ? formatNumber(perf.sharpe_ratio, 2) : 'N/A';

            }

            // Update System Metrics (from /api/metrics -> metrics.system)
            if (metrics.system) {
                 const system = metrics.system;
                 const cpuUsageElement = document.getElementById('stat-cpu-usage'); // Need to add this ID
                 const memoryUsageElement = document.getElementById('stat-memory-usage'); // Need to add this ID
                 const diskUsageElement = document.getElementById('stat-disk-usage'); // Need to add this ID
                 const memoryAvailableElement = document.getElementById('stat-memory-available'); // Need to add this ID
                 const swapUsageElement = document.getElementById('stat-swap-usage'); // Need to add this ID
                 const networkIoSentElement = document.getElementById('stat-network-io-sent'); // Need to add this ID
                 const networkIoRecvElement = document.getElementById('stat-network-io-recv'); // Need to add this ID
                 const processThreadsElement = document.getElementById('stat-process-threads'); // Need to add this ID
                 const systemUptimeElement = document.getElementById('stat-system-uptime'); // Need to add this ID
                 const botUptimeElement = document.getElementById('stat-bot-uptime'); // Need to add this ID

                 // Ajoutez les lignes suivantes pour mettre à jour les éléments système
                 if (cpuUsageElement) cpuUsageElement.textContent = (system.cpu_usage !== undefined && system.cpu_usage !== null) ? `${formatNumber(system.cpu_usage, 1)}%` : 'N/A';
                 if (memoryUsageElement) memoryUsageElement.textContent = (system.memory_usage !== undefined && system.memory_usage !== null) ? `${formatNumber(system.memory_usage, 1)}%` : 'N/A';
                 if (diskUsageElement) diskUsageElement.textContent = (system.disk_usage !== undefined && system.disk_usage !== null) ? `${formatNumber(system.disk_usage, 1)}%` : 'N/A';
                 if (memoryAvailableElement) memoryAvailableElement.textContent = (system.memory_available !== undefined && system.memory_available !== null) ? `${formatNumber(system.memory_available / (1024 * 1024), 2)} MB` : 'N/A'; // Assuming bytes, convert to MB
                 if (swapUsageElement) swapUsageElement.textContent = (system.swap_usage !== undefined && system.swap_usage !== null) ? `${formatNumber(system.swap_usage, 1)}%` : 'N/A';
                 if (networkIoSentElement) networkIoSentElement.textContent = (system.network_io_sent !== undefined && system.network_io_sent !== null) ? `${formatNumber(system.network_io_sent / 1024, 2)} KB/s` : 'N/A'; // Assuming bytes/s, convert to KB/s
                 if (networkIoRecvElement) networkIoRecvElement.textContent = (system.network_io_recv !== undefined && system.network_io_recv !== null) ? `${formatNumber(system.network_io_recv / 1024, 2)} KB/s` : 'N/A'; // Assuming bytes/s, convert to KB/s
                 if (processThreadsElement) processThreadsElement.textContent = system.process_threads ?? 'N/A';
                 if (systemUptimeElement) systemUptimeElement.textContent = (system.system_uptime !== undefined && system.system_uptime !== null) ? `${formatNumber(system.system_uptime / 60, 0)} min` : 'N/A'; // Assuming seconds
                 if (botUptimeElement) botUptimeElement.textContent = (system.bot_uptime !== undefined && system.bot_uptime !== null) ? `${formatNumber(system.bot_uptime / 60, 0)} min` : 'N/A'; // Assuming seconds

            }

            // Update Realtime Metrics (from /api/metrics -> metrics.realtime)
            if (metrics.realtime) {
                 const realtime = metrics.realtime;
                 const ordersPerMinuteElement = document.getElementById('stat-orders-per-minute'); // Need to add this ID
                 const apiCallsPerMinuteElement = document.getElementById('stat-api-calls-per-minute'); // Need to add this ID
                 const wsReconnectsElement = document.getElementById('stat-ws-reconnects'); // Need to add this ID
                 const lastOrderLatencyElement = document.getElementById('stat-last-order-latency'); // Need to add this ID
                 const averageOrderLatencyElement = document.getElementById('stat-average-order-latency'); // Need to add this ID
                 const orderQueueSizeElement = document.getElementById('stat-order-queue-size'); // Need to add this ID
                 const lastSignalTimeElement = document.getElementById('stat-last-signal-time'); // Need to add this ID
                 const signalsPerHourElement = document.getElementById('stat-signals-per-hour'); // Need to add this ID
                 const currentPositionDurationElement = document.getElementById('stat-current-position-duration'); // Need to add this ID
                 const lastErrorTimeElement = document.getElementById('stat-last-error-time'); // Need to add this ID
                 const errorCountElement = document.getElementById('stat-error-count'); // Need to add this ID

                 // Ajoutez les lignes suivantes pour mettre à jour les éléments temps réel
                 if (ordersPerMinuteElement) ordersPerMinuteElement.textContent = (realtime.orders_per_minute !== undefined && realtime.orders_per_minute !== null) ? formatNumber(realtime.orders_per_minute, 1) : 'N/A';
                 if (apiCallsPerMinuteElement) apiCallsPerMinuteElement.textContent = (realtime.api_calls_per_minute !== undefined && realtime.api_calls_per_minute !== null) ? formatNumber(realtime.api_calls_per_minute, 1) : 'N/A';
                 if (wsReconnectsElement) wsReconnectsElement.textContent = realtime.websocket_reconnects ?? 'N/A';
                 if (lastOrderLatencyElement) lastOrderLatencyElement.textContent = (realtime.last_order_latency_ms !== undefined && realtime.last_order_latency_ms !== null) ? `${formatNumber(realtime.last_order_latency_ms, 0)} ms` : 'N/A';
                 if (averageOrderLatencyElement) averageOrderLatencyElement.textContent = (realtime.average_order_latency_ms !== undefined && realtime.average_order_latency_ms !== null) ? `${formatNumber(realtime.average_order_latency_ms, 0)} ms` : 'N/A';
                 if (orderQueueSizeElement) orderQueueSizeElement.textContent = realtime.order_queue_size ?? 'N/A';
                 if (lastSignalTimeElement) lastSignalTimeElement.textContent = (realtime.last_signal_time !== undefined && realtime.last_signal_time !== null) ? new Date(realtime.last_signal_time * 1000).toLocaleTimeString() : 'N/A'; // Assuming timestamp in seconds
                 if (signalsPerHourElement) signalsPerHourElement.textContent = (realtime.signals_per_hour !== undefined && realtime.signals_per_hour !== null) ? formatNumber(realtime.signals_per_hour, 1) : 'N/A';
                 if (currentPositionDurationElement) currentPositionDurationElement.textContent = (realtime.current_position_duration_seconds !== undefined && realtime.current_position_duration_seconds !== null) ? `${formatNumber(realtime.current_position_duration_seconds / 60, 0)} min` : 'N/A'; // Assuming seconds
                 if (lastErrorTimeElement) lastErrorTimeElement.textContent = (realtime.last_error_time !== undefined && realtime.last_error_time !== null) ? new Date(realtime.last_error_time * 1000).toLocaleTimeString() : 'N/A'; // Assuming timestamp in seconds
                 if (errorCountElement) errorCountElement.textContent = realtime.error_count ?? 'N/A';

            }

            // Note: Chart updates are not handled here, as the plan is to integrate metrics into existing stats section.
            // The monitoring.js file's chart logic might become redundant or need to be adapted.

        }
    } catch (error) {
        console.error('Error fetching and displaying metrics:', error);
        // UI.appendLog(`Erreur affichage métriques: ${error.message}`, 'error'); // Trop verbeux
        // Optionally clear metric displays on error
    }
}
// Keep updateOrderHistory, updateParameterVisibility, appendLog, updatePriceDisplay, displaySignalEvent, updateStatsDisplay, getSelectedStrategy, getLastKnownState as they are.

// Remove or comment out the initializeMonitoring and updateMetrics functions from monitoring.js if they are integrated here.
// The plan is to integrate, so let's assume monitoring.js will be removed or refactored.
// The logic from monitoring.js's updateMetrics is now partially moved into fetchAndDisplayMetrics.
// The chart logic from monitoring.js is not being moved here as per the plan to integrate into existing stats.

// // Export the new functions
export {
    initializeOrderHistoryTable,
    updateUI,
    fillParameters,
    updateOrderHistory,
    updateParameterVisibility,
    updateParamSaveStatus,
    appendLog,
    updatePriceDisplay,
    displaySignalEvent,
    updateStatsDisplay,
    getSelectedStrategy,
    getLastKnownState,
    startMetricsPolling,
    stopMetricsPolling,  
    fetchAndDisplayMetrics,
    
    
    
}
