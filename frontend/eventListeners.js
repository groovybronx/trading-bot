import * as DOM from './domElements.js';
import * as API from './apiService.js';
import * as UI from './uiManager.js';
import * as SessionManager from './sessionManager.js';

/**
 * Attaches all necessary event listeners to the DOM elements.
 */
export function initializeEventListeners() {
    // Bot control buttons
    if (DOM.startBotBtn) {
        DOM.startBotBtn.addEventListener('click', async () => {
            try {
                await API.startBot();
                // Optionally refresh sessions after start attempt
                await SessionManager.fetchAndDisplaySessions();
            } catch (error) {
                // Error is already logged by API.startBot
                console.error("Start bot event listener caught error:", error);
                // UI state should be updated via WebSocket or subsequent state fetch
            }
        });
    }

    if (DOM.stopBotBtn) {
        DOM.stopBotBtn.addEventListener('click', async () => {
            try {
                await API.stopBot();
                // Optionally refresh sessions after stop attempt
                await SessionManager.fetchAndDisplaySessions();
            } catch (error) {
                // Error is already logged by API.stopBot
                console.error("Stop bot event listener caught error:", error);
                // UI state should be updated via WebSocket or subsequent state fetch
            }
        });
    }

    // Parameter saving
    if (DOM.saveParamsBtn) {
        DOM.saveParamsBtn.addEventListener('click', async () => {
            try {
                await API.saveParameters();
                // No need to refresh state here, backend handles it.
                // A success message is shown by saveParameters -> updateParamSaveStatus
            } catch (error) {
                // Error is already logged by API.saveParameters
                 console.error("Save parameters event listener caught error:", error);
            }
        });
    }

    // Strategy selector change
    if (DOM.strategySelector) {
        DOM.strategySelector.addEventListener('change', (event) => {
            const selectedStrategy = event.target.value;
            UI.updateParameterVisibility(selectedStrategy);
            // Re-fill parameters based on the *last known state* but for the *newly selected* strategy type
            const lastState = UI.getLastKnownState();
            if (lastState && lastState.config) {
                UI.fillParameters(lastState.config, selectedStrategy);
            } else {
                 console.warn("Cannot fill parameters on strategy change: last known state or config is missing.");
                 // Optionally clear parameters or leave them as they are
            }
        });
    }

    // Session management buttons and selector
    if (DOM.sessionSelector) {
        // Use the handler directly from SessionManager
        DOM.sessionSelector.addEventListener('change', SessionManager.handleSessionChange);
    }

    if (DOM.newSessionBtn) {
        // Use the handler directly from SessionManager
        DOM.newSessionBtn.addEventListener('click', SessionManager.createNewSession);
    }

    if (DOM.deleteSessionBtn) {
        // Use the handler directly from SessionManager
        DOM.deleteSessionBtn.addEventListener('click', SessionManager.deleteSelectedSession);
    }

    console.log("Event listeners initialized.");
}
