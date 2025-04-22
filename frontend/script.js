// /Users/davidmichels/Desktop/trading-bot/frontend/script.js

document.addEventListener('DOMContentLoaded', () => {

    // --- Configuration ---
    const API_BASE_URL = `http://${window.location.hostname}:5000`;
    const WS_URL = `ws://${window.location.hostname}:5000/ws_logs`;

    // --- DOM Element References ---
    const statusValue = document.getElementById('status-value');
    const strategyTypeValueSpan = document.getElementById('strategy-type-value');
    const symbolValue = document.getElementById('symbol-value');
    const timeframeValue = document.getElementById('timeframe-value');
    const balanceValue = document.getElementById('balance-value');
    const quantityValue = document.getElementById('quantity-value');
    const priceValue = document.getElementById('current-price');
    const positionValue = document.getElementById('position-value');
    const quoteAssetLabel = document.getElementById('quote-asset-label');
    const baseAssetLabel = document.getElementById('base-asset-label');
    const symbolPriceLabel = document.getElementById('symbol-price-label');
    const orderHistoryBody = document.getElementById('order-history-body');
    const orderHistoryPlaceholder = document.getElementById('order-history-placeholder');
    const logOutput = document.getElementById('log-output');
    const startBotBtn = document.getElementById('start-bot-btn');
    const stopBotBtn = document.getElementById('stop-bot-btn');
    const saveParamsBtn = document.getElementById('save-params-btn');
    const paramSaveStatus = document.getElementById('param-save-status');

    // Parameter Inputs
    const strategySelector = document.getElementById('param-strategy-type');
    const swingParamsDiv = document.getElementById('swing-params');
    const scalpingParamsDiv = document.getElementById('scalping-params');
    const timeframeRelevance = document.getElementById('timeframe-relevance');

    // SWING Params
    const paramTimeframe = document.getElementById('param-timeframe');
    const paramEmaShort = document.getElementById('param-ema-short');
    const paramEmaLong = document.getElementById('param-ema-long');
    const paramEmaFilter = document.getElementById('param-ema-filter');
    const paramRsiPeriod = document.getElementById('param-rsi-period');
    const paramRsiOb = document.getElementById('param-rsi-ob');
    const paramRsiOs = document.getElementById('param-rsi-os');
    const paramRisk = document.getElementById('param-risk');
    const paramCapitalAllocation = document.getElementById('param-capital-allocation');
    const paramVolumeAvg = document.getElementById('param-volume-avg');
    const paramUseEmaFilter = document.getElementById('param-use-ema-filter');
    const paramUseVolume = document.getElementById('param-use-volume');

    // SCALPING Params
    const paramSl = document.getElementById('param-sl');
    const paramTp1 = document.getElementById('param-tp1');
    const paramTp2 = document.getElementById('param-tp2');

    // Scalping Advanced Params
    const paramSupertrendAtr = document.getElementById('param-supertrend-atr');
    const paramSupertrendMult = document.getElementById('param-supertrend-mult');
    const paramRsiPeriodScalp = document.getElementById('param-rsi-period-scalp');
    const paramStochK = document.getElementById('param-stoch-k');
    const paramStochD = document.getElementById('param-stoch-d');
    const paramStochSmooth = document.getElementById('param-stoch-smooth');
    const paramBbPeriod = document.getElementById('param-bb-period');
    const paramBbStd = document.getElementById('param-bb-std');
    const paramTrailing = document.getElementById('param-trailing');
    const paramTimeStop = document.getElementById('param-time-stop');
    const paramVolMa = document.getElementById('param-vol-ma');

    let ws = null; // WebSocket connection

    // --- Helper Functions ---

    function formatNumber(num, decimals = 8) {
        const number = parseFloat(num);
        if (isNaN(number) || num === null || num === undefined) return 'N/A';
        if (Math.abs(number) > 1000) decimals = 2;
        else if (Math.abs(number) > 10) decimals = 4;
        else if (Math.abs(number) > 0.1) decimals = 6;
        try {
            return number.toLocaleString(undefined, {
                minimumFractionDigits: decimals,
                maximumFractionDigits: decimals
            });
        } catch (e) {
            console.error("Error formatting number:", num, e);
            return number.toFixed(decimals);
        }
    }

    function formatTimestamp(timestamp) {
        if (!timestamp) return 'N/A';
        try {
            const date = new Date(parseInt(timestamp));
            if (isNaN(date.getTime())) return 'Invalid Date';
            return date.toLocaleString();
        } catch (e) {
            console.error("Error formatting timestamp:", timestamp, e);
            return 'Invalid Date';
        }
    }

    function updateParameterVisibility(selectedStrategy) {
        if (selectedStrategy === 'SCALPING' || selectedStrategy === 'SCALPING2') {
            swingParamsDiv.style.display = 'none';
            scalpingParamsDiv.style.display = 'block';
            paramTimeframe.disabled = true;
            timeframeRelevance.textContent = '(Non pertinent pour SCALPING)';
        } else {
            swingParamsDiv.style.display = 'block';
            scalpingParamsDiv.style.display = 'none';
            paramTimeframe.disabled = false;
            timeframeRelevance.textContent = '(Pertinent pour SWING)';
        }
    }

    // --- Log Appending Function ---
    function appendLog(message, level = 'log') {
        if (!logOutput) {
            console.error("logOutput element not found!");
            return;
        }
        const logEntry = document.createElement('div');
        logEntry.textContent = message;
        logEntry.className = `log-entry log-${level}`;
        logOutput.appendChild(logEntry);
        logOutput.scrollTop = logOutput.scrollHeight;
    }

    // --- Factorized Price Update Function ---
    function updatePriceDisplay(tickerData) {
        let displayPrice = 'N/A';
        if (tickerData && tickerData.b && tickerData.a) {
            try {
                const bid = parseFloat(tickerData.b);
                const ask = parseFloat(tickerData.a);
                if (!isNaN(bid) && !isNaN(ask) && ask > 0) {
                    const midPrice = (bid + ask) / 2;
                    displayPrice = formatNumber(midPrice, 2);
                } else if (!isNaN(bid)) {
                    displayPrice = formatNumber(bid, 2); // Fallback to bid
                }
            } catch (e) {
                console.error("Error parsing ticker price:", e, tickerData);
                displayPrice = "Erreur";
            }
        }
        if (priceValue) {
            priceValue.textContent = displayPrice;
        } else {
            console.warn("Element with ID 'current-price' not found for price update.");
        }
    }

    // --- WebSocket Logic ---
    function connectWebSocket() {
        if (ws) {
            console.warn("WebSocket connection already exists or is connecting.");
            return;
        }
        console.log(`Attempting to connect WebSocket to: ${WS_URL}`);
        appendLog("Tentative de connexion au backend...", "info");
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            console.log('WebSocket connection established');
            appendLog("WebSocket connecté.", "info");
            fetchBotState();
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                // console.debug('WebSocket message received:', data); // Keep commented unless debugging

                switch (data.type) {
                    case 'log':
                        appendLog(data.message, 'log');
                        break;
                    case 'info':
                        appendLog(data.message, 'info');
                        break;
                    case 'error':
                        appendLog(`ERREUR Backend: ${data.message}`, 'error');
                        break;
                    case 'warning':
                        appendLog(data.message, 'warn');
                        break;
                    case 'critical':
                        appendLog(`CRITICAL: ${data.message}`, 'error');
                        break;
                    case 'status_update':
                        if (data.state) {
                            // console.log("Status Update Received:", data.state); // Keep commented unless debugging
                            updateUI(data.state); // Updates non-price elements
                            updatePriceDisplay(data.state.latest_book_ticker); // Updates price
                        } else {
                            console.warn("Received status_update without state data:", data);
                        }
                        break;
                    case 'ticker_update': // Handles lightweight ticker updates
                        // console.debug("Ticker Update Received:", data.ticker); // Keep commented unless debugging
                        updatePriceDisplay(data.ticker); // Updates only price
                        break;
                    case 'order_history_update':
                        if (data.history) {
                            // console.log("Order History Update Received:", data.history); // Keep commented unless debugging
                            updateOrderHistory(data.history);
                            appendLog("Historique des ordres mis à jour.", "info");
                        } else {
                            console.warn("Received order_history_update without history data:", data);
                        }
                        break;
                    case 'ping':
                        // Server might send pings, client usually handles pongs automatically
                        // If explicit pong is needed: ws.send(JSON.stringify({ type: 'pong' }));
                        break;
                    case 'signal_event':
                        displaySignalEvent(data);
                        break;
                    default:
                        console.warn('Unknown WebSocket message type received:', data);
                        appendLog(`[WS Type Inconnu: ${data.type}] ${JSON.stringify(data.message || data.payload || data)}`, 'warn');
                }

            } catch (error) {
                console.error('Error processing WebSocket message (Malformed JSON?):', error);
                appendLog(`Erreur traitement WS (JSON invalide?): ${event.data}`, 'error');
            }
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            appendLog('Erreur de connexion WebSocket. Le backend est-il démarré et accessible?', 'error');
            statusValue.textContent = 'Erreur Connexion';
            statusValue.className = 'status-error';
            stopBotBtn.disabled = true;
            startBotBtn.disabled = false;
            ws = null;
        };

        ws.onclose = (event) => {
            const wasConnected = !!ws; // Check if ws was non-null before resetting
            ws = null; // Reset ws variable FIRST
            console.log(`WebSocket connection closed. Code: ${event.code}, Reason: ${event.reason}`);

            // Update UI to reflect disconnected state
            statusValue.textContent = 'Déconnecté';
            statusValue.className = 'status-stopped';
            stopBotBtn.disabled = true;
            startBotBtn.disabled = false;

            // Only log warning and attempt reconnect if closure was unexpected
            if (wasConnected && event.code !== 1000 && event.code !== 1001) { // 1000 = Normal, 1001 = Going Away
                 appendLog(`Connexion WebSocket fermée (Code: ${event.code}). Tentative de reconnexion dans 5s...`, 'warn');
                 // Simple reconnect attempt after 5 seconds
                 setTimeout(connectWebSocket, 5000); // ADDED RECONNECTION ATTEMPT
            } else {
                 appendLog(`Connexion WebSocket fermée.`, 'info');
            }
        };
    }

    // --- UI Update Functions ---

    function updateUI(state) {
        if (!state) {
            console.warn("updateUI called with null or undefined state");
            return;
        }

        // Update Bot Status section - only if elements exist
        if (statusValue) statusValue.textContent = state.status || 'Inconnu';
        if (statusValue) statusValue.className = `status-${(state.status || 'unknown').toLowerCase()}`;
        if (strategyTypeValueSpan) strategyTypeValueSpan.textContent = state.config?.STRATEGY_TYPE || 'N/A';
        if (symbolValue) symbolValue.textContent = state.symbol || 'N/A';
        if (timeframeValue) timeframeValue.textContent = state.timeframe || 'N/A';
        if (quoteAssetLabel) quoteAssetLabel.textContent = state.quote_asset || 'USDT';
        if (baseAssetLabel) baseAssetLabel.textContent = state.base_asset || 'N/A';
        if (symbolPriceLabel) symbolPriceLabel.textContent = state.symbol ? `${state.symbol} / ${state.quote_asset || 'USDT'}` : 'N/A';
        if (balanceValue) balanceValue.textContent = formatNumber(state.available_balance, 2);
        if (quantityValue) quantityValue.textContent = formatNumber(state.symbol_quantity, 8);

        // Update Position Status
        if (positionValue) {
            if (state.in_position && state.entry_details) {
                const entryPrice = formatNumber(state.entry_details.avg_price, 2);
                const entryQty = formatNumber(state.entry_details.quantity, 8);
                positionValue.textContent = `Oui (Entrée @ ${entryPrice}, Qté: ${entryQty})`;
                positionValue.className = 'status-running';
            } else {
                positionValue.textContent = 'Aucune';
                positionValue.className = '';
            }
        }

        // Update Control Buttons state
        if (startBotBtn) startBotBtn.disabled = state.status === 'RUNNING' || state.status === 'STARTING';
        if (stopBotBtn) stopBotBtn.disabled = state.status !== 'RUNNING';

        // Update Parameter Inputs
        if (state.config) {
            // Strategy selector and visibility
            if (strategySelector) {
                strategySelector.value = state.config.STRATEGY_TYPE || 'SWING';
                updateParameterVisibility(strategySelector.value);
            }

            // Helper function to convert decimals to percentages
            const toPercent = (value) => value !== null && value !== undefined ? (value * 100).toString() : '';

            // SWING Params
            if (paramTimeframe) paramTimeframe.value = state.config.TIMEFRAME_STR || '1m';
            if (paramEmaShort) paramEmaShort.value = state.config.EMA_SHORT_PERIOD ?? '';
            if (paramEmaLong) paramEmaLong.value = state.config.EMA_LONG_PERIOD ?? '';
            if (paramEmaFilter) paramEmaFilter.value = state.config.EMA_FILTER_PERIOD ?? '';
            if (paramRsiPeriod) paramRsiPeriod.value = state.config.RSI_PERIOD ?? '';
            if (paramRsiOb) paramRsiOb.value = state.config.RSI_OVERBOUGHT ?? '';
            if (paramRsiOs) paramRsiOs.value = state.config.RSI_OVERSOLD ?? '';
            if (paramRisk) paramRisk.value = toPercent(state.config.RISK_PER_TRADE);
            if (paramCapitalAllocation) paramCapitalAllocation.value = toPercent(state.config.CAPITAL_ALLOCATION);
            if (paramVolumeAvg) paramVolumeAvg.value = state.config.VOLUME_AVG_PERIOD ?? '';
            if (paramUseEmaFilter) paramUseEmaFilter.checked = state.config.USE_EMA_FILTER ?? false;
            if (paramUseVolume) paramUseVolume.checked = state.config.USE_VOLUME_CONFIRMATION ?? false;

            // Scalping Advanced Params
            if (paramSupertrendAtr) paramSupertrendAtr.value = state.config.SUPERTREND_ATR_PERIOD ?? '3';
            if (paramSupertrendMult) paramSupertrendMult.value = state.config.SUPERTREND_ATR_MULTIPLIER ?? '1.5';
            if (paramRsiPeriodScalp) paramRsiPeriodScalp.value = state.config.SCALPING_RSI_PERIOD ?? '7';
            if (paramStochK) paramStochK.value = state.config.STOCH_K_PERIOD ?? '14';
            if (paramStochD) paramStochD.value = state.config.STOCH_D_PERIOD ?? '3';
            if (paramStochSmooth) paramStochSmooth.value = state.config.STOCH_SMOOTH ?? '3';
            if (paramBbPeriod) paramBbPeriod.value = state.config.BB_PERIOD ?? '20';
            if (paramBbStd) paramBbStd.value = state.config.BB_STD ?? '2';

            // Exit Parameters avec valeurs par défaut si la config est nulle
            if (paramSl) paramSl.value = toPercent(state.config.STOP_LOSS_PERCENTAGE) || '0.5';
            if (paramTp1) paramTp1.value = toPercent(state.config.TAKE_PROFIT_1_PERCENTAGE) || '0.75';
            if (paramTp2) paramTp2.value = toPercent(state.config.TAKE_PROFIT_2_PERCENTAGE) || '1.0';
            if (paramTrailing) paramTrailing.value = toPercent(state.config.TRAILING_STOP_PERCENTAGE) || '0.3';
            if (paramTimeStop) paramTimeStop.value = state.config.TIME_STOP_MINUTES ?? '15';
            if (paramVolMa) paramVolMa.value = state.config.VOLUME_MA_PERIOD ?? '20';
        } else {
            console.warn("State received without config object. Cannot update parameters.");
        }
    }

    function updateOrderHistory(history) {
        if (!orderHistoryBody) {
            console.error("Order history table body not found!");
            return;
        }
        orderHistoryBody.innerHTML = '';

        // console.log("Updating order history table with data:", history); // Keep commented unless debugging

        if (!Array.isArray(history) || history.length === 0) {
            if (orderHistoryPlaceholder) {
                 try {
                    const placeholderClone = orderHistoryPlaceholder.content.cloneNode(true);
                    orderHistoryBody.appendChild(placeholderClone);
                 } catch (e) {
                     console.error("Error using order history placeholder template:", e);
                     const row = orderHistoryBody.insertRow();
                     const cell = row.insertCell();
                     cell.colSpan = 10;
                     cell.textContent = "Aucun ordre dans l'historique.";
                     cell.style.textAlign = 'center';
                 }
            } else {
                 const row = orderHistoryBody.insertRow();
                 const cell = row.insertCell();
                 cell.colSpan = 10;
                 cell.textContent = "Aucun ordre dans l'historique.";
                 cell.style.textAlign = 'center';
            }
            return;
        }

        history.sort((a, b) => (parseInt(b.timestamp || 0)) - (parseInt(a.timestamp || 0)));

        history.forEach(order => {
            const row = document.createElement('tr');

            const performancePctValue = order.performance_pct;
            const performancePctText = (performancePctValue !== null && performancePctValue !== undefined)
                ? `${formatNumber(performancePctValue * 100, 2)}%`
                : '-';

            let avgPrice = order.price;
            const executedQtyNum = parseFloat(order.executedQty || 0);
            const cummQuoteQtyNum = parseFloat(order.cummulativeQuoteQty || 0);

            if ((!avgPrice || parseFloat(avgPrice) === 0) && cummQuoteQtyNum > 0 && executedQtyNum > 0) {
                avgPrice = cummQuoteQtyNum / executedQtyNum;
            }

            const priceOrValueText = formatNumber(avgPrice, 4);

            const sideClass = order.side === 'BUY' ? 'side-buy' : (order.side === 'SELL' ? 'side-sell' : '');
            const perfClass = (performancePctValue === null || performancePctValue === undefined) ? '' : (performancePctValue >= 0 ? 'perf-positive' : 'perf-negative');

            row.innerHTML = `
                <td>${formatTimestamp(order.timestamp)}</td>
                <td>${order.symbol || 'N/A'}</td>
                <td class="${sideClass}">${order.side || 'N/A'}</td>
                <td>${order.type || 'N/A'}</td>
                <td>${formatNumber(order.origQty, 8)}</td>
                <td>${formatNumber(order.executedQty, 8)}</td>
                <td>${priceOrValueText}</td>
                <td>${order.status || 'N/A'}</td>
                <td class="${perfClass}">${performancePctText}</td>
                <td>${order.orderId || 'N/A'}</td>
            `;
            orderHistoryBody.appendChild(row);
        });
    }


    // --- API Call Functions ---

    async function fetchBotState() {
        appendLog("Récupération de l'état initial du bot...", "info");
        try {
            const response = await fetch(`${API_BASE_URL}/api/status`);
            if (!response.ok) {
                let errorMsg = `HTTP error! status: ${response.status}`;
                try {
                    const errorResult = await response.json();
                    errorMsg = errorResult.message || errorMsg;
                } catch (e) { console.error("Error parsing error response:", e); }
                throw new Error(errorMsg);
            }
            const state = await response.json();
            updateUI(state);
            // History is updated via WebSocket push
            appendLog("État initial récupéré.", "info");
        } catch (error) {
            console.error('Error fetching bot state:', error);
            appendLog(`Erreur récupération état initial: ${error.message}`, 'error');
            statusValue.textContent = 'Erreur API';
            statusValue.className = 'status-error';
        }
    }

    async function startBot() {
        appendLog("Envoi de la commande Démarrer...", "info");
        startBotBtn.disabled = true;
        stopBotBtn.disabled = true;
        try {
            const response = await fetch(`${API_BASE_URL}/api/start`, { method: 'POST' });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.message || `Erreur serveur: ${response.status}`);
            }
            appendLog(result.message || 'Commande Démarrer envoyée.', 'info');
        } catch (error) {
            console.error('Error starting bot:', error);
            appendLog(`Erreur au démarrage du bot: ${error.message}`, 'error');
            startBotBtn.disabled = false;
            fetchBotState();
        }
    }

    async function stopBot() {
        appendLog("Envoi de la commande Arrêter...", "info");
        stopBotBtn.disabled = true;
        startBotBtn.disabled = true;
        try {
            const response = await fetch(`${API_BASE_URL}/api/stop`, { method: 'POST' });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.message || `Erreur serveur: ${response.status}`);
            }
            appendLog(result.message || 'Commande Arrêter envoyée.', 'info');
        } catch (error) {
            console.error('Error stopping bot:', error);
            appendLog(`Erreur à l'arrêt du bot: ${error.message}`, 'error');
            fetchBotState();
        }
    }

    async function saveParameters() {
        paramSaveStatus.textContent = 'Sauvegarde en cours...';
        paramSaveStatus.className = 'status-saving';
        saveParamsBtn.disabled = true;

        // Convert percentages to decimal values
        const toDecimal = (value) => value ? parseFloat(value) / 100 : null;

        const paramsToSend = {
            STRATEGY_TYPE: strategySelector.value,
            TIMEFRAME_STR: paramTimeframe.value,
            
            // SWING strategy params (existing)
            EMA_SHORT_PERIOD: parseInt(paramEmaShort.value) || null,
            EMA_LONG_PERIOD: parseInt(paramEmaLong.value) || null,
            EMA_FILTER_PERIOD: parseInt(paramEmaFilter.value) || null,
            RSI_PERIOD: parseInt(paramRsiPeriod.value) || null,
            RSI_OVERBOUGHT: parseInt(paramRsiOb.value) || null,
            RSI_OVERSOLD: parseInt(paramRsiOs.value) || null,
            RISK_PER_TRADE: toDecimal(paramRisk.value),
            CAPITAL_ALLOCATION: toDecimal(paramCapitalAllocation.value),
            VOLUME_AVG_PERIOD: parseInt(paramVolumeAvg.value) || null,
            USE_EMA_FILTER: paramUseEmaFilter.checked,
            USE_VOLUME_CONFIRMATION: paramUseVolume.checked,

            // Advanced Scalping strategy params
            SUPERTREND_ATR_PERIOD: parseInt(paramSupertrendAtr?.value) || 3,
            SUPERTREND_ATR_MULTIPLIER: parseFloat(paramSupertrendMult?.value) || 1.5,
            SCALPING_RSI_PERIOD: parseInt(paramRsiPeriodScalp?.value) || 7,
            STOCH_K_PERIOD: parseInt(paramStochK?.value) || 14,
            STOCH_D_PERIOD: parseInt(paramStochD?.value) || 3,
            STOCH_SMOOTH: parseInt(paramStochSmooth?.value) || 3,
            BB_PERIOD: parseInt(paramBbPeriod?.value) || 20,
            BB_STD: parseFloat(paramBbStd?.value) || 2,
            STOP_LOSS_PERCENTAGE: toDecimal(paramSl.value),
            TAKE_PROFIT_1_PERCENTAGE: toDecimal(paramTp1?.value),
            TAKE_PROFIT_2_PERCENTAGE: toDecimal(paramTp2?.value),
            TRAILING_STOP_PERCENTAGE: toDecimal(paramTrailing?.value),
            TIME_STOP_MINUTES: parseInt(paramTimeStop?.value) || 15,
            VOLUME_MA_PERIOD: parseInt(paramVolMa?.value) || 20,
        };

        try {
            const response = await fetch(`${API_BASE_URL}/api/parameters`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(paramsToSend),
            });
            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.message || `Erreur serveur: ${response.status}`);
            }
            paramSaveStatus.textContent = result.message || 'Paramètres sauvegardés!';
            paramSaveStatus.className = 'status-success';
        } catch (error) {
            console.error('Error saving parameters:', error);
            paramSaveStatus.textContent = `Erreur sauvegarde: ${error.message}`;
            paramSaveStatus.className = 'status-error';
        } finally {
            setTimeout(() => {
                paramSaveStatus.textContent = '';
                paramSaveStatus.className = '';
            }, 5000);
            saveParamsBtn.disabled = false;
        }
    }

    // --- Event Listeners ---
    if (startBotBtn) startBotBtn.addEventListener('click', startBot);
    if (stopBotBtn) stopBotBtn.addEventListener('click', stopBot);
    if (saveParamsBtn) saveParamsBtn.addEventListener('click', saveParameters);

    if (strategySelector) {
        strategySelector.addEventListener('change', (event) => {
            updateParameterVisibility(event.target.value);
        });
    }


    // --- Initial Setup ---
    if (strategySelector) {
        updateParameterVisibility(strategySelector.value);
    }
    connectWebSocket();

    function displaySignalEvent(event) {
        const container = document.getElementById("signals-output");
        if (!container) return;
        // Crée le tableau s'il n'existe pas
        let table = container.querySelector("table");
        if (!table) {
            table = document.createElement("table");
            table.className = "signals-table";
            table.innerHTML = `<thead><tr><th>Heure</th><th>Type</th><th>Direction</th><th>Validé</th><th>Raison</th><th>Prix</th></tr></thead><tbody></tbody>`;
            container.innerHTML = "";
            container.appendChild(table);
        }
        const tbody = table.querySelector("tbody");
        const ts = new Date().toLocaleTimeString();
        const row = document.createElement("tr");
        row.innerHTML = `
            <td>${ts}</td>
            <td>${event.signal_type ? event.signal_type.toUpperCase() : ""}</td>
            <td>${event.direction ? event.direction.toUpperCase() : ""}</td>
            <td>${event.valid ? "✅" : "❌"}</td>
            <td>${event.reason || ""}</td>
            <td>${event.price !== undefined ? event.price : ""}</td>
        `;
        // Ajoute la nouvelle ligne en haut
        tbody.insertBefore(row, tbody.firstChild);
        // Limite à 4 lignes
        while (tbody.rows.length > 4) {
            tbody.deleteRow(tbody.rows.length - 1);
        }
    }

}); // End DOMContentLoaded
