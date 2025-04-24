import { WS_URL } from './constants.js';
import * as UI from './uiManager.js';
import * as API from './apiService.js';
import * as SessionManager from './sessionManager.js'; // Import session manager
import * as DOM from './domElements.js'; // For updating button states on disconnect

let ws = null; // WebSocket connection instance
let reconnectTimeout = null; // To store the timeout ID for reconnection

/**
 * Handles incoming WebSocket messages.
 * @param {MessageEvent} event - The WebSocket message event.
 */
function handleWebSocketMessage(event) {
    try {
        const data = JSON.parse(event.data);
        const currentSessionId = SessionManager.getCurrentSessionId(); // Get current session ID

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
                    UI.updateUI(data.state, currentSessionId); // Pass currentSessionId for context if needed
                    // Check if active session ID changed and refresh if necessary
                    if (data.state.active_session_id !== undefined && data.state.active_session_id !== currentSessionId) {
                        console.log("Active session ID changed via status update, refreshing sessions list.");
                        SessionManager.fetchAndDisplaySessions(); // Refresh list and selection
                    }
                } else {
                    console.warn("Received status_update without state data:", data);
                }
                break;
            case 'ticker_update':
                UI.updatePriceDisplay(data.ticker);
                break;
            case 'order_history_update':
                // Refresh history ONLY if the update is for the currently selected session
                if (data.session_id !== undefined && data.session_id === currentSessionId) {
                    console.debug(`Order history update received for current session ${currentSessionId}. Refreshing.`);
                    SessionManager.fetchAndDisplayOrderHistoryForCurrentSession(); // Use SessionManager function
                    UI.appendLog("Historique des ordres mis à jour (via push).", "info");
                } else {
                     console.debug(`Ignoring order history update for non-selected session ${data.session_id}`);
                }
                break;
            case 'ping':
                // console.debug("Ping received"); // Optional: log pings
                break; // Ignore ping messages
            case 'signal_event':
                UI.displaySignalEvent(data);
                break;
            case 'stats_update':
                // Update stats ONLY if the update is for the currently selected session
                if (data.stats && data.session_id !== undefined && data.session_id === currentSessionId) {
                    console.debug(`Received stats update for current session ${currentSessionId}`);
                    UI.updateStatsDisplay(data.stats);
                } else if (data.session_id !== currentSessionId) {
                    console.debug(`Ignoring stats update for non-selected session ${data.session_id}`);
                }
                break;
            default:
                console.warn('Unknown WebSocket message type received:', data);
                UI.appendLog(`[WS Type Inconnu: ${data.type}] ${JSON.stringify(data.message || data.payload || data)}`, 'warn');
        }
    } catch (error) {
        console.error('Error processing WebSocket message (Malformed JSON?):', error, event.data);
        UI.appendLog(`Erreur traitement WS (JSON invalide?): ${event.data}`, 'error');
    }
}

/**
 * Establishes the WebSocket connection and sets up handlers.
 */
export function connectWebSocket() {
    // Clear any existing reconnect timeout
    if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
    }

    // Prevent multiple connections
    if (ws && ws.readyState !== WebSocket.CLOSED) {
        console.warn("WebSocket connection attempt skipped: Connection already exists or is connecting.");
        return;
    }

    console.log(`Attempting to connect WebSocket to: ${WS_URL}`);
    UI.appendLog("Tentative de connexion au backend...", "info");
    console.log('WS URL Check:', WS_URL); // Vérification explicite de l'URL
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        console.log('WebSocket connection established');
        UI.appendLog("WebSocket connecté.", "info");
        // Fetch initial data on successful connection
        API.fetchBotState().then(state => {
            UI.updateUI(state, SessionManager.getCurrentSessionId());
            // Fetch sessions *after* getting initial state to know the active one
            SessionManager.fetchAndDisplaySessions();
        }).catch(error => {
             console.error("Error fetching initial state after WS open:", error);
             // Still try to fetch sessions even if state fetch fails
             SessionManager.fetchAndDisplaySessions();
        });
    };

    ws.onmessage = handleWebSocketMessage; // Use the dedicated handler function

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        UI.appendLog('Erreur de connexion WebSocket. Le backend est-il démarré et accessible?', 'error');
        // Update UI to reflect error state
        if (DOM.statusValue) {
            DOM.statusValue.textContent = 'Erreur Connexion';
            DOM.statusValue.className = 'status-error';
        }
        // Ensure buttons reflect a non-connected state
        if (DOM.stopBotBtn) DOM.stopBotBtn.disabled = true;
        if (DOM.startBotBtn) DOM.startBotBtn.disabled = false; // Allow attempting to start
        // ws instance might be unusable, nullify it after error?
        // The 'onclose' event usually follows 'onerror', so cleanup might happen there.
    };

    ws.onclose = (event) => {
        const wasConnected = !!ws; // Check if we thought we were connected
        ws = null; // Clear the instance
        console.log(`WebSocket connection closed. Code: ${event.code}, Reason: ${event.reason || 'No reason given'}`);

        // Update UI to reflect disconnected state
        if (DOM.statusValue) {
            DOM.statusValue.textContent = 'Déconnecté';
            DOM.statusValue.className = 'status-stopped'; // Or a dedicated 'disconnected' status
        }
        if (DOM.stopBotBtn) DOM.stopBotBtn.disabled = true;
        if (DOM.startBotBtn) DOM.startBotBtn.disabled = false; // Allow attempting to start

        // Attempt to reconnect only if the closure was unexpected
        // Codes 1000 (Normal Closure) and 1001 (Going Away) are considered expected.
        if (wasConnected && event.code !== 1000 && event.code !== 1001) {
            UI.appendLog(`Connexion WebSocket fermée (Code: ${event.code}). Tentative de reconnexion dans 5s...`, 'warn');
            // Clear any previous timeout just in case
            if (reconnectTimeout) clearTimeout(reconnectTimeout);
            reconnectTimeout = setTimeout(connectWebSocket, 5000); // Schedule reconnection
        } else {
            UI.appendLog(`Connexion WebSocket fermée (Code: ${event.code}).`, "info");
        }
    };
}

/**
 * Closes the WebSocket connection intentionally.
 */
export function disconnectWebSocket() {
    if (reconnectTimeout) {
        clearTimeout(reconnectTimeout); // Cancel any pending reconnection attempts
        reconnectTimeout = null;
    }
    if (ws) {
        console.log("Closing WebSocket connection intentionally.");
        ws.close(1000, "Client disconnecting"); // Use normal closure code
        ws = null;
    }
}
