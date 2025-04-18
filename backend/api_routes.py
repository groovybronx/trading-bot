# /Users/davidmichels/Desktop/trading-bot/backend/api_routes.py
import logging
import time
import queue
from flask import Blueprint, jsonify, request, Response

# Importer état, config, locks
from state_manager import bot_state, config_lock, latest_price_queue, kline_history, kline_history_lock
from config_manager import bot_config, VALID_TIMEFRAMES
# Importer les fonctions core start/stop
import bot_core
# Importer la queue de logs depuis le module logging
from logging_config import log_queue
# Importer collections pour le type deque
import collections

logger = logging.getLogger()

# Créer un Blueprint pour les routes API
api_bp = Blueprint('api', __name__)

# --- Routes API ---

@api_bp.route('/status')
def get_status():
    """Retourne l'état actuel du bot et le dernier prix."""
    status_data_to_send = {}
    latest_price = 0.0

    # Lire dernier prix (non bloquant)
    try:
        last_price_item = None
        while not latest_price_queue.empty(): # Vider pour avoir le plus récent
            last_price_item = latest_price_queue.get_nowait()
        if last_price_item is not None:
            latest_price = last_price_item
        # Si la queue était vide, essayer de récupérer la dernière valeur mise (si elle existe)
        elif latest_price_queue.maxsize == 1 and not latest_price_queue.empty():
             try: latest_price = latest_price_queue.queue[0]
             except IndexError: pass

    except queue.Empty: pass
    except Exception as q_err: logger.error(f"API /status: Erreur lecture queue prix: {q_err}")

    # Copier l'état sous verrou
    with config_lock:
        # Exclure les objets non sérialisables/internes
        excluded_keys = {'main_thread', 'websocket_manager', 'keepalive_thread'}
        status_data_to_send = {k: v for k, v in bot_state.items() if k not in excluded_keys}

    status_data_to_send["current_price"] = latest_price
    return jsonify(status_data_to_send)

@api_bp.route('/parameters', methods=['GET'])
def get_parameters():
    """Retourne la configuration actuelle du bot."""
    with config_lock:
        current_config = bot_config.copy()
    return jsonify(current_config)

@api_bp.route('/parameters', methods=['POST'])
def set_parameters():
    """Met à jour les paramètres de configuration du bot."""
    new_params = request.json
    if not new_params:
        return jsonify({"success": False, "message": "Aucun paramètre fourni."}), 400

    logger.info(f"API /parameters: Tentative MAJ: {new_params}")
    restart_recommended = False
    validated_params = {}
    error_message = None

    with config_lock: # Verrouiller pendant la validation et la mise à jour
        current_tf = bot_config["TIMEFRAME_STR"]
        current_required_limit = bot_state["required_klines"]

        try:
            # --- Validation --- (Reprise de l'ancien code)
            new_tf = str(new_params.get("TIMEFRAME_STR", current_tf))
            if new_tf not in VALID_TIMEFRAMES: raise ValueError(f"TIMEFRAME_STR invalide: {new_tf}")
            validated_params["TIMEFRAME_STR"] = new_tf
            if new_tf != current_tf: restart_recommended = True

            validated_params["RISK_PER_TRADE"] = float(new_params.get("RISK_PER_TRADE", bot_config["RISK_PER_TRADE"]))
            if not (0 < validated_params["RISK_PER_TRADE"] < 1): raise ValueError("RISK_PER_TRADE doit être > 0 et < 1")
            # ... (ajouter toutes les autres validations comme dans bot.py original) ...
            validated_params["CAPITAL_ALLOCATION"] = float(new_params.get("CAPITAL_ALLOCATION", bot_config["CAPITAL_ALLOCATION"]))
            if not (0 < validated_params["CAPITAL_ALLOCATION"] <= 1): raise ValueError("CAPITAL_ALLOCATION doit être > 0 et <= 1")
            validated_params["STOP_LOSS_PERCENTAGE"] = float(new_params.get("STOP_LOSS_PERCENTAGE", bot_config["STOP_LOSS_PERCENTAGE"]))
            if not (0 < validated_params["STOP_LOSS_PERCENTAGE"] < 1): raise ValueError("STOP_LOSS_PERCENTAGE doit être > 0 et < 1")
            validated_params["TAKE_PROFIT_PERCENTAGE"] = float(new_params.get("TAKE_PROFIT_PERCENTAGE", bot_config["TAKE_PROFIT_PERCENTAGE"]))
            if not (0 < validated_params["TAKE_PROFIT_PERCENTAGE"] < 1): raise ValueError("TAKE_PROFIT_PERCENTAGE doit être > 0 et < 1")
            validated_params["EMA_SHORT_PERIOD"] = int(new_params.get("EMA_SHORT_PERIOD", bot_config["EMA_SHORT_PERIOD"]))
            if validated_params["EMA_SHORT_PERIOD"] <= 0: raise ValueError("EMA_SHORT_PERIOD doit être > 0")
            validated_params["EMA_LONG_PERIOD"] = int(new_params.get("EMA_LONG_PERIOD", bot_config["EMA_LONG_PERIOD"]))
            if validated_params["EMA_LONG_PERIOD"] <= validated_params["EMA_SHORT_PERIOD"]: raise ValueError("EMA_LONG_PERIOD doit être > EMA_SHORT_PERIOD")
            validated_params["EMA_FILTER_PERIOD"] = int(new_params.get("EMA_FILTER_PERIOD", bot_config["EMA_FILTER_PERIOD"]))
            if validated_params["EMA_FILTER_PERIOD"] <= 0: raise ValueError("EMA_FILTER_PERIOD doit être > 0")
            validated_params["RSI_PERIOD"] = int(new_params.get("RSI_PERIOD", bot_config["RSI_PERIOD"]))
            if validated_params["RSI_PERIOD"] <= 1: raise ValueError("RSI_PERIOD doit être > 1")
            validated_params["RSI_OVERBOUGHT"] = int(new_params.get("RSI_OVERBOUGHT", bot_config["RSI_OVERBOUGHT"]))
            if not (50 < validated_params["RSI_OVERBOUGHT"] <= 100): raise ValueError("RSI_OB > 50 et <= 100")
            validated_params["RSI_OVERSOLD"] = int(new_params.get("RSI_OVERSOLD", bot_config["RSI_OVERSOLD"]))
            if not (0 <= validated_params["RSI_OVERSOLD"] < 50): raise ValueError("RSI_OS >= 0 et < 50")
            if validated_params["RSI_OVERSOLD"] >= validated_params["RSI_OVERBOUGHT"]: raise ValueError("RSI_OS < RSI_OB")
            validated_params["VOLUME_AVG_PERIOD"] = int(new_params.get("VOLUME_AVG_PERIOD", bot_config["VOLUME_AVG_PERIOD"]))
            if validated_params["VOLUME_AVG_PERIOD"] <= 0: raise ValueError("VOL_AVG > 0")
            validated_params["USE_EMA_FILTER"] = bool(new_params.get("USE_EMA_FILTER", bot_config["USE_EMA_FILTER"]))
            validated_params["USE_VOLUME_CONFIRMATION"] = bool(new_params.get("USE_VOLUME_CONFIRMATION", bot_config["USE_VOLUME_CONFIRMATION"]))
            # --- Fin Validations ---

            # Recalculer required_limit
            new_periods = [validated_params["EMA_LONG_PERIOD"], validated_params["RSI_PERIOD"]]
            if validated_params["USE_EMA_FILTER"]: new_periods.append(validated_params["EMA_FILTER_PERIOD"])
            if validated_params["USE_VOLUME_CONFIRMATION"]: new_periods.append(validated_params["VOLUME_AVG_PERIOD"])
            new_required_limit = max(new_periods) + 5
            if new_required_limit != current_required_limit: restart_recommended = True

            # --- Mise à jour ---
            bot_config.update(validated_params)
            bot_state["timeframe"] = bot_config["TIMEFRAME_STR"] # Mettre à jour aussi dans l'état
            bot_state["required_klines"] = new_required_limit

            # Ajuster la taille du deque kline_history si nécessaire
            with kline_history_lock:
                if kline_history.maxlen != new_required_limit:
                    logger.info(f"API /parameters: MAJ taille historique klines de {kline_history.maxlen} à {new_required_limit}")
                    # Créer un nouveau deque avec la bonne taille et les anciennes données
                    current_data = list(kline_history)
                    # Remplacer l'ancien deque par le nouveau
                    # Note: Il faut réassigner la variable globale importée
                    # Ceci est un peu délicat en Python. Une meilleure approche serait une classe StateManager.
                    # Pour l'instant, on modifie directement l'objet importé.
                    globals()['kline_history'] = collections.deque(current_data, maxlen=new_required_limit)


        except (ValueError, TypeError) as e:
            error_message = f"Paramètres invalides: {e}"
            logger.error(f"API /parameters: {error_message}")
            # Pas de mise à jour si erreur

    # Réponse en dehors du lock
    if error_message:
        return jsonify({"success": False, "message": error_message}), 400
    else:
        logger.info("API /parameters: Paramètres mis à jour avec succès.")
        message = "Paramètres mis à jour."
        if restart_recommended:
            message += " Redémarrage du bot conseillé pour appliquer changements (timeframe/périodes indicateurs)."
        return jsonify({"success": True, "message": message})


@api_bp.route('/start', methods=['POST'])
def start_bot_route():
    """Route API pour démarrer le bot."""
    logger.info("API /start: Requête reçue.")

    # S'assurer que le bot est bien arrêté avant de démarrer (nettoyage)
    with config_lock:
        is_running = bot_state.get("main_thread") and bot_state["main_thread"].is_alive()
    if is_running:
         logger.warning("API /start: Tentative de démarrage alors que le bot est déjà en cours. Arrêt préalable...")
         success_stop, msg_stop = bot_core.stop_bot_core()
         if not success_stop and "déjà arrêté" not in msg_stop: # Si l'arrêt échoue (et pas parce qu'il était déjà arrêté)
              logger.error(f"API /start: Échec de l'arrêt préalable: {msg_stop}")
              return jsonify({"success": False, "message": f"Échec de l'arrêt préalable: {msg_stop}"}), 500
         time.sleep(1) # Laisser le temps au nettoyage

    # Démarrer le bot via la fonction core
    success, message = bot_core.start_bot_core()
    status_code = 200 if success else 500
    return jsonify({"success": success, "message": message}), status_code

@api_bp.route('/stop', methods=['POST'])
def stop_bot_route():
    """Route API pour arrêter le bot."""
    logger.info("API /stop: Requête reçue.")
    # Arrêter le bot via la fonction core
    success, message = bot_core.stop_bot_core()
    status_code = 200 if success else (400 if "déjà arrêté" in message else 500)
    return jsonify({"success": success, "message": message}), status_code


@api_bp.route('/stream_logs')
def stream_logs():
    """Route SSE pour streamer les logs vers le frontend."""
    def generate():
        # Envoyer un message initial
        yield f"data: Connexion au flux de logs établie.\n\n"
        logger.info("API /stream_logs: Client connecté.")
        try:
            while True:
                try:
                    # Attendre un log de la queue (avec timeout pour keep-alive)
                    log_entry = log_queue.get(timeout=1)
                    yield f"data: {log_entry}\n\n"
                    log_queue.task_done() # Marquer comme traité
                except queue.Empty:
                    # Envoyer un commentaire keep-alive si pas de log
                    yield ": keep-alive\n\n"
                    continue
        except GeneratorExit:
            # Le client s'est déconnecté
            logger.info("API /stream_logs: Client déconnecté.")
        finally:
            # Nettoyage si nécessaire (ex: retirer le handler?) - Pas forcément utile ici
            pass

    # Créer la réponse SSE
    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no' # Important pour Nginx/proxy
    return response

@api_bp.route('/order_history')
def get_order_history():
    """Retourne l'historique des ordres stocké en mémoire."""
    with config_lock:
        # Copier et trier l'historique (du plus récent au plus ancien)
        history_copy = sorted(
            list(bot_state.get('order_history', [])),
            key=lambda x: x.get('timestamp', 0),
            reverse=True
        )
    return jsonify(history_copy)

# Exporter le Blueprint
__all__ = ['api_bp']
