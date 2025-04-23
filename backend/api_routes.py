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

# Utilitaires WebSocket et Handlers
from websocket_utils import broadcast_state_update
import websocket_handlers # Importer pour appeler execute_exit

# CORRECTION: Importer les fonctions nécessaires de order_utils au niveau du module
from utils.order_utils import format_quantity, format_price, get_min_notional, check_min_notional

# Config Logging (si log_queue est utilisé)
# from logging_config import log_queue # Décommenter si utilisé

import db

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
        # Récupérer config, ticker, historique via state_manager/config_manager
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
    """Retourne l'historique des ordres, filtré par stratégie si précisé."""
    try:
        strategy = request.args.get('strategy')
        history = state_manager.get_order_history(strategy)
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
        # Appelle execute_exit du handler dans un thread pour ne pas bloquer la réponse API
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

    # Clés requises de base
    required_keys = ["symbol", "side", "order_type"]
    if not all(key in data for key in required_keys):
        missing = [key for key in required_keys if key not in data]
        logger.error(f"API /place_order: Missing base data: {missing}")
        return jsonify({"success": False, "message": f"Données de base manquantes: {', '.join(missing)}"}), 400

    order_type = data["order_type"].upper()
    side = data["side"].upper()

    # Préparer les paramètres, vérifier les clés spécifiques au type
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
                elif "quantity" in data: # Permettre achat MARKET par quantité base aussi
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
            # Ajouter d'autres types si nécessaire (STOP_LOSS_LIMIT, etc.)
            raise ValueError(f"Order type '{order_type}' not supported by this API endpoint.")

        # --- Validation et Formatage avant appel API ---
        symbol_info = binance_client_wrapper.get_symbol_info(order_params["symbol"])
        if not symbol_info:
            raise ValueError(f"Cannot get symbol info for {order_params['symbol']}")

        # CORRECTION: Utiliser get_min_notional importé
        min_notional = get_min_notional(symbol_info)

        # Formater quantité et prix si nécessaire (en utilisant les fonctions importées)
        if "quantity" in order_params:
            formatted_qty = format_quantity(order_params["quantity"], symbol_info)
            if formatted_qty is None:
                raise ValueError(f"Invalid quantity after formatting: {order_params['quantity']}")
            order_params["quantity"] = formatted_qty # Utiliser la quantité formatée

        if "price" in order_params: # Pour LIMIT
            formatted_price = format_price(order_params["price"], symbol_info)
            if formatted_price is None:
                raise ValueError(f"Invalid price after formatting: {order_params['price']}")
            order_params["price"] = formatted_price # Utiliser le prix formaté

        # Vérifier Min Notional (en utilisant check_min_notional importé)
        check_price = order_params.get("price") # Prix LIMIT
        if not check_price and order_type == "MARKET": # Estimer prix pour MARKET
             ticker = binance_client_wrapper.get_symbol_ticker(order_params["symbol"])
             if ticker and ticker.get("price"):
                  check_price = Decimal(ticker["price"])
             else: logger.warning("Cannot check minNotional for MARKET order, price unavailable.")

        if "quantity" in order_params and check_price:
             if not check_min_notional(order_params["quantity"], check_price, min_notional):
                  raise ValueError(f"Order does not meet MIN_NOTIONAL ({min_notional}). Estimated: {order_params['quantity'] * check_price:.4f}")
        elif "quoteOrderQty" in order_params: # Pour MARKET BUY par quote
             if order_params["quoteOrderQty"] < min_notional:
                  raise ValueError(f"quoteOrderQty ({order_params['quoteOrderQty']}) is less than MIN_NOTIONAL ({min_notional}).")

        # --- Fin Validation et Formatage ---

        logger.info(f"API /place_order: Placing validated order via wrapper: {order_params}")
        # Lancer dans un thread pour ne pas bloquer la réponse API trop longtemps
        threading.Thread(target=websocket_handlers._execute_order_thread,
                         args=(order_params.copy(), "MANUAL_API"), # Utiliser une copie
                         daemon=True).start()

        return jsonify({"success": True, "message": f"Requête d'ordre {order_type} {side} envoyée (traitement asynchrone)."}), 202 # Accepted

    except (ValueError, InvalidOperation, TypeError) as e:
        logger.error(f"API /place_order: Validation Error: {e}")
        return jsonify({"success": False, "message": f"Erreur de validation: {e}"}), 400
    except Exception as e:
        logger.exception("API /place_order: Unexpected error during preparation or sending.")
        return jsonify({"success": False, "message": f"Erreur interne serveur: {e}"}), 500

@api_bp.route('/reset', methods=['POST'])
def reset_bot():
    """Réinitialise l’historique des ordres pour la stratégie sélectionnée."""
    try:
        data = request.get_json() or {}
        strategy = data.get('strategy') or state_manager.get_state('strategy') or 'SCALPING'
        db.reset_orders(strategy)
        state_manager.clear_order_history()  # Ajout : efface aussi l'historique en mémoire
        logger.info(f"API /reset: Historique des ordres réinitialisé pour la stratégie {strategy}.")
        broadcast_state_update()
        return jsonify({"success": True, "message": f"Historique réinitialisé pour {strategy}."})
    except Exception as e:
        logger.error(f"API /reset: Error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur lors du reset."}), 500

@api_bp.route('/stats')
def get_stats():
    """Retourne les statistiques pour la stratégie sélectionnée (calculées sur l'historique filtré)."""
    try:
        strategy = request.args.get('strategy') or state_manager.get_state('strategy') or 'SCALPING'
        history = state_manager.get_order_history(strategy)
        total = len(history)
        wins = 0
        losses = 0
        pnl = Decimal('0')
        pnl_sum = Decimal('0')
        pnl_count = 0
        for order in history:
            if order.get('side') == 'SELL' and order.get('status') == 'FILLED':
                perf = order.get('performance_pct')
                if perf:
                    try:
                        perf_val = Decimal(perf.replace('%','')) / 100 if '%' in str(perf) else Decimal(perf)
                        pnl += perf_val
                        pnl_sum += perf_val
                        pnl_count += 1
                        if perf_val > 0:
                            wins += 1
                        else:
                            losses += 1
                    except Exception:
                        pass
        winrate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
        avg_pnl = (pnl_sum / pnl_count * 100) if pnl_count > 0 else Decimal('0')
        stats = {
            'total_trades': total,
            'wins': wins,
            'losses': losses,
            'winrate': round(winrate, 2),
            'pnl_percent': round(pnl * 100, 2),
            'roi': round(pnl * 100, 2), # Ajouté pour compatibilité frontend
            'avg_pnl': round(avg_pnl, 2) # Ajouté pour compatibilité frontend
        }
        return jsonify(stats)
    except Exception as e:
        logger.error(f"API /stats: Error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Erreur lors du calcul des stats."}), 500

# Exporter le Blueprint
__all__ = ['api_bp']
