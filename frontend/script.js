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
    const scalpingParamsDiv = document.getElementById('scalping-params'); // Div pour les params communs Scalping/Scalping2
    const scalpingSpecificParamsDiv = document.getElementById('scalping-specific-params'); // Div pour params spécifiques Scalping (Order Book)
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
    const paramOrderCooldown = document.getElementById('param-order-cooldown');

    let ws = null; // WebSocket connection

    // === INIT FUNCTION ===
    function init() {
        // Initialisation de l’UI, listeners, WebSocket, etc.
        // Ex: DOM.saveParamsBtn.addEventListener('click', ...)
        // Ex: API.getStatus().then(updateUI)
    }

    document.addEventListener('DOMContentLoaded', init);

    // === UI MANAGEMENT ===
    const UI = {
        updateUI: function(state) {
            if (!state) {
                console.warn("updateUI called with null or undefined state");
                return;
            }

            // Update Bot Status section - vérifier existence éléments
            if (statusValue) statusValue.textContent = state.status || 'Inconnu';
            if (statusValue) statusValue.className = `status-${(state.status || 'unknown').toLowerCase().replace(/\s+/g, '-')}`; // Gérer espaces potentiels
            if (strategyTypeValueSpan) strategyTypeValueSpan.textContent = state.config?.STRATEGY_TYPE || 'N/A';
            if (symbolValue) symbolValue.textContent = state.symbol || 'N/A';
            if (timeframeValue) timeframeValue.textContent = state.timeframe || 'N/A';
            if (quoteAssetLabel) quoteAssetLabel.textContent = state.quote_asset || 'USDT';
            if (baseAssetLabel) baseAssetLabel.textContent = state.base_asset || 'N/A';
            if (symbolPriceLabel) symbolPriceLabel.textContent = state.symbol ? `${state.symbol} / ${state.quote_asset || 'USDT'}` : 'N/A';
            if (balanceValue) balanceValue.textContent = formatNumber(state.available_balance, 2); // Précision 2 pour quote
            if (quantityValue) quantityValue.textContent = formatNumber(state.symbol_quantity, 8); // Précision 8 pour base

            // Update Position Status
            if (positionValue) {
                if (state.in_position && state.entry_details) {
                    const entryPrice = formatNumber(state.entry_details.avg_price, 2); // Précision 2 pour prix entrée
                    const entryQty = formatNumber(state.entry_details.quantity, 8); // Précision 8 pour quantité
                    positionValue.textContent = `Oui (Entrée @ ${entryPrice}, Qté: ${entryQty})`;
                    positionValue.className = 'status-running'; // Ou une classe spécifique 'in-position'
                } else {
                    positionValue.textContent = 'Aucune';
                    positionValue.className = '';
                }
            }

            // Update Control Buttons state
            if (startBotBtn) startBotBtn.disabled = state.status === 'RUNNING' || state.status === 'STARTING' || state.status === 'STOPPING';
            if (stopBotBtn) stopBotBtn.disabled = state.status !== 'RUNNING';

            // Update Parameter Inputs if config exists
            if (state.config) {
                // Strategy selector and visibility
                if (strategySelector) {
                    strategySelector.value = state.config.STRATEGY_TYPE || 'SWING'; // Default to SWING if missing
                    UI.updateParameterVisibility(strategySelector.value);
                }

                // Helper function to convert backend fractions to frontend percentages
                const toPercent = (value) => (value !== null && value !== undefined && !isNaN(parseFloat(value))) ? (parseFloat(value) * 100).toString() : '';

                // Common Params (Risk/Capital/Exit)
                if (paramRisk) paramRisk.value = toPercent(state.config.RISK_PER_TRADE);
                if (paramCapitalAllocation) paramCapitalAllocation.value = toPercent(state.config.CAPITAL_ALLOCATION);
                if (paramSl) paramSl.value = toPercent(state.config.STOP_LOSS_PERCENTAGE);
                if (paramTp1) paramTp1.value = toPercent(state.config.TAKE_PROFIT_1_PERCENTAGE);
                if (paramTp2) paramTp2.value = toPercent(state.config.TAKE_PROFIT_2_PERCENTAGE);
                if (paramTrailing) paramTrailing.value = toPercent(state.config.TRAILING_STOP_PERCENTAGE);
                if (paramTimeStop) paramTimeStop.value = state.config.TIME_STOP_MINUTES ?? ''; // Utiliser '' si null/undefined

                // SWING Params
                if (paramTimeframe) paramTimeframe.value = state.config.TIMEFRAME || '1m'; // Utiliser TIMEFRAME
                if (paramEmaShort) paramEmaShort.value = state.config.EMA_SHORT_PERIOD ?? '';
                if (paramEmaLong) paramEmaLong.value = state.config.EMA_LONG_PERIOD ?? '';
                if (paramEmaFilter) paramEmaFilter.value = state.config.EMA_FILTER_PERIOD ?? '';
                if (paramRsiPeriod) paramRsiPeriod.value = state.config.RSI_PERIOD ?? '';
                if (paramRsiOb) paramRsiOb.value = state.config.RSI_OVERBOUGHT ?? '';
                if (paramRsiOs) paramRsiOs.value = state.config.RSI_OVERSOLD ?? '';
                if (paramVolumeAvg) paramVolumeAvg.value = state.config.VOLUME_AVG_PERIOD ?? '';
                if (paramUseEmaFilter) paramUseEmaFilter.checked = state.config.USE_EMA_FILTER ?? false;
                if (paramUseVolume) paramUseVolume.checked = state.config.USE_VOLUME_CONFIRMATION ?? false;

                // SCALPING (Order Book) Specific Params
                if(paramScalpingOrderType) paramScalpingOrderType.value = state.config.SCALPING_ORDER_TYPE || 'MARKET';
                if(paramScalpingLimitTif) paramScalpingLimitTif.value = state.config.SCALPING_LIMIT_TIF || 'GTC';
                if(paramScalpingLimitTimeout) paramScalpingLimitTimeout.value = state.config.SCALPING_LIMIT_ORDER_TIMEOUT_MS ?? '';
                if(paramScalpingDepthLevels) paramScalpingDepthLevels.value = state.config.SCALPING_DEPTH_LEVELS || '5';
                if(paramScalpingDepthSpeed) paramScalpingDepthSpeed.value = state.config.SCALPING_DEPTH_SPEED || '1000ms';
                // Pour les seuils, afficher la valeur brute (fraction ou nombre)
                if(paramScalpingSpreadThreshold) paramScalpingSpreadThreshold.value = state.config.SCALPING_SPREAD_THRESHOLD ?? '';
                if(paramScalpingImbalanceThreshold) paramScalpingImbalanceThreshold.value = state.config.SCALPING_IMBALANCE_THRESHOLD ?? '';
                if (paramOrderCooldown) paramOrderCooldown.value = state.config.ORDER_COOLDOWN_MS ?? '';


                // SCALPING 2 (Indicators) Specific Params
                if (paramSupertrendAtr) paramSupertrendAtr.value = state.config.SUPERTREND_ATR_PERIOD ?? '';
                if (paramSupertrendMult) paramSupertrendMult.value = state.config.SUPERTREND_ATR_MULTIPLIER ?? '';
                if (paramRsiPeriodScalp) paramRsiPeriodScalp.value = state.config.SCALPING_RSI_PERIOD ?? '';
                if (paramStochK) paramStochK.value = state.config.STOCH_K_PERIOD ?? '';
                if (paramStochD) paramStochD.value = state.config.STOCH_D_PERIOD ?? '';
                if (paramStochSmooth) paramStochSmooth.value = state.config.STOCH_SMOOTH ?? '';
                if (paramBbPeriod) paramBbPeriod.value = state.config.BB_PERIOD ?? '';
                if (paramBbStd) paramBbStd.value = state.config.BB_STD ?? '';
                if (paramVolMa) paramVolMa.value = state.config.VOLUME_MA_PERIOD ?? ''; // Volume MA pour Scalping2

            } else {
                console.warn("State received without config object. Cannot update parameters.");
                // Optionnel: Vider les champs de paramètres ou afficher un message
            }
        },
        updateOrderHistory: function(history) {
            if (!orderHistoryBody) {
                console.error("Order history table body not found!");
                return;
            }
            orderHistoryBody.innerHTML = ''; // Vider le contenu actuel

            // console.log("Updating order history table with data:", history); // Garder commenté sauf pour debug

            if (!Array.isArray(history) || history.length === 0) {
                if (orderHistoryPlaceholder && 'content' in orderHistoryPlaceholder) { // Vérifier si c'est un template
                     try {
                        const placeholderClone = orderHistoryPlaceholder.content.cloneNode(true);
                        orderHistoryBody.appendChild(placeholderClone);
                     } catch (e) {
                         console.error("Error using order history placeholder template:", e);
                         // Fallback si le template échoue
                         const row = orderHistoryBody.insertRow();
                         const cell = row.insertCell();
                         cell.colSpan = 12; // Ajuster selon le nombre de colonnes
                         cell.textContent = "Aucun ordre dans l'historique.";
                         cell.style.textAlign = 'center';
                     }
                } else {
                     // Fallback si l'élément placeholder n'est pas un template
                     const row = orderHistoryBody.insertRow();
                     const cell = row.insertCell();
                     cell.colSpan = 12; // Ajuster selon le nombre de colonnes
                     cell.textContent = "Aucun ordre dans l'historique.";
                     cell.style.textAlign = 'center';
                }
                return;
            }

            // Trier l'historique par timestamp décroissant (le plus récent en premier)
            // Assurer que les timestamps sont bien des nombres pour le tri
            history.sort((a, b) => (parseInt(b.timestamp || 0)) - (parseInt(a.timestamp || 0)));

            history.forEach(order => {
                const row = document.createElement('tr'); // Créer une nouvelle ligne

                // Performance Pct - Gérer null/undefined et formater
                const performancePctValue = order.performance_pct; // Peut être string "x.xx%" ou null
                let performancePctText = '-';
                let perfClass = '';
                if (performancePctValue !== null && performancePctValue !== undefined) {
                    // Si c'est déjà un string formaté en %, l'utiliser directement
                    if (typeof performancePctValue === 'string' && performancePctValue.includes('%')) {
                        performancePctText = performancePctValue;
                        // Essayer d'extraire la valeur numérique pour la classe CSS
                        const numericPerf = parseFloat(performancePctValue.replace('%', ''));
                        if (!isNaN(numericPerf)) {
                            perfClass = numericPerf >= 0 ? 'perf-positive' : 'perf-negative';
                        }
                    } else {
                        // Sinon, essayer de convertir en nombre et formater
                        const numericPerf = parseFloat(performancePctValue);
                        if (!isNaN(numericPerf)) {
                            performancePctText = `${formatNumber(numericPerf * 100, 2)}%`; // Multiplier par 100 si c'est une fraction
                            perfClass = numericPerf >= 0 ? 'perf-positive' : 'perf-negative';
                        }
                    }
                }


                // Calculer Avg Price si nécessaire (pour ordres MARKET)
                let avgPrice = order.price; // Prix de l'ordre (pour LIMIT)
                const executedQtyNum = parseFloat(order.executedQty || 0);
                const cummQuoteQtyNum = parseFloat(order.cummulativeQuoteQty || 0);

                // Si prix est 0 ou invalide, et que l'ordre a été exécuté, calculer le prix moyen
                if ((!avgPrice || parseFloat(avgPrice) === 0) && cummQuoteQtyNum > 0 && executedQtyNum > 0) {
                    avgPrice = cummQuoteQtyNum / executedQtyNum;
                }

                const priceOrValueText = formatNumber(avgPrice, 4); // Formater le prix (calculé ou direct)

                // Valeur en quote asset
                let quoteValue = '-';
                if (!isNaN(cummQuoteQtyNum) && cummQuoteQtyNum > 0) {
                    quoteValue = formatNumber(cummQuoteQtyNum, 2);
                } else if (!isNaN(executedQtyNum) && !isNaN(avgPrice)) {
                    quoteValue = formatNumber(executedQtyNum * avgPrice, 2);
                }

                // Classe CSS pour BUY/SELL
                const sideClass = order.side === 'BUY' ? 'side-buy' : (order.side === 'SELL' ? 'side-sell' : '');

                // Remplir la ligne
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
                orderHistoryBody.appendChild(row); // Ajouter la ligne au tbody
            });
        },
        updateParameterVisibility: function(selectedStrategy) {
            // Cacher tout par défaut, mais vérifier si l'élément existe avant
            if (swingParamsDiv) swingParamsDiv.style.display = 'none';
            if (scalpingParamsDiv) scalpingParamsDiv.style.display = 'none'; // Contient les params communs SL/TP etc.
            if (scalpingSpecificParamsDiv) scalpingSpecificParamsDiv.style.display = 'none';
            if (scalping2SpecificParamsDiv) scalping2SpecificParamsDiv.style.display = 'none';

            // Désactiver/Réactiver Timeframe - Vérifier si l'élément existe
            if (paramTimeframe) paramTimeframe.disabled = false; // Réactiver par défaut
            if (timeframeRelevance) timeframeRelevance.textContent = ''; // Effacer par défaut

            if (selectedStrategy === 'SWING') {
                if (swingParamsDiv) swingParamsDiv.style.display = 'block';
                if (scalpingParamsDiv) scalpingParamsDiv.style.display = 'none'; // Afficher SL/TP etc.
                if (timeframeRelevance) timeframeRelevance.textContent = '(Pertinent pour SWING)';
            } else if (selectedStrategy === 'SCALPING') {
                if (scalpingParamsDiv) scalpingParamsDiv.style.display = 'block'; // Afficher SL/TP etc.
                if (scalpingSpecificParamsDiv) scalpingSpecificParamsDiv.style.display = 'block';
                if (paramTimeframe) paramTimeframe.disabled = true;
                if (timeframeRelevance) timeframeRelevance.textContent = '(Non pertinent pour SCALPING)';
            } else if (selectedStrategy === 'SCALPING2') {
                if (scalpingParamsDiv) scalpingParamsDiv.style.display = 'block'; // Afficher SL/TP etc.
                if (scalping2SpecificParamsDiv) scalping2SpecificParamsDiv.style.display = 'block';
                // Timeframe est pertinent pour SCALPING2, donc on ne le désactive pas (déjà fait par défaut)
                if (timeframeRelevance) timeframeRelevance.textContent = '(Pertinent pour SCALPING2)';
            }
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
                        // Utiliser formatNumber pour une précision adaptative
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

            // Crée le tableau et l'en-tête s'ils n'existent pas
            let table = container.querySelector("table.signals-table");
            if (!table) {
                table = document.createElement("table");
                table.className = "signals-table"; // Ajouter une classe pour le style
                table.innerHTML = `<thead><tr><th>Heure</th><th>Type</th><th>Direction</th><th>Validé</th><th>Raison</th><th>Prix</th></tr></thead><tbody></tbody>`;
                container.innerHTML = ""; // Vider le conteneur avant d'ajouter le tableau
                container.appendChild(table);
            }

            const tbody = table.querySelector("tbody");
            if (!tbody) return; // Sécurité

            const ts = new Date().toLocaleTimeString(); // Heure locale
            const row = document.createElement("tr"); // Créer une nouvelle ligne

            // Remplir la ligne avec les données de l'événement
            row.innerHTML = `
                <td>${ts}</td>
                <td>${event.signal_type ? event.signal_type.toUpperCase() : "-"}</td>
                <td>${event.direction ? event.direction.toUpperCase() : "-"}</td>
                <td>${event.valid ? "✅" : "❌"}</td>
                <td>${event.reason || "-"}</td>
                <td>${event.price !== undefined ? formatNumber(event.price, 2) : "-"}</td>
            `;

            // Ajouter la nouvelle ligne en haut du tbody
            tbody.insertBefore(row, tbody.firstChild);

            // Limiter le nombre de lignes affichées (par exemple, les 5 dernières)
            const maxSignalRows = 5;
            while (tbody.rows.length > maxSignalRows) {
                tbody.deleteRow(tbody.rows.length - 1); // Supprimer la ligne la plus ancienne
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
        // Ajuster la précision basée sur la magnitude
        if (Math.abs(number) >= 1000) decimals = 2;
        else if (Math.abs(number) >= 10) decimals = 4;
        else if (Math.abs(number) >= 0.1) decimals = 6;
        // Sinon, garder 8 par défaut pour les petites quantités/prix crypto
        try {
            return number.toLocaleString(undefined, {
                minimumFractionDigits: decimals,
                maximumFractionDigits: decimals
            });
        } catch (e) {
            console.error("Error formatting number:", num, e);
            // Fallback simple si toLocaleString échoue
            return number.toFixed(decimals);
        }
    }

    function formatTimestamp(timestamp) {
        if (!timestamp) return 'N/A';
        try {
            const date = new Date(parseInt(timestamp));
            if (isNaN(date.getTime())) return 'Invalid Date';
            return date.toLocaleString(); // Utilise le format local de l'utilisateur
        } catch (e) {
            console.error("Error formatting timestamp:", timestamp, e);
            return 'Invalid Date';
        }
    }

    // --- WebSocket Logic ---
    function connectWebSocket() {
        if (ws && ws.readyState !== WebSocket.CLOSED) { // Vérifier aussi readyState
            console.warn("WebSocket connection already exists or is connecting.");
            return;
        }
        console.log(`Attempting to connect WebSocket to: ${WS_URL}`);
        UI.appendLog("Tentative de connexion au backend...", "info");
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            console.log('WebSocket connection established');
            UI.appendLog("WebSocket connecté.", "info");
            fetchBotState(); // Récupérer l'état une fois connecté
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                // console.debug('WebSocket message received:', data); // Garder commenté sauf pour debug

                switch (data.type) {
                    case 'log':
                    case 'debug': // Traiter debug comme log normal
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
                            // console.log("Status Update Received:", data.state); // Garder commenté sauf pour debug
                            UI.updateUI(data.state); // Met à jour les éléments non-prix
                            UI.updatePriceDisplay(data.state.latest_book_ticker); // Met à jour le prix
                            // L'historique est inclus dans l'état complet, le mettre à jour aussi
                            if (data.state.order_history) {
                                UI.updateOrderHistory(data.state.order_history);
                            }
                        } else {
                            console.warn("Received status_update without state data:", data);
                        }
                        break;
                    case 'ticker_update': // Gère les mises à jour légères du ticker
                        // console.debug("Ticker Update Received:", data.ticker); // Garder commenté sauf pour debug
                        UI.updatePriceDisplay(data.ticker); // Met à jour seulement le prix
                        break;
                    case 'order_history_update': // Peut être redondant si status_update l'inclut déjà
                        // Rafraîchir l'historique filtré côté client
                        fetchAndDisplayOrderHistory();
                        UI.appendLog("Historique des ordres mis à jour (via push dédié).", "info");
                        break;
                    case 'ping':
                        // Le serveur peut envoyer des pings, le client gère généralement les pongs automatiquement
                        // Si un pong explicite est nécessaire: ws.send(JSON.stringify({ type: 'pong' }));
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
            if (startBotBtn) startBotBtn.disabled = false; // Permettre de réessayer ? Ou laisser désactivé ?
            ws = null; // Important de remettre à null en cas d'erreur
        };

        ws.onclose = (event) => {
            const wasConnected = !!ws; // Vérifier si ws était non-null avant de réinitialiser
            ws = null; // Réinitialiser la variable ws D'ABORD
            console.log(`WebSocket connection closed. Code: ${event.code}, Reason: ${event.reason}`);

            // Mettre à jour l'UI pour refléter l'état déconnecté
            if (statusValue) {
                statusValue.textContent = 'Déconnecté';
                statusValue.className = 'status-stopped';
            }
            if (stopBotBtn) stopBotBtn.disabled = true;
            if (startBotBtn) startBotBtn.disabled = false; // Permettre de redémarrer

            // Ne loguer un avertissement et tenter une reconnexion que si la fermeture était inattendue
            if (wasConnected && event.code !== 1000 && event.code !== 1001) { // 1000 = Normal, 1001 = Going Away (fermeture onglet)
                 UI.appendLog(`Connexion WebSocket fermée (Code: ${event.code}). Tentative de reconnexion dans 5s...`, 'warn');
                 // Tentative simple de reconnexion après 5 secondes
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
                    // Essayer de lire le message d'erreur JSON du backend
                    const errorResult = await response.json();
                    errorMsg = errorResult.message || errorMsg;
                } catch (e) { console.error("Error parsing error response:", e); }
                throw new Error(errorMsg);
            }
            const state = await response.json();
            UI.updateUI(state); // Mettre à jour l'UI avec l'état complet
            // L'historique est maintenant mis à jour via UI.updateUI si présent dans l'état
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
        if(stopBotBtn) stopBotBtn.disabled = true; // Désactiver aussi Stop pendant le démarrage
        try {
            const response = await fetch(`${API_BASE_URL}/api/start`, { method: 'POST' });
            const result = await response.json();
            if (!response.ok) {
                // Si échec, l'erreur est levée et catchée
                throw new Error(result.message || `Erreur serveur: ${response.status}`);
            }
            UI.appendLog(result.message || 'Commande Démarrer envoyée.', 'info');
            // L'état sera mis à jour par WebSocket (status_update)
        } catch (error) {
            console.error('Error starting bot:', error);
            UI.appendLog(`Erreur au démarrage du bot: ${error.message}`, 'error');
            // Réactiver les boutons seulement si l'API échoue, sinon laisser WS gérer
            if(startBotBtn) startBotBtn.disabled = false;
            // Ne pas réactiver Stop ici, car l'état est incertain
            // fetchBotState(); // Optionnel: forcer refresh état si WS lent
        }
    }

    async function stopBot() {
        UI.appendLog("Envoi de la commande Arrêter...", "info");
        if(stopBotBtn) stopBotBtn.disabled = true;
        if(startBotBtn) startBotBtn.disabled = true; // Désactiver aussi Start pendant l'arrêt
        try {
            const response = await fetch(`${API_BASE_URL}/api/stop`, { method: 'POST' });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.message || `Erreur serveur: ${response.status}`);
            }
            UI.appendLog(result.message || 'Commande Arrêter envoyée.', 'info');
            // L'état sera mis à jour par WebSocket (status_update)
        } catch (error) {
            console.error('Error stopping bot:', error);
            UI.appendLog(`Erreur à l'arrêt du bot: ${error.message}`, 'error');
            // Réactiver les boutons seulement si l'API échoue
             if(stopBotBtn) stopBotBtn.disabled = false; // Ou se fier à l'état reçu par WS ?
            // fetchBotState(); // Optionnel: forcer refresh état
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
            // --- Stratégie ---
            STRATEGY_TYPE: strategySelector ? strategySelector.value : null,
            TIMEFRAME: safeValue(paramTimeframe),

            // --- Paramètres Communs (Gestion Risque/Capital/Exit) ---
            RISK_PER_TRADE: safeValue(paramRisk, parseFloat),
            CAPITAL_ALLOCATION: safeValue(paramCapitalAllocation, parseFloat),
            STOP_LOSS_PERCENTAGE: safeValue(paramSl, parseFloat),
            TAKE_PROFIT_1_PERCENTAGE: safeValue(paramTp1, parseFloat),
            TAKE_PROFIT_2_PERCENTAGE: safeValue(paramTp2, parseFloat),
            TRAILING_STOP_PERCENTAGE: safeValue(paramTrailing, parseFloat),
            TIME_STOP_MINUTES: safeValue(paramTimeStop, v => parseInt(v, 10)),

            // --- Paramètres Swing ---
            EMA_SHORT_PERIOD: safeValue(paramEmaShort, v => parseInt(v, 10)),
            EMA_LONG_PERIOD: safeValue(paramEmaLong, v => parseInt(v, 10)),
            EMA_FILTER_PERIOD: safeValue(paramEmaFilter, v => parseInt(v, 10)),
            RSI_PERIOD: safeValue(paramRsiPeriod, v => parseInt(v, 10)),
            RSI_OVERBOUGHT: safeValue(paramRsiOb, v => parseInt(v, 10)),
            RSI_OVERSOLD: safeValue(paramRsiOs, v => parseInt(v, 10)),
            VOLUME_AVG_PERIOD: safeValue(paramVolumeAvg, v => parseInt(v, 10)),
            USE_EMA_FILTER: paramUseEmaFilter ? paramUseEmaFilter.checked : null,
            USE_VOLUME_CONFIRMATION: paramUseVolume ? paramUseVolume.checked : null,

            // --- Paramètres Scalping (Order Book) ---
            SCALPING_ORDER_TYPE: paramScalpingOrderType ? paramScalpingOrderType.value : null,
            SCALPING_LIMIT_TIF: paramScalpingLimitTif ? paramScalpingLimitTif.value : null,
            SCALPING_LIMIT_ORDER_TIMEOUT_MS: safeValue(paramScalpingLimitTimeout, v => parseInt(v, 10)),
            SCALPING_DEPTH_LEVELS: safeValue(paramScalpingDepthLevels, v => parseInt(v, 10)),
            SCALPING_DEPTH_SPEED: paramScalpingDepthSpeed ? paramScalpingDepthSpeed.value : null,
            SCALPING_SPREAD_THRESHOLD: safeValue(paramScalpingSpreadThreshold, parseFloat),
            SCALPING_IMBALANCE_THRESHOLD: safeValue(paramScalpingImbalanceThreshold, parseFloat),
            ORDER_COOLDOWN_MS: safeValue(paramOrderCooldown, v => parseInt(v, 10)),

            // --- Paramètres Scalping 2 (Indicateurs) ---
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

        // Filtrer les clés avec valeur null (le backend les ignorera)
        const cleanedParamsToSend = Object.fromEntries(
            Object.entries(paramsToSend).filter(([_, v]) => v !== null && v !== undefined && !(typeof v === 'number' && isNaN(v)))
        );

        console.log("Sending parameters:", JSON.stringify(cleanedParamsToSend, null, 2)); // Log pour vérifier

        try {
            const response = await fetch(`${API_BASE_URL}/api/parameters`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(cleanedParamsToSend), // Envoyer les paramètres nettoyés
            });
            const result = await response.json(); // Toujours essayer de parser JSON

            if (!response.ok) {
                // Lever une erreur avec le message du backend si disponible
                throw new Error(result.message || `Erreur serveur: ${response.status}`);
            }

            // Succès
            if (paramSaveStatus) {
                paramSaveStatus.textContent = result.message || 'Paramètres sauvegardés!';
                paramSaveStatus.className = 'status-success';
            }
            UI.appendLog(result.message || 'Paramètres sauvegardés.', 'info'); // Log succès
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
            UI.appendLog(`Erreur sauvegarde paramètres: ${error.message}`, 'error'); // Log erreur

        } finally {
            // Réactiver le bouton et effacer le statut après un délai
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
        } catch (e) {
            UI.updateOrderHistory([]); // Afficher vide en cas d'erreur
        }
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
        });
    }


    // --- Initial Setup ---
    // Mettre à jour la visibilité initiale basée sur la valeur par défaut du sélecteur
    if (strategySelector) {
        UI.updateParameterVisibility(strategySelector.value);
    }
    // Établir la connexion WebSocket
    connectWebSocket();

}); // End DOMContentLoaded
