# /Users/davidmichels/Desktop/trading-bot/backend/websocket_utils.py
import logging
import json

# REMOVED imports from top:
# from state_manager import state_manager
# from config_manager import config_manager

logger = logging.getLogger(__name__)

connected_clients = set()

def broadcast_message(message_dict: dict):
    """Envoie un message JSON à tous les clients WebSocket connectés."""
    if not connected_clients:
        return

    try:
        logger.debug(f"Attempting to JSON dump: {message_dict}")
        # default=str handles non-serializable types like Decimal or datetime if they appear
        message_json = json.dumps(message_dict, default=str)
        # Create a copy to iterate over, allowing modification of the original set
        clients_to_send = list(connected_clients)
        disconnected_clients = set()

        for ws in clients_to_send:
            try:
                ws.send(message_json)
            except Exception as e:
                # Log specific error and mark client for removal
                logger.warning(f"Erreur envoi WS broadcast vers {ws.environ.get('REMOTE_ADDR', '?')}: {e}. Client marqué pour suppression.")
                disconnected_clients.add(ws)

        # Remove disconnected clients outside the loop
        if disconnected_clients:
            for ws in disconnected_clients:
                if ws in connected_clients:
                    connected_clients.remove(ws)
            # Update the handler's client list if it's being used directly elsewhere
            # (Assuming ws_log_handler is accessible or managed globally/contextually if needed)
            # Example: logging_config.ws_log_handler.clients = connected_clients

    except TypeError as e:
        logger.error(f"Erreur de sérialisation JSON lors du broadcast WS: {e} - Data: {message_dict}", exc_info=True)
    except Exception as e:
        logger.error(f"Erreur inattendue lors du broadcast WS: {e}", exc_info=True)


def broadcast_state_update():
    """Récupère l'état actuel et le diffuse."""
    # --- MOVED IMPORTS HERE ---
    from state_manager import state_manager
    from config_manager import config_manager
    # --- END MOVED IMPORTS ---
    try:
        current_state = state_manager.get_state()

        # Exclude non-serializable or internal objects
        excluded_keys = {'main_thread', 'websocket_client', 'order_history', 'kline_history', 'keepalive_thread'}
        state_serializable = {k: v for k, v in current_state.items() if k not in excluded_keys}

        # Add relevant computed/related data
        state_serializable["config"] = config_manager.get_config()
        state_serializable["latest_book_ticker"] = state_manager.get_book_ticker()

        broadcast_message({"type": "status_update", "state": state_serializable})
    except Exception as e:
        logger.error(f"Erreur dans broadcast_state_update: {e}", exc_info=True)

def broadcast_order_history_update():
    """Récupère l'historique des ordres et le diffuse."""
    # --- MOVED IMPORT HERE ---
    from state_manager import state_manager
    # --- END MOVED IMPORT ---
    try:
        history = state_manager.get_order_history()
        broadcast_message({"type": "order_history_update", "history": history})
        # Keep INFO level for this as it's a significant event
        logger.info("Broadcast order history update envoyé.")
    except Exception as e:
        logger.error(f"Erreur dans broadcast_order_history_update: {e}", exc_info=True)

# --- Exports ---
__all__ = [
    'connected_clients',
    'broadcast_message',
    'broadcast_state_update',
    'broadcast_order_history_update'
]
