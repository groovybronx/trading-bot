document.addEventListener('DOMContentLoaded', () => {
    // Éléments du DOM (existants)
    const statusValue = document.getElementById('status-value');
    const symbolValue = document.getElementById('symbol-value');
    const timeframeValue = document.getElementById('timeframe-value'); // Affiche le timeframe utilisé par le bot
    const positionValue = document.getElementById('position-value');
    const balanceValue = document.getElementById('balance-value');
    // --- AJOUT DES LIGNES MANQUANTES ---
    const priceValue = document.getElementById('price-value');       // Pour le prix
    const symbolPriceLabel = document.getElementById('symbol-price-label'); // Pour le label du prix
    // --- FIN AJOUT ---
    const logOutput = document.getElementById('log-output');
    const startBtn = document.getElementById('start-bot-btn');
    const stopBtn = document.getElementById('stop-bot-btn');


    // --- Éléments du DOM pour les Paramètres ---
    const paramInputs = {
        TIMEFRAME_STR: document.getElementById('param-timeframe'), // Ajouté
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
    // --- FIN NOUVEAUX Éléments ---


    // État initial
    statusValue.textContent = 'Chargement...';
    statusValue.style.color = 'orange';
    logOutput.textContent = 'Le frontend est prêt. Connexion au backend...';
    startBtn.disabled = true;
    stopBtn.disabled = true;

    // --- Communication avec le Backend ---
    const API_BASE_URL = 'http://127.0.0.1:5000';

    function fetchBotStatus() {
        console.log("Récupération du statut du bot depuis le backend...");
        fetch(`${API_BASE_URL}/status`)
        .then(response => {
             if (!response.ok) {
                 return response.text().then(text => { throw new Error(`HTTP error! status: ${response.status}, message: ${text || 'No error message body'}`); });
             }
             return response.json();
         })
        .then(data => {
            updateStatusUI(data);
        })
        .catch(error => {
            console.error('Erreur de récupération du statut:', error);
            addLog(`Erreur connexion statut: ${error.message}`);
            statusValue.textContent = 'Erreur Connexion';
            statusValue.style.color = 'orange';
            // Mettre à jour l'UI pour indiquer l'erreur sur les autres champs aussi
            symbolValue.textContent = 'N/A';
            timeframeValue.textContent = 'N/A';
            if (balanceValue) balanceValue.textContent = 'N/A'; // Vérifier si existe avant d'accéder
            if (priceValue) priceValue.textContent = 'N/A';       // Vérifier si existe avant d'accéder
            if (symbolPriceLabel) symbolPriceLabel.textContent = 'N/A'; // Vérifier si existe avant d'accéder
            positionValue.textContent = 'N/A';
            startBtn.disabled = true;
            stopBtn.disabled = true;
        });
    }

    function fetchParameters() {
        console.log("Récupération des paramètres depuis le backend...");
        addLog("Chargement des paramètres...");
        fetch(`${API_BASE_URL}/parameters`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                console.log("Paramètres reçus:", data);
                // Remplir les champs du formulaire
                for (const key in paramInputs) {
                    if (data.hasOwnProperty(key) && paramInputs[key]) {
                        const inputElement = paramInputs[key];
                        if (inputElement.type === 'checkbox') {
                            inputElement.checked = data[key];
                        } else if (inputElement.name === 'RISK_PER_TRADE') {
                            inputElement.value = (data[key] * 100).toFixed(1);
                        }
                         else {
                            inputElement.value = data[key];
                        }
                    } else if (paramInputs[key]) {
                        console.warn(`Clé de paramètre "${key}" non trouvée dans les données reçues du backend.`);
                    }
                }
                addLog("Paramètres chargés.");
                startBtn.disabled = false;
                stopBtn.disabled = false;
                fetchBotStatus(); // Mettre à jour l'état des boutons basé sur le statut réel
            })
            .catch(error => {
                console.error('Erreur de récupération des paramètres:', error);
                addLog(`Erreur chargement paramètres: ${error.message}`);
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

        // --- AJOUT DE LA LOGIQUE D'AFFICHAGE PRIX/BALANCE ---
        if (balanceValue) { // Vérifier si l'élément existe
            balanceValue.textContent = data.available_balance !== undefined && data.available_balance !== null
                ? parseFloat(data.available_balance).toFixed(2) // Formatage à 2 décimales
                : 'N/A';
        }

        if (priceValue) { // Vérifier si l'élément existe
             // Accepter 0.0 comme prix valide
             priceValue.textContent = data.current_price !== undefined && data.current_price !== null
                ? parseFloat(data.current_price).toFixed(4) // Formatage à 4 décimales (ajuster si besoin)
                : 'N/A';
        }
        // Mettre à jour aussi le label du symbole pour le prix
        if (symbolPriceLabel) { // Vérifier si l'élément existe
             symbolPriceLabel.textContent = data.symbol || 'N/A';
        }
        // --- FIN AJOUT LOGIQUE ---

        // Logique d'activation/désactivation des boutons
        if (data.status === 'En cours') {
            statusValue.style.color = 'green';
            startBtn.disabled = true;
            stopBtn.disabled = false;
        } else if (data.status === 'Arrêté') {
            statusValue.style.color = 'red';
            startBtn.disabled = false;
            stopBtn.disabled = true;
        } else { // Démarrage, Arrêt, Erreur, Erreur Connexion, etc.
            statusValue.style.color = 'orange';
            startBtn.disabled = true;
            stopBtn.disabled = true;
        }

    }
    function addLog(message) {
        const timestamp = new Date().toLocaleTimeString();
        logOutput.textContent += `\n[${timestamp}] ${message}`;
        logOutput.scrollTop = logOutput.scrollHeight;
    }
    // --- Gestion des Contrôles (Start/Stop - inchangés) ---
    startBtn.addEventListener('click', () => {
        // ... (code inchangé) ...
        console.log("Clic sur Démarrer le Bot");
        addLog("Tentative de démarrage du bot...");
        fetch(`${API_BASE_URL}/start`, { method: 'POST' })
            .then(response => {
                if (!response.ok) {
                     return response.json().then(errData => { throw new Error(errData.message || `Erreur serveur: ${response.status}`); })
                           .catch(() => { throw new Error(`Erreur HTTP ${response.status}`); });
                }
                return response.json();
            })
            .then(data => {
                addLog(`Réponse démarrage: ${data.message || JSON.stringify(data)}`);
                if(data.success) {
                    statusValue.textContent = 'Démarrage...';
                    statusValue.style.color = 'orange';
                    startBtn.disabled = true;
                    stopBtn.disabled = true;
                    fetchBotStatus();
                }
            })
            .catch(error => {
                console.error('Erreur démarrage:', error);
                addLog(`Erreur communication démarrage: ${error.message}`);
            });
    });

    stopBtn.addEventListener('click', () => {
        // ... (code inchangé) ...
        console.log("Clic sur Arrêter le Bot");
        addLog("Tentative d'arrêt du bot...");
        fetch(`${API_BASE_URL}/stop`, { method: 'POST' })
             .then(response => {
                if (!response.ok) {
                     return response.json().then(errData => { throw new Error(errData.message || `Erreur serveur: ${response.status}`); })
                           .catch(() => { throw new Error(`Erreur HTTP ${response.status}`); });
                }
                return response.json();
            })
            .then(data => {
                addLog(`Réponse arrêt: ${data.message || JSON.stringify(data)}`);
                 if(data.success) {
                    statusValue.textContent = 'Arrêt...';
                    statusValue.style.color = 'orange';
                    startBtn.disabled = true;
                    stopBtn.disabled = true;
                    fetchBotStatus();
                }
            })
            .catch(error => {
                console.error('Erreur arrêt:', error);
                addLog(`Erreur communication arrêt: ${error.message}`);
            });
    });

// --- Écouteur pour Sauvegarder les Paramètres ---
saveParamsBtn.addEventListener('click', () => {
    console.log("Clic sur Sauvegarder les Paramètres");
    addLog("Sauvegarde des paramètres en cours...");
    paramSaveStatus.textContent = "Sauvegarde...";
    paramSaveStatus.style.color = "orange";
    saveParamsBtn.disabled = true;

    const newParams = {};
    let isValid = true;

    // Boucle pour lire tous les inputs définis dans paramInputs
    for (const key in paramInputs) {
        if (paramInputs[key]) { // Vérifier si l'élément DOM existe
            const inputElement = paramInputs[key];
            if (inputElement.type === 'checkbox') {
                newParams[key] = inputElement.checked;
            } else if (inputElement.type === 'number') {
                const value = parseFloat(inputElement.value);
                if (isNaN(value)) {
                    // Utiliser le label associé s'il existe pour un message plus clair
                    const label = document.querySelector(`label[for='${inputElement.id}']`);
                    addLog(`Erreur: Valeur invalide pour ${label?.textContent || key}`);
                    isValid = false;
                    break;
                }
                if (inputElement.name === 'RISK_PER_TRADE') {
                     newParams[key] = value / 100.0;
                } else {
                     newParams[key] = value; // Garder comme nombre (entier ou float)
                }
            } else if (inputElement.tagName === 'SELECT') { // Gérer le select
                 newParams[key] = inputElement.value;
            }
             else {
                // Gérer d'autres types si nécessaire
                newParams[key] = inputElement.value;
            }
        }
    }

    if (!isValid) {
        paramSaveStatus.textContent = "Erreur de validation côté client.";
        paramSaveStatus.style.color = "red";
        saveParamsBtn.disabled = false;
        return;
    }

    console.log("Envoi des paramètres:", newParams);

    fetch(`${API_BASE_URL}/parameters`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newParams),
    })
    .then(response => response.json().then(data => ({ ok: response.ok, status: response.status, data })))
    .then(({ ok, status, data }) => {
        const message = data.message || `Erreur HTTP ${status}`;
        if (ok) {
            addLog(`Paramètres sauvegardés: ${message}`);
            paramSaveStatus.textContent = "Paramètres sauvegardés !";
            paramSaveStatus.style.color = "green";
            // Afficher la recommandation de redémarrage si présente
            if (message.includes("redémarrage")) {
                 paramSaveStatus.textContent += " (Redémarrage conseillé)";
                 paramSaveStatus.style.color = "darkorange"; // Couleur différente pour la recommandation
            }
        } else {
            console.error("Erreur sauvegarde paramètres (serveur):", data);
            addLog(`Erreur sauvegarde paramètres: ${message}`);
            paramSaveStatus.textContent = `Erreur: ${message}`;
            paramSaveStatus.style.color = "red";
        }
    })
    .catch(error => {
        console.error('Erreur communication sauvegarde paramètres:', error);
        addLog(`Erreur communication sauvegarde: ${error.message}`);
        paramSaveStatus.textContent = "Erreur communication.";
        paramSaveStatus.style.color = "red";
    })
    .finally(() => {
        saveParamsBtn.disabled = false;
        setTimeout(() => { paramSaveStatus.textContent = ""; }, 7000); // Laisser le message plus longtemps si redémarrage conseillé
    });
});
// --- FIN NOUVEL Écouteur ---

    // --- Initialisation ---
    // fetchBotStatus(); // Appelé après fetchParameters maintenant
    fetchParameters(); // Charger les paramètres en premier
    const statusInterval = setInterval(fetchBotStatus, 5000);

    addLog("Frontend initialisé. Prêt à interagir.");
});
