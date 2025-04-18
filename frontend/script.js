document.addEventListener('DOMContentLoaded', () => {
    // Éléments du DOM
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
    const orderHistoryPlaceholder = document.getElementById('order-history-placeholder'); // Récupérer le placeholder
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
    logOutput.textContent = 'Initialisation du frontend...';
    startBtn.disabled = true;
    stopBtn.disabled = true;

    // --- Communication avec le Backend ---
    const API_BASE_URL = 'http://127.0.0.1:5000'; // Ou l'URL de votre backend

    // --- Connexion au flux de logs SSE ---
    let evtSource = null;
    function connectLogStream() {
        if (evtSource && evtSource.readyState !== EventSource.CLOSED) {
            evtSource.close();
            console.log("Ancienne connexion SSE fermée.");
        }
        addLogDirect("Tentative de connexion au flux de logs...");
        evtSource = new EventSource(`${API_BASE_URL}/stream_logs`);

        evtSource.onopen = function() {
            console.log("Connexion SSE ouverte.");
            addLogDirect("Connecté au flux de logs du backend."); // Message de confirmation
        };

        // --- MODIFICATION ICI: Gestion des messages SSE ---
        evtSource.onmessage = function(event) {
            const messageData = event.data;

            // Vérifier si c'est l'événement spécial pour l'historique
            if (messageData === "EVENT:ORDER_HISTORY_UPDATED") {
                console.log("Received order history update event via SSE.");
                addLogFromJS("Événement de mise à jour de l'historique reçu, rafraîchissement...");
                fetchOrderHistory(); // Déclencher le rafraîchissement de l'historique
            }
            // Ignorer les messages keep-alive vides ou commentaires (commençant par ':')
            else if (messageData && !messageData.startsWith(':')) {
                // Traiter comme un message de log normal
                addLogDirect(messageData);
            }
            // else { console.debug("SSE Keep-alive received"); } // Optionnel: log keep-alive
        };
        // --- FIN MODIFICATION SSE ---

        evtSource.onerror = function(err) {
            console.error("Erreur EventSource:", err);
            addLogDirect("!!! Erreur de connexion au flux de logs. Vérifiez que le backend est lancé. Reconnexion auto...");
            // L'EventSource tente de se reconnecter automatiquement.
            // Si la reconnexion échoue constamment, il faudra peut-être une logique plus avancée.
        };
    }
    // --- FIN SSE ---

    // Ajoute un message brut à la zone de log
    function addLogDirect(message) {
        if (logOutput) {
            // Ajouter une nouvelle ligne avant le message sauf si c'est le premier
            if (logOutput.textContent !== 'Initialisation du frontend...') {
                 logOutput.textContent += `\n${message}`;
            } else {
                 logOutput.textContent = message; // Remplacer le message initial
            }
            logOutput.scrollTop = logOutput.scrollHeight; // Auto-scroll vers le bas
        } else {
            console.warn("Élément logOutput non trouvé ! Message:", message);
        }
    }

    // Ajoute un message formaté (avec timestamp) depuis le JS frontend
    function addLogFromJS(message) {
        const timestamp = new Date().toLocaleTimeString();
        addLogDirect(`[${timestamp}] (FRONTEND) ${message}`);
    }

    // --- Fonctions pour l'historique des ordres ---
    function fetchOrderHistory() {
        addLogFromJS("Récupération de l'historique des ordres...");
        fetch(`${API_BASE_URL}/order_history`)
            .then(response => {
                if (!response.ok) {
                    // Essayer de lire le corps de la réponse pour une erreur plus détaillée
                    return response.text().then(text => {
                        throw new Error(`HTTP ${response.status}: ${text || response.statusText}`);
                    });
                }
                return response.json();
            })
            .then(orders => {
                addLogFromJS("Historique des ordres récupéré avec succès.");
                updateOrderHistoryUI(orders);
            })
            .catch(error => {
                console.error('Erreur de récupération de l\'historique des ordres:', error);
                addLogFromJS(`Erreur historique ordres: ${error.message}`);
                if (orderHistoryBody) {
                     // Afficher l'erreur dans le tableau
                     orderHistoryBody.innerHTML = `<tr><td colspan="10" style="color: red; text-align: center;">Erreur chargement historique: ${error.message}</td></tr>`;
                }
            });
    }

    // Met à jour l'UI de l'historique des ordres
    function updateOrderHistoryUI(orders) {
        if (!orderHistoryBody) {
            console.error("Element 'order-history-body' not found.");
            return;
        }
        orderHistoryBody.innerHTML = ''; // Vider le corps du tableau

        if (!orders || orders.length === 0) {
            // Si le placeholder existe, le réinsérer, sinon mettre un message par défaut
            if (orderHistoryPlaceholder) {
                 orderHistoryBody.appendChild(orderHistoryPlaceholder.cloneNode(true));
            } else {
                 orderHistoryBody.innerHTML = '<tr><td colspan="10" style="text-align: center; font-style: italic; color: #888;">Aucun ordre dans l\'historique.</td></tr>';
            }
            return;
        }

        // --- MODIFICATION ICI: Retrait de .slice().reverse() ---
        // Le backend trie déjà les ordres du plus récent au plus ancien.
        orders.forEach(order => {
        // --- FIN MODIFICATION ---
            const row = document.createElement('tr');
            const timestamp = order.timestamp ? new Date(order.timestamp).toLocaleString() : 'N/A';

            // Calcul et formatage du prix/valeur
            let priceOrValue = 'N/A';
            const executedQtyNum = parseFloat(order.executedQty);
            const cummulativeQuoteQtyNum = parseFloat(order.cummulativeQuoteQty);
            const priceNum = parseFloat(order.price); // Pour ordres LIMIT

            if (!isNaN(cummulativeQuoteQtyNum) && !isNaN(executedQtyNum) && executedQtyNum > 0) {
                // Calculer le prix moyen si quantité exécutée > 0
                const avgPrice = cummulativeQuoteQtyNum / executedQtyNum;
                // Afficher la valeur totale et le prix moyen entre parenthèses
                priceOrValue = `${cummulativeQuoteQtyNum.toFixed(4)} (${avgPrice.toFixed(4)} avg)`;
            } else if (!isNaN(priceNum) && priceNum > 0) {
                // Si pas exécuté mais prix défini (ordre LIMIT), afficher le prix
                priceOrValue = priceNum.toFixed(4);
            } else if (order.type === 'MARKET') {
                 priceOrValue = '(MARKET)'; // Indiquer ordre Market non (encore) rempli
            }

            // Formatage des quantités
            const origQtyStr = order.origQty ? parseFloat(order.origQty).toFixed(6) : 'N/A';
            const executedQtyStr = order.executedQty ? parseFloat(order.executedQty).toFixed(6) : 'N/A';

            // Formatage de la performance
            let performanceHtml = '<td>N/A</td>'; // Cellule par défaut
            if (typeof order.performance_pct === 'number' && isFinite(order.performance_pct)) {
                const perfValue = order.performance_pct;
                const perfFormatted = perfValue.toFixed(2) + '%';
                let perfClass = '';
                if (perfValue > 0) {
                    perfClass = 'performance-positive';
                } else if (perfValue < 0) {
                    perfClass = 'performance-negative';
                }
                // Créer la cellule avec la classe et le contenu
                performanceHtml = `<td class="${perfClass}">${perfFormatted}</td>`;
            }

            // Ajouter une classe CSS basée sur le statut de l'ordre
            row.className = `status-${(order.status || 'unknown').toLowerCase().replace(/ /g, '_')}`; // ex: status-partially_filled

            // Construire le HTML de la ligne
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
            orderHistoryBody.appendChild(row); // Ajouter la ligne au tableau
        });
    }
    // --- FIN HISTORIQUE ---

    // --- Fonctions Statut et Paramètres (inchangées) ---
    function fetchBotStatus() {
        fetch(`${API_BASE_URL}/status`)
        .then(response => {
             if (!response.ok) {
                 // Tenter de lire le message d'erreur du backend
                 return response.text().then(text => { throw new Error(`HTTP ${response.status}: ${text || response.statusText}`); });
             }
             return response.json();
         })
        .then(data => {
            updateStatusUI(data);
        })
        .catch(error => {
            console.error('Erreur de récupération du statut:', error);
            // Ne pas spammer les logs JS avec des erreurs de connexion répétées si le backend est down
            // addLogFromJS(`Erreur connexion statut: ${error.message}`);
            updateStatusUI({ status: 'Erreur Connexion' }); // Afficher l'erreur dans l'UI
        });
    }

    function fetchParameters() {
        addLogFromJS("Chargement des paramètres initiaux...");
        fetch(`${API_BASE_URL}/parameters`)
            .then(response => {
                if (!response.ok) { throw new Error(`HTTP ${response.status}: ${response.statusText}`); }
                return response.json();
            })
            .then(data => {
                console.log("Paramètres reçus:", data);
                // Appliquer les paramètres aux champs input
                for (const key in paramInputs) {
                    if (data.hasOwnProperty(key) && paramInputs[key]) {
                        const inputElement = paramInputs[key];
                        const backendValue = data[key];
                        try {
                            if (inputElement.type === 'checkbox') {
                                inputElement.checked = backendValue;
                            } else if (inputElement.name === 'RISK_PER_TRADE' || inputElement.name === 'CAPITAL_ALLOCATION') {
                                // Convertir les pourcentages (0.01 -> 1.0)
                                inputElement.value = (backendValue * 100).toFixed(inputElement.name === 'RISK_PER_TRADE' ? 1 : 0);
                            } else {
                                inputElement.value = backendValue;
                            }
                        } catch (e) {
                            console.error(`Erreur application paramètre ${key}:`, e);
                        }
                    } else if (paramInputs[key]) {
                        console.warn(`Clé paramètre "${key}" non trouvée dans les données backend ou élément input manquant.`);
                    }
                }
                addLogFromJS("Paramètres chargés.");
                // Une fois les paramètres chargés, récupérer le statut initial
                fetchBotStatus();
            })
            .catch(error => {
                console.error('Erreur de récupération des paramètres:', error);
                addLogFromJS(`Erreur chargement paramètres: ${error.message}`);
                paramSaveStatus.textContent = "Erreur chargement paramètres initiaux."; paramSaveStatus.style.color = 'red';
                // Désactiver les contrôles si les paramètres ne peuvent être chargés
                startBtn.disabled = true;
                stopBtn.disabled = true;
            });
    }

    function updateStatusUI(data) {
        const status = data.status || 'Inconnu';
        statusValue.textContent = status;
        symbolValue.textContent = data.symbol || 'N/A';
        timeframeValue.textContent = data.timeframe || 'N/A';

        // Mise à jour de la position
        const isInPosition = data.in_position || false;
        positionValue.textContent = isInPosition ? 'Oui' : 'Non';
        positionValue.style.fontWeight = isInPosition ? 'bold' : 'normal';
        positionValue.style.color = isInPosition ? 'blue' : 'inherit';
        if (isInPosition && data.entry_details) {
             const entryPrice = parseFloat(data.entry_details.avg_price).toFixed(4);
             const entryQty = parseFloat(data.entry_details.quantity).toFixed(6);
             positionValue.textContent += ` (Entrée: ${entryQty} @ ${entryPrice})`;
        }

        // Mise à jour des labels et valeurs des assets/balances
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

        // Mise à jour de l'état des boutons et couleur du statut
        if (status === 'En cours') {
            statusValue.style.color = 'green';
            startBtn.disabled = true;
            stopBtn.disabled = false;
        } else if (status === 'Arrêté') {
            statusValue.style.color = 'red';
            startBtn.disabled = false;
            stopBtn.disabled = true;
        } else if (status === 'Erreur Connexion') {
             statusValue.style.color = 'darkred';
             startBtn.disabled = true; // Ne pas permettre de démarrer si erreur connexion
             stopBtn.disabled = true;
        } else { // Démarrage, Arrêt en cours, Erreur Init/Run etc.
            statusValue.style.color = 'orange';
            startBtn.disabled = true;
            stopBtn.disabled = true;
        }
    }

    // --- Gestion des Contrôles (Start/Stop) ---
    startBtn.addEventListener('click', () => {
        addLogFromJS("Tentative de démarrage du bot...");
        startBtn.disabled = true;
        stopBtn.disabled = true;
        statusValue.textContent = 'Démarrage...'; statusValue.style.color = 'orange';

        fetch(`${API_BASE_URL}/start`, { method: 'POST' })
            .then(response => {
                // Gérer les erreurs HTTP et les erreurs logiques du backend
                return response.json().then(data => ({ ok: response.ok, status: response.status, data }));
            })
            .then(({ ok, status, data }) => {
                const message = data.message || `Erreur inconnue (HTTP ${status})`;
                if (ok && data.success) {
                    addLogFromJS(message);
                    // Rafraîchir immédiatement le statut et l'historique après l'ordre de démarrage
                    fetchBotStatus();
                    fetchOrderHistory();
                } else {
                    addLogFromJS(`Échec démarrage: ${message}`);
                    console.warn("Échec démarrage (logique backend):", data);
                    fetchBotStatus(); // Mettre à jour l'UI même en cas d'échec
                }
            })
            .catch(error => {
                console.error('Erreur communication démarrage:', error);
                addLogFromJS(`Erreur communication démarrage: ${error.message}`);
                fetchBotStatus(); // Mettre à jour l'UI pour refléter l'échec
            });
    });

    stopBtn.addEventListener('click', () => {
        addLogFromJS("Tentative d'arrêt du bot...");
        startBtn.disabled = true;
        stopBtn.disabled = true;
        statusValue.textContent = 'Arrêt...'; statusValue.style.color = 'orange';

        fetch(`${API_BASE_URL}/stop`, { method: 'POST' })
             .then(response => {
                return response.json().then(data => ({ ok: response.ok, status: response.status, data }));
            })
            .then(({ ok, status, data }) => {
                 const message = data.message || `Erreur inconnue (HTTP ${status})`;
                 if (ok && data.success) {
                    addLogFromJS(message);
                    fetchBotStatus(); // Rafraîchir le statut
                } else {
                    // Gérer le cas où le bot était déjà arrêté (pas une vraie erreur)
                    if (message.includes("déjà arrêté")) {
                         addLogFromJS("Le bot était déjà arrêté.");
                    } else {
                         addLogFromJS(`Échec arrêt: ${message}`);
                         console.warn("Échec arrêt (logique backend):", data);
                    }
                    fetchBotStatus(); // Mettre à jour l'UI
                }
            })
            .catch(error => {
                console.error('Erreur communication arrêt:', error);
                addLogFromJS(`Erreur communication arrêt: ${error.message}`);
                fetchBotStatus(); // Mettre à jour l'UI
            });
    });

    // --- Écouteur pour Sauvegarder les Paramètres ---
    saveParamsBtn.addEventListener('click', () => {
        addLogFromJS("Sauvegarde des paramètres...");
        paramSaveStatus.textContent = "Sauvegarde en cours..."; paramSaveStatus.style.color = "orange";
        saveParamsBtn.disabled = true;

        const newParams = {};
        let isValid = true;
        // Récupérer et valider (basiquement) les valeurs des inputs
        for (const key in paramInputs) {
            if (paramInputs[key]) {
                const inputElement = paramInputs[key];
                const label = document.querySelector(`label[for='${inputElement.id}']`);
                const paramName = label ? label.textContent.replace(':', '').trim() : key;
                try {
                    if (inputElement.type === 'checkbox') {
                        newParams[key] = inputElement.checked;
                    } else if (inputElement.type === 'number') {
                        const value = parseFloat(inputElement.value);
                        if (isNaN(value) || !isFinite(value)) {
                            throw new Error(`Valeur numérique invalide pour ${paramName}`);
                        }
                        // Vérifier min/max si définis sur l'input
                        const min = parseFloat(inputElement.min);
                        const max = parseFloat(inputElement.max);
                        if (!isNaN(min) && value < min) throw new Error(`${paramName} doit être >= ${min}`);
                        if (!isNaN(max) && value > max) throw new Error(`${paramName} doit être <= ${max}`);

                        // Convertir les pourcentages pour le backend
                        if (inputElement.name === 'RISK_PER_TRADE' || inputElement.name === 'CAPITAL_ALLOCATION') {
                            newParams[key] = value / 100.0;
                        } else {
                            newParams[key] = value; // Assumer entier pour les autres
                        }
                    } else if (inputElement.tagName === 'SELECT') {
                        newParams[key] = inputElement.value;
                    } else { // type text, etc. (non utilisé ici mais pour l'exhaustivité)
                        newParams[key] = inputElement.value;
                    }
                } catch (e) {
                     addLogFromJS(`Erreur validation: ${e.message}`);
                     isValid = false;
                     paramSaveStatus.textContent = `Erreur: ${e.message}`; paramSaveStatus.style.color = "red";
                     break; // Arrêter à la première erreur
                }
            }
        }

        if (!isValid) {
            saveParamsBtn.disabled = false;
            setTimeout(() => { paramSaveStatus.textContent = ""; }, 7000);
            return; // Ne pas envoyer si invalide
        }

        console.log("Envoi des paramètres:", newParams);
        // Envoyer les paramètres au backend
        fetch(`${API_BASE_URL}/parameters`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newParams),
        })
        .then(response => response.json().then(data => ({ ok: response.ok, status: response.status, data })))
        .then(({ ok, status, data }) => {
            const message = data.message || `Erreur inconnue (HTTP ${status})`;
            if (ok && data.success) {
                paramSaveStatus.textContent = "Paramètres sauvegardés !"; paramSaveStatus.style.color = "green";
                if (message.includes("redémarrage")) {
                    paramSaveStatus.textContent += " (Redémarrage conseillé)";
                    paramSaveStatus.style.color = "darkorange"; // Couleur différente pour l'avertissement
                }
                addLogFromJS("Paramètres sauvegardés avec succès.");
                // Recharger le statut pour refléter le nouveau timeframe potentiellement
                fetchBotStatus();
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
            paramSaveStatus.textContent = "Erreur communication serveur."; paramSaveStatus.style.color = "red";
        })
        .finally(() => {
            saveParamsBtn.disabled = false;
            // Effacer le message de statut après quelques secondes
            setTimeout(() => { paramSaveStatus.textContent = ""; }, 7000);
        });
    });

    // --- Initialisation au chargement de la page ---
    addLogFromJS("Initialisation de l'interface...");
    fetchParameters(); // Charger les paramètres en premier (déclenche fetchBotStatus ensuite)
    connectLogStream(); // Démarrer la connexion SSE pour les logs
    fetchOrderHistory(); // Charger l'historique initial une fois

    // Intervalle pour rafraîchir PÉRIODIQUEMENT le statut (pas l'historique)
    const statusInterval = setInterval(() => {
        fetchBotStatus();
    }, 5000); // Toutes les 5 secondes

     // Gérer la fermeture de la page/onglet
     window.addEventListener('beforeunload', () => {
        if (evtSource && evtSource.readyState !== EventSource.CLOSED) {
            evtSource.close();
            console.log("Flux de logs SSE fermé.");
        }
        clearInterval(statusInterval); // Arrêter le rafraîchissement du statut
        console.log("Intervalle de statut arrêté.");
    });

    addLogFromJS("Interface initialisée. En attente de connexion backend...");
});
