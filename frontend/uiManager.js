import * as DOM from './domElements.js';
import { formatNumber, formatTimestamp } from './utils.js';
// Import sessionManager functions when available
// import { fetchAndDisplaySessions } from './sessionManager.js';

let lastKnownState = null; // Stocke le dernier état reçu pour référence interne
let orderHistoryTable = null; // Instance DataTables

/**
 * Initializes the DataTables instance for the order history table.
 */
export function initializeOrderHistoryTable() {
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
export function updateUI(state) {
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

    // Update Position Status
    if (DOM.positionValue) {
        if (state.in_position && state.entry_details) {
            const entryPrice = formatNumber(state.entry_details.avg_price, 2);
            const entryQty = formatNumber(state.entry_details.quantity, 8);
            DOM.positionValue.textContent = `Oui (Entrée @ ${entryPrice}, Qté: ${entryQty})`;
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
export function fillParameters(config, strategyToFill) {
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
export function updateOrderHistory(history) {
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
export function updateParameterVisibility(selectedStrategy) {
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
export function appendLog(message, level = 'log') {
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
export function updatePriceDisplay(tickerData) {
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
export function displaySignalEvent(event) {
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
export function updateStatsDisplay(stats) {
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
export function updateParamSaveStatus(message, statusType) {
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
export function getSelectedStrategy() {
    return DOM.strategySelector ? DOM.strategySelector.value : null;
}

/**
 * Gets the last known state received from the backend.
 * Used for re-filling parameters when strategy changes.
 * @returns {object | null}
 */
export function getLastKnownState() {
    return lastKnownState;
}
