document.addEventListener('DOMContentLoaded', () => {
    // Éléments du DOM
    const statusValue = document.getElementById('status-value');
    const symbolValue = document.getElementById('symbol-value');
    const timeframeValue = document.getElementById('timeframe-value');
    const positionValue = document.getElementById('position-value');
    const logOutput = document.getElementById('log-output');
    const startBtn = document.getElementById('start-bot-btn');
    const stopBtn = document.getElementById('stop-bot-btn');

    // État initial
    statusValue.textContent = 'Arrêté';
    statusValue.style.color = 'red';
    logOutput.textContent = 'Le frontend est prêt. En attente de connexion au backend...';

    // --- Communication avec le Backend ---
    const API_BASE_URL = 'http://127.0.0.1:5000'; // Remplacez par l'URL de votre backend si nécessaire

    function fetchBotStatus() {
        console.log("Récupération du statut du bot depuis le backend...");
        fetch(`${API_BASE_URL}/status`, {
            mode: 'cors',
            headers: {
                'Origin': 'http://127.0.0.1:5000' // Ou une autre origine valide
            }
        })
        .then(response => response.json())
        .then(data => {
            updateStatusUI(data);
            addLog(`Statut récupéré du backend: ${JSON.stringify(data)}`);
        })
        .catch(error => {
            console.error('Erreur de récupération du statut:', error);
            addLog("Erreur de connexion au backend pour le statut.");
            statusValue.textContent = 'Erreur Connexion';
            statusValue.style.color = 'orange';
        });
    }

    function updateStatusUI(data) {
        statusValue.textContent = data.status || 'Inconnu';
        symbolValue.textContent = data.symbol || 'N/A';
        timeframeValue.textContent = data.timeframe || 'N/A';
        positionValue.textContent = data.in_position ? 'Oui' : 'Non';

        if (data.status === 'En cours') {
            statusValue.style.color = 'green';
            startBtn.disabled = true;
            stopBtn.disabled = false;
        } else if (data.status === 'Arrêté') {
            statusValue.style.color = 'red';
            startBtn.disabled = false;
            stopBtn.disabled = true;
        } else {
            statusValue.style.color = 'orange'; // Pour 'Erreur' ou 'Inconnu'
            // Gérer l'état des boutons en cas d'erreur ?
        }
    }

    function addLog(message) {
        const timestamp = new Date().toLocaleTimeString();
        logOutput.textContent += `\n[${timestamp}] ${message}`;
        // Auto-scroll vers le bas
        logOutput.scrollTop = logOutput.scrollHeight;
    }

    // --- Gestion des Contrôles ---
    startBtn.addEventListener('click', () => {
        console.log("Clic sur Démarrer le Bot");
        addLog("Tentative de démarrage du bot...");
        // Placeholder: Envoyer une requête au backend pour démarrer
        fetch(`${API_BASE_URL}/start`, { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                if(data.success) {
                    addLog("Ordre de démarrage envoyé au backend.");
                    // Mettre à jour l'UI immédiatement ou attendre confirmation via status poll/websocket
                    statusValue.textContent = 'Démarrage...';
                    statusValue.style.color = 'orange';
                    startBtn.disabled = true;
                    stopBtn.disabled = false; // Permettre l'arrêt pendant le démarrage
                } else {
                    addLog(`Erreur au démarrage: ${data.message || 'Erreur inconnue'}`);
                }
            })
            .catch(error => {
                console.error('Erreur démarrage:', error);
                addLog("Erreur de communication lors du démarrage.");
            });
    });

    stopBtn.addEventListener('click', () => {
        console.log("Clic sur Arrêter le Bot");
        addLog("Tentative d'arrêt du bot...");
        // Placeholder: Envoyer une requête au backend pour arrêter
        fetch(`${API_BASE_URL}/stop`, { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                if(data.success) {
                    addLog("Ordre d'arrêt envoyé au backend.");
                    statusValue.textContent = 'Arrêt...';
                    statusValue.style.color = 'orange';
                    stopBtn.disabled = true; // Désactiver pendant l'arrêt
                } else {
                    addLog(`Erreur à l'arrêt: ${data.message || 'Erreur inconnue'}`);
                }
            })
            .catch(error => {
                console.error('Erreur arrêt:', error);
                addLog("Erreur de communication lors de l'arrêt.");
            });
    });

    // --- Initialisation ---
    fetchBotStatus(); // Premier appel pour obtenir le statut initial
    // Mettre en place un polling régulier ou une connexion WebSocket pour les mises à jour
    setInterval(fetchBotStatus, 5000); // Exemple de polling toutes les 5 secondes

    addLog("Frontend initialisé. Prêt à interagir.");
});
