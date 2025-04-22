# /Users/davidmichels/Desktop/trading-bot/backend/api_routes.py
import logging
import time
import queue # Gardé si logging_config l'utilise
from flask import Blueprint, jsonify, request, Response
from decimal import Decimal, InvalidOperation
import collections # Pour type hinting si besoin
import threading

# Gestionnaires et Core
from state_manager import state_manager
from config_manager import config_manager, VALID_TIMEFRAMES
import bot_core

# Wrapper Client Binance
import binance_client_wrapper

# Utilitaires WebSocket
from websocket_utils import broadcast_state_update

# Config Logging (si log_queue est utilisé)
# from logging_config import log_queue # Décommenter si utilisé

logger = logging.getLogger(__name__)
api_bp = Blueprint('api', __name__)

# --- Routes API ---

@api_bp.route('/status')
def get_status():
    """Retourne l'état actuel, la config, ticker et historique."""
    try:
        status_data = state_manager.get_state()
        excluded_keys = {'main_thread', 'websocket_client', 'keepalive_thread'}
        status_data_serializable = {k: v for k, v in status_data.items() if k not in excluded_keys}
        status_data_serializable["config"] = config_manager.get_config()
        status_data_serializable["latest_book_ticker"] = state_manager.get_book_ticker()
        status_data_serializable["order_history"] = state_manager.get_order_history() # Utilise la méthode get
        return jsonify(status_data_serializable)
    except Exception as e:
        logger.error(f"API /status: Error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (état)."}), 500

@api_bp.route('/parameters', methods=['GET'])
def get_parameters():
    """Retourne la configuration actuelle (sans clés sensibles)."""
    try:
        current_config = config_manager.get_config()
        sensitive_keys = {"BINANCE_API_KEY", "BINANCE_API_SECRET"}
        config_to_send = {k: v for k, v in current_config.items() if k not in sensitive_keys}
        return jsonify(config_to_send)
    except Exception as e:
        logger.error(f"API /parameters (GET): Error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (config)."}), 500

@api_bp.route('/parameters', methods=['POST'])
def set_parameters():
    """Met à jour les paramètres de configuration."""
    new_params = request.json
    if not new_params:
        return jsonify({"success": False, "message": "Aucun paramètre fourni."}), 400

    logger.info(f"API /parameters (POST): Attempting update with: {new_params}")
    try:
        # Utilise state_manager pour mettre à jour config ET état interne si besoin
        success, message, restart_recommended = state_manager.update_config_values(new_params)

        if success:
            logger.info(f"API /parameters (POST): {message}")
            broadcast_state_update() # Diffuser le nouvel état/config
            return jsonify({"success": True, "message": message, "restart_recommended": restart_recommended})
        else:
            logger.error(f"API /parameters (POST): Validation/Update failed: {message}")
            return jsonify({"success": False, "message": message}), 400

    except Exception as e:
        logger.error(f"API /parameters (POST): Unexpected error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (MAJ params)."}), 500

@api_bp.route('/start', methods=['POST'])
def start_bot_route():
    """Démarre le bot."""
    logger.info("API /start: Request received.")
    try:
        success, message = bot_core.start_bot_core()
        status_code = 200 if success else 500
        if not success and "déjà" in message.lower(): status_code = 400 # Bad request si déjà démarré
        return jsonify({"success": success, "message": message}), status_code
    except Exception as e:
        logger.error(f"API /start: Unexpected error: {e}", exc_info=True)
        try:
            state_manager.update_state({"status": "ERROR"})
            broadcast_state_update()
        except Exception as inner_e: logger.error(f"API /start: Error updating/broadcasting after exception: {inner_e}")
        return jsonify({"success": False, "message": "Erreur interne serveur (démarrage)."}), 500

@api_bp.route('/stop', methods=['POST'])
def stop_bot_route():
    """Arrête le bot."""
    logger.info("API /stop: Request received.")
    try:
        result = bot_core.stop_bot_core()
        if result is None: result = (False, "Erreur: stop_bot_core returned None.")
        success, message = result
        status_code = 200 if success else 400 # Bad request si déjà arrêté?
        return jsonify({"success": success, "message": message}), status_code
    except Exception as e:
        logger.error(f"API /stop: Unexpected error: {e}", exc_info=True)
        try:
            state_manager.update_state({"status": "ERROR"})
            broadcast_state_update()
        except Exception as inner_e: logger.error(f"API /stop: Error updating/broadcasting after exception: {inner_e}")
        return jsonify({"success": False, "message": "Erreur interne serveur (arrêt)."}), 500

@api_bp.route('/order_history')
def get_order_history():
    """Retourne l'historique des ordres."""
    try:
        history = state_manager.get_order_history()
        return jsonify(history)
    except Exception as e:
        logger.error(f"API /order_history: Error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (historique)."}), 500

@api_bp.route('/manual_exit', methods=['POST'])
def manual_exit_route():
    """Déclenche une sortie manuelle."""
    logger.info("API /manual_exit: Request received.")
    try:
        if not state_manager.get_state("in_position"):
             return jsonify({"success": False, "message": "Le bot n'est pas en position."}), 400

        logger.warning("API /manual_exit: Triggering manual exit via API...")
        # Appelle execute_exit dans un thread pour ne pas bloquer la réponse API
        threading.Thread(target=bot_core.execute_exit, args=("Sortie Manuelle API",), daemon=True).start()
        return jsonify({"success": True, "message": "Requête de sortie manuelle initiée."}), 202 # Accepted
    except Exception as e:
        logger.error(f"API /manual_exit: Unexpected error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (sortie manuelle)."}), 500

@api_bp.route('/place_order', methods=['POST'])
def handle_place_order():
    """Endpoint pour placer un ordre manuel via l'API."""
    logger.info("API /place_order: Request received.")
    data = request.get_json()

    if not data:
        logger.error("API /place_order: No JSON data received.")
        return jsonify({"success": False, "message": "Requête invalide (JSON manquant)."}), 400

    required_keys = ["symbol", "side", "order_type", "quantity"]
    if not all(key in data for key in required_keys):
        missing = [key for key in required_keys if key not in data]
        logger.error(f"API /place_order: Missing data: {missing}")
        return jsonify({"success": False, "message": f"Données manquantes: {', '.join(missing)}"}), 400

    order_params = {k: data.get(k) for k in required_keys + ["price", "time_in_force"]}
    order_params = {k: v for k, v in order_params.items() if v is not None} # Clean None values

    if order_params["order_type"] == 'LIMIT' and "price" not in order_params:
         logger.error("API /place_order: Price missing for LIMIT order.")
         return jsonify({"success": False, "message": "Prix manquant pour ordre LIMIT."}), 400

    try:
        logger.info(f"API /place_order: Placing order via wrapper: {order_params}")
        order_result = binance_client_wrapper.place_order(**order_params)

        if not order_result:
            logger.error("API /place_order: Order placement failed (wrapper returned None).")
            return jsonify({"success": False, "message": "Échec requête Binance (voir logs)."}), 500

        order_status = order_result.get('status', 'UNKNOWN')
        order_id = order_result.get('orderId', 'N/A')
        logger.info(f"API /place_order: Order request sent. API Status: {order_status}, ID: {order_id}")

        # Rafraîchir l'historique en arrière-plan
        symbol = order_result.get('symbol')
        if symbol:
            threading.Thread(target=bot_core.refresh_order_history_via_rest, args=(symbol, 50), daemon=True).start()

        # Mise à jour état si MARKET BUY FILLED (pour UI rapide)
        if order_params['order_type'] == 'MARKET' and order_status == 'FILLED' and order_params['side'] == 'BUY':
            try:
                exec_qty = float(order_result.get('executedQty', 0))
                quote_qty = float(order_result.get('cummulativeQuoteQty', 0))
                if exec_qty > 0:
                    avg_price = quote_qty / exec_qty
                    entry_timestamp = order_result.get('transactTime', int(time.time() * 1000))
                    state_updates = {
                        "in_position": True,
                        "entry_details": {"order_id": order_id, "avg_price": avg_price, "quantity": exec_qty, "timestamp": entry_timestamp},
                        "open_order_id": None, "open_order_timestamp": None,
                    }
                    state_manager.update_state(state_updates)
                    state_manager.save_persistent_data()
                    threading.Thread(target=broadcast_state_update, daemon=True).start() # Broadcast async
                    logger.info(f"API /place_order: State updated for MARKET BUY fill (via REST).")
            except Exception as e: logger.error(f"API /place_order: Error processing MARKET fill: {e}", exc_info=True)

        return jsonify({"success": True, "message": f"Ordre {order_id} envoyé. Statut API: {order_status}", "order_details": order_result}), 200

    except Exception as e:
        logger.exception("API /place_order: Unexpected error calling place_order.")
        return jsonify({"success": False, "message": f"Erreur interne serveur: {e}"}), 500

# Exporter le Blueprint
__all__ = ['api_bp']
