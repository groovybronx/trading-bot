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
    const API_BASE_URL = 'http://127.0.0.1:5000';

    // --- Connexion au flux de logs SSE ---
    let evtSource = null; // Garder une référence pour pouvoir fermer
    function connectLogStream() {
        // Fermer une connexion existante si elle existe
        if (evtSource) {
            evtSource.close();
            console.log("Ancienne connexion SSE fermée.");
        }

        addLogDirect("Tentative de connexion au flux de logs..."); // Log direct sans timestamp
        evtSource = new EventSource(`${API_BASE_URL}/stream_logs`);

        evtSource.onopen = function() {
            // Ce message vient du backend maintenant via le premier yield
            // addLogDirect("Connexion au flux de logs établie.");
            console.log("Connexion SSE ouverte.");
        };

        evtSource.onmessage = function(event) {
            // Ajouter le message reçu (qui contient déjà le timestamp)
            addLogDirect(event.data);
        };

        evtSource.onerror = function(err) {
            console.error("Erreur EventSource:", err);
            addLogDirect("!!! Erreur de connexion au flux de logs. Reconnexion auto...");
            // EventSource tente de se reconnecter automatiquement.
            // Si la reconnexion échoue continuellement, l'erreur persistera ici.
            // On pourrait ajouter un compteur d'erreurs pour arrêter après N tentatives.
            // Pas besoin de fermer et reconnecter manuellement ici, car EventSource le fait.
        };
    }
    // --- FIN SSE ---

    // Fonction pour ajouter un log directement (sans timestamp JS)
    function addLogDirect(message) {
        if (logOutput) {
            logOutput.textContent += `\n${message}`;
            logOutput.scrollTop = logOutput.scrollHeight;
        } else {
            console.warn("Élément logOutput non trouvé ! Message:", message);
        }
    }

    // Fonction pour ajouter un log depuis le JS (AVEC timestamp JS)
    function addLogFromJS(message) {
        const timestamp = new Date().toLocaleTimeString();
        addLogDirect(`[${timestamp}] (FRONTEND) ${message}`); // Préfixer pour distinguer
    }


    function fetchBotStatus() {
        // console.log("Récupération du statut du bot depuis le backend...");
        fetch(`${API_BASE_URL}/status`)
        .then(response => {
             if (!response.ok) {
                 // Essayer de lire le corps pour plus de détails sur l'erreur
                 return response.text().then(text => {
                     throw new Error(`HTTP ${response.status}: ${text || response.statusText}`);
                 });
             }
             return response.json();
         })
        .then(data => {
            updateStatusUI(data);
        })
        .catch(error => {
            console.error('Erreur de récupération du statut:', error);
            addLogFromJS(`Erreur connexion statut: ${error.message}`); // Utiliser addLogFromJS
            statusValue.textContent = 'Erreur Connexion';
            statusValue.style.color = 'orange';
            // Réinitialiser tous les champs en cas d'erreur
            if (symbolValue) symbolValue.textContent = 'N/A';
            if (timeframeValue) timeframeValue.textContent = 'N/A';
            if (balanceValue) balanceValue.textContent = 'N/A';
            if (quoteAssetLabel) quoteAssetLabel.textContent = 'USDT'; // Remettre défaut
            if (quantityValue) quantityValue.textContent = 'N/A';     // Réinitialiser quantité
            if (baseAssetLabel) baseAssetLabel.textContent = 'N/A';     // Réinitialiser label quantité
            if (priceValue) priceValue.textContent = 'N/A';
            if (symbolPriceLabel) symbolPriceLabel.textContent = 'N/A';
            if (positionValue) positionValue.textContent = 'N/A';
            startBtn.disabled = true;
            stopBtn.disabled = true;
        });
    }

    function fetchParameters() {
        // console.log("Récupération des paramètres depuis le backend...");
        addLogFromJS("Chargement des paramètres..."); // Utiliser addLogFromJS
        fetch(`${API_BASE_URL}/parameters`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                console.log("Paramètres reçus:", data);
                for (const key in paramInputs) {
                    if (data.hasOwnProperty(key) && paramInputs[key]) {
                        const inputElement = paramInputs[key];
                        if (inputElement.type === 'checkbox') { inputElement.checked = data[key]; }
                        else if (inputElement.name === 'RISK_PER_TRADE') { inputElement.value = (data[key] * 100).toFixed(1); }
                        else { inputElement.value = data[key]; }
                    } else if (paramInputs[key]) { console.warn(`Clé paramètre "${key}" non trouvée dans les données backend.`); }
                }
                addLogFromJS("Paramètres chargés."); // Utiliser addLogFromJS
                startBtn.disabled = false;
                stopBtn.disabled = false;
                fetchBotStatus(); // Mettre à jour l'état des boutons basé sur le statut réel
            })
            .catch(error => {
                console.error('Erreur de récupération des paramètres:', error);
                addLogFromJS(`Erreur chargement paramètres: ${error.message}`); // Utiliser addLogFromJS
                paramSaveStatus.textContent = "Erreur chargement paramètres.";
                paramSaveStatus.style.color = 'red';
                startBtn.disabled = true;
                stopBtn.disabled = true;
            });
    }


    function updateStatusUI(data) {
        statusValue.textContent = data.status || 'Inconnu';
        symbolValue.textContent = data.symbol || 'N/A';
        timeframeValue.textContent = data.timeframe || 'N/A';
        positionValue.textContent = data.in_position ? 'Oui' : 'Non';

        // Mettre à jour la balance (Quote Asset)
        if (quoteAssetLabel) { quoteAssetLabel.textContent = data.quote_asset || 'USDT'; }
        if (balanceValue) {
            balanceValue.textContent = data.available_balance !== undefined && data.available_balance !== null
                ? parseFloat(data.available_balance).toFixed(2) // Formatage à 2 décimales pour USDT/BUSD etc.
                : 'N/A';
        }

        // Mettre à jour la quantité (Base Asset)
        if (baseAssetLabel) { baseAssetLabel.textContent = data.base_asset || 'N/A'; }
        if (quantityValue) {
            quantityValue.textContent = data.symbol_quantity !== undefined && data.symbol_quantity !== null
                ? parseFloat(data.symbol_quantity).toFixed(6) // Formatage à 6 décimales (ajuster si besoin)
                : 'N/A';
        }

        // Mettre à jour le prix
        if (symbolPriceLabel) { symbolPriceLabel.textContent = data.symbol || 'N/A'; }
        if (priceValue) {
             priceValue.textContent = data.current_price !== undefined && data.current_price !== null
                ? parseFloat(data.current_price).toFixed(4) // Formatage à 4 décimales (ajuster si besoin)
                : 'N/A';
        }

        // Logique d'activation/désactivation des boutons
        if (data.status === 'En cours') { statusValue.style.color = 'green'; startBtn.disabled = true; stopBtn.disabled = false; }
        else if (data.status === 'Arrêté') { statusValue.style.color = 'red'; startBtn.disabled = false; stopBtn.disabled = true; }
        else { statusValue.style.color = 'orange'; startBtn.disabled = true; stopBtn.disabled = true; }
    }

    // --- Gestion des Contrôles (Start/Stop) ---
    startBtn.addEventListener('click', () => {
        console.log("Clic sur Démarrer le Bot");
        addLogFromJS("Tentative de démarrage du bot..."); // Utiliser addLogFromJS
        fetch(`${API_BASE_URL}/start`, { method: 'POST' })
            .then(response => response.json().then(data => ({ ok: response.ok, data })))
            .then(({ ok, data }) => {
                const message = data.message || `Erreur serveur inconnue`;
                // Le log de succès/échec du démarrage viendra du backend via SSE
                // addLogFromJS(`Réponse démarrage: ${message}`);
                if(ok && data.success) {
                    statusValue.textContent = 'Démarrage...'; statusValue.style.color = 'orange';
                    startBtn.disabled = true; stopBtn.disabled = true;
                    fetchBotStatus(); // Rafraîchir statut
                } else if (!ok) {
                     console.error("Erreur HTTP démarrage:", data);
                     addLogFromJS(`Erreur HTTP démarrage: ${message}`); // Logguer l'erreur JS si HTTP échoue
                } else { // ok mais success: false
                     console.warn("Échec démarrage (logique backend):", data);
                     // Le message d'échec viendra du backend via SSE
                }
            })
            .catch(error => {
                console.error('Erreur communication démarrage:', error);
                addLogFromJS(`Erreur communication démarrage: ${error.message}`); // Utiliser addLogFromJS
            });
    });

    stopBtn.addEventListener('click', () => {
        console.log("Clic sur Arrêter le Bot");
        addLogFromJS("Tentative d'arrêt du bot..."); // Utiliser addLogFromJS
        fetch(`${API_BASE_URL}/stop`, { method: 'POST' })
             .then(response => response.json().then(data => ({ ok: response.ok, data })))
            .then(({ ok, data }) => {
                const message = data.message || `Erreur serveur inconnue`;
                // Le log de succès/échec de l'arrêt viendra du backend via SSE
                // addLogFromJS(`Réponse arrêt: ${message}`);
                 if(ok && data.success) {
                    statusValue.textContent = 'Arrêt...'; statusValue.style.color = 'orange';
                    startBtn.disabled = true; stopBtn.disabled = true;
                    fetchBotStatus(); // Rafraîchir statut
                } else if (!ok) {
                     console.error("Erreur HTTP arrêt:", data);
                     addLogFromJS(`Erreur HTTP arrêt: ${message}`); // Logguer l'erreur JS si HTTP échoue
                } else { // ok mais success: false
                     console.warn("Échec arrêt (logique backend):", data);
                     // Le message d'échec viendra du backend via SSE
                }
            })
            .catch(error => {
                console.error('Erreur communication arrêt:', error);
                addLogFromJS(`Erreur communication arrêt: ${error.message}`); // Utiliser addLogFromJS
            });
    });

    // --- Écouteur pour Sauvegarder les Paramètres ---
    saveParamsBtn.addEventListener('click', () => {
        console.log("Clic sur Sauvegarder les Paramètres");
        addLogFromJS("Sauvegarde des paramètres en cours..."); // Utiliser addLogFromJS
        paramSaveStatus.textContent = "Sauvegarde...";
        paramSaveStatus.style.color = "orange";
        saveParamsBtn.disabled = true;

        const newParams = {};
        let isValid = true;
        for (const key in paramInputs) {
            if (paramInputs[key]) {
                const inputElement = paramInputs[key];
                if (inputElement.type === 'checkbox') { newParams[key] = inputElement.checked; }
                else if (inputElement.type === 'number') {
                    const value = parseFloat(inputElement.value);
                    if (isNaN(value)) {
                        const label = document.querySelector(`label[for='${inputElement.id}']`);
                        addLogFromJS(`Erreur: Valeur invalide pour ${label?.textContent || key}`); // Utiliser addLogFromJS
                        isValid = false; break;
                    }
                    if (inputElement.name === 'RISK_PER_TRADE') { newParams[key] = value / 100.0; }
                    else { newParams[key] = value; }
                } else if (inputElement.tagName === 'SELECT') { newParams[key] = inputElement.value; }
                else { newParams[key] = inputElement.value; }
            }
        }

        if (!isValid) {
            paramSaveStatus.textContent = "Erreur de validation côté client.";
            paramSaveStatus.style.color = "red";
            saveParamsBtn.disabled = false; return;
        }

        console.log("Envoi des paramètres:", newParams);
        fetch(`${API_BASE_URL}/parameters`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newParams),
        })
        .then(response => response.json().then(data => ({ ok: response.ok, status: response.status, data })))
        .then(({ ok, status, data }) => {
            const message = data.message || `Erreur HTTP ${status}`;
            // Le log de succès/erreur de la sauvegarde viendra maintenant du backend via SSE
            if (ok) {
                paramSaveStatus.textContent = "Paramètres sauvegardés !"; paramSaveStatus.style.color = "green";
                if (message.includes("redémarrage")) { paramSaveStatus.textContent += " (Redémarrage conseillé)"; paramSaveStatus.style.color = "darkorange"; }
            } else {
                console.error("Erreur sauvegarde paramètres (serveur):", data);
                paramSaveStatus.textContent = `Erreur: ${message}`; paramSaveStatus.style.color = "red";
                // Le log d'erreur viendra aussi du backend via SSE
            }
        })
        .catch(error => {
            console.error('Erreur communication sauvegarde paramètres:', error);
            addLogFromJS(`Erreur communication sauvegarde: ${error.message}`); // Utiliser addLogFromJS
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
    const statusInterval = setInterval(fetchBotStatus, 5000); // Garder le polling pour le statut

     // Gérer la fermeture de la page/onglet pour fermer SSE
     window.addEventListener('beforeunload', () => {
        if (evtSource) {
            evtSource.close();
            console.log("Flux de logs SSE fermé.");
        }
    });
});
