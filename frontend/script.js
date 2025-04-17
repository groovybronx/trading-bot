document.addEventListener('DOMContentLoaded', () => {
    // Éléments du DOM (inchangés)
    const statusValue = document.getElementById('status-value');
    const symbolValue = document.getElementById('symbol-value');
    const timeframeValue = document.getElementById('timeframe-value');
    const positionValue = document.getElementById('position-value');
    const balanceValue = document.getElementById('balance-value');
    const quoteAssetLabel = document.getElementById('quote-asset-label');
    const quantityValue = document.getElementById('quantity-value');
    const baseAssetLabel = document.getElementById('base-asset-label');
    const priceValue = document.getElementById('price-value');
    const symbolPriceLabel = document.getElementById('symbol-price-label');
    const logOutput = document.getElementById('log-output');
    const startBtn = document.getElementById('start-bot-btn');
    const stopBtn = document.getElementById('stop-bot-btn');
    const orderHistoryBody = document.getElementById('order-history-body');
    const paramInputs = { /* ... (inchangé) ... */
        TIMEFRAME_STR: document.getElementById('param-timeframe'),
        EMA_SHORT_PERIOD: document.getElementById('param-ema-short'),
        EMA_LONG_PERIOD: document.getElementById('param-ema-long'),
        EMA_FILTER_PERIOD: document.getElementById('param-ema-filter'),
        RSI_PERIOD: document.getElementById('param-rsi-period'),
        RSI_OVERBOUGHT: document.getElementById('param-rsi-ob'),
        RSI_OVERSOLD: document.getElementById('param-rsi-os'),
        RISK_PER_TRADE: document.getElementById('param-risk'),
        CAPITAL_ALLOCATION: document.getElementById('param-capital-allocation'),
        VOLUME_AVG_PERIOD: document.getElementById('param-volume-avg'),
        USE_EMA_FILTER: document.getElementById('param-use-ema-filter'),
        USE_VOLUME_CONFIRMATION: document.getElementById('param-use-volume'),
    };
    const saveParamsBtn = document.getElementById('save-params-btn');
    const paramSaveStatus = document.getElementById('param-save-status');

    // État initial (inchangé)
    statusValue.textContent = 'Chargement...';
    statusValue.style.color = 'orange';
    logOutput.textContent = 'Initialisation du frontend...';
    startBtn.disabled = true;
    stopBtn.disabled = true;

    // --- Communication avec le Backend ---
    const API_BASE_URL = 'http://127.0.0.1:5000';

    // --- Connexion au flux de logs SSE ---
    let evtSource = null;
    function connectLogStream() {
        if (evtSource) {
            evtSource.close();
            console.log("Ancienne connexion SSE fermée.");
        }
        addLogDirect("Tentative de connexion au flux de logs...");
        evtSource = new EventSource(`${API_BASE_URL}/stream_logs`);

        evtSource.onopen = function() {
            console.log("Connexion SSE ouverte.");
            // addLogDirect("Connecté au flux de logs du backend.");
        };

        // --- MODIFICATION ICI ---
        evtSource.onmessage = function(event) {
            const logMessage = event.data;
            addLogDirect(logMessage); // Ajouter le log à l'affichage

            // Vérifier si le message indique qu'un ordre a été ajouté
            // Utiliser une condition plus spécifique pour éviter les faux positifs
            if (logMessage.includes("Ordre ") && logMessage.includes("ajouté à l'historique")) {
                console.log("Détection d'un nouvel ordre dans les logs, mise à jour de l'historique...");
                addLogFromJS("Nouvel ordre détecté, rafraîchissement de l'historique...");
                fetchOrderHistory(); // Appeler la fonction pour rafraîchir l'historique
            }
        };
        // --- FIN MODIFICATION ---

        evtSource.onerror = function(err) {
            console.error("Erreur EventSource:", err);
            addLogDirect("!!! Erreur de connexion au flux de logs. Vérifiez que le backend est lancé. Reconnexion auto...");
        };
    }
    // --- FIN SSE ---

    function addLogDirect(message) {
        if (logOutput) {
            logOutput.textContent += `\n${message}`;
            logOutput.scrollTop = logOutput.scrollHeight;
        } else {
            console.warn("Élément logOutput non trouvé ! Message:", message);
        }
    }

    function addLogFromJS(message) {
        const timestamp = new Date().toLocaleTimeString();
        addLogDirect(`[${timestamp}] (FRONTEND) ${message}`);
    }

    // --- Fonctions pour l'historique des ordres (inchangées) ---
    function fetchOrderHistory() {
        fetch(`${API_BASE_URL}/order_history`)
            .then(response => {
                if (!response.ok) {
                    return response.text().then(text => {
                        throw new Error(`HTTP ${response.status}: ${text || response.statusText}`);
                    });
                }
                return response.json();
            })
            .then(orders => {
                updateOrderHistoryUI(orders);
            })
            .catch(error => {
                console.error('Erreur de récupération de l\'historique des ordres:', error);
                addLogFromJS(`Erreur historique ordres: ${error.message}`);
                if (orderHistoryBody) {
                     orderHistoryBody.innerHTML = `<tr><td colspan="10" style="color: red;">Erreur chargement historique: ${error.message}</td></tr>`;
                }
            });
    }

    function updateOrderHistoryUI(orders) {
        // ... (contenu de la fonction updateOrderHistoryUI reste exactement le même qu'avant) ...
        if (!orderHistoryBody) return;
        orderHistoryBody.innerHTML = ''; // Vider le corps du tableau

        const placeholderElement = document.getElementById('order-history-placeholder');

        if (!orders || orders.length === 0) {
             if (placeholderElement) {
                if (placeholderElement.tagName === 'TR') {
                    const clonedPlaceholder = placeholderElement.cloneNode(true);
                    const td = clonedPlaceholder.querySelector('td');
                    if (td) td.colSpan = 10;
                    orderHistoryBody.appendChild(clonedPlaceholder);
                } else {
                     orderHistoryBody.innerHTML = '<tr><td colspan="10">Aucun ordre dans l\'historique de cette session.</td></tr>';
                }
             } else {
                 orderHistoryBody.innerHTML = '<tr><td colspan="10">Aucun ordre dans l\'historique de cette session.</td></tr>';
             }
            return;
        }

        orders.slice().reverse().forEach(order => {
            const row = document.createElement('tr');
            const timestamp = order.timestamp ? new Date(order.timestamp).toLocaleString() : 'N/A';

            let priceOrValue = 'N/A';
            const executedQtyNum = parseFloat(order.executedQty);
            const cummulativeQuoteQtyNum = parseFloat(order.cummulativeQuoteQty);
            if (order.type === 'MARKET' && !isNaN(cummulativeQuoteQtyNum) && !isNaN(executedQtyNum) && executedQtyNum > 0) {
                const avgPrice = cummulativeQuoteQtyNum / executedQtyNum;
                priceOrValue = `${cummulativeQuoteQtyNum.toFixed(2)} (${avgPrice.toFixed(4)} avg)`;
            } else if (order.price) {
                try { priceOrValue = parseFloat(order.price).toFixed(4); }
                catch (e) { priceOrValue = order.price; }
            }

            const origQtyStr = order.origQty ? parseFloat(order.origQty).toFixed(6) : 'N/A';
            const executedQtyStr = order.executedQty ? parseFloat(order.executedQty).toFixed(6) : 'N/A';

            let performanceHtml = '<td>N/A</td>';
            if (typeof order.performance_pct === 'number' && isFinite(order.performance_pct)) {
                const perfValue = order.performance_pct;
                const perfFormatted = perfValue.toFixed(2) + '%';
                let perfClass = '';
                if (perfValue > 0) {
                    perfClass = 'performance-positive';
                } else if (perfValue < 0) {
                    perfClass = 'performance-negative';
                }
                performanceHtml = `<td class="${perfClass}">${perfFormatted}</td>`;
            }

            row.className = `status-${(order.status || 'unknown').toLowerCase()}`;

            row.innerHTML = `
                <td>${timestamp}</td>
                <td>${order.symbol || 'N/A'}</td>
                <td class="${order.side?.toLowerCase()}">${order.side || 'N/A'}</td>
                <td>${order.type || 'N/A'}</td>
                <td>${origQtyStr}</td>
                <td>${executedQtyStr}</td>
                <td>${priceOrValue}</td>
                <td>${order.status || 'N/A'}</td>
                ${performanceHtml}
                <td>${order.orderId || 'N/A'}</td>
            `;
            orderHistoryBody.appendChild(row);
        });
    }
    // --- FIN HISTORIQUE ---

    // --- Fonctions Statut et Paramètres (inchangées) ---
    function fetchBotStatus() { /* ... (inchangé) ... */
        fetch(`${API_BASE_URL}/status`)
        .then(response => {
             if (!response.ok) {
                 return response.text().then(text => { throw new Error(`HTTP ${response.status}: ${text || response.statusText}`); });
             }
             return response.json();
         })
        .then(data => {
            updateStatusUI(data);
        })
        .catch(error => {
            console.error('Erreur de récupération du statut:', error);
            addLogFromJS(`Erreur connexion statut: ${error.message}`);
            updateStatusUI({ status: 'Erreur Connexion' });
        });
    }

    function fetchParameters() { /* ... (inchangé) ... */
        addLogFromJS("Chargement des paramètres...");
        fetch(`${API_BASE_URL}/parameters`)
            .then(response => {
                if (!response.ok) { throw new Error(`HTTP ${response.status}: ${response.statusText}`); }
                return response.json();
            })
            .then(data => {
                console.log("Paramètres reçus:", data);
                for (const key in paramInputs) {
                    if (data.hasOwnProperty(key) && paramInputs[key]) {
                        const inputElement = paramInputs[key];
                        if (inputElement.type === 'checkbox') { inputElement.checked = data[key]; }
                        else if (inputElement.name === 'RISK_PER_TRADE') { inputElement.value = (data[key] * 100).toFixed(1); }
                        else if (inputElement.name === 'CAPITAL_ALLOCATION') { inputElement.value = (data[key] * 100).toFixed(0); }
                        else { inputElement.value = data[key]; }
                    } else if (paramInputs[key]) { console.warn(`Clé paramètre "${key}" non trouvée dans les données backend.`); }
                }
                addLogFromJS("Paramètres chargés.");
                fetchBotStatus();
            })
            .catch(error => {
                console.error('Erreur de récupération des paramètres:', error);
                addLogFromJS(`Erreur chargement paramètres: ${error.message}`);
                paramSaveStatus.textContent = "Erreur chargement paramètres."; paramSaveStatus.style.color = 'red';
                startBtn.disabled = true; stopBtn.disabled = true;
            });
    }

    function updateStatusUI(data) { /* ... (inchangé) ... */
        const status = data.status || 'Inconnu';
        statusValue.textContent = status;
        symbolValue.textContent = data.symbol || 'N/A';
        timeframeValue.textContent = data.timeframe || 'N/A';
        positionValue.textContent = data.in_position ? 'Oui' : 'Non';
        positionValue.style.fontWeight = data.in_position ? 'bold' : 'normal';
        positionValue.style.color = data.in_position ? 'blue' : 'inherit';

        if (quoteAssetLabel) { quoteAssetLabel.textContent = data.quote_asset || 'USDT'; }
        if (balanceValue) {
            balanceValue.textContent = data.available_balance !== undefined && data.available_balance !== null
                ? parseFloat(data.available_balance).toFixed(2) : 'N/A';
        }
        if (baseAssetLabel) { baseAssetLabel.textContent = data.base_asset || 'N/A'; }
        if (quantityValue) {
            quantityValue.textContent = data.symbol_quantity !== undefined && data.symbol_quantity !== null
                ? parseFloat(data.symbol_quantity).toFixed(6) : 'N/A';
        }
        if (symbolPriceLabel) { symbolPriceLabel.textContent = data.symbol || 'N/A'; }
        if (priceValue) {
             priceValue.textContent = data.current_price !== undefined && data.current_price !== null
                ? parseFloat(data.current_price).toFixed(4) : 'N/A';
        }

        if (status === 'En cours') {
            statusValue.style.color = 'green';
            startBtn.disabled = true;
            stopBtn.disabled = false;
        } else if (status === 'Arrêté') {
            statusValue.style.color = 'red';
            startBtn.disabled = false;
            stopBtn.disabled = true;
        } else {
            statusValue.style.color = 'orange';
            startBtn.disabled = true;
            stopBtn.disabled = true;
        }
    }

    // --- Gestion des Contrôles (Start/Stop) (inchangée) ---
    startBtn.addEventListener('click', () => { /* ... (inchangé) ... */
        addLogFromJS("Tentative de démarrage du bot...");
        startBtn.disabled = true;
        stopBtn.disabled = true;
        statusValue.textContent = 'Démarrage...'; statusValue.style.color = 'orange';

        fetch(`${API_BASE_URL}/start`, { method: 'POST' })
            .then(response => {
                if (!response.ok) {
                    return response.json().catch(() => null)
                        .then(errorData => {
                            const errorMsg = errorData?.message || `Erreur HTTP ${response.status}`;
                            throw new Error(errorMsg);
                        });
                }
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    addLogFromJS(data.message || "Ordre de démarrage envoyé.");
                    fetchBotStatus();
                    fetchOrderHistory(); // Rafraîchir l'historique au démarrage
                } else {
                    addLogFromJS(`Échec démarrage: ${data.message || 'Raison inconnue'}`);
                    console.warn("Échec démarrage (logique backend):", data);
                    fetchBotStatus();
                }
            })
            .catch(error => {
                console.error('Erreur communication démarrage:', error);
                addLogFromJS(`Erreur communication démarrage: ${error.message}`);
                fetchBotStatus();
            });
    });

    stopBtn.addEventListener('click', () => { /* ... (inchangé) ... */
        addLogFromJS("Tentative d'arrêt du bot...");
        startBtn.disabled = true;
        stopBtn.disabled = true;
        statusValue.textContent = 'Arrêt...'; statusValue.style.color = 'orange';

        fetch(`${API_BASE_URL}/stop`, { method: 'POST' })
             .then(response => {
                if (!response.ok) {
                    return response.json().catch(() => null)
                        .then(errorData => {
                            const errorMsg = errorData?.message || `Erreur HTTP ${response.status}`;
                            throw new Error(errorMsg);
                        });
                }
                return response.json();
            })
            .then(data => {
                 if (data.success) {
                    addLogFromJS(data.message || "Ordre d'arrêt envoyé.");
                    fetchBotStatus();
                } else {
                    addLogFromJS(`Échec arrêt: ${data.message || 'Raison inconnue'}`);
                    console.warn("Échec arrêt (logique backend):", data);
                    fetchBotStatus();
                }
            })
            .catch(error => {
                console.error('Erreur communication arrêt:', error);
                addLogFromJS(`Erreur communication arrêt: ${error.message}`);
                fetchBotStatus();
            });
    });

    // --- Écouteur pour Sauvegarder les Paramètres (inchangé) ---
    saveParamsBtn.addEventListener('click', () => { /* ... (inchangé) ... */
        addLogFromJS("Sauvegarde des paramètres en cours...");
        paramSaveStatus.textContent = "Sauvegarde..."; paramSaveStatus.style.color = "orange";
        saveParamsBtn.disabled = true;

        const newParams = {};
        let isValid = true;
        for (const key in paramInputs) {
            if (paramInputs[key]) {
                const inputElement = paramInputs[key];
                try {
                    if (inputElement.type === 'checkbox') { newParams[key] = inputElement.checked; }
                    else if (inputElement.type === 'number') {
                        const value = parseFloat(inputElement.value);
                        if (isNaN(value)) { throw new Error(`Valeur invalide pour ${key}`); }

                        if (inputElement.name === 'RISK_PER_TRADE') { newParams[key] = value / 100.0; }
                        else if (inputElement.name === 'CAPITAL_ALLOCATION') { newParams[key] = value / 100.0; }
                        else { newParams[key] = value; }
                    }
                    else if (inputElement.tagName === 'SELECT') { newParams[key] = inputElement.value; }
                    else { newParams[key] = inputElement.value; }
                } catch (e) {
                     const label = document.querySelector(`label[for='${inputElement.id}']`);
                     addLogFromJS(`Erreur: ${e.message || 'Valeur invalide'} pour ${label?.textContent || key}`);
                     isValid = false; break;
                }
            }
        }

        if (!isValid) {
            paramSaveStatus.textContent = "Erreur de validation côté client."; paramSaveStatus.style.color = "red";
            saveParamsBtn.disabled = false;
            setTimeout(() => { paramSaveStatus.textContent = ""; }, 7000);
            return;
        }

        console.log("Envoi des paramètres:", newParams);
        fetch(`${API_BASE_URL}/parameters`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newParams),
        })
        .then(response => response.json().then(data => ({ ok: response.ok, status: response.status, data })))
        .then(({ ok, status, data }) => {
            const message = data.message || `Erreur HTTP ${status}`;
            if (ok && data.success) {
                paramSaveStatus.textContent = "Paramètres sauvegardés !"; paramSaveStatus.style.color = "green";
                if (message.includes("redémarrage")) {
                    paramSaveStatus.textContent += " (Redémarrage conseillé)";
                    paramSaveStatus.style.color = "darkorange";
                }
                addLogFromJS("Paramètres sauvegardés avec succès.");
            } else {
                const errorMsg = data.message || `Erreur serveur ${status}`;
                console.error("Erreur sauvegarde paramètres (serveur):", data);
                paramSaveStatus.textContent = `Erreur: ${errorMsg}`; paramSaveStatus.style.color = "red";
                addLogFromJS(`Erreur sauvegarde paramètres: ${errorMsg}`);
            }
        })
        .catch(error => {
            console.error('Erreur communication sauvegarde paramètres:', error);
            addLogFromJS(`Erreur communication sauvegarde: ${error.message}`);
            paramSaveStatus.textContent = "Erreur communication."; paramSaveStatus.style.color = "red";
        })
        .finally(() => {
            saveParamsBtn.disabled = false;
            setTimeout(() => { paramSaveStatus.textContent = ""; }, 7000);
        });
    });

    // --- Initialisation ---
    fetchParameters(); // Charger les paramètres en premier
    connectLogStream(); // Démarrer la connexion SSE pour les logs
    fetchOrderHistory(); // Charger l'historique initial une fois

    // --- MODIFICATION ICI: Intervalle pour rafraîchir UNIQUEMENT le statut ---
    const statusInterval = setInterval(() => {
        fetchBotStatus();
        // fetchOrderHistory(); // RETIRÉ D'ICI
    }, 5000); // Intervalle de 5 secondes

     // Gérer la fermeture de la page/onglet (inchangé)
     window.addEventListener('beforeunload', () => {
        if (evtSource) {
            evtSource.close();
            console.log("Flux de logs SSE fermé.");
        }
        // clearInterval(statusInterval); // Optionnel
    });
});
