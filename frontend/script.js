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
    const scalpingOrderBookParamsDiv = document.getElementById('scalping-params'); // Points to the SCALPING (Order Book) specific params div
    const scalping2SpecificParamsDiv = document.getElementById('scalping2-specific-params'); // Div pour params spécifiques Scalping2 (Indicateurs)
    const timeframeRelevance = document.getElementById('timeframe-relevance');

    // Common Params (Risk/Capital/Exit) - Utilisés par toutes les stratégies
    const paramRisk = document.getElementById('param-risk');
    const paramCapitalAllocation = document.getElementById('param-capital-allocation');
    const paramSl = document.getElementById('param-sl');
    const paramTp1 = document.getElementById('param-tp1');
    const paramTp2 = document.getElementById('param-tp2');
    const paramTrailing = document.getElementById('param-trailing');
    const paramTimeStop = document.getElementById('param-time-stop');
    const paramOrderCooldown = document.getElementById('param-order-cooldown'); // Moved to common

    // SWING Params
    const paramTimeframe = document.getElementById('param-timeframe');
    const paramEmaShort = document.getElementById('param-ema-short');
    const paramEmaLong = document.getElementById('param-ema-long');
    const paramEmaFilter = document.getElementById('param-ema-filter');
    const paramRsiPeriod = document.getElementById('param-rsi-period');
    const paramRsiOb = document.getElementById('param-rsi-ob');
    const paramRsiOs = document.getElementById('param-rsi-os');
    const paramVolumeAvg = document.getElementById('param-volume-avg');
    const paramUseEmaFilter = document.getElementById('param-use-ema-filter');
    const paramUseVolume = document.getElementById('param-use-volume');

    // SCALPING (Order Book) Specific Params
    const paramScalpingOrderType = document.getElementById('param-scalping-order-type');
    const paramScalpingLimitTif = document.getElementById('param-scalping-limit-tif');
    const paramScalpingLimitTimeout = document.getElementById('param-scalping-limit-timeout');
    const paramScalpingDepthLevels = document.getElementById('param-scalping-depth-levels');
    const paramScalpingDepthSpeed = document.getElementById('param-scalping-depth-speed');
    const paramScalpingSpreadThreshold = document.getElementById('param-scalping-spread-threshold');
    const paramScalpingImbalanceThreshold = document.getElementById('param-scalping-imbalance-threshold');

    // SCALPING 2 (Indicators) Specific Params
    const paramSupertrendAtr = document.getElementById('param-supertrend-atr');
    const paramSupertrendMult = document.getElementById('param-supertrend-mult');
    const paramRsiPeriodScalp = document.getElementById('param-rsi-period-scalp');
    const paramStochK = document.getElementById('param-stoch-k');
    const paramStochD = document.getElementById('param-stoch-d');
    const paramStochSmooth = document.getElementById('param-stoch-smooth');
    const paramBbPeriod = document.getElementById('param-bb-period');
    const paramBbStd = document.getElementById('param-bb-std');
    const paramVolMa = document.getElementById('param-vol-ma'); // Volume MA pour Scalping2

    let ws = null; // WebSocket connection
    let lastKnownState = null; // Variable pour stocker le dernier état reçu

    // === INIT FUNCTION ===
    function init() {
        // Initialisation de l’UI, listeners, WebSocket, etc.
    }

    document.addEventListener('DOMContentLoaded', init);

    // === UI MANAGEMENT ===
    const UI = {
        updateUI: function(state) {
            if (!state) {
                console.warn("updateUI called with null or undefined state");
                return; // Ne pas mettre à jour lastKnownState si l'état est invalide
            }
            lastKnownState = state; // Stocker le dernier état valide reçu
            if (!state.config) { // Vérifier si config existe après avoir stocké l'état
                console.warn("State received without config object. Cannot update parameters.");
                return;
            }

            // Update Bot Status section - vérifier existence éléments
            if (statusValue) statusValue.textContent = state.status || 'Inconnu';
            if (statusValue) statusValue.className = `status-${(state.status || 'unknown').toLowerCase().replace(/\s+/g, '-')}`;
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
            if (startBotBtn) startBotBtn.disabled = state.status === 'RUNNING' || state.status === 'STARTING' || state.status === 'STOPPING';
            if (stopBotBtn) stopBotBtn.disabled = state.status !== 'RUNNING';

            // Update Parameter Inputs
            const currentStrategy = state.config.STRATEGY_TYPE || 'SWING';
            if (strategySelector) {
                strategySelector.value = currentStrategy;
                UI.updateParameterVisibility(currentStrategy); // Gère la visibilité
            }
            // Appeler la fonction pour remplir les paramètres
            UI.fillParameters(state.config, currentStrategy);

            // Update Order History (if included in state)
             if (state.order_history) {
                 UI.updateOrderHistory(state.order_history);
             }
             // Update Price Display
             UI.updatePriceDisplay(state.latest_book_ticker);
        },

        // Fonction pour remplir les champs de paramètres
        fillParameters: function(config, strategyToFill) {
            if (!config) {
                console.warn("fillParameters called without config object.");
                return;
            }

            // Helper function to convert backend fractions to frontend percentages
            const toPercent = (value) => (value !== null && value !== undefined && !isNaN(parseFloat(value))) ? (parseFloat(value) * 100).toString() : '';

            // Common Params (Risk/Capital/Exit/Cooldown) - TOUJOURS REMPLIS
            if (paramRisk) paramRisk.value = toPercent(config.RISK_PER_TRADE);
            if (paramCapitalAllocation) paramCapitalAllocation.value = toPercent(config.CAPITAL_ALLOCATION);
            if (paramSl) paramSl.value = toPercent(config.STOP_LOSS_PERCENTAGE);
            if (paramTp1) paramTp1.value = toPercent(config.TAKE_PROFIT_1_PERCENTAGE);
            if (paramTp2) paramTp2.value = toPercent(config.TAKE_PROFIT_2_PERCENTAGE);
            if (paramTrailing) paramTrailing.value = toPercent(config.TRAILING_STOP_PERCENTAGE);
            if (paramTimeStop) paramTimeStop.value = config.TIME_STOP_MINUTES ?? '';
            if (paramOrderCooldown) paramOrderCooldown.value = config.ORDER_COOLDOWN_MS ?? '';

            // SWING Params - Remplir SEULEMENT si SWING est la stratégie à remplir
            if (strategyToFill === 'SWING') {
                if (paramTimeframe) paramTimeframe.value = config.TIMEFRAME || '1m';
                if (paramEmaShort) paramEmaShort.value = config.EMA_SHORT_PERIOD ?? '';
                if (paramEmaLong) paramEmaLong.value = config.EMA_LONG_PERIOD ?? '';
                if (paramEmaFilter) paramEmaFilter.value = config.EMA_FILTER_PERIOD ?? '';
                if (paramRsiPeriod) paramRsiPeriod.value = config.RSI_PERIOD ?? '';
                if (paramRsiOb) paramRsiOb.value = config.RSI_OVERBOUGHT ?? '';
                if (paramRsiOs) paramRsiOs.value = config.RSI_OVERSOLD ?? '';
                if (paramVolumeAvg) paramVolumeAvg.value = config.VOLUME_AVG_PERIOD ?? '';
                if (paramUseEmaFilter) paramUseEmaFilter.checked = config.USE_EMA_FILTER ?? false;
                if (paramUseVolume) paramUseVolume.checked = config.USE_VOLUME_CONFIRMATION ?? false;
            }

            // SCALPING (Order Book) Specific Params - Remplir SEULEMENT si SCALPING est la stratégie à remplir
            if (strategyToFill === 'SCALPING') {
                if(paramScalpingOrderType) paramScalpingOrderType.value = config.SCALPING_ORDER_TYPE || 'MARKET';
                if(paramScalpingLimitTif) paramScalpingLimitTif.value = config.SCALPING_LIMIT_TIF || 'GTC';
                if(paramScalpingLimitTimeout) paramScalpingLimitTimeout.value = config.SCALPING_LIMIT_ORDER_TIMEOUT_MS ?? '';
                if(paramScalpingDepthLevels) paramScalpingDepthLevels.value = config.SCALPING_DEPTH_LEVELS || '5';
                if(paramScalpingDepthSpeed) paramScalpingDepthSpeed.value = config.SCALPING_DEPTH_SPEED || '1000ms';
                if(paramScalpingSpreadThreshold) paramScalpingSpreadThreshold.value = config.SCALPING_SPREAD_THRESHOLD ?? '';
                if(paramScalpingImbalanceThreshold) paramScalpingImbalanceThreshold.value = config.SCALPING_IMBALANCE_THRESHOLD ?? '';
            }

            // SCALPING 2 (Indicators) Specific Params - Remplir SEULEMENT si SCALPING2 est la stratégie à remplir
            if (strategyToFill === 'SCALPING2') {
                if (paramTimeframe) paramTimeframe.value = config.TIMEFRAME || '1m'; // Timeframe pertinent aussi
                if (paramSupertrendAtr) paramSupertrendAtr.value = config.SUPERTREND_ATR_PERIOD ?? '';
                if (paramSupertrendMult) paramSupertrendMult.value = config.SUPERTREND_ATR_MULTIPLIER ?? '';
                if (paramRsiPeriodScalp) paramRsiPeriodScalp.value = config.SCALPING_RSI_PERIOD ?? '';
                if (paramStochK) paramStochK.value = config.STOCH_K_PERIOD ?? '';
                if (paramStochD) paramStochD.value = config.STOCH_D_PERIOD ?? '';
                if (paramStochSmooth) paramStochSmooth.value = config.STOCH_SMOOTH ?? '';
                if (paramBbPeriod) paramBbPeriod.value = config.BB_PERIOD ?? '';
                if (paramBbStd) paramBbStd.value = config.BB_STD ?? '';
                if (paramVolMa) paramVolMa.value = config.VOLUME_MA_PERIOD ?? '';
            }
        },

        updateOrderHistory: function(history) {
            if (!orderHistoryBody) {
                console.error("Order history table body not found!");
                return;
            }
            orderHistoryBody.innerHTML = ''; // Vider le contenu actuel

            if (!Array.isArray(history) || history.length === 0) {
                if (orderHistoryPlaceholder && 'content' in orderHistoryPlaceholder) {
                     try {
                        const placeholderClone = orderHistoryPlaceholder.content.cloneNode(true);
                        orderHistoryBody.appendChild(placeholderClone);
                    } catch (e) {
                         console.error("Error using order history placeholder template:", e);
                         const row = orderHistoryBody.insertRow();
                         const cell = row.insertCell();
                         cell.colSpan = 12;
                         cell.textContent = "Aucun ordre dans l'historique.";
                         cell.style.textAlign = 'center';
                     }
                } else {
                     const row = orderHistoryBody.insertRow();
                     const cell = row.insertCell();
                     cell.colSpan = 12;
                     cell.textContent = "Aucun ordre dans l'historique.";
                     cell.style.textAlign = 'center';
                }
                return;
            }

            history.sort((a, b) => (parseInt(b.timestamp || 0)) - (parseInt(a.timestamp || 0)));

            history.forEach(order => {
                const row = document.createElement('tr');

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

                row.innerHTML = `
                    <td>${formatTimestamp(order.timestamp)}</td>
                    <td>${order.symbol || 'N/A'}</td>
                    <td>${order.strategy || '-'}</td>
                    <td class="${sideClass}">${order.side || 'N/A'}</td>
                    <td>${order.type || 'N/A'}</td>
                    <td>${formatNumber(order.origQty, 8)}</td>
                    <td>${formatNumber(order.executedQty, 8)}</td>
                    <td>${priceOrValueText}</td>
                    <td>${quoteValue}</td>
                    <td>${order.status || 'N/A'}</td>
                    <td class="${perfClass}">${performancePctText}</td>
                    <td>${order.orderId || 'N/A'}</td>
                `;
                orderHistoryBody.appendChild(row);
            });
        },
        updateParameterVisibility: function(selectedStrategy) {
            // Cacher toutes les sections spécifiques par défaut
            if (swingParamsDiv) swingParamsDiv.style.display = 'none';
            if (scalpingOrderBookParamsDiv) scalpingOrderBookParamsDiv.style.display = 'none'; // Cache la section spécifique SCALPING (Order Book)
            if (scalping2SpecificParamsDiv) scalping2SpecificParamsDiv.style.display = 'none'; // Cache la section spécifique SCALPING2 (Indicateurs)

            // Réactiver Timeframe par défaut et effacer la note de pertinence
            if (paramTimeframe) paramTimeframe.disabled = false;
            if (timeframeRelevance) timeframeRelevance.textContent = '';

            // Afficher la section spécifique correspondante et ajuster Timeframe/note
            if (selectedStrategy === 'SWING') {
                if (swingParamsDiv) swingParamsDiv.style.display = 'block';
                if (timeframeRelevance) timeframeRelevance.textContent = '(Pertinent pour SWING)';
            } else if (selectedStrategy === 'SCALPING') {
                if (scalpingOrderBookParamsDiv) scalpingOrderBookParamsDiv.style.display = 'block'; // Affiche la section spécifique SCALPING (Order Book)
                if (paramTimeframe) paramTimeframe.disabled = true; // Désactive Timeframe
                if (timeframeRelevance) timeframeRelevance.textContent = '(Non pertinent pour SCALPING)';
            } else if (selectedStrategy === 'SCALPING2') {
                if (scalping2SpecificParamsDiv) scalping2SpecificParamsDiv.style.display = 'block'; // Affiche la section spécifique SCALPING2 (Indicateurs)
                // Timeframe reste activé
                if (timeframeRelevance) timeframeRelevance.textContent = '(Pertinent pour SCALPING2)';
            }
            // La section 'general-params' reste toujours visible
        },
        appendLog: function(message, level = 'log') {
            if (!logOutput) {
                console.error("logOutput element not found!");
                return;
            }
            const logEntry = document.createElement('div');
            logEntry.textContent = message;
            logEntry.className = `log-entry log-${level}`;
            logOutput.appendChild(logEntry);
            logOutput.scrollTop = logOutput.scrollHeight; // Auto-scroll
        },
        updatePriceDisplay: function(tickerData) {
            let displayPrice = 'N/A';
            if (tickerData && tickerData.b && tickerData.a) { // Utilise best bid/ask
                try {
                    const bid = parseFloat(tickerData.b);
                    const ask = parseFloat(tickerData.a);
                    if (!isNaN(bid) && !isNaN(ask) && ask > 0) {
                        const midPrice = (bid + ask) / 2;
                        displayPrice = formatNumber(midPrice);
                    } else if (!isNaN(bid)) {
                        displayPrice = formatNumber(bid); // Fallback to bid
                    } else if (!isNaN(ask)) {
                        displayPrice = formatNumber(ask); // Fallback to ask
                    }
                } catch (e) {
                    console.error("Error parsing ticker price:", e, tickerData);
                    displayPrice = "Erreur";
                }
            } else if (tickerData && tickerData.c) { // Fallback to last price 'c'
                 try {
                     const lastPrice = parseFloat(tickerData.c);
                     if (!isNaN(lastPrice)) {
                         displayPrice = formatNumber(lastPrice);
                     }
                 } catch (e) {
                     console.error("Error parsing last price:", e, tickerData);
                     displayPrice = "Erreur";
                 }
            }

            if (priceValue) {
                priceValue.textContent = displayPrice;
            } else {
                console.warn("Element with ID 'current-price' not found for price update.");
            }
        },
        displaySignalEvent: function(event) {
            const container = document.getElementById("signals-output");
            if (!container) return;

            let table = container.querySelector("table.signals-table");
            if (!table) {
                table = document.createElement("table");
                table.className = "signals-table";
                table.innerHTML = `<thead><tr><th>Heure</th><th>Type</th><th>Direction</th><th>Validé</th><th>Raison</th><th>Prix</th></tr></thead><tbody></tbody>`;
                container.innerHTML = "";
                container.appendChild(table);
            }

            const tbody = table.querySelector("tbody");
            if (!tbody) return;

            const ts = new Date().toLocaleTimeString();
            const row = document.createElement("tr");

            row.innerHTML = `
                <td>${ts}</td>
                <td>${event.signal_type ? event.signal_type.toUpperCase() : "-"}</td>
                <td>${event.direction ? event.direction.toUpperCase() : "-"}</td>
                <td>${event.valid ? "✅" : "❌"}</td>
                <td>${event.reason || "-"}</td>
                <td>${event.price !== undefined ? formatNumber(event.price, 2) : "-"}</td>
            `;

            tbody.insertBefore(row, tbody.firstChild);

            const maxSignalRows = 5;
            while (tbody.rows.length > maxSignalRows) {
                tbody.deleteRow(tbody.rows.length - 1);
            }
        }
    };

    // --- Statistiques ---
    const statRoi = document.getElementById('stat-roi');
    const statWinrate = document.getElementById('stat-winrate');
    const statWins = document.getElementById('stat-wins');
    const statLosses = document.getElementById('stat-losses');
    const statTotal = document.getElementById('stat-total');
    const statAvgPnl = document.getElementById('stat-avg-pnl');
    const resetBotBtn = document.getElementById('reset-bot-btn');

    // --- Helper Functions ---

    function formatNumber(num, decimals = 8) {
        const number = parseFloat(num);
        if (isNaN(number) || num === null || num === undefined) return 'N/A';
        if (Math.abs(number) >= 1000) decimals = 2;
        else if (Math.abs(number) >= 10) decimals = 4;
        else if (Math.abs(number) >= 0.1) decimals = 6;
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

    // --- WebSocket Logic ---
    function connectWebSocket() {
        if (ws && ws.readyState !== WebSocket.CLOSED) {
            console.warn("WebSocket connection already exists or is connecting.");
            return;
        }
        console.log(`Attempting to connect WebSocket to: ${WS_URL}`);
        UI.appendLog("Tentative de connexion au backend...", "info");
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            console.log('WebSocket connection established');
            UI.appendLog("WebSocket connecté.", "info");
            fetchBotState();
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                switch (data.type) {
                    case 'log':
                    case 'debug':
                        UI.appendLog(data.message, 'log');
                        break;
                    case 'info':
                        UI.appendLog(data.message, 'info');
                        break;
                    case 'error':
                        UI.appendLog(`ERREUR Backend: ${data.message}`, 'error');
                        break;
                    case 'warning':
                        UI.appendLog(data.message, 'warn');
                        break;
                    case 'critical':
                        UI.appendLog(`CRITICAL: ${data.message}`, 'error');
                        break;
                    case 'status_update':
                        if (data.state) {
                            UI.updateUI(data.state);
                        } else {
                            console.warn("Received status_update without state data:", data);
                        }
                        break;
                    case 'ticker_update':
                        UI.updatePriceDisplay(data.ticker);
                        break;
                    case 'order_history_update':
                        fetchAndDisplayOrderHistory();
                        UI.appendLog("Historique des ordres mis à jour (via push dédié).", "info");
                        break;
                    case 'ping':
                        break;
                    case 'signal_event':
                        UI.displaySignalEvent(data);
                        break;
                    default:
                        console.warn('Unknown WebSocket message type received:', data);
                        UI.appendLog(`[WS Type Inconnu: ${data.type}] ${JSON.stringify(data.message || data.payload || data)}`, 'warn');
                }
            } catch (error) {
                console.error('Error processing WebSocket message (Malformed JSON?):', error);
                UI.appendLog(`Erreur traitement WS (JSON invalide?): ${event.data}`, 'error');
            }
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            UI.appendLog('Erreur de connexion WebSocket. Le backend est-il démarré et accessible?', 'error');
            if (statusValue) {
                statusValue.textContent = 'Erreur Connexion';
                statusValue.className = 'status-error';
            }
            if (stopBotBtn) stopBotBtn.disabled = true;
            if (startBotBtn) startBotBtn.disabled = false;
            ws = null;
        };

        ws.onclose = (event) => {
            const wasConnected = !!ws;
            ws = null;
            console.log(`WebSocket connection closed. Code: ${event.code}, Reason: ${event.reason}`);
            if (statusValue) {
                statusValue.textContent = 'Déconnecté';
                statusValue.className = 'status-stopped';
            }
            if (stopBotBtn) stopBotBtn.disabled = true;
            if (startBotBtn) startBotBtn.disabled = false;
            if (wasConnected && event.code !== 1000 && event.code !== 1001) {
                 UI.appendLog(`Connexion WebSocket fermée (Code: ${event.code}). Tentative de reconnexion dans 5s...`, 'warn');
                 setTimeout(connectWebSocket, 5000);
            } else {
                 UI.appendLog(`Connexion WebSocket fermée.`, "info");
            }
        };
    }

    // --- API Call Functions ---

    async function fetchBotState() {
        UI.appendLog("Récupération de l'état initial du bot...", "info");
        try {
            const response = await fetch(`${API_BASE_URL}/api/status`);
            if (!response.ok) {
                let errorMsg = `HTTP error! status: ${response.status}`;
                try {
                    const errorResult = await response.json();
                    errorMsg = errorResult.message || errorMsg;
                } catch {}
                throw new Error(errorMsg);
            }
            const state = await response.json();
            UI.updateUI(state);
            UI.appendLog("État initial récupéré.", "info");
        } catch (error) {
            console.error('Error fetching bot state:', error);
            UI.appendLog(`Erreur récupération état initial: ${error.message}`, 'error');
            if (statusValue) {
                statusValue.textContent = 'Erreur API';
                statusValue.className = 'status-error';
            }
        }
    }

    async function startBot() {
        UI.appendLog("Envoi de la commande Démarrer...", "info");
        if(startBotBtn) startBotBtn.disabled = true;
        if(stopBotBtn) stopBotBtn.disabled = true;
        try {
            const response = await fetch(`${API_BASE_URL}/api/start`, { method: 'POST' });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.message || `Erreur serveur: ${response.status}`);
            }
            UI.appendLog(result.message || 'Commande Démarrer envoyée.', 'info');
        } catch (error) {
            console.error('Error starting bot:', error);
            UI.appendLog(`Erreur au démarrage du bot: ${error.message}`, 'error');
            if(startBotBtn) startBotBtn.disabled = false;
        }
    }

    async function stopBot() {
        UI.appendLog("Envoi de la commande Arrêter...", "info");
        if(stopBotBtn) stopBotBtn.disabled = true;
        if(startBotBtn) startBotBtn.disabled = true;
        try {
            const response = await fetch(`${API_BASE_URL}/api/stop`, { method: 'POST' });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.message || `Erreur serveur: ${response.status}`);
            }
            UI.appendLog(result.message || 'Commande Arrêter envoyée.', 'info');
        } catch (error) {
            console.error('Error stopping bot:', error);
            UI.appendLog(`Erreur à l'arrêt du bot: ${error.message}`, 'error');
             if(stopBotBtn) stopBotBtn.disabled = false;
        }
    }

    // Utilitaire pour lire la valeur d'un champ DOM s'il existe
    function safeValue(input, parseFn = v => v) {
        return input ? parseFn(input.value) || null : null;
    }

    async function saveParameters() {
        if (paramSaveStatus) {
            paramSaveStatus.textContent = 'Sauvegarde en cours...';
            paramSaveStatus.className = 'status-saving';
        }
        if (saveParamsBtn) saveParamsBtn.disabled = true;

        const paramsToSend = {
            STRATEGY_TYPE: strategySelector ? strategySelector.value : null,
            TIMEFRAME: safeValue(paramTimeframe),
            RISK_PER_TRADE: safeValue(paramRisk, parseFloat),
            CAPITAL_ALLOCATION: safeValue(paramCapitalAllocation, parseFloat),
            STOP_LOSS_PERCENTAGE: safeValue(paramSl, parseFloat),
            TAKE_PROFIT_1_PERCENTAGE: safeValue(paramTp1, parseFloat),
            TAKE_PROFIT_2_PERCENTAGE: safeValue(paramTp2, parseFloat),
            TRAILING_STOP_PERCENTAGE: safeValue(paramTrailing, parseFloat),
            TIME_STOP_MINUTES: safeValue(paramTimeStop, v => parseInt(v, 10)),
            EMA_SHORT_PERIOD: safeValue(paramEmaShort, v => parseInt(v, 10)),
            EMA_LONG_PERIOD: safeValue(paramEmaLong, v => parseInt(v, 10)),
            EMA_FILTER_PERIOD: safeValue(paramEmaFilter, v => parseInt(v, 10)),
            RSI_PERIOD: safeValue(paramRsiPeriod, v => parseInt(v, 10)),
            RSI_OVERBOUGHT: safeValue(paramRsiOb, v => parseInt(v, 10)),
            RSI_OVERSOLD: safeValue(paramRsiOs, v => parseInt(v, 10)),
            VOLUME_AVG_PERIOD: safeValue(paramVolumeAvg, v => parseInt(v, 10)),
            USE_EMA_FILTER: paramUseEmaFilter ? paramUseEmaFilter.checked : null,
            USE_VOLUME_CONFIRMATION: paramUseVolume ? paramUseVolume.checked : null,
            SCALPING_ORDER_TYPE: paramScalpingOrderType ? paramScalpingOrderType.value : null,
            SCALPING_LIMIT_TIF: paramScalpingLimitTif ? paramScalpingLimitTif.value : null,
            SCALPING_LIMIT_ORDER_TIMEOUT_MS: safeValue(paramScalpingLimitTimeout, v => parseInt(v, 10)),
            SCALPING_DEPTH_LEVELS: safeValue(paramScalpingDepthLevels, v => parseInt(v, 10)),
            SCALPING_DEPTH_SPEED: paramScalpingDepthSpeed ? paramScalpingDepthSpeed.value : null,
            SCALPING_SPREAD_THRESHOLD: safeValue(paramScalpingSpreadThreshold, parseFloat),
            SCALPING_IMBALANCE_THRESHOLD: safeValue(paramScalpingImbalanceThreshold, parseFloat),
            ORDER_COOLDOWN_MS: safeValue(paramOrderCooldown, v => parseInt(v, 10)),
            SUPERTREND_ATR_PERIOD: safeValue(paramSupertrendAtr, v => parseInt(v, 10)),
            SUPERTREND_ATR_MULTIPLIER: safeValue(paramSupertrendMult, parseFloat),
            SCALPING_RSI_PERIOD: safeValue(paramRsiPeriodScalp, v => parseInt(v, 10)),
            STOCH_K_PERIOD: safeValue(paramStochK, v => parseInt(v, 10)),
            STOCH_D_PERIOD: safeValue(paramStochD, v => parseInt(v, 10)),
            STOCH_SMOOTH: safeValue(paramStochSmooth, v => parseInt(v, 10)),
            BB_PERIOD: safeValue(paramBbPeriod, v => parseInt(v, 10)),
            BB_STD: safeValue(paramBbStd, parseFloat),
            VOLUME_MA_PERIOD: safeValue(paramVolMa, v => parseInt(v, 10)),
        };

        const cleanedParamsToSend = Object.fromEntries(
            Object.entries(paramsToSend).filter(([_, v]) => v !== null && v !== undefined && !(typeof v === 'number' && isNaN(v)))
        );

        console.log("Sending parameters:", JSON.stringify(cleanedParamsToSend, null, 2));

        try {
            const response = await fetch(`${API_BASE_URL}/api/parameters`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(cleanedParamsToSend),
            });
            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.message || `Erreur serveur: ${response.status}`);
            }

            if (paramSaveStatus) {
                paramSaveStatus.textContent = result.message || 'Paramètres sauvegardés!';
                paramSaveStatus.className = 'status-success';
            }
            UI.appendLog(result.message || 'Paramètres sauvegardés.', 'info');
            if (result.restart_recommended) {
                alert("Un redémarrage du bot est conseillé pour appliquer certains changements.");
                UI.appendLog("Redémarrage bot conseillé.", "warn");
            }

        } catch (error) {
            console.error('Error saving parameters:', error);
            if (paramSaveStatus) {
                paramSaveStatus.textContent = `Erreur sauvegarde: ${error.message}`;
                paramSaveStatus.className = 'status-error';
            }
            UI.appendLog(`Erreur sauvegarde paramètres: ${error.message}`, 'error');

        } finally {
            setTimeout(() => {
                if (paramSaveStatus) {
                    paramSaveStatus.textContent = '';
                    paramSaveStatus.className = '';
                }
            }, 5000);
            if (saveParamsBtn) saveParamsBtn.disabled = false;
        }
    }

    // --- Fonction pour récupérer et afficher les stats ---
    async function fetchAndDisplayStats() {
        let strategy = strategySelector ? strategySelector.value : 'SCALPING';
        try {
            const response = await fetch(`${API_BASE_URL}/api/stats?strategy=${strategy}`);
            if (!response.ok) throw new Error('Erreur API stats');
            const stats = await response.json();
            if (statRoi) statRoi.textContent = (stats.roi !== undefined) ? formatNumber(stats.roi, 4) : 'N/A';
            if (statWinrate) statWinrate.textContent = (stats.winrate !== undefined) ? `${formatNumber(stats.winrate, 2)}%` : 'N/A';
            if (statWins) statWins.textContent = stats.wins ?? 'N/A';
            if (statLosses) statLosses.textContent = stats.losses ?? 'N/A';
            if (statTotal) statTotal.textContent = stats.total_trades ?? 'N/A';
            if (statAvgPnl) statAvgPnl.textContent = (stats.avg_pnl !== undefined) ? formatNumber(stats.avg_pnl, 4) : 'N/A';
        } catch (e) {
            if (statRoi) statRoi.textContent = 'N/A';
            if (statWinrate) statWinrate.textContent = 'N/A';
            if (statWins) statWins.textContent = 'N/A';
            if (statLosses) statLosses.textContent = 'N/A';
            if (statTotal) statTotal.textContent = 'N/A';
            if (statAvgPnl) statAvgPnl.textContent = 'N/A';
        }
    }

    // --- Fonction pour récupérer et afficher l'historique filtré par stratégie ---
    async function fetchAndDisplayOrderHistory() {
        let strategy = strategySelector ? strategySelector.value : 'SCALPING';
        try {
            const response = await fetch(`${API_BASE_URL}/api/order_history?strategy=${strategy}`);
            if (!response.ok) throw new Error('Erreur API historique');
            const history = await response.json();
            UI.updateOrderHistory(history);
        } catch {}
    }

    // --- Fonction pour reset le bot ---
    async function resetBot() {
        let strategy = strategySelector ? strategySelector.value : 'SCALPING';
        if (resetBotBtn) resetBotBtn.disabled = true;
        try {
            const response = await fetch(`${API_BASE_URL}/api/reset`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ strategy })
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.message || 'Erreur reset');
            UI.appendLog(result.message || 'Bot réinitialisé.', 'info');
            fetchBotState();
            fetchAndDisplayStats();
        } catch (e) {
            UI.appendLog(`Erreur reset: ${e.message}`, 'error');
        } finally {
            if (resetBotBtn) resetBotBtn.disabled = false;
        }
    }

    // --- Listener bouton reset ---
    if (resetBotBtn) resetBotBtn.addEventListener('click', resetBot);

    // --- Rafraîchir stats au chargement et au changement de stratégie ---
    document.addEventListener('DOMContentLoaded', fetchAndDisplayStats);
    if (strategySelector) {
        strategySelector.addEventListener('change', fetchAndDisplayStats);
    }

    // --- Rafraîchir l'historique au chargement et au changement de stratégie ---
    document.addEventListener('DOMContentLoaded', fetchAndDisplayOrderHistory);
    if (strategySelector) {
        strategySelector.addEventListener('change', fetchAndDisplayOrderHistory);
    }

    // --- Event Listeners ---
    if (startBotBtn) startBotBtn.addEventListener('click', startBot);
    if (stopBotBtn) stopBotBtn.addEventListener('click', stopBot);
    if (saveParamsBtn) saveParamsBtn.addEventListener('click', saveParameters);

    // Mettre à jour la visibilité des paramètres quand la stratégie change
    if (strategySelector) {
        strategySelector.addEventListener('change', (event) => {
            UI.updateParameterVisibility(event.target.value);
            // *** CORRECTION: Appeler fillParameters ici aussi ***
            if (lastKnownState) {
                UI.fillParameters(lastKnownState.config, event.target.value);
            }
        });
    }


    // --- Initial Setup ---
    // Mettre à jour la visibilité initiale basée sur la valeur par défaut du sélecteur
    if (strategySelector) {
        UI.updateParameterVisibility(strategySelector.value);
        // *** CORRECTION: Appeler fillParameters ici aussi au chargement initial ***
        // (Attendre que fetchBotState ait rempli lastKnownState)
        // Note: fetchBotState appelle déjà UI.updateUI qui appelle fillParameters
    }
    // Établir la connexion WebSocket
    connectWebSocket();

}); // End DOMContentLoaded
