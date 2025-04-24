import { API_BASE_URL } from './constants.js';
import * as UI from './uiManager.js'; // For logging and status updates
import * as DOM from './domElements.js'; // For accessing button states maybe? (Less ideal)
import { safeValue } from './utils.js'; // For collecting parameters

/**
 * Fetches the current state of the bot from the API.
 * @returns {Promise<object>} The bot state object.
 * @throws {Error} If the API call fails.
 */
export async function fetchBotState() {
    UI.appendLog("Récupération de l'état du bot...", "info");
    try {
        const response = await fetch(`${API_BASE_URL}/api/status`);
        if (!response.ok) {
            let errorMsg = `Erreur API état: ${response.status}`;
            try {
                const errorResult = await response.json();
                errorMsg = errorResult.message || errorMsg;
            } catch { /* Ignore if response is not JSON */ }
            throw new Error(errorMsg);
        }
        const state = await response.json();
        UI.appendLog("État du bot récupéré.", "info");
        return state;
    } catch (error) {
        console.error('Error fetching bot state:', error);
        UI.appendLog(`Erreur récupération état: ${error.message}`, 'error');
        // Update UI to show error status directly?
        if (DOM.statusValue) {
            DOM.statusValue.textContent = 'Erreur API';
            DOM.statusValue.className = 'status-error';
        }
        throw error; // Re-throw to allow caller to handle
    }
}

/**
 * Sends the start command to the bot API.
 * @returns {Promise<object>} The API response object.
 * @throws {Error} If the API call fails.
 */
export async function startBot() {
    UI.appendLog("Envoi de la commande Démarrer...", "info");
    if (DOM.startBotBtn) DOM.startBotBtn.disabled = true;
    if (DOM.stopBotBtn) DOM.stopBotBtn.disabled = true; // Disable both during request
    try {
        const response = await fetch(`${API_BASE_URL}/api/start`, { method: 'POST' });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.message || `Erreur serveur (start): ${response.status}`);
        }
        UI.appendLog(result.message || 'Commande Démarrer envoyée.', 'info');
        return result;
    } catch (error) {
        console.error('Error starting bot:', error);
        UI.appendLog(`Erreur au démarrage du bot: ${error.message}`, 'error');
        // Re-enable buttons based on actual state fetched after error? Or just enable start?
        if (DOM.startBotBtn) DOM.startBotBtn.disabled = false;
        // Stop button state depends on whether the bot is actually running, fetch state to know for sure.
        throw error;
    }
    // Note: Refreshing sessions should be handled by the caller (e.g., sessionManager)
}

/**
 * Sends the stop command to the bot API.
 * @returns {Promise<object>} The API response object.
 * @throws {Error} If the API call fails.
 */
export async function stopBot() {
    UI.appendLog("Envoi de la commande Arrêter...", "info");
    if (DOM.stopBotBtn) DOM.stopBotBtn.disabled = true;
    if (DOM.startBotBtn) DOM.startBotBtn.disabled = true; // Disable both during request
    try {
        const response = await fetch(`${API_BASE_URL}/api/stop`, { method: 'POST' });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.message || `Erreur serveur (stop): ${response.status}`);
        }
        UI.appendLog(result.message || 'Commande Arrêter envoyée.', 'info');
        return result;
    } catch (error) {
        console.error('Error stopping bot:', error);
        UI.appendLog(`Erreur à l'arrêt du bot: ${error.message}`, 'error');
        // Re-enable buttons based on actual state fetched after error? Or just enable start?
        if (DOM.startBotBtn) DOM.startBotBtn.disabled = false;
        // Stop button state depends on whether the bot is actually running.
        throw error;
    }
    // Note: Refreshing sessions should be handled by the caller (e.g., sessionManager)
}

/**
 * Collects parameters from the DOM and sends them to the API.
 * @returns {Promise<object>} The API response object.
 * @throws {Error} If the API call fails or parameter collection fails.
 */
export async function saveParameters() {
    UI.updateParamSaveStatus('Sauvegarde en cours...', 'saving');

    try {
        // Collect parameters using safeValue from utils.js and DOM elements
        // Les valeurs de type pourcentage doivent être saisies en pourcentage (ex: 0.5 pour 0.5%)
        // et seront converties en fraction ici (division par 100)
        const paramsToSend = {
            STRATEGY_TYPE: safeValue(DOM.strategySelector),
            TIMEFRAME: safeValue(DOM.paramTimeframe),
            RISK_PER_TRADE: safeValue(DOM.paramRisk, v => parseFloat(v) ),
            CAPITAL_ALLOCATION: safeValue(DOM.paramCapitalAllocation, v => parseFloat(v) ),
            STOP_LOSS_PERCENTAGE: safeValue(DOM.paramSl, v => parseFloat(v) ), // Saisir en % (ex: 0.5 pour 0.5%)
            TAKE_PROFIT_1_PERCENTAGE: safeValue(DOM.paramTp1, v => parseFloat(v) ), // Saisir en %
            TAKE_PROFIT_2_PERCENTAGE: safeValue(DOM.paramTp2, v => parseFloat(v) ), // Saisir en %
            TRAILING_STOP_PERCENTAGE: safeValue(DOM.paramTrailing, v => parseFloat(v) ), // Saisir en %
            TIME_STOP_MINUTES: safeValue(DOM.paramTimeStop, v => parseInt(v, 10)),
            EMA_SHORT_PERIOD: safeValue(DOM.paramEmaShort, v => parseInt(v, 10)),
            EMA_LONG_PERIOD: safeValue(DOM.paramEmaLong, v => parseInt(v, 10)),
            EMA_FILTER_PERIOD: safeValue(DOM.paramEmaFilter, v => parseInt(v, 10)),
            RSI_PERIOD: safeValue(DOM.paramRsiPeriod, v => parseInt(v, 10)),
            RSI_OVERBOUGHT: safeValue(DOM.paramRsiOb, v => parseInt(v, 10)),
            RSI_OVERSOLD: safeValue(DOM.paramRsiOs, v => parseInt(v, 10)),
            VOLUME_AVG_PERIOD: safeValue(DOM.paramVolumeAvg, v => parseInt(v, 10)),
            USE_EMA_FILTER: safeValue(DOM.paramUseEmaFilter),
            USE_VOLUME_CONFIRMATION: safeValue(DOM.paramUseVolume),
            SCALPING_ORDER_TYPE: safeValue(DOM.paramScalpingOrderType),
            SCALPING_LIMIT_TIF: safeValue(DOM.paramScalpingLimitTif),
            SCALPING_LIMIT_ORDER_TIMEOUT_MS: safeValue(DOM.paramScalpingLimitTimeout, v => parseInt(v, 10)),
            SCALPING_DEPTH_LEVELS: safeValue(DOM.paramScalpingDepthLevels, v => parseInt(v, 10)),
            SCALPING_DEPTH_SPEED: safeValue(DOM.paramScalpingDepthSpeed),
            SCALPING_SPREAD_THRESHOLD: safeValue(DOM.paramScalpingSpreadThreshold, parseFloat),
            SCALPING_IMBALANCE_THRESHOLD: safeValue(DOM.paramScalpingImbalanceThreshold, parseFloat),
            ORDER_COOLDOWN_MS: safeValue(DOM.paramOrderCooldown, v => parseInt(v, 10)),
            SUPERTREND_ATR_PERIOD: safeValue(DOM.paramSupertrendAtr, v => parseInt(v, 10)),
            SUPERTREND_ATR_MULTIPLIER: safeValue(DOM.paramSupertrendMult, parseFloat),
            SCALPING_RSI_PERIOD: safeValue(DOM.paramRsiPeriodScalp, v => parseInt(v, 10)),
            STOCH_K_PERIOD: safeValue(DOM.paramStochK, v => parseInt(v, 10)),
            STOCH_D_PERIOD: safeValue(DOM.paramStochD, v => parseInt(v, 10)),
            STOCH_SMOOTH: safeValue(DOM.paramStochSmooth, v => parseInt(v, 10)),
            BB_PERIOD: safeValue(DOM.paramBbPeriod, v => parseInt(v, 10)),
            BB_STD: safeValue(DOM.paramBbStd, parseFloat),
            VOLUME_MA_PERIOD: safeValue(DOM.paramVolMa, v => parseInt(v, 10)),
        };

        // Clean parameters: remove null/undefined/NaN
        const cleanedParamsToSend = {};
        for (const key in paramsToSend) {
            let value = paramsToSend[key];
            if (value === null || value === undefined) {
                continue; // Skip null/undefined right away
            }
            cleanedParamsToSend[key] = value;
        }

        console.log("Sending parameters:", JSON.stringify(cleanedParamsToSend, null, 2));

        // Send cleaned parameters to the backend
        const response = await fetch(`${API_BASE_URL}/api/parameters`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cleanedParamsToSend),
        });
        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.message || `Erreur serveur (parameters): ${response.status}`);
        }

        UI.updateParamSaveStatus(result.message || 'Paramètres sauvegardés!', 'success');
        UI.appendLog(result.message || 'Paramètres sauvegardés.', 'info');
        if (result.restart_recommended) {
            alert("Un redémarrage du bot est conseillé pour appliquer certains changements.");
            UI.appendLog("Redémarrage bot conseillé.", "warn");
        }
        return result;

    } catch (error) {
        console.error('Error saving parameters:', error);
        UI.updateParamSaveStatus(`Erreur sauvegarde: ${error.message}`, 'error');
        UI.appendLog(`Erreur sauvegarde paramètres: ${error.message}`, 'error');
        throw error;
    }
    // Status message clearing is handled by updateParamSaveStatus
}

/**
 * Fetches statistics for a specific session ID.
 * @param {number|string|null} sessionId - The ID of the session.
 * @returns {Promise<object|null>} The statistics object or null if no session ID provided.
 * @throws {Error} If the API call fails.
 */
export async function fetchStats(sessionId) {
    if (sessionId === null || sessionId === undefined) {
        console.warn("fetchStats: No session ID provided.");
        return null; // Return null or empty object? Null seems clearer.
    }
    console.debug(`Fetching stats for session ID: ${sessionId}`);
    try {
        const response = await fetch(`${API_BASE_URL}/api/stats?session_id=${sessionId}`);
        if (!response.ok) {
            throw new Error(`Erreur API stats (${response.status}) pour session ${sessionId}`);
        }
        const stats = await response.json();
        console.debug("Stats received:", stats);
        return stats;
    } catch (e) {
        console.error(`Error fetching stats for session ${sessionId}:`, e);
        // Let UI handle displaying the error based on the thrown error
        throw e;
    }
}

/**
 * Fetches order history for a specific session ID.
 * @param {number|string|null} sessionId - The ID of the session.
 * @returns {Promise<Array<object>|null>} Array of order objects or null if no session ID.
 * @throws {Error} If the API call fails.
 */
export async function fetchOrderHistory(sessionId) {
    if (sessionId === null || sessionId === undefined) {
        console.warn("fetchOrderHistory: No session ID provided.");
        return null;
    }
    console.debug(`Fetching order history for session ID: ${sessionId}`);
    if (DOM.historySessionIdSpan) DOM.historySessionIdSpan.textContent = `#${sessionId}`; // Update title span
    try {
        const response = await fetch(`${API_BASE_URL}/api/order_history?session_id=${sessionId}`);
        if (!response.ok) {
            throw new Error(`Erreur API historique (${response.status}) pour session ${sessionId}`);
        }
        const history = await response.json();
        console.debug("Order history received:", history);
        return history;
    } catch (e) {
        console.error(`Error fetching order history for session ${sessionId}:`, e);
        if (DOM.historySessionIdSpan) DOM.historySessionIdSpan.textContent = `Erreur`;
        // Let UI handle clearing/displaying error in the table based on the thrown error
        throw e;
    }
}

// --- NEW Session Management API Calls ---

/**
 * Fetches the ID of the currently active session.
 * @returns {Promise<number|null>} The active session ID or null.
 * @throws {Error} If the API call fails but returns non-OK status.
 */
export async function fetchActiveSessionId() {
    console.debug("Fetching active session ID...");
    try {
        const response = await fetch(`${API_BASE_URL}/api/sessions/active`);
        if (response.ok) {
            const data = await response.json();
            console.debug("Active session ID data:", data);
            return data.active_session_id; // Can be null if none active
        } else {
            console.warn("Could not fetch active session status:", response.status);
            // Don't throw an error for non-OK, just return null as if none active
            return null;
        }
    } catch (e) {
        console.error("Error fetching active session ID:", e);
        throw e; // Throw network or JSON parsing errors
    }
}

/**
 * Fetches the list of all sessions.
 * @returns {Promise<Array<object>>} Array of session objects.
 * @throws {Error} If the API call fails.
 */
export async function fetchAllSessions() {
    console.debug("Fetching all sessions...");
    try {
        const response = await fetch(`${API_BASE_URL}/api/sessions`);
        if (!response.ok) {
            throw new Error(`Erreur API sessions (${response.status})`);
        }
        const sessions = await response.json();
        console.debug("All sessions data received:", sessions);
        return sessions;
    } catch (e) {
        console.error("Error fetching all sessions:", e);
        throw e;
    }
}

/**
 * Sends a request to create a new session.
 * @param {string} strategy - The strategy type for the new session.
 * @returns {Promise<object>} The API response object.
 * @throws {Error} If the API call fails.
 */
export async function createNewSessionApi(strategy) {
    console.log(`Attempting to create new session with strategy: ${strategy}...`);
    try {
        const response = await fetch(`${API_BASE_URL}/api/sessions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ strategy: strategy || 'UNKNOWN' }) // Send strategy
        });
        const result = await response.json();
        if (!response.ok || !result.success) {
            throw new Error(result.message || `Erreur API création session (${response.status})`);
        }
        UI.appendLog(result.message || "Nouvelle session créée via API.", "info");
        return result;
    } catch (e) {
        console.error("Error creating new session via API:", e);
        UI.appendLog(`Erreur création session API: ${e.message}`, 'error');
        throw e;
    }
}

/**
 * Sends a request to delete a specific session.
 * @param {number|string} sessionId - The ID of the session to delete.
 * @returns {Promise<object>} The API response object.
 * @throws {Error} If the API call fails.
 */
export async function deleteSessionApi(sessionId) {
    console.log(`Attempting to delete session ID via API: ${sessionId}`);
    try {
        const response = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}`, {
            method: 'DELETE'
        });
        const result = await response.json();
        if (!response.ok || !result.success) {
            throw new Error(result.message || `Erreur API suppression session (${response.status})`);
        }
        UI.appendLog(result.message || `Session ${sessionId} supprimée via API.`, "info");
        return result;
    } catch (e) {
        console.error(`Error deleting session ${sessionId} via API:`, e);
        UI.appendLog(`Erreur suppression session API ${sessionId}: ${e.message}`, 'error');
        throw e;
    }
}
