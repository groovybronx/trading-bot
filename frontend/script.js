document.addEventListener('DOMContentLoaded', () => {
    // Éléments du DOM
    const statusValue = document.getElementById('status-value');
    const symbolValue = document.getElementById('symbol-value');
    const timeframeValue = document.getElementById('timeframe-value');
    const positionValue = document.getElementById('position-value');
    const balanceValue = document.getElementById('balance-value'); // Solde Quote Asset (ex: USDT)
    const quoteAssetLabel = document.getElementById('quote-asset-label'); // Label pour Quote Asset
    const quantityValue = document.getElementById('quantity-value');     // Quantité Base Asset (ex: BTC)
    const baseAssetLabel = document.getElementById('base-asset-label');   // Label pour Base Asset
    const priceValue = document.getElementById('price-value');
    const symbolPriceLabel = document.getElementById('symbol-price-label');
    const logOutput = document.getElementById('log-output');
    const startBtn = document.getElementById('start-bot-btn');
    const stopBtn = document.getElementById('stop-bot-btn');
    // AJOUT: Éléments pour l'historique
    const orderHistoryBody = document.getElementById('order-history-body');
    const orderHistoryPlaceholder = document.getElementById('order-history-placeholder');


    // Éléments pour les Paramètres
    const paramInputs = {
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

    // État initial
    statusValue.textContent = 'Chargement...';
    statusValue.style.color = 'orange';
    logOutput.textContent = 'Initialisation du frontend...'; // Message initial
    startBtn.disabled = true;
    stopBtn.disabled = true;

    // --- Communication avec le Backend ---
    const API_BASE_URL = 'http://127.0.0.1:5000'; // CORRECT

    // --- Connexion au flux de logs SSE ---
    let evtSource = null; // Garder une référence pour pouvoir fermer
    function connectLogStream() {
        if (evtSource) {
            evtSource.close();
            console.log("Ancienne connexion SSE fermée.");
        }
        addLogDirect("Tentative de connexion au flux de logs...");
        evtSource = new EventSource(`${API_BASE_URL}/stream_logs`); // CORRECT

        evtSource.onopen = function() {
            console.log("Connexion SSE ouverte.");
            // Optionnel: Logguer la réussite de la connexion dans l'UI
            // addLogDirect("Connecté au flux de logs du backend.");
        };
        evtSource.onmessage = function(event) {
            addLogDirect(event.data);
        };
        evtSource.onerror = function(err) {
            console.error("Erreur EventSource:", err);
            addLogDirect("!!! Erreur de connexion au flux de logs. Vérifiez que le backend est lancé. Reconnexion auto...");
            // Optionnel: Fermer explicitement pour éviter les tentatives de reconnexion si le serveur est vraiment down
            // if (evtSource) evtSource.close();
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

    // --- Fonctions pour l'historique des ordres ---
    function fetchOrderHistory() {
        fetch(`${API_BASE_URL}/order_history`) // CORRECT
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
                     orderHistoryBody.innerHTML = `<tr><td colspan="9" style="color: red;">Erreur chargement historique: ${error.message}</td></tr>`;
                }
            });
    }

    function updateOrderHistoryUI(orders) {
        if (!orderHistoryBody) return;
        orderHistoryBody.innerHTML = '';

        if (!orders || orders.length === 0) {
             const placeholderElement = document.getElementById('order-history-placeholder');
             if (placeholderElement) {
                // S'assurer que le placeholder est bien un TR pour être valide dans TBODY
                if (placeholderElement.tagName === 'TR') {
                    orderHistoryBody.appendChild(placeholderElement.cloneNode(true));
                } else { // Si le placeholder n'est pas un TR, insérer un TR par défaut
                     orderHistoryBody.innerHTML = '<tr><td colspan="9">Aucun ordre dans l\'historique de cette session.</td></tr>';
                }
             } else {
                 orderHistoryBody.innerHTML = '<tr><td colspan="9">Aucun ordre dans l\'historique de cette session.</td></tr>';
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

            row.className = `status-${(order.status || 'unknown').toLowerCase()}`;
            const origQtyStr = order.origQty ? parseFloat(order.origQty).toFixed(6) : 'N/A';
            const executedQtyStr = order.executedQty ? parseFloat(order.executedQty).toFixed(6) : 'N/A';

            row.innerHTML = `
                <td>${timestamp}</td>
                <td>${order.symbol || 'N/A'}</td>
                <td class="${order.side?.toLowerCase()}">${order.side || 'N/A'}</td>
                <td>${order.type || 'N/A'}</td>
                <td>${origQtyStr}</td>
                <td>${executedQtyStr}</td>
                <td>${priceOrValue}</td>
                <td>${order.status || 'N/A'}</td>
                <td>${order.orderId || 'N/A'}</td>
            `;
            orderHistoryBody.appendChild(row);
        });
    }
    // --- FIN HISTORIQUE ---

    function fetchBotStatus() {
        fetch(`${API_BASE_URL}/status`) // CORRECT
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
            updateStatusUI({ status: 'Erreur Connexion' }); // Mettre à jour l'UI avec l'erreur
        });
    }

    function fetchParameters() {
        addLogFromJS("Chargement des paramètres...");
        fetch(`${API_BASE_URL}/parameters`) // CORRECT
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
                // Activer les boutons seulement si le statut n'est pas en cours d'exécution
                fetchBotStatus(); // Récupérer le statut actuel pour décider de l'état des boutons
            })
            .catch(error => {
                console.error('Erreur de récupération des paramètres:', error);
                addLogFromJS(`Erreur chargement paramètres: ${error.message}`);
                paramSaveStatus.textContent = "Erreur chargement paramètres."; paramSaveStatus.style.color = 'red';
                startBtn.disabled = true; stopBtn.disabled = true; // Garder désactivé si erreur
            });
    }

    function updateStatusUI(data) {
        const status = data.status || 'Inconnu';
        statusValue.textContent = status;
        symbolValue.textContent = data.symbol || 'N/A';
        timeframeValue.textContent = data.timeframe || 'N/A';
        positionValue.textContent = data.in_position ? 'Oui' : 'Non';
        positionValue.className = data.in_position ? 'in-position-yes' : 'in-position-no'; // Classe pour style

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

        // Gestion état boutons et couleur statut
        if (status === 'En cours') {
            statusValue.style.color = 'green';
            startBtn.disabled = true;
            stopBtn.disabled = false;
        } else if (status === 'Arrêté') {
            statusValue.style.color = 'red';
            startBtn.disabled = false;
            stopBtn.disabled = true;
        } else { // Inclut 'Erreur Connexion', 'Démarrage...', 'Arrêt...', etc.
            statusValue.style.color = 'orange';
            startBtn.disabled = true;
            stopBtn.disabled = true;
        }
    }

    // --- Gestion des Contrôles (Start/Stop) ---
    startBtn.addEventListener('click', () => {
        addLogFromJS("Tentative de démarrage du bot...");
        startBtn.disabled = true; // Désactiver immédiatement
        stopBtn.disabled = true;
        statusValue.textContent = 'Démarrage...'; statusValue.style.color = 'orange';

        fetch(`${API_BASE_URL}/start`, { method: 'POST' }) // CORRECT
            .then(response => {
                // Vérifier si la réponse est OK avant de parser le JSON
                if (!response.ok) {
                    // Essayer de lire le corps pour un message d'erreur plus précis
                    return response.json().catch(() => null) // Essayer de parser, sinon retourner null
                        .then(errorData => {
                            const errorMsg = errorData?.message || `Erreur HTTP ${response.status}`;
                            throw new Error(errorMsg); // Lancer une erreur avec le message
                        });
                }
                return response.json(); // Si OK, parser le JSON
            })
            .then(data => {
                if (data.success) {
                    addLogFromJS(data.message || "Ordre de démarrage envoyé.");
                    // Le statut sera mis à jour par le prochain fetchBotStatus
                    fetchBotStatus();
                    fetchOrderHistory(); // Rafraîchir l'historique
                } else {
                    // Le backend a retourné success: false
                    addLogFromJS(`Échec démarrage: ${data.message || 'Raison inconnue'}`);
                    console.warn("Échec démarrage (logique backend):", data);
                    fetchBotStatus(); // Mettre à jour l'UI avec le statut actuel (probablement 'Arrêté' ou une erreur)
                }
            })
            .catch(error => {
                console.error('Erreur communication démarrage:', error);
                addLogFromJS(`Erreur communication démarrage: ${error.message}`);
                fetchBotStatus(); // Mettre à jour l'UI même en cas d'erreur de communication
            });
    });

    stopBtn.addEventListener('click', () => {
        addLogFromJS("Tentative d'arrêt du bot...");
        startBtn.disabled = true; // Désactiver immédiatement
        stopBtn.disabled = true;
        statusValue.textContent = 'Arrêt...'; statusValue.style.color = 'orange';

        fetch(`${API_BASE_URL}/stop`, { method: 'POST' }) // CORRECT
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
                    // Le statut sera mis à jour par le prochain fetchBotStatus
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

    // --- Écouteur pour Sauvegarder les Paramètres ---
    saveParamsBtn.addEventListener('click', () => {
        addLogFromJS("Sauvegarde des paramètres en cours...");
        paramSaveStatus.textContent = "Sauvegarde..."; paramSaveStatus.style.color = "orange";
        saveParamsBtn.disabled = true;

        const newParams = {};
        let isValid = true;
        for (const key in paramInputs) {
            if (paramInputs[key]) {
                const inputElement = paramInputs[key];
                try { // Ajouter un try/catch pour la conversion
                    if (inputElement.type === 'checkbox') { newParams[key] = inputElement.checked; }
                    else if (inputElement.type === 'number') {
                        const value = parseFloat(inputElement.value);
                        if (isNaN(value)) { throw new Error(`Valeur invalide pour ${key}`); }

                        if (inputElement.name === 'RISK_PER_TRADE') { newParams[key] = value / 100.0; }
                        else if (inputElement.name === 'CAPITAL_ALLOCATION') { newParams[key] = value / 100.0; }
                        else { newParams[key] = value; }
                    }
                    else if (inputElement.tagName === 'SELECT') { newParams[key] = inputElement.value; }
                    else { newParams[key] = inputElement.value; } // Pour d'autres types éventuels
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
        fetch(`${API_BASE_URL}/parameters`, { // CORRECT
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newParams),
        })
        .then(response => response.json().then(data => ({ ok: response.ok, status: response.status, data })))
        .then(({ ok, status, data }) => {
            const message = data.message || `Erreur HTTP ${status}`;
            if (ok && data.success) { // Vérifier aussi data.success
                paramSaveStatus.textContent = "Paramètres sauvegardés !"; paramSaveStatus.style.color = "green";
                if (message.includes("redémarrage")) {
                    paramSaveStatus.textContent += " (Redémarrage conseillé)";
                    paramSaveStatus.style.color = "darkorange";
                }
                addLogFromJS("Paramètres sauvegardés avec succès.");
            } else {
                // Erreur logique backend ou HTTP
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
    fetchParameters(); // Charger les paramètres en premier (mettra à jour le statut et l'état des boutons)
    connectLogStream(); // Démarrer la connexion SSE pour les logs
    fetchOrderHistory(); // Charger l'historique initial

    // Intervalle pour rafraîchir statut et historique
    const statusInterval = setInterval(() => {
        fetchBotStatus();
        fetchOrderHistory();
    }, 5000); // Intervalle de 5 secondes

     // Gérer la fermeture de la page/onglet pour fermer SSE
     window.addEventListener('beforeunload', () => {
        if (evtSource) {
            evtSource.close();
            console.log("Flux de logs SSE fermé.");
        }
        // Optionnel: Arrêter l'intervalle
        // clearInterval(statusInterval);
    });
});
