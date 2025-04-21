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
    const priceValue = document.getElementById('price-value');
    const positionValue = document.getElementById('position-value');
    const quoteAssetLabel = document.getElementById('quote-asset-label');
    const baseAssetLabel = document.getElementById('base-asset-label');
    const symbolPriceLabel = document.getElementById('symbol-price-label');
    const orderHistoryBody = document.getElementById('order-history-body');
    const orderHistoryPlaceholder = document.getElementById('order-history-placeholder');
    const logOutput = document.getElementById('log-output'); // Utiliser log-output au lieu de logOutput
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
        return number.toLocaleString(undefined, {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        });
        // return number.toFixed(decimals); // Alternative simple
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
        // Utiliser textContent est plus sûr que innerHTML pour les messages venant de l'extérieur
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
            // Ne pas effacer les logs précédents, juste ajouter un message de connexion
            appendLog("WebSocket connecté.", "info");
            // Request initial state upon connection
            fetchBotState();
        };

        ws.onmessage = (event) => {
            try {
                // Le backend envoie maintenant du JSON
                const data = JSON.parse(event.data);
                // console.debug('WebSocket message received:', data); // Décommenter pour debug détaillé

                // --- MODIFIÉ: Gérer les types de messages JSON ---
                switch (data.type) {
                    case 'log':
                        appendLog(data.message, 'log'); // Niveau 'log' par défaut
                        break;
                    case 'info':
                        appendLog(data.message, 'info'); // Niveau 'info'
                        break;
                    case 'error': // Erreur spécifique envoyée par le backend
                        appendLog(`ERREUR Backend: ${data.message}`, 'error');
                        break;
                    case 'warning': // <<< CHECK THIS CASE
                        addLogMessage(data.message, 'warning');
                        break;
                    case 'critical': // <<< CHECK THIS CASE (often handled like error)
                        addLogMessage(data.message, 'error');
                        break;
                    
                    case 'status_update':
                        // Mettre à jour l'UI avec l'état reçu
                        if (data.state) {
                            updateUI(data.state);
                            appendLog("État du bot mis à jour.", "info");
                        } else {
                            console.warn("Received status_update without state data:", data);
                        }
                        break;
                    case 'order_history_update':
                        // Mettre à jour le tableau de l'historique des ordres
                        if (data.history) {
                            updateOrderHistory(data.history);
                            appendLog("Historique des ordres mis à jour.", "info");
                        } else {
                            console.warn("Received order_history_update without history data:", data);
                        }
                        break;
                    case 'ping':
                        // C'est le message keep-alive, on peut l'ignorer
                        // console.debug('WebSocket ping received');
                        break;
                    default:
                        // Type de message inconnu
                        console.warn('Message WebSocket de type inconnu reçu:', data);
                        appendLog(`[WS Type Inconnu: ${data.type}] ${JSON.stringify(data.message || data.payload || data)}`, 'warn');
                }
                // --- FIN MODIFIÉ ---

            } catch (error) {
                // Erreur si le message reçu n'est PAS du JSON valide
                console.error('Error processing WebSocket message (JSON malformé?):', error);
                appendLog(`Erreur traitement WS (JSON invalide?): ${event.data}`, 'error');
            }
        };

        ws.onerror = (error) => {
            // Cette erreur se produit souvent si le serveur backend n'est pas joignable
            console.error('WebSocket error:', error);
            appendLog('Erreur de connexion WebSocket. Le backend est-il démarré et accessible?', 'error');
            statusValue.textContent = 'Erreur Connexion';
            statusValue.className = 'status-error'; // Utiliser une classe d'erreur
            stopBotBtn.disabled = true;
            startBotBtn.disabled = false; // Permettre de réessayer de démarrer (ce qui refera un fetch)
            ws = null; // Important de réinitialiser ws ici
        };

        ws.onclose = (event) => {
            console.log(`WebSocket connection closed. Code: ${event.code}, Reason: ${event.reason}`);
            // Ne pas afficher si la fermeture était propre (code 1000 ou 1001) et que ws est null (déjà géré)
            if (ws && event.code !== 1000 && event.code !== 1001) {
                 appendLog(`Connexion WebSocket fermée (Code: ${event.code}). Tentative de reconnexion possible.`, 'warn');
            } else if (!ws) {
                 appendLog(`Connexion WebSocket fermée.`, 'info');
            }
            statusValue.textContent = 'Déconnecté';
            statusValue.className = 'status-stopped';
            stopBotBtn.disabled = true;
            startBotBtn.disabled = false;
            ws = null; // Réinitialiser ws variable
            // Optionnel: Tentative de reconnexion automatique après un délai
            // setTimeout(connectWebSocket, 5000); // Attention aux boucles infinies si le serveur est down
        };
    }

    // --- UI Update Functions ---

    function updateUI(state) {
        if (!state) {
            console.warn("updateUI called with null or undefined state");
            return;
        }
        // console.log("Updating UI with state:", state); // Debug

        // Update Bot Status section
        statusValue.textContent = state.status || 'Inconnu';
        statusValue.className = state.status === 'RUNNING' ? 'status-running' : (state.status === 'STOPPED' ? 'status-stopped' : 'status-error');
        strategyTypeValueSpan.textContent = state.config.STRATEGY_TYPE || 'N/A';
        symbolValue.textContent = state.symbol || 'N/A';
        timeframeValue.textContent = state.timeframe || 'N/A';
        quoteAssetLabel.textContent = state.quote_asset || 'USDT';
        baseAssetLabel.textContent = state.base_asset || 'N/A';
        symbolPriceLabel.textContent = state.symbol ? `${state.symbol} / ${state.quote_asset || 'USDT'}` : 'N/A';
        balanceValue.textContent = formatNumber(state.available_balance, 2);
        quantityValue.textContent = formatNumber(state.symbol_quantity, 8);

        // Update current price
        // Utiliser state.current_price s'il est fourni directement par le backend, sinon fallback sur book ticker
        if (state.current_price) {
             priceValue.textContent = formatNumber(state.current_price);
        } else if (state.latest_book_ticker && state.latest_book_ticker.b) {
             priceValue.textContent = formatNumber(state.latest_book_ticker.b);
        } else {
             priceValue.textContent = 'N/A';
        }

        // Update Position Status
        if (state.in_position && state.entry_details) {
            const entryPrice = formatNumber(state.entry_details.avg_price);
            const entryQty = formatNumber(state.entry_details.quantity);
            positionValue.textContent = `Oui (Entrée @ ${entryPrice}, Qté: ${entryQty})`;
            positionValue.className = 'status-running';
        } else {
            positionValue.textContent = 'Aucune';
            positionValue.className = '';
        }

        // Update Control Buttons state
        startBotBtn.disabled = state.status === 'RUNNING';
        stopBotBtn.disabled = state.status !== 'RUNNING';

        // Update Parameter Inputs
        if (state.config) {
            strategySelector.value = state.config.STRATEGY_TYPE || 'SWING';
            updateParameterVisibility(strategySelector.value);

            // SWING Params
            paramTimeframe.value = state.config.TIMEFRAME_STR || '1h';
            paramEmaShort.value = state.config.EMA_SHORT_PERIOD ?? ''; // Utiliser ?? pour gérer null/undefined
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
        if (!orderHistoryBody) return;
        orderHistoryBody.innerHTML = ''; // Clear existing rows

        if (!history || history.length === 0) {
            // Clone and append placeholder if it exists
            if (orderHistoryPlaceholder) {
                 const placeholderClone = orderHistoryPlaceholder.content.cloneNode(true); // Use template content
                 orderHistoryBody.appendChild(placeholderClone);
            } else {
                 // Fallback if placeholder template is missing
                 const row = orderHistoryBody.insertRow();
                 const cell = row.insertCell();
                 cell.colSpan = 10; // Adjust colspan based on actual columns
                 cell.textContent = "Aucun ordre dans l'historique.";
                 cell.style.textAlign = 'center';
            }
            return;
        }

        // Sort history by timestamp descending (most recent first)
        // Ensure timestamps are numbers for correct sorting
        history.sort((a, b) => (parseInt(b.timestamp || 0)) - (parseInt(a.timestamp || 0)));

        history.forEach(order => {
            const row = document.createElement('tr');
            const performancePct = (order.performance_pct !== null && order.performance_pct !== undefined)
                ? `${formatNumber(order.performance_pct * 100, 2)}%`
                : 'N/A';

            // Calculate average price if price is zero or missing but quantities are present
            let avgPrice = order.price;
            if ((!avgPrice || parseFloat(avgPrice) === 0) && parseFloat(order.cummulativeQuoteQty) > 0 && parseFloat(order.executedQty) > 0) {
                avgPrice = parseFloat(order.cummulativeQuoteQty) / parseFloat(order.executedQty);
            }

            // Display average price for BUY/SELL, or total value if preferred for SELL
            const priceOrValue = formatNumber(avgPrice, 8);
            // const priceOrValue = order.side === 'BUY'
            //     ? formatNumber(avgPrice, 8)
            //     : formatNumber(order.cummulativeQuoteQty, 2); // Alternative: Show total value for sells

            row.innerHTML = `
                <td>${formatTimestamp(order.timestamp)}</td>
                <td>${order.symbol || 'N/A'}</td>
                <td class="${order.side === 'BUY' ? 'side-buy' : 'side-sell'}">${order.side || 'N/A'}</td>
                <td>${order.type || 'N/A'}</td>
                <td>${formatNumber(order.origQty)}</td>
                <td>${formatNumber(order.executedQty)}</td>
                <td>${priceOrValue}</td>
                <td>${order.status || 'N/A'}</td>
                <td class="${(order.performance_pct || 0) >= 0 ? 'perf-positive' : 'perf-negative'}">${performancePct}</td>
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
                // Try to get error message from backend response body
                let errorMsg = `HTTP error! status: ${response.status}`;
                try {
                    const errorResult = await response.json();
                    errorMsg = errorResult.error || errorMsg;
                } catch (e) { /* Ignore if response is not JSON */ }
                throw new Error(errorMsg);
            }
            const state = await response.json();
            updateUI(state);
            updateOrderHistory(state.order_history);
            appendLog("État initial et historique récupérés.", "info");
        } catch (error) {
            console.error('Error fetching bot state:', error);
            appendLog(`Erreur récupération état initial: ${error.message}`, 'error');
            statusValue.textContent = 'Erreur';
            statusValue.className = 'status-error';
        }
    }

    async function startBot() {
        appendLog("Envoi de la commande Démarrer...", "info");
        try {
            // Disable button immediately to prevent double clicks
            startBotBtn.disabled = true;
            const response = await fetch(`${API_BASE_URL}/api/start`, { method: 'POST' });
            const result = await response.json(); // Always try to parse JSON
            if (!response.ok) {
                throw new Error(result.error || `Erreur serveur: ${response.status}`);
            }
            appendLog(result.message || 'Commande Démarrer envoyée avec succès.', 'info');
            // UI state (like button disabling) will be updated via WebSocket 'status_update'
        } catch (error) {
            console.error('Error starting bot:', error);
            appendLog(`Erreur au démarrage du bot: ${error.message}`, 'error');
            // Re-enable button if start failed
            startBotBtn.disabled = false;
        }
    }

    async function stopBot() {
        appendLog("Envoi de la commande Arrêter...", "info");
        try {
            // Disable button immediately
            stopBotBtn.disabled = true;
            const response = await fetch(`${API_BASE_URL}/api/stop`, { method: 'POST' });
            const result = await response.json(); // Always try to parse JSON
            if (!response.ok) {
                throw new Error(result.error || `Erreur serveur: ${response.status}`);
            }
            appendLog(result.message || 'Commande Arrêter envoyée avec succès.', 'info');
            // UI state will be updated via WebSocket 'status_update'
        } catch (error) {
            console.error('Error stopping bot:', error);
            appendLog(`Erreur à l'arrêt du bot: ${error.message}`, 'error');
            // Re-enable button if stop failed (though state might be inconsistent)
             stopBotBtn.disabled = false; // Or rely on WebSocket update
        }
    }

    async function saveParameters() {
        paramSaveStatus.textContent = 'Sauvegarde en cours...';
        paramSaveStatus.className = 'status-saving';
        saveParamsBtn.disabled = true; // Disable button during save

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
            // --- AJOUT: Envoyer aussi les autres paramètres scalping si définis dans l'UI ---
            // SCALPING_ORDER_TYPE: document.getElementById('param-scalping-order-type').value, // Exemple si vous ajoutez ces champs
            // SCALPING_LIMIT_TIF: document.getElementById('param-scalping-tif').value,
            // SCALPING_DEPTH_LEVELS: parseInt(document.getElementById('param-scalping-depth-levels').value) || null,
            // SCALPING_DEPTH_SPEED: document.getElementById('param-scalping-depth-speed').value,
            // SCALPING_SPREAD_THRESHOLD: parseFloat(document.getElementById('param-scalping-spread').value) || null,
            // SCALPING_IMBALANCE_THRESHOLD: parseFloat(document.getElementById('param-scalping-imbalance').value) || null,
            // SCALPING_MIN_TRADE_VOLUME: parseFloat(document.getElementById('param-scalping-min-volume').value) || null,
            // --- FIN AJOUT ---DER_TIMEOUT_MS: parseInt(paramLimitTimeout.value) || null,
        };

        // Clean object: remove keys with null or empty string values if backend prefers that
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
            const result = await response.json(); // Always try to parse JSON

            if (!response.ok) {
                throw new Error(result.error || `Erreur serveur: ${response.status}`);
            }
            paramSaveStatus.textContent = result.message || 'Paramètres sauvegardés avec succès!';
            paramSaveStatus.className = 'status-success';
            // Re-fetch state to confirm update in UI inputs immediately
            fetchBotState();
        } catch (error) {
            console.error('Error saving parameters:', error);
            paramSaveStatus.textContent = `Erreur de sauvegarde: ${error.message}`;
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
    startBotBtn.addEventListener('click', startBot);
    stopBotBtn.addEventListener('click', stopBot);
    saveParamsBtn.addEventListener('click', saveParameters);

    strategySelector.addEventListener('change', (event) => {
        updateParameterVisibility(event.target.value);
    });


    // --- Initial Setup ---
    // Set initial visibility based on the default selected strategy in HTML
    updateParameterVisibility(strategySelector.value);
    // Connect WebSocket (this will also trigger fetchBotState on successful connection)
    connectWebSocket();

}); // End DOMContentLoaded
