import logging
from typing import Dict, Any

# --- Import des handlers spécifiques ---
from websocket_market_handlers import (
    process_book_ticker_message,
    process_depth_message,
    process_agg_trade_message,
    process_kline_message,
)
from websocket_user_data_handlers import process_user_data_message

# Les fonctions d'exécution d'ordre (execute_entry, execute_exit) sont maintenant importées dans websocket_market_handlers si nécessaire.
# check_limit_order_timeout est également dans order_execution_handlers.

logger = logging.getLogger(__name__)

# Le point d'entrée principal pour les messages WebSocket
def handle_websocket_message(msg: Dict[str, Any]):
    """Distribue les messages WebSocket aux handlers appropriés."""
    event_type = msg.get("e")
    stream_name = msg.get("stream") # Pour les messages combinés

    if stream_name:
        # Gérer les messages de flux combinés
        if "@bookTicker" in stream_name:
            process_book_ticker_message(msg.get("data", {}))
        elif "@depth" in stream_name:
             process_depth_message(msg.get("data", {}))
        elif "@aggTrade" in stream_name:
             process_agg_trade_message(msg.get("data", {}))
        elif "@kline" in stream_name:
             process_kline_message(msg.get("data", {}))
        # Ajouter d'autres types de flux combinés si nécessaire
    elif event_type:
        # Gérer les messages User Data Stream
        if event_type in ["executionReport", "outboundAccountPosition", "balanceUpdate"]:
            process_user_data_message(msg)
        # Ajouter d'autres types d'événements User Data si nécessaire
    else:
        logger.warning(f"Received unhandled WebSocket message: {msg}")


# --- Exports ---
__all__ = [
    "handle_websocket_message",
]
