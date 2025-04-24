import * as DOM from './domElements.js';
import * as API from './apiService.js';
import * as UI from './uiManager.js';

let currentSessionId = null; // ID de la session actuellement sélectionnée dans l'UI
let allSessionsData = []; // Cache local des données de toutes les sessions

/**
 * Récupère l'ID de la session actuellement sélectionnée.
 * @returns {number | null}
 */
export function getCurrentSessionId() {
    return currentSessionId;
}

/**
 * Met à jour l'affichage de l'historique et des statistiques pour la session courante.
 * Déclenché par un changement de session ou une mise à jour WebSocket.
 */
export async function fetchAndDisplayOrderHistoryForCurrentSession() {
    if (currentSessionId !== null) {
        try {
            const history = await API.fetchOrderHistory(currentSessionId);
            UI.updateOrderHistory(history || []); // Pass empty array if null
        } catch (error) {
            console.error(`Failed to fetch/display order history for session ${currentSessionId}:`, error);
            UI.updateOrderHistory([]); // Clear table on error
            UI.appendLog(`Erreur chargement historique session ${currentSessionId}: ${error.message}`, 'error');
        }
    } else {
        UI.updateOrderHistory([]); // Clear history if no session selected
    }
}

/**
 * Met à jour l'affichage des statistiques pour la session courante.
 */
async function fetchAndDisplayStatsForCurrentSession() {
    if (currentSessionId !== null) {
        try {
            const stats = await API.fetchStats(currentSessionId);
            UI.updateStatsDisplay(stats); // Pass stats or null
        } catch (error) {
            console.error(`Failed to fetch/display stats for session ${currentSessionId}:`, error);
            UI.updateStatsDisplay(null); // Clear stats on error
            UI.appendLog(`Erreur chargement stats session ${currentSessionId}: ${error.message}`, 'error');
        }
    } else {
        UI.updateStatsDisplay(null); // Clear stats if no session selected
    }
}


/**
 * Met à jour l'indicateur de statut de la session et l'état du bouton de suppression.
 * @param {number | null} sessionId - L'ID de la session sélectionnée.
 */
function updateSessionStatusIndicator(sessionId) {
    const selectedSession = allSessionsData.find(s => s.id === sessionId);
    if (DOM.sessionStatusIndicator) {
        DOM.sessionStatusIndicator.textContent = selectedSession ? `(${selectedSession.status})` : '';
        DOM.sessionStatusIndicator.className = selectedSession ? `status-${selectedSession.status}` : '';
    }
    if (DOM.deleteSessionBtn) {
        const isActive = selectedSession && selectedSession.status === 'active';
        DOM.deleteSessionBtn.disabled = (sessionId === null || isActive);
        DOM.deleteSessionBtn.title = isActive ? "Impossible de supprimer une session active." : "Supprimer la session sélectionnée";
    }
}

/**
 * Met à jour l'affichage complet lié à la session sélectionnée (historique, stats, indicateur).
 * @param {number | null} sessionId - L'ID de la session à afficher.
 */
export function updateSessionDisplay(sessionId) {
    currentSessionId = sessionId; // Met à jour le tracker global
    console.debug("Updating display for session ID:", currentSessionId);

    // Met à jour l'historique et les stats
    fetchAndDisplayOrderHistoryForCurrentSession();
    fetchAndDisplayStatsForCurrentSession();

    // Met à jour l'indicateur de statut et le bouton supprimer
    updateSessionStatusIndicator(sessionId);

     // Met à jour le titre de la section historique
     if (DOM.historySessionIdSpan) {
        DOM.historySessionIdSpan.textContent = sessionId !== null ? `#${sessionId}` : 'N/A';
    }
}

/**
 * Récupère toutes les sessions depuis l'API et met à jour le sélecteur déroulant.
 * Sélectionne automatiquement la session active ou la session précédemment sélectionnée.
 */
export async function fetchAndDisplaySessions() {
    console.debug("Fetching sessions...");
    let activeId = null;
    let previouslySelectedValue = DOM.sessionSelector ? DOM.sessionSelector.value : null; // Mémoriser la sélection

    try {
        // 1. Récupérer l'ID de la session active
        activeId = await API.fetchActiveSessionId();
        console.debug("Active session ID from API:", activeId);

        // 2. Récupérer toutes les sessions
        allSessionsData = await API.fetchAllSessions(); // Stocker globalement
        console.debug("All sessions data from API:", allSessionsData);

        // 3. Peupler le sélecteur
        if (DOM.sessionSelector) {
            DOM.sessionSelector.innerHTML = '<option value="">-- Sélectionner une session --</option>'; // Option par défaut
            let activeIdFoundInList = false;
            let sessionToSelect = null; // Garder une trace de l'ID à sélectionner

            allSessionsData.forEach(session => {
                const option = document.createElement('option');
                option.value = session.id;
                const startTime = session.start_time ? new Date(session.start_time).toLocaleString() : 'N/A';
                const endTime = session.end_time ? ` - ${new Date(session.end_time).toLocaleString()}` : (session.status === 'active' ? ' - Active' : '');
                const sessionName = session.name || `Session ${session.id}`;
                option.textContent = `${sessionName} (${session.strategy} / ${startTime}${endTime})`;
                DOM.sessionSelector.appendChild(option);

                // Déterminer quelle session sélectionner
                if (session.id === activeId) {
                    sessionToSelect = session.id; // Priorité à la session active
                    activeIdFoundInList = true;
                } else if (String(session.id) === previouslySelectedValue && !activeIdFoundInList) {
                    // Si pas de session active trouvée, essayer de resélectionner l'ancienne
                    sessionToSelect = session.id;
                }
            });

            // Appliquer la sélection déterminée
            if (sessionToSelect !== null) {
                DOM.sessionSelector.value = sessionToSelect;
            } else {
                 // Si rien à sélectionner (ni active, ni ancienne), s'assurer que "-- Sélectionner --" est choisi
                 DOM.sessionSelector.value = "";
            }

            // Mettre à jour l'affichage pour la session sélectionnée (ou aucune)
            handleSessionChange(); // Déclenche la mise à jour de l'UI pour la sélection actuelle

        } else {
            updateSessionDisplay(null); // Effacer l'affichage si le sélecteur n'existe pas
        }

    } catch (e) {
        console.error("Error fetching/displaying sessions:", e);
        if (DOM.sessionSelector) DOM.sessionSelector.innerHTML = '<option value="">Erreur chargement</option>';
        updateSessionDisplay(null); // Effacer l'affichage en cas d'erreur
        UI.appendLog(`Erreur chargement sessions: ${e.message}`, 'error');
    }
}


/**
 * Gère le changement de sélection dans le sélecteur de session.
 */
export function handleSessionChange() {
    const selectedIdStr = DOM.sessionSelector ? DOM.sessionSelector.value : null;
    const selectedId = selectedIdStr ? parseInt(selectedIdStr, 10) : null;

    if (selectedId !== null && !isNaN(selectedId)) {
        updateSessionDisplay(selectedId);
    } else {
        updateSessionDisplay(null); // Gère le cas "-- Sélectionner --"
    }
}

/**
 * Gère le clic sur le bouton "Nouvelle Session".
 */
export async function createNewSession() {
    console.log("Handling create new session button click...");
    if (DOM.newSessionBtn) DOM.newSessionBtn.disabled = true;
    try {
        const currentStrategy = UI.getSelectedStrategy() || 'SWING'; // Récupère la stratégie depuis l'UI
        await API.createNewSessionApi(currentStrategy);
        // Rafraîchir la liste des sessions pour inclure la nouvelle et la sélectionner
        await fetchAndDisplaySessions();
    } catch (e) {
        // L'erreur est déjà loggée par createNewSessionApi
        console.error("Failed to create new session from SessionManager:", e);
    } finally {
        if (DOM.newSessionBtn) DOM.newSessionBtn.disabled = false;
    }
}

/**
 * Gère le clic sur le bouton "Supprimer Session".
 */
export async function deleteSelectedSession() {
    const sessionIdToDelete = currentSessionId;
    if (sessionIdToDelete === null) {
        alert("Veuillez sélectionner une session à supprimer.");
        return;
    }

    // Vérification supplémentaire (normalement déjà gérée par l'état du bouton)
    const selectedSession = allSessionsData.find(s => s.id === sessionIdToDelete);
    if (selectedSession && selectedSession.status === 'active') {
        alert("Impossible de supprimer une session active.");
        return;
    }

    if (!confirm(`Êtes-vous sûr de vouloir supprimer la session #${sessionIdToDelete} et TOUS ses ordres associés ? Cette action est irréversible.`)) {
        return;
    }

    console.log(`Handling delete session button click for ID: ${sessionIdToDelete}`);
    if (DOM.deleteSessionBtn) DOM.deleteSessionBtn.disabled = true;

    try {
        await API.deleteSessionApi(sessionIdToDelete);
        // Rafraîchir la liste, ce qui désélectionnera la session supprimée
        // et mettra à jour l'état du bouton via fetchAndDisplaySessions -> handleSessionChange -> updateSessionDisplay
        await fetchAndDisplaySessions();
    } catch (e) {
        // L'erreur est déjà loggée par deleteSessionApi
        console.error(`Failed to delete session ${sessionIdToDelete} from SessionManager:`, e);
        // Essayer de rafraîchir quand même pour potentiellement corriger l'état du bouton
        await fetchAndDisplaySessions();
    }
    // L'état du bouton est géré par la logique dans fetchAndDisplaySessions/updateSessionDisplay
}
