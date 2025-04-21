// /Users/davidmichels/Desktop/trading-bot/frontend/script.js

document.addEventListener('DOMContentLoaded', () => {

    // --- Configuration ---
    // Assurez-vous que cela pointe vers l'adresse et le PORT de votre backend Flask
    const API_BASE_URL = `http://${window.location.hostname}:5000`;
    const WS_URL = `ws://${window.location.hostname}:5000/ws_logs`;// URL pour WebSocket

    // --- DOM Element References ---
    const statusValue = document.getElementById('status-value');
    const strategyTypeValueSpan = document.getElementById('strategy-type-value');
    const symbolValue = document.getElementById('symbol-value');
    const timeframeValue = document.getElementById('timeframe-value');
    const balanceValue = document.getElementById('balance-value');
    const quantityValue = document.getElementById('quantity-value');
    const priceValue = document.getElementById('current-price'); // Corrected ID reference
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
    const paramTp = document.getElementById('param-tp');
    const paramLimitTimeout = document.getElementById('param-limit-timeout');

    let ws = null; // WebSocket connection

    // --- Helper Functions ---

    function formatNumber(num, decimals = 8) {
        const number = parseFloat(num);
        if (isNaN(number) || num === null || num === undefined) return 'N/A';
        // Adjust decimals based on magnitude for better readability
        if (Math.abs(number) > 1000) decimals = 2;
        else if (Math.abs(number) > 10) decimals = 4;
        else if (Math.abs(number) > 0.1) decimals = 6;
        // Use Intl.NumberFormat for locale-aware formatting (optional but good practice)
        try {
            return number.toLocaleString(undefined, {
                minimumFractionDigits: decimals,
                maximumFractionDigits: decimals
            });
        } catch (e) {
            console.error("Error formatting number:", num, e);
            return number.toFixed(decimals); // Fallback to simple toFixed
        }
    }

    function formatTimestamp(timestamp) {
        if (!timestamp) return 'N/A';
        try {
            const date = new Date(parseInt(timestamp));
            if (isNaN(date.getTime())) return 'Invalid Date';
            return date.toLocaleString(); // Format based on user's locale
        } catch (e) {
            console.error("Error formatting timestamp:", timestamp, e);
            return 'Invalid Date';
        }
    }

    function updateParameterVisibility(selectedStrategy) {
        if (selectedStrategy === 'SCALPING') {
            swingParamsDiv.style.display = 'none';
            scalpingParamsDiv.style.display = 'block';
            paramTimeframe.disabled = true;
            timeframeRelevance.textContent = '(Non pertinent pour SCALPING)';
        } else { // Default to SWING or other future strategies
            swingParamsDiv.style.display = 'block';
            scalpingParamsDiv.style.display = 'none';
            paramTimeframe.disabled = false;
            timeframeRelevance.textContent = '(Pertinent pour SWING)';
        }
    }

    // --- Log Appending Function ---
    function appendLog(message, level = 'log') { // level can be 'log', 'info', 'error', 'warn'
        if (!logOutput) {
            console.error("logOutput element not found!");
            return;
        }
        const logEntry = document.createElement('div');
        // Use textContent for safety against XSS if messages could contain HTML
        logEntry.textContent = message;
        logEntry.className = `log-entry log-${level}`; // Add classes for styling
        logOutput.appendChild(logEntry);
        // Auto-scroll to the bottom
        logOutput.scrollTop = logOutput.scrollHeight;
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
            // Request initial state upon connection (API call)
            fetchBotState();
            // Note: Initial history is sent by backend upon connection via WS now
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                console.debug('WebSocket message received:', data); // Keep for debugging

                switch (data.type) {
                    case 'log':
                        appendLog(data.message, 'log');
                        break;
                    case 'info':
                        appendLog(data.message, 'info');
                        break;
                    case 'error': // Specific error message from backend
                        appendLog(`ERREUR Backend: ${data.message}`, 'error');
                        break;
                    case 'warning': // Use appendLog consistently
                        appendLog(data.message, 'warn');
                        break;
                    case 'critical': // Use appendLog consistently
                        appendLog(`CRITICAL: ${data.message}`, 'error'); // Treat critical as error visually
                        break;
                    case 'status_update':
                        if (data.state) {
                            console.log("Status Update Received:", data.state); // Debug log
                            updateUI(data.state);
                            // appendLog("État du bot mis à jour.", "info"); // Can be noisy
                        } else {
                            console.warn("Received status_update without state data:", data);
                        }
                        break;
                    case 'order_history_update':
                        if (data.history) {
                            console.log("Order History Update Received:", data.history); // Debug log
                            updateOrderHistory(data.history);
                            appendLog("Historique des ordres mis à jour.", "info");
                        } else {
                            console.warn("Received order_history_update without history data:", data);
                        }
                        break;
                    case 'ping':
                        // console.debug('WebSocket ping received'); // Ignore ping
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
            ws = null; // Reset ws variable
        };

        ws.onclose = (event) => {
            console.log(`WebSocket connection closed. Code: ${event.code}, Reason: ${event.reason}`);
            // Only log warning if closure was unexpected
            if (ws && event.code !== 1000 && event.code !== 1001) {
                 appendLog(`Connexion WebSocket fermée (Code: ${event.code}). Tentative de reconnexion possible.`, 'warn');
            } else if (!ws) { // If ws is already null, it was likely intentional or handled by onerror
                 appendLog(`Connexion WebSocket fermée.`, 'info');
            }
            // Update UI to reflect disconnected state
            statusValue.textContent = 'Déconnecté';
            statusValue.className = 'status-stopped'; // Use 'stopped' style for disconnected
            stopBotBtn.disabled = true;
            startBotBtn.disabled = false; // Allow attempting to reconnect via start
            ws = null; // Reset ws variable
            // Optional: Implement automatic reconnection logic here if desired
            // setTimeout(connectWebSocket, 5000); // Be careful with infinite loops
        };
    }

    // --- UI Update Functions ---

    function updateUI(state) {
        if (!state) {
            console.warn("updateUI called with null or undefined state");
            return;
        }
        console.log("Updating UI with state:", state); // Keep this debug log

        // Update Bot Status section
        statusValue.textContent = state.status || 'Inconnu';
        // Apply CSS class based on status
        statusValue.className = `status-${(state.status || 'unknown').toLowerCase()}`;
        strategyTypeValueSpan.textContent = state.config?.STRATEGY_TYPE || 'N/A'; // Use optional chaining
        symbolValue.textContent = state.symbol || 'N/A';
        timeframeValue.textContent = state.timeframe || 'N/A';
        quoteAssetLabel.textContent = state.quote_asset || 'USDT';
        baseAssetLabel.textContent = state.base_asset || 'N/A';
        symbolPriceLabel.textContent = state.symbol ? `${state.symbol} / ${state.quote_asset || 'USDT'}` : 'N/A';
        balanceValue.textContent = formatNumber(state.available_balance, 2); // Format quote balance
        quantityValue.textContent = formatNumber(state.symbol_quantity, 8); // Format base quantity

        // --- Update current price using latest_book_ticker ---
        let displayPrice = 'N/A';
        if (state.latest_book_ticker && state.latest_book_ticker.b && state.latest_book_ticker.a) {
            try {
                const bid = parseFloat(state.latest_book_ticker.b);
                const ask = parseFloat(state.latest_book_ticker.a);
                if (!isNaN(bid) && !isNaN(ask) && ask > 0) { // Ensure ask is positive for mid-price calc
                    // Display mid-price with appropriate precision
                    const midPrice = (bid + ask) / 2;
                    displayPrice = formatNumber(midPrice, 2); // Use formatNumber for consistency
                } else if (!isNaN(bid)) {
                    displayPrice = formatNumber(bid, 2); // Fallback to bid if ask is invalid
                }
            } catch (e) {
                console.error("Error parsing ticker price:", e, state.latest_book_ticker);
                displayPrice = "Erreur";
            }
        }
        priceValue.textContent = displayPrice;
        // --- End Price Update ---

        // Update Position Status
        if (state.in_position && state.entry_details) {
            const entryPrice = formatNumber(state.entry_details.avg_price, 2); // Format entry price
            const entryQty = formatNumber(state.entry_details.quantity, 8); // Format entry quantity
            positionValue.textContent = `Oui (Entrée @ ${entryPrice}, Qté: ${entryQty})`;
            positionValue.className = 'status-running'; // Use 'running' style for active position
        } else {
            positionValue.textContent = 'Aucune';
            positionValue.className = ''; // Reset class
        }

        // Update Control Buttons state based on bot status
        startBotBtn.disabled = state.status === 'RUNNING' || state.status === 'STARTING';
        stopBotBtn.disabled = state.status !== 'RUNNING';

        // Update Parameter Inputs if config is present
        if (state.config) {
            // Only update inputs if the bot is NOT running to avoid overwriting user changes
            // Or, alternatively, always update to reflect the backend's current config
            // Let's always update for now to ensure consistency
            strategySelector.value = state.config.STRATEGY_TYPE || 'SWING';
            updateParameterVisibility(strategySelector.value);

            // SWING Params
            paramTimeframe.value = state.config.TIMEFRAME_STR || '1m'; // Default to 1m if missing
            paramEmaShort.value = state.config.EMA_SHORT_PERIOD ?? '';
            paramEmaLong.value = state.config.EMA_LONG_PERIOD ?? '';
            paramEmaFilter.value = state.config.EMA_FILTER_PERIOD ?? '';
            paramRsiPeriod.value = state.config.RSI_PERIOD ?? '';
            paramRsiOb.value = state.config.RSI_OVERBOUGHT ?? '';
            paramRsiOs.value = state.config.RSI_OVERSOLD ?? '';
            paramRisk.value = state.config.RISK_PER_TRADE ?? '';
            paramCapitalAllocation.value = state.config.CAPITAL_ALLOCATION ?? '';
            paramVolumeAvg.value = state.config.VOLUME_AVG_PERIOD ?? '';
            paramUseEmaFilter.checked = state.config.USE_EMA_FILTER || false;
            paramUseVolume.checked = state.config.USE_VOLUME_CONFIRMATION || false;

            // SCALPING Params
            paramSl.value = state.config.STOP_LOSS_PERCENTAGE ?? '';
            paramTp.value = state.config.TAKE_PROFIT_PERCENTAGE ?? '';
            paramLimitTimeout.value = state.config.SCALPING_LIMIT_ORDER_TIMEOUT_MS ?? '';
        } else {
            console.warn("State received without config object. Cannot update parameters.");
        }
    }

    function updateOrderHistory(history) {
        if (!orderHistoryBody) {
            console.error("Order history table body not found!");
            return;
        }
        orderHistoryBody.innerHTML = ''; // Clear existing rows

        console.log("Updating order history table with data:", history); // Keep this debug log

        if (!Array.isArray(history) || history.length === 0) {
            // Use placeholder template if available
            if (orderHistoryPlaceholder) {
                 try {
                    const placeholderClone = orderHistoryPlaceholder.content.cloneNode(true);
                    orderHistoryBody.appendChild(placeholderClone);
                 } catch (e) {
                     console.error("Error using order history placeholder template:", e);
                     // Fallback if template fails
                     const row = orderHistoryBody.insertRow();
                     const cell = row.insertCell();
                     cell.colSpan = 10; // Adjust to number of columns
                     cell.textContent = "Aucun ordre dans l'historique.";
                     cell.style.textAlign = 'center';
                 }
            } else {
                 // Fallback if placeholder template ID is wrong or missing
                 const row = orderHistoryBody.insertRow();
                 const cell = row.insertCell();
                 cell.colSpan = 10; // Adjust to number of columns
                 cell.textContent = "Aucun ordre dans l'historique.";
                 cell.style.textAlign = 'center';
            }
            return;
        }

        // Sort history by timestamp descending (ensure timestamps are numbers)
        history.sort((a, b) => (parseInt(b.timestamp || 0)) - (parseInt(a.timestamp || 0)));

        history.forEach(order => {
            const row = document.createElement('tr'); // Create row element

            // Format performance percentage
            const performancePctValue = order.performance_pct;
            const performancePctText = (performancePctValue !== null && performancePctValue !== undefined)
                ? `${formatNumber(performancePctValue * 100, 2)}%` // Format as percentage
                : '-'; // Use hyphen for N/A

            // Calculate average price if not directly available but quantities are
            let avgPrice = order.price; // Use order price by default (for LIMIT)
            const executedQtyNum = parseFloat(order.executedQty || 0);
            const cummQuoteQtyNum = parseFloat(order.cummulativeQuoteQty || 0);

            if ((!avgPrice || parseFloat(avgPrice) === 0) && cummQuoteQtyNum > 0 && executedQtyNum > 0) {
                avgPrice = cummQuoteQtyNum / executedQtyNum; // Calculate average price
            }

            // Format the price/value column
            const priceOrValueText = formatNumber(avgPrice, 4); // Format avg price with 4 decimals

            // Determine CSS classes for side and performance
            const sideClass = order.side === 'BUY' ? 'side-buy' : (order.side === 'SELL' ? 'side-sell' : '');
            const perfClass = (performancePctValue === null || performancePctValue === undefined) ? '' : (performancePctValue >= 0 ? 'perf-positive' : 'perf-negative');

            // Populate row using innerHTML for structure
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
            orderHistoryBody.appendChild(row); // Append the populated row
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
                    errorMsg = errorResult.message || errorMsg; // Use 'message' from backend JSON
                } catch (e) { console.error("Error parsing error response:", e); }
                throw new Error(errorMsg);
            }
            const state = await response.json();
            // Update UI with fetched state (config, status etc.)
            updateUI(state);
            // Note: History is now primarily updated via WebSocket push
            // updateOrderHistory(state.order_history); // Remove this if history isn't in /status
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
        startBotBtn.disabled = true; // Disable button immediately
        stopBotBtn.disabled = true; // Disable stop button too during start attempt
        try {
            const response = await fetch(`${API_BASE_URL}/api/start`, { method: 'POST' });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.message || `Erreur serveur: ${response.status}`);
            }
            appendLog(result.message || 'Commande Démarrer envoyée.', 'info');
            // UI state (buttons, status) will be updated via WebSocket 'status_update'
        } catch (error) {
            console.error('Error starting bot:', error);
            appendLog(`Erreur au démarrage du bot: ${error.message}`, 'error');
            startBotBtn.disabled = false; // Re-enable start button on failure
            // Stop button state depends on whether bot was previously running or not
            // Fetching state again might clarify, or rely on WS error state
            fetchBotState();
        }
    }

    async function stopBot() {
        appendLog("Envoi de la commande Arrêter...", "info");
        stopBotBtn.disabled = true; // Disable button immediately
        startBotBtn.disabled = true; // Disable start button too during stop attempt
        try {
            const response = await fetch(`${API_BASE_URL}/api/stop`, { method: 'POST' });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.message || `Erreur serveur: ${response.status}`);
            }
            appendLog(result.message || 'Commande Arrêter envoyée.', 'info');
            // UI state will be updated via WebSocket 'status_update'
        } catch (error) {
            console.error('Error stopping bot:', error);
            appendLog(`Erreur à l'arrêt du bot: ${error.message}`, 'error');
            // Re-enable stop button? Or rely on WS update? Let's rely on WS.
            // If WS fails, user might need to refresh.
            fetchBotState(); // Fetch state to try and sync UI
        }
    }

    async function saveParameters() {
        paramSaveStatus.textContent = 'Sauvegarde en cours...';
        paramSaveStatus.className = 'status-saving';
        saveParamsBtn.disabled = true;

        const paramsToSend = {
            STRATEGY_TYPE: strategySelector.value,
            // SWING Params
            TIMEFRAME_STR: paramTimeframe.value,
            EMA_SHORT_PERIOD: parseInt(paramEmaShort.value) || null,
            EMA_LONG_PERIOD: parseInt(paramEmaLong.value) || null,
            EMA_FILTER_PERIOD: parseInt(paramEmaFilter.value) || null,
            RSI_PERIOD: parseInt(paramRsiPeriod.value) || null,
            RSI_OVERBOUGHT: parseInt(paramRsiOb.value) || null,
            RSI_OVERSOLD: parseInt(paramRsiOs.value) || null,
            RISK_PER_TRADE: parseFloat(paramRisk.value) || null,
            CAPITAL_ALLOCATION: parseFloat(paramCapitalAllocation.value) || null,
            VOLUME_AVG_PERIOD: parseInt(paramVolumeAvg.value) || null,
            USE_EMA_FILTER: paramUseEmaFilter.checked,
            USE_VOLUME_CONFIRMATION: paramUseVolume.checked,
            // SCALPING Params
            STOP_LOSS_PERCENTAGE: parseFloat(paramSl.value) || null,
            TAKE_PROFIT_PERCENTAGE: parseFloat(paramTp.value) || null,
            SCALPING_LIMIT_ORDER_TIMEOUT_MS: parseInt(paramLimitTimeout.value) || null,
            // Add other SCALPING params if they exist in the HTML form
            // SCALPING_ORDER_TYPE: document.getElementById('param-scalping-order-type')?.value || 'MARKET',
            // SCALPING_LIMIT_TIF: document.getElementById('param-scalping-tif')?.value || 'GTC',
            // etc.
        };

        // Optional: Clean object by removing null/empty values if backend handles missing keys better
        // Object.keys(paramsToSend).forEach(key => {
        //     if (paramsToSend[key] === null || paramsToSend[key] === '') {
        //         delete paramsToSend[key];
        //     }
        // });

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
            // Re-fetch state to confirm update in UI inputs immediately
            // (Backend should broadcast the state update anyway, but this can be faster)
            // fetchBotState(); // Optional: remove if WS update is reliable enough
        } catch (error) {
            console.error('Error saving parameters:', error);
            paramSaveStatus.textContent = `Erreur sauvegarde: ${error.message}`;
            paramSaveStatus.className = 'status-error';
        } finally {
            // Clear status message after a delay
            setTimeout(() => {
                paramSaveStatus.textContent = '';
                paramSaveStatus.className = '';
            }, 5000);
            saveParamsBtn.disabled = false; // Re-enable button
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
    // Set initial visibility based on the default selected strategy in HTML
    if (strategySelector) {
        updateParameterVisibility(strategySelector.value);
    }
    // Connect WebSocket (this will also trigger fetchBotState on successful connection)
    connectWebSocket();

}); // End DOMContentLoaded
