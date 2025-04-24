# /Users/davidmichels/Desktop/trading-bot/backend/api_routes.py
import logging
import time
import queue
from flask import Blueprint, jsonify, request, Response
from decimal import Decimal, InvalidOperation
import collections
import threading
import json # Add this import

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
        # Add active session ID to status
        status_data_serializable["active_session_id"] = state_manager.get_active_session_id()
        # History is no longer included here, frontend fetches based on session_id

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
@api_bp.route('/order_history') # MODIFIED: Takes session_id
def get_order_history():
    """Retourne l'historique des ordres pour une session_id donnée."""
    session_id_str = request.args.get('session_id')
    limit = request.args.get('limit', default=100, type=int)

    if not session_id_str:
        return jsonify({"success": False, "message": "Paramètre 'session_id' manquant."}), 400

    try:
        session_id = int(session_id_str)
        # Call db function directly using the parsed session_id
        history = db.get_order_history(session_id=session_id, limit=limit)
        return jsonify(history)
    except ValueError:
        return jsonify({"success": False, "message": "Paramètre 'session_id' doit être un entier."}), 400
    except Exception as e:
        logger.error(f"API /order_history?session_id={session_id_str}: Error: {e}", exc_info=True)
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

# --- DEPRECATED: /reset ---
# @api_bp.route('/reset', methods=['POST'])
# def reset_bot():
#     """DEPRECATED: Use session management endpoints instead."""
#     logger.warning("API /reset endpoint called (DEPRECATED). Use session management.")
#     return jsonify({"success": False, "message": "Endpoint /reset est obsolète. Utilisez la gestion de session."}), 410

# --- MODIFIED: /stats ---
@api_bp.route('/stats') # MODIFIED: Takes session_id
def get_stats():
    """Retourne les statistiques pour une session_id donnée."""
    session_id_str = request.args.get('session_id')

    if not session_id_str:
        return jsonify({"success": False, "message": "Paramètre 'session_id' manquant."}), 400

    try:
        session_id = int(session_id_str)
        # Call db function directly using the parsed session_id
        stats = db.get_stats(session_id=session_id)
        return jsonify(stats)
    except ValueError:
        return jsonify({"success": False, "message": "Paramètre 'session_id' doit être un entier."}), 400
    except Exception as e:
        logger.error(f"API /stats?session_id={session_id_str}: Error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur lors du calcul des stats depuis la DB."}), 500

# --- NEW Session Management Endpoints ---

@api_bp.route('/sessions', methods=['GET'])
def list_sessions_route():
    """Liste toutes les sessions enregistrées."""
    try:
        sessions = db.list_sessions()
        return jsonify(sessions)
    except Exception as e:
        logger.error(f"API /sessions (GET): Error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (liste sessions)."}), 500

@api_bp.route('/sessions', methods=['POST'])
def create_session_route():
    """Crée une nouvelle session de bot."""
    logger.info("API /sessions (POST): Request received to create new session.")
    data = request.get_json() or {}
    strategy = data.get('strategy') or config_manager.get_value('STRATEGY_TYPE', 'UNKNOWN')
    name = data.get('name') # Optional name from request

    # Optional: End current active session first?
    # current_active_session_id = state_manager.get_active_session_id()
    # if current_active_session_id:
    #     logger.info(f"API /sessions (POST): Ending previous active session {current_active_session_id}...")
    #     db.end_session(current_active_session_id, final_status='completed') # Or 'aborted'?

    try:
        # Get current config as JSON string
        current_config_dict = config_manager.get_config()
        config_json = json.dumps(current_config_dict, default=str) # Use default=str for Decimal etc.
        new_session_id = db.create_new_session(strategy=strategy, config_snapshot_json=config_json, name=name)
        if new_session_id:
            state_manager.set_active_session_id(new_session_id) # Set new session as active
            logger.info(f"API /sessions (POST): New session {new_session_id} created and set active.")
            # Optionally trigger initial history refresh here?
            # threading.Thread(target=bot_core.refresh_order_history_via_rest, args=(state_manager.get_state('symbol'), 200), daemon=True).start()
            # Return the details of the newly created session
            new_session_details = {"id": new_session_id, "strategy": strategy, "name": name or f"{strategy}_..."} # Simplified return
            return jsonify({"success": True, "message": "Nouvelle session créée.", "session": new_session_details}), 201
        else:
            logger.error("API /sessions (POST): Failed to create session in DB.")
            return jsonify({"success": False, "message": "Échec de la création de la session en base de données."}), 500
    except Exception as e:
        logger.error(f"API /sessions (POST): Error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (création session)."}), 500

@api_bp.route('/sessions/<int:session_id>', methods=['DELETE'])
def delete_session_route(session_id):
    """Supprime une session et ses ordres associés."""
    logger.warning(f"API /sessions DELETE: Request received for session ID: {session_id}")
    try:
        current_active_id = state_manager.get_active_session_id()
        delete_success = db.delete_session(session_id)
        if delete_success:
            logger.info(f"API /sessions DELETE: Session {session_id} deleted successfully.")
            if current_active_id == session_id:
                logger.warning(f"API /sessions DELETE: Deleted the active session ({session_id}). Clearing active session ID.")
                state_manager.set_active_session_id(None)
            # Optionally broadcast an update? Maybe just let frontend refresh lists.
            return jsonify({"success": True, "message": f"Session {session_id} supprimée."})
        else:
            logger.error(f"API /sessions DELETE: Failed to delete session {session_id} (not found or DB error).")
            return jsonify({"success": False, "message": f"Échec de la suppression de la session {session_id} (non trouvée?)."}), 404
    except Exception as e:
        logger.error(f"API /sessions DELETE: Error for session {session_id}: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (suppression session)."}), 500

@api_bp.route('/sessions/active', methods=['GET'])
def get_active_session_route():
    """Retourne l'ID de la session active actuelle."""
    try:
        active_id = state_manager.get_active_session_id()
        if active_id is not None:
            # Optionally fetch full details from DB if needed
            # session_details = db.get_session_details(active_id) # Assumes such a function exists
            return jsonify({"success": True, "active_session_id": active_id})
        else:
            return jsonify({"success": True, "active_session_id": None})
    except Exception as e:
        logger.error(f"API /sessions/active (GET): Error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur interne serveur (session active)."}), 500


# Exporter le Blueprint
__all__ = ['api_bp']
