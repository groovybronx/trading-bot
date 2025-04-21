# /Users/davidmichels/Desktop/trading-bot/backend/api_routes.py
import logging
import time
import queue
from flask import Blueprint, jsonify, request, Response
from decimal import Decimal, InvalidOperation
import collections # Pour le type deque
import threading

# MODIFIÉ: Importer les instances des managers
from state_manager import state_manager # Importe l'instance
from config_manager import config_manager, VALID_TIMEFRAMES

# MODIFIÉ: Importer les fonctions core start/stop
import bot_core

# --- AJOUT: Importer le wrapper pour place_order ---
import binance_client_wrapper
# --- FIN AJOUT ---

# Importer la queue de logs depuis le module logging
from logging_config import log_queue

# --- MODIFIÉ: Importer depuis websocket_utils ---
from websocket_utils import broadcast_state_update
# --- FIN MODIFIÉ ---

logger = logging.getLogger(__name__)

# Créer un Blueprint pour les routes API
api_bp = Blueprint('api', __name__)

# --- Routes API ---

@api_bp.route('/status')
def get_status():
    """Retourne l'état actuel du bot, la config et les dernières données temps réel."""
    try:
        status_data = state_manager.get_state()
        excluded_keys = {'main_thread', 'websocket_client', 'keepalive_thread'}
        status_data_serializable = {k: v for k, v in status_data.items() if k not in excluded_keys}
        status_data_serializable["config"] = config_manager.get_config()
        status_data_serializable["latest_book_ticker"] = state_manager.get_book_ticker()
        order_history = state_manager.get_order_history()
        status_data_serializable["order_history"] = order_history
        return jsonify(status_data_serializable)
    except Exception as e:
        logger.error(f"API /status: Erreur récupération état: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (état)."}), 500

@api_bp.route('/parameters', methods=['GET'])
def get_parameters():
    """Retourne la configuration actuelle du bot (sans clés API)."""
    try:
        current_config = config_manager.get_config()
        sensitive_keys = {"BINANCE_API_KEY", "BINANCE_API_SECRET"}
        config_to_send = {k: v for k, v in current_config.items() if k not in sensitive_keys}
        return jsonify(config_to_send)
    except Exception as e:
        logger.error(f"API /parameters (GET): Erreur récupération config: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (config)."}), 500

@api_bp.route('/parameters', methods=['POST'])
def set_parameters():
    """Met à jour les paramètres de configuration du bot après validation."""
    new_params = request.json
    if not new_params:
        return jsonify({"success": False, "message": "Aucun paramètre fourni."}), 400

    logger.info(f"API /parameters (POST): Tentative MAJ avec: {new_params}")
    try:
        success, message, restart_recommended = state_manager.update_config_values(new_params)

        if success:
            logger.info(f"API /parameters (POST): {message}")
            broadcast_state_update()
            return jsonify({"success": True, "message": message, "restart_recommended": restart_recommended})
        else:
            logger.error(f"API /parameters (POST): Échec validation/mise à jour: {message}")
            return jsonify({"success": False, "message": message}), 400

    except Exception as e:
        logger.error(f"API /parameters (POST): Erreur inattendue: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (MAJ params)."}), 500

@api_bp.route('/start', methods=['POST'])
def start_bot_route():
    """Route API pour démarrer le bot."""
    logger.info("API /start: Requête reçue.")
    try:
        success, message = bot_core.start_bot_core()
        status_code = 200 if success else 500
        if not success and "déjà" in message.lower(): status_code = 400
        return jsonify({"success": success, "message": message}), status_code
    except Exception as e:
        logger.error(f"API /start: Erreur inattendue: {e}", exc_info=True)
        try:
            state_manager.update_state({"status": "ERROR"})
            broadcast_state_update()
        except Exception as inner_e:
            logger.error(f"API /start: Erreur lors de la mise à jour/broadcast après exception: {inner_e}")
        return jsonify({"success": False, "message": "Erreur interne serveur (démarrage)."}), 500

@api_bp.route('/stop', methods=['POST'])
def stop_bot_route():
    """Route API pour arrêter le bot."""
    logger.info("API /stop: Requête reçue.")
    try:
        result = bot_core.stop_bot_core()
        if result is None:
            result = (False, "Erreur: stop_bot_core a retourné None.")
        success, message = result
        status_code = 200 if success else 400
        return jsonify({"success": success, "message": message}), status_code
    except Exception as e:
        logger.error(f"API /stop: Erreur inattendue: {e}", exc_info=True)
        try:
            state_manager.update_state({"status": "ERROR"})
            broadcast_state_update()
        except Exception as inner_e:
            logger.error(f"API /stop: Erreur lors de la mise à jour/broadcast après exception: {inner_e}")
        return jsonify({"success": False, "message": "Erreur interne serveur (arrêt)."}), 500

@api_bp.route('/order_history')
def get_order_history():
    """Retourne l'historique des ordres stocké."""
    try:
        history = state_manager.get_order_history()
        # Return the history list directly
        return jsonify(history)
    except Exception as e:
        logger.error(f"API /order_history: Erreur récupération historique: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (historique)."}), 500

@api_bp.route('/manual_exit', methods=['POST'])
def manual_exit_route():
    """Route API pour déclencher une sortie manuelle."""
    logger.info("API /manual_exit: Requête reçue.")
    try:
        current_pos = state_manager.get_state("in_position")
        if not current_pos:
             return jsonify({"success": False, "message": "Le bot n'est pas en position."}), 400

        logger.warning("API /manual_exit: Déclenchement sortie manuelle via API...")
        threading.Thread(target=bot_core.execute_exit, args=("Sortie Manuelle API",), daemon=True).start()
        return jsonify({"success": True, "message": "Requête de sortie manuelle initiée."}), 202
    except Exception as e:
        logger.error(f"API /manual_exit: Erreur inattendue: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (sortie manuelle)."}), 500

@api_bp.route('/place_order', methods=['POST'])
def handle_place_order():
    """
    Endpoint pour placer un ordre via l'API.
    Attend un JSON avec: symbol, side, order_type, quantity, [price, time_in_force]
    """
    request_start_time = time.monotonic() # Track request time
    logger.info("API /place_order: Requête reçue.")
    data = request.get_json()

    if not data:
        logger.error("API /place_order: Aucune donnée JSON reçue.")
        return jsonify({"success": False, "message": "Requête invalide (JSON manquant)."}), 400

    logger.debug(f"API /place_order: Données reçues: {data}")

    # Validate required fields
    required_keys = ["symbol", "side", "order_type", "quantity"]
    if not all(key in data for key in required_keys):
        missing = [key for key in required_keys if key not in data]
        logger.error(f"API /place_order: Données manquantes: {missing}")
        return jsonify({"success": False, "message": f"Données manquantes: {', '.join(missing)}"}), 400

    # Prepare parameters for the wrapper, removing None values
    order_params = {
        "symbol": data["symbol"],
        "side": data["side"],
        "order_type": data["order_type"],
        "quantity": data["quantity"],
        "price": data.get("price"), # Optional for LIMIT
        "time_in_force": data.get("time_in_force") # Optional for LIMIT
    }
    order_params = {k: v for k, v in order_params.items() if v is not None}

    # Validate price for LIMIT orders
    if order_params["order_type"] == 'LIMIT' and "price" not in order_params:
         logger.error("API /place_order: Prix manquant pour ordre LIMIT.")
         return jsonify({"success": False, "message": "Prix manquant pour ordre LIMIT."}), 400

    try:
        logger.debug("API /place_order: Calling binance_client_wrapper.place_order...")
        order_result = binance_client_wrapper.place_order(**order_params)
        logger.debug("API /place_order: binance_client_wrapper.place_order returned.")

        # Check if the order placement call itself failed
        if not order_result:
            logger.error("API /place_order: Échec placement ordre (wrapper a retourné None).")
            return jsonify({"success": False, "message": "Échec de la requête de placement d'ordre auprès de Binance (voir logs backend)."}), 500

        # Log the immediate result from the API
        order_status = order_result.get('status', 'UNKNOWN')
        order_id = order_result.get('orderId', 'N/A')
        logger.info(f"API /place_order: Requête d'ordre envoyée via wrapper. Résultat API: {order_status}")

        # --- *** MODIFIED: Trigger history refresh via REST in background *** ---
        symbol_from_result = order_result.get('symbol')
        if symbol_from_result:
            logger.debug(f"API /place_order: Triggering history refresh for {symbol_from_result} via REST...")
            # Run the refresh in a background thread to avoid blocking the response
            threading.Thread(target=bot_core.refresh_order_history_via_rest, args=(symbol_from_result, 50), daemon=True).start()
        else:
            logger.warning("API /place_order: Cannot trigger history refresh, symbol missing in order result.")
        # --- *** END MODIFIED *** ---

        # --- Specific Handling for Immediate MARKET BUY Fill via REST ---
        # This state update logic remains important for immediate UI feedback on position status
        order_type = order_result.get('type')
        order_side = order_result.get('side')
        if order_type == 'MARKET' and order_status == 'FILLED' and order_side == 'BUY':
            logger.info(f"API /place_order: Ordre MARKET BUY {order_id} FILLED via REST. Mise à jour état immédiate.")
            try:
                exec_qty = float(order_result.get('executedQty', 0))
                quote_qty = float(order_result.get('cummulativeQuoteQty', 0))
                if exec_qty > 0:
                    avg_price = quote_qty / exec_qty
                    entry_timestamp = order_result.get('transactTime', int(time.time() * 1000))

                    state_updates = {
                        "in_position": True,
                        "entry_details": {
                            "order_id": order_id, "avg_price": avg_price,
                            "quantity": exec_qty, "timestamp": entry_timestamp,
                        },
                        "open_order_id": None, # Clear any previous open order ID
                        "open_order_timestamp": None,
                    }

                    logger.debug(f"API /place_order: Attempting state_manager.update_state...")
                    update_start = time.monotonic()
                    state_manager.update_state(state_updates)
                    update_duration = time.monotonic() - update_start
                    logger.debug(f"API /place_order: state_manager.update_state finished (took {update_duration:.4f}s).")

                    # Save persistent data *after* state update
                    logger.debug(f"API /place_order: Attempting state_manager.save_persistent_data (for state)...")
                    save_start = time.monotonic()
                    state_manager.save_persistent_data()
                    save_duration = time.monotonic() - save_start
                    logger.debug(f"API /place_order: state_manager.save_persistent_data finished (took {save_duration:.4f}s).")

                    # Broadcast the state update in a separate thread
                    logger.debug(f"API /place_order: Starting state broadcast thread...")
                    broadcast_thread = threading.Thread(target=broadcast_state_update, daemon=True)
                    broadcast_thread.start()
                    logger.debug(f"API /place_order: State broadcast thread started.")

                    logger.info(f"API /place_order: État mis à jour (via REST): EN POSITION @ {avg_price:.4f}, Qty={exec_qty}")
                else:
                    logger.warning(f"API /place_order: Ordre MARKET BUY {order_id} FILLED via REST mais quantité nulle?")
            except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
                logger.error(f"API /place_order: Erreur traitement MARKET FILLED via REST {order_id}: {e}", exc_info=True)
        # --- End Specific Handling ---

        # Return success response with order details
        total_request_time = time.monotonic() - request_start_time
        logger.debug(f"API /place_order: Preparing to return JSON response (Total time: {total_request_time:.4f}s)...")
        return jsonify({"success": True, "message": f"Requête d'ordre {order_id} envoyée. Statut API: {order_status}", "order_details": order_result}), 200

    except Exception as e:
        logger.exception("API /place_order: Erreur inattendue lors de l'appel à place_order.")
        return jsonify({"success": False, "message": f"Erreur interne du serveur: {e}"}), 500

# Exporter le Blueprint
__all__ = ['api_bp']