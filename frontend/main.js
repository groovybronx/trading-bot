import * as UI from './uiManager.js';
import * as WebSocketService from './websocketService.js';
import * as EventListeners from './eventListeners.js';
//import * as SessionManager from './sessionManager.js';
import * as DOM from './domElements.js'; // Needed for initial visibility check

// Attend que le DOM soit entièrement chargé et parsé
document.addEventListener('DOMContentLoaded', () => {
    console.log("DOM fully loaded and parsed. Initializing application.");
    UI.appendLog("Initialisation de l'interface...", "info");

    // 1. Initialiser DataTables pour l'historique des ordres
    // uiManager contient maintenant la logique d'initialisation
    UI.initializeOrderHistoryTable();

    // 2. Attacher tous les écouteurs d'événements
    EventListeners.initializeEventListeners();

    // 3. Mettre à jour la visibilité initiale des paramètres
    // Basé sur la valeur par défaut du sélecteur de stratégie
    if (DOM.strategySelector) {
        UI.updateParameterVisibility(DOM.strategySelector.value);
        // Note: fillParameters sera appelé dans updateUI lorsque l'état initial sera reçu via WebSocket
    } else {
        console.warn("Strategy selector not found during initialization.");
    }

    // 4. Établir la connexion WebSocket
    // Ceci déclenchera la récupération de l'état initial et des sessions via les callbacks onopen
    WebSocketService.connectWebSocket();

    // 5. (Optionnel/Fallback) Récupérer les sessions initiales au cas où la connexion WS échouerait rapidement
    // SessionManager.fetchAndDisplaySessions(); // Déjà appelé dans ws.onopen, peut-être redondant mais sans danger

    UI.appendLog("Interface initialisée. En attente de connexion...", "info");
});

// Gérer la déconnexion propre lors de la fermeture de la page/onglet
window.addEventListener('beforeunload', () => {
    WebSocketService.disconnectWebSocket(); // Ferme la connexion WS proprement
});

// Démarrer le polling des métriques lorsque la connexion WebSocket est ouverte
// Cette logique est maintenant dans websocketService.js onopen handler
// UI.startMetricsPolling(); // REMOVED - Handled by websocketService.js

// Arrêter le polling des métriques lorsque la connexion WebSocket est fermée
// Cette logique est maintenant dans websocketService.js onclose handler
// UI.stopMetricsPolling(); // REMOVED - Handled by websocketService.js
