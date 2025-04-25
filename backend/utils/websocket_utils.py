# /Users/davidmichels/Desktop/trading-bot/backend/websocket_utils.py
import logging
import json
import asyncio  # Keep asyncio import in case needed elsewhere, though not directly used in sync broadcast
from typing import Dict, Any, Set, cast  # Import cast

logger = logging.getLogger(__name__)

connected_clients: Set = set()  # Assuming this set holds the WebSocket client objects


def broadcast_message(message_dict: dict):
    """Envoie un message JSON à tous les clients WebSocket connectés."""
    if not connected_clients:
        return

    try:
        # default=str handles non-serializable types like Decimal
        message_json = json.dumps(message_dict, default=str)
        # Create a copy to iterate over safely if the set might change
        clients_to_send = list(connected_clients)
        disconnected_clients = set()

        for ws in clients_to_send:
            try:
                # Vérifier si l'objet WebSocket possède l'attribut 'closed'
                if hasattr(ws, "closed") and ws.closed:
                    disconnected_clients.add(ws)
                    continue

                # Envoyer le message
                ws.send(message_json)
            except Exception as e:
                # Log specific error and mark client for removal
                remote_addr = "?"
                try:
                    remote_addr = (
                        ws.environ.get("REMOTE_ADDR", "?")
                        if hasattr(ws, "environ")
                        else "?"
                    )
                except:
                    pass  # Ignore errors getting address
                logger.warning(
                    f"Erreur envoi WS broadcast vers {remote_addr}: {e}. Client marqué pour suppression."
                )
                disconnected_clients.add(ws)

        # Remove disconnected clients outside the loop
        if disconnected_clients:
            for ws in disconnected_clients:
                if ws in connected_clients:
                    connected_clients.remove(ws)
            logger.info(f"Removed {len(disconnected_clients)} disconnected client(s).")

    except TypeError as e:
        logger.error(
            f"Erreur de sérialisation JSON lors du broadcast WS: {e} - Data: {message_dict}",
            exc_info=True,
        )
    except Exception as e:
        logger.error(f"Erreur inattendue lors du broadcast WS: {e}", exc_info=True)


def broadcast_state_update():
    """Récupère l'état actuel complet et le diffuse."""
    # Imports locaux pour éviter dépendances circulaires au chargement
    from manager.state_manager import state_manager
    from manager.config_manager import config_manager

    try:
        current_state = state_manager.get_state()
        excluded_keys = {
            "main_thread",
            "websocket_client",
            "keepalive_thread",
        }  # Exclure objets non sérialisables/internes
        state_serializable = {
            k: v for k, v in current_state.items() if k not in excluded_keys
        }

        # Ajouter des données potentiellement utiles non stockées directement dans l'état principal
        state_serializable["config"] = config_manager.get_config()
        state_serializable["latest_book_ticker"] = state_manager.get_book_ticker()
        # Get active session ID and fetch history for that session
        active_session_id = state_manager.get_active_session_id()
        if active_session_id is not None:
            # Pass session_id to state_manager.get_order_history
            # Use cast to assure Pylance that active_session_id is int here
            state_serializable["order_history"] = state_manager.get_order_history(
                session_id=cast(int, active_session_id)
            )
        else:
            state_serializable["order_history"] = (
                []
            )  # Send empty history if no active session
            logger.debug(
                "broadcast_state_update: No active session, sending empty order history."
            )
        state_serializable["active_session_id"] = (
            active_session_id  # Also include the active session ID itself
        )

        logger.debug("Broadcasting full state update...")
        broadcast_message({"type": "status_update", "state": state_serializable})
    except Exception as e:
        logger.error(f"Erreur dans broadcast_state_update: {e}", exc_info=True)


def broadcast_order_history_update():
    """Récupère l'historique des ordres et le diffuse."""
    # Import local
    from manager.state_manager import state_manager

    try:
        # Get history for the currently active session
        active_session_id = state_manager.get_active_session_id()
        if active_session_id is not None:
            # Pass session_id to state_manager.get_order_history
            # Use cast to assure Pylance that active_session_id is int here
            history = state_manager.get_order_history(
                session_id=cast(int, active_session_id)
            )
            logger.info(
                f"Broadcasting order history update for session {active_session_id}..."
            )
            broadcast_message(
                {
                    "type": "order_history_update",
                    "history": history,
                    "session_id": active_session_id,
                }
            )
        else:
            logger.warning(
                "broadcast_order_history_update: No active session ID found. Cannot broadcast history."
            )
            # Optionally broadcast an empty history?
            # broadcast_message({"type": "order_history_update", "history": [], "session_id": None})
    except Exception as e:
        logger.error(f"Erreur dans broadcast_order_history_update: {e}", exc_info=True)


def broadcast_stats_update(session_id: int):
    """Récupère les stats pour une session et les diffuse."""
    # Import local
    import db

    try:
        if session_id is not None:
            stats = db.get_stats(session_id=session_id)
            logger.info(f"Broadcasting stats update for session {session_id}...")
            broadcast_message(
                {"type": "stats_update", "stats": stats, "session_id": session_id}
            )
        else:
            logger.warning("broadcast_stats_update: No session ID provided.")
    except Exception as e:
        logger.error(
            f"Erreur dans broadcast_stats_update for session {session_id}: {e}",
            exc_info=True,
        )


# --- AJOUT DE LA FONCTION MANQUANTE ---
def broadcast_ticker_update(ticker_data: Dict[str, Any]):
    """Diffuse uniquement les données du ticker aux clients."""
    # logger.debug(f"Broadcasting Ticker Update for {ticker_data.get('s')}") # Verbeux
    try:
        # Appel direct car broadcast_message est synchrone dans cet exemple
        broadcast_message(
            {
                "type": "ticker_update",  # Type spécifique pour le frontend
                "ticker": ticker_data,
            }
        )
    except Exception as e:
        # Logguer toute erreur inattendue pendant le broadcast du ticker
        logger.error(f"Erreur dans broadcast_ticker_update: {e}", exc_info=True)


# --- FIN AJOUT ---


def broadcast_signal_event(
    signal_type: str,
    direction: str,
    valid: bool,
    reason: str,
    extra: dict[str, Any] | None = None,
):
    """Diffuse un événement de signal (entrée/sortie, validé ou non) aux clients WebSocket."""
    event = {
        "type": "signal_event",
        "signal_type": signal_type,  # e.g. 'entry', 'exit'
        "direction": direction,  # e.g. 'LONG', 'SHORT', 'BUY', 'SELL', or ''
        "valid": valid,  # True si validé, False sinon
        "reason": reason,  # Message explicatif
    }
    if extra:
        event.update(extra)
    broadcast_message(event)


# --- Exports ---
# MODIFIÉ: Ajout de broadcast_signal_event à __all__
__all__ = [
    "connected_clients",
    "broadcast_message",
    "broadcast_state_update",
    "broadcast_order_history_update",
    "broadcast_ticker_update",
    "broadcast_signal_event",
    "broadcast_stats_update",  # Export de la nouvelle fonction
]
# --- FIN MODIFIÉ ---
