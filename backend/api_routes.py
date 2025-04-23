# /Users/davidmichels/Desktop/trading-bot/backend/api_routes.py
import logging
import time
import queue
from flask import Blueprint, jsonify, request, Response
from decimal import Decimal, InvalidOperation
import collections
import threading

# Gestionnaires et Core
from manager.state_manager import state_manager
from manager.config_manager import config_manager, VALID_TIMEFRAMES
import bot_core

# Wrapper Client Binance
import binance_client_wrapper

# Utilitaires WebSocket et Handlers
from utils.websocket_utils import broadcast_state_update, broadcast_order_history_update # Import history update
import websocket_handlers

from utils.order_utils import format_quantity, format_price, get_min_notional, check_min_notional

# --- MODIFIED: Import DB ---
import db

logger = logging.getLogger(__name__)
api_bp = Blueprint('api', __name__)

# --- Routes API ---

@api_bp.route('/status')
def get_status():
    """Retourne l'état actuel, la config, ticker et historique (depuis DB)."""
    try:
        status_data = state_manager.get_state()
        excluded_keys = {'main_thread', 'websocket_client', 'keepalive_thread'}
        status_data_serializable = {k: v for k, v in status_data.items() if k not in excluded_keys}

        status_data_serializable["config"] = config_manager.get_config()
        status_data_serializable["latest_book_ticker"] = state_manager.get_book_ticker()
        # --- MODIFIED: Get history from state_manager (which gets it from DB) ---
        strategy = status_data_serializable.get("config", {}).get("STRATEGY_TYPE")
        status_data_serializable["order_history"] = state_manager.get_order_history(strategy=strategy)
        # --- End Modification ---

        return jsonify(status_data_serializable)
    except Exception as e:
        logger.error(f"API /status: Error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (état)."}), 500

# --- /parameters GET/POST (Unchanged) ---
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
        success, message, restart_recommended = state_manager.update_config_values(new_params)

        if success:
            logger.info(f"API /parameters (POST): {message}")
            # broadcast_state_update() # State update now saves and broadcasts
            return jsonify({"success": True, "message": message, "restart_recommended": restart_recommended})
        else:
            logger.error(f"API /parameters (POST): Validation/Update failed: {message}")
            return jsonify({"success": False, "message": message}), 400

    except Exception as e:
        logger.error(f"API /parameters (POST): Unexpected error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (MAJ params)."}), 500

# --- /start, /stop (Unchanged) ---
@api_bp.route('/start', methods=['POST'])
def start_bot_route():
    """Démarre le bot."""
    logger.info("API /start: Request received.")
    try:
        success, message = bot_core.start_bot_core()
        status_code = 200 if success else 500
        if not success and "déjà" in message.lower(): status_code = 400
        return jsonify({"success": success, "message": message}), status_code
    except Exception as e:
        logger.error(f"API /start: Unexpected error: {e}", exc_info=True)
        try:
            state_manager.update_state({"status": "ERROR"})
            # broadcast_state_update() # State update now saves and broadcasts
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
        status_code = 200 if success else 400
        return jsonify({"success": success, "message": message}), status_code
    except Exception as e:
        logger.error(f"API /stop: Unexpected error: {e}", exc_info=True)
        try:
            state_manager.update_state({"status": "ERROR"})
            # broadcast_state_update() # State update now saves and broadcasts
        except Exception as inner_e: logger.error(f"API /stop: Error updating/broadcasting after exception: {inner_e}")
        return jsonify({"success": False, "message": "Erreur interne serveur (arrêt)."}), 500

# --- MODIFIED: /order_history ---
@api_bp.route('/order_history')
def get_order_history():
    """Retourne l'historique des ordres depuis la DB, filtré par stratégie si précisé."""
    try:
        strategy = request.args.get('strategy') # Optional filter
        limit = request.args.get('limit', default=100, type=int) # Optional limit
        # Get history via state_manager which calls db.get_order_history
        history = state_manager.get_order_history(strategy=strategy, limit=limit)
        return jsonify(history)
    except Exception as e:
        logger.error(f"API /order_history: Error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (historique)."}), 500

# --- /manual_exit, /place_order (Unchanged logic, but state updates broadcast automatically) ---
@api_bp.route('/manual_exit', methods=['POST'])
def manual_exit_route():
    """Déclenche une sortie manuelle."""
    logger.info("API /manual_exit: Request received.")
    try:
        if not state_manager.get_state("in_position"):
             return jsonify({"success": False, "message": "Le bot n'est pas en position."}), 400

        logger.warning("API /manual_exit: Triggering manual exit via API...")
        threading.Thread(target=websocket_handlers.execute_exit, args=("Sortie Manuelle API",), daemon=True).start()
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

    required_keys = ["symbol", "side", "order_type"]
    if not all(key in data for key in required_keys):
        missing = [key for key in required_keys if key not in data]
        logger.error(f"API /place_order: Missing base data: {missing}")
        return jsonify({"success": False, "message": f"Données de base manquantes: {', '.join(missing)}"}), 400

    order_type = data["order_type"].upper()
    side = data["side"].upper()

    order_params = {
        "symbol": data["symbol"],
        "side": side,
        "order_type": order_type,
    }

    try:
        if order_type == "MARKET":
            if side == "BUY":
                if "quoteOrderQty" in data:
                    order_params["quoteOrderQty"] = Decimal(str(data["quoteOrderQty"]))
                elif "quantity" in data:
                    order_params["quantity"] = Decimal(str(data["quantity"]))
                else:
                    raise ValueError("MARKET BUY requires 'quoteOrderQty' or 'quantity'.")
            else: # SELL
                if "quantity" not in data:
                    raise ValueError("MARKET SELL requires 'quantity'.")
                order_params["quantity"] = Decimal(str(data["quantity"]))
        elif order_type == "LIMIT":
            if "quantity" not in data or "price" not in data:
                raise ValueError("LIMIT order requires 'quantity' and 'price'.")
            order_params["quantity"] = Decimal(str(data["quantity"]))
            order_params["price"] = Decimal(str(data["price"]))
            if "time_in_force" in data:
                order_params["time_in_force"] = data["time_in_force"]
        else:
            raise ValueError(f"Order type '{order_type}' not supported by this API endpoint.")

        symbol_info = binance_client_wrapper.get_symbol_info(order_params["symbol"])
        if not symbol_info:
            raise ValueError(f"Cannot get symbol info for {order_params['symbol']}")

        min_notional = get_min_notional(symbol_info)

        if "quantity" in order_params:
            formatted_qty = format_quantity(order_params["quantity"], symbol_info)
            if formatted_qty is None:
                raise ValueError(f"Invalid quantity after formatting: {order_params['quantity']}")
            order_params["quantity"] = formatted_qty

        if "price" in order_params:
            formatted_price = format_price(order_params["price"], symbol_info)
            if formatted_price is None:
                raise ValueError(f"Invalid price after formatting: {order_params['price']}")
            order_params["price"] = formatted_price

        check_price = order_params.get("price")
        if not check_price and order_type == "MARKET":
             ticker = binance_client_wrapper.get_symbol_ticker(order_params["symbol"])
             if ticker and ticker.get("price"): check_price = Decimal(ticker["price"])
             else: logger.warning("Cannot check minNotional for MARKET order, price unavailable.")

        if "quantity" in order_params and check_price:
             if not check_min_notional(order_params["quantity"], check_price, min_notional):
                  raise ValueError(f"Order does not meet MIN_NOTIONAL ({min_notional}). Estimated: {order_params['quantity'] * check_price:.4f}")
        elif "quoteOrderQty" in order_params:
             if order_params["quoteOrderQty"] < min_notional:
                  raise ValueError(f"quoteOrderQty ({order_params['quoteOrderQty']}) is less than MIN_NOTIONAL ({min_notional}).")

        logger.info(f"API /place_order: Placing validated order via wrapper: {order_params}")
        threading.Thread(target=websocket_handlers._execute_order_thread,
                         args=(order_params.copy(), "MANUAL_API"),
                         daemon=True).start()

        return jsonify({"success": True, "message": f"Requête d'ordre {order_type} {side} envoyée (traitement asynchrone)."}), 202

    except (ValueError, InvalidOperation, TypeError) as e:
        logger.error(f"API /place_order: Validation Error: {e}")
        return jsonify({"success": False, "message": f"Erreur de validation: {e}"}), 400
    except Exception as e:
        logger.exception("API /place_order: Unexpected error during preparation or sending.")
        return jsonify({"success": False, "message": f"Erreur interne serveur: {e}"}), 500

# --- MODIFIED: /reset ---
@api_bp.route('/reset', methods=['POST'])
def reset_bot():
    """Réinitialise l’historique des ordres dans la DB pour la stratégie sélectionnée."""
    try:
        data = request.get_json() or {}
        # Determine strategy: from request, or current state, or default
        strategy = data.get('strategy') or state_manager.get_state('strategy') or config_manager.get_value('STRATEGY_TYPE', 'SCALPING')

        # Call DB reset
        reset_success = db.reset_orders(strategy)

        if reset_success:
            logger.info(f"API /reset: Historique des ordres réinitialisé dans la DB pour la stratégie {strategy}.")
            # Broadcast the (now empty) history
            broadcast_order_history_update()
            return jsonify({"success": True, "message": f"Historique réinitialisé pour {strategy}."})
        else:
            logger.error(f"API /reset: Failed to reset history in DB for strategy {strategy}.")
            return jsonify({"success": False, "message": f"Erreur lors du reset pour {strategy}."}), 500

    except Exception as e:
        logger.error(f"API /reset: Error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne lors du reset."}), 500

# --- MODIFIED: /stats ---
@api_bp.route('/stats')
def get_stats():
    """Retourne les statistiques depuis la DB pour la stratégie sélectionnée."""
    try:
        # Determine strategy: from request arg, or current state, or default
        strategy = request.args.get('strategy') or state_manager.get_state('strategy') or config_manager.get_value('STRATEGY_TYPE', 'SCALPING')

        # Call db.get_stats directly
        stats = db.get_stats(strategy)

        return jsonify(stats)
    except Exception as e:
        logger.error(f"API /stats: Error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur lors du calcul des stats depuis la DB."}), 500

# Exporter le Blueprint
__all__ = ['api_bp']
