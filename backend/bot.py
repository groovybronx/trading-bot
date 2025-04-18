import logging
import queue
import threading
import time
import json
import os
from typing import Optional, Dict, Any, List

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from binance.client import Client as BinanceClient # Import direct pour constantes KLINE_INTERVAL_*
from binance.exceptions import BinanceAPIException, BinanceRequestException

# Importer les modules locaux
import config # Pour les clés API et certains defaults
import strategy # Logique de trading
import binance_client_wrapper # Accès à l'API Binance

# --- Configuration du Logging ---
log_queue = queue.Queue()

class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
    def emit(self, record):
        if record.levelno >= logging.INFO:
            log_entry = self.format(record)
            self.log_queue.put(log_entry)

log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_level = logging.INFO
stream_handler = logging.StreamHandler(); stream_handler.setFormatter(log_formatter)
queue_handler = QueueHandler(log_queue); queue_handler.setFormatter(log_formatter)
logger = logging.getLogger(); logger.setLevel(log_level)
if logger.hasHandlers(): logger.handlers.clear()
logger.addHandler(stream_handler); logger.addHandler(queue_handler)

# --- Constantes et Configuration ---
# Utiliser les valeurs de config.py comme base, mais bot_config sera la référence modifiable
SYMBOL = getattr(config, 'SYMBOL', 'BTCUSDT')
VALID_TIMEFRAMES = ['1s', '1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']
TIMEFRAME_CONSTANT_MAP = {
    '1s': BinanceClient.KLINE_INTERVAL_1SECOND, '1m': BinanceClient.KLINE_INTERVAL_1MINUTE,
    '3m': BinanceClient.KLINE_INTERVAL_3MINUTE, '5m': BinanceClient.KLINE_INTERVAL_5MINUTE,
    '15m': BinanceClient.KLINE_INTERVAL_15MINUTE, '30m': BinanceClient.KLINE_INTERVAL_30MINUTE,
    '1h': BinanceClient.KLINE_INTERVAL_1HOUR, '2h': BinanceClient.KLINE_INTERVAL_2HOUR,
    '4h': BinanceClient.KLINE_INTERVAL_4HOUR, '6h': BinanceClient.KLINE_INTERVAL_6HOUR,
    '8h': BinanceClient.KLINE_INTERVAL_8HOUR, '12h': BinanceClient.KLINE_INTERVAL_12HOUR,
    '1d': BinanceClient.KLINE_INTERVAL_1DAY, '3d': BinanceClient.KLINE_INTERVAL_3DAY,
    '1w': BinanceClient.KLINE_INTERVAL_1WEEK, '1M': BinanceClient.KLINE_INTERVAL_1MONTH,
}

config_lock = threading.Lock() # Lock pour bot_config et bot_state

# Configuration modifiable du bot (initialisée depuis config.py)
bot_config = {
    "TIMEFRAME_STR": getattr(config, 'TIMEFRAME', '5m'),
    "RISK_PER_TRADE": getattr(config, 'RISK_PER_TRADE', 0.01),
    "CAPITAL_ALLOCATION": getattr(config, 'CAPITAL_ALLOCATION', 1.0),
    "STOP_LOSS_PERCENTAGE": getattr(config, 'STOP_LOSS_PERCENTAGE', 0.02), # Ajouté ici
    "EMA_SHORT_PERIOD": getattr(config, 'EMA_SHORT_PERIOD', 9),
    "EMA_LONG_PERIOD": getattr(config, 'EMA_LONG_PERIOD', 21),
    "EMA_FILTER_PERIOD": getattr(config, 'EMA_FILTER_PERIOD', 50),
    "RSI_PERIOD": getattr(config, 'RSI_PERIOD', 14),
    "RSI_OVERBOUGHT": getattr(config, 'RSI_OVERBOUGHT', 75),
    "RSI_OVERSOLD": getattr(config, 'RSI_OVERSOLD', 25),
    "VOLUME_AVG_PERIOD": getattr(config, 'VOLUME_AVG_PERIOD', 20),
    "USE_EMA_FILTER": getattr(config, 'USE_EMA_FILTER', True),
    "USE_VOLUME_CONFIRMATION": getattr(config, 'USE_VOLUME_CONFIRMATION', False),
}

# --- État Global du Bot (Persistant) ---
DATA_FILENAME = "bot_data.json"
bot_state = { # État par défaut si aucun fichier n'est chargé
    "status": "Arrêté",
    "in_position": False,
    "available_balance": 0.0, # Sera mis à jour au démarrage
    "current_price": 0.0,
    "symbol_quantity": 0.0,   # Sera mis à jour au démarrage
    "base_asset": "",         # Sera déterminé au démarrage
    "quote_asset": "USDT",    # Sera déterminé au démarrage
    "symbol": SYMBOL,
    "timeframe": bot_config["TIMEFRAME_STR"], # Sera mis à jour depuis bot_config
    "thread": None,
    "stop_requested": False,
    "entry_details": None,    # { 'order_id': ..., 'avg_price': ..., 'quantity': ..., 'timestamp': ... }
    "order_history": [],      # Liste des ordres simplifiés
    "max_history_length": 100 # Limite de l'historique en mémoire
}

# --- Fonctions de Persistance ---
def save_data():
    """Sauvegarde l'état pertinent et l'historique dans un fichier JSON."""
    with config_lock:
        data_to_save = {
            "state": {
                "in_position": bot_state.get("in_position", False),
                "entry_details": bot_state.get("entry_details", None)
            },
            "history": list(bot_state.get("order_history", []))
        }
    try:
        with open(DATA_FILENAME, 'w') as f:
            json.dump(data_to_save, f, indent=4)
        logger.debug(f"Données sauvegardées dans {DATA_FILENAME}")
        return True
    except IOError as e:
        logger.error(f"Erreur IO lors de la sauvegarde dans {DATA_FILENAME}: {e}")
        return False
    except Exception as e:
        logger.exception(f"Erreur inattendue lors de la sauvegarde des données: {e}")
        return False

def load_data() -> Optional[Dict[str, Any]]:
    """Charge l'état et l'historique depuis le fichier JSON, si existant."""
    if not os.path.exists(DATA_FILENAME):
        logger.info(f"Fichier de données {DATA_FILENAME} non trouvé. Démarrage avec état initial.")
        return None
    try:
        with open(DATA_FILENAME, 'r') as f:
            loaded_data = json.load(f)
        logger.info(f"Données chargées depuis {DATA_FILENAME}")
        return loaded_data
    except (IOError, json.JSONDecodeError) as e:
        logger.error(f"Erreur lors du chargement/décodage de {DATA_FILENAME}: {e}. Utilisation de l'état initial.")
        return None
    except Exception as e:
        logger.exception(f"Erreur inattendue lors du chargement des données: {e}")
        return None

# --- Fonctions Utilitaires ---
def interval_to_seconds(interval_str: str) -> int:
    """Convertit une chaîne d'intervalle (ex: '1m', '1h') en secondes."""
    try:
        unit = interval_str[-1].lower()
        value = int(interval_str[:-1])
        if unit == 's': return value
        elif unit == 'm': return value * 60
        elif unit == 'h': return value * 3600
        elif unit == 'd': return value * 86400
        elif unit == 'w': return value * 604800
        elif unit == 'M': return value * 2592000 # Approximation 30 jours
        else: logger.warning(f"Intervalle non reconnu pour conversion secondes: {interval_str}"); return 0
    except (IndexError, ValueError, TypeError):
        logger.warning(f"Format d'intervalle invalide pour conversion secondes: {interval_str}"); return 0

# --- Flask App ---
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Routes API ---
@app.route('/status')
def get_status():
    """Retourne le statut actuel du bot."""
    with config_lock:
        # Retourner une copie pour éviter les modifications pendant la sérialisation JSON
        status_data = {k: v for k, v in bot_state.items() if k not in ['thread', 'stop_requested']}
    return jsonify(status_data)

@app.route('/parameters', methods=['GET'])
def get_parameters():
    """Retourne les paramètres de configuration actuels du bot."""
    with config_lock:
        current_config = bot_config.copy()
    return jsonify(current_config)

@app.route('/parameters', methods=['POST'])
def set_parameters():
    """Met à jour les paramètres de configuration du bot."""
    global bot_config # On modifie la config globale
    new_params = request.json
    if not new_params:
        return jsonify({"success": False, "message": "Aucun paramètre fourni."}), 400

    logger.info(f"Tentative de mise à jour des paramètres: {new_params}")
    restart_recommended = False
    validated_params = {}
    current_timeframe = bot_config["TIMEFRAME_STR"] # Sauvegarder avant modif

    try:
        # Valider chaque paramètre (type, bornes, etc.)
        new_timeframe = str(new_params.get("TIMEFRAME_STR", current_timeframe))
        if new_timeframe not in VALID_TIMEFRAMES: raise ValueError(f"TIMEFRAME_STR invalide: {new_timeframe}")
        validated_params["TIMEFRAME_STR"] = new_timeframe
        if new_timeframe != current_timeframe: restart_recommended = True

        # --- Validation des autres paramètres ---
        validated_params["RISK_PER_TRADE"] = float(new_params.get("RISK_PER_TRADE", bot_config["RISK_PER_TRADE"]))
        if not (0 < validated_params["RISK_PER_TRADE"] < 1): raise ValueError("RISK_PER_TRADE doit être > 0 et < 1")

        validated_params["CAPITAL_ALLOCATION"] = float(new_params.get("CAPITAL_ALLOCATION", bot_config["CAPITAL_ALLOCATION"]))
        if not (0 < validated_params["CAPITAL_ALLOCATION"] <= 1): raise ValueError("CAPITAL_ALLOCATION doit être > 0 et <= 1")

        validated_params["STOP_LOSS_PERCENTAGE"] = float(new_params.get("STOP_LOSS_PERCENTAGE", bot_config["STOP_LOSS_PERCENTAGE"]))
        if not (0 < validated_params["STOP_LOSS_PERCENTAGE"] < 1): raise ValueError("STOP_LOSS_PERCENTAGE doit être > 0 et < 1")

        validated_params["EMA_SHORT_PERIOD"] = int(new_params.get("EMA_SHORT_PERIOD", bot_config["EMA_SHORT_PERIOD"]))
        if validated_params["EMA_SHORT_PERIOD"] <= 0: raise ValueError("EMA_SHORT_PERIOD doit être > 0")

        validated_params["EMA_LONG_PERIOD"] = int(new_params.get("EMA_LONG_PERIOD", bot_config["EMA_LONG_PERIOD"]))
        if validated_params["EMA_LONG_PERIOD"] <= validated_params["EMA_SHORT_PERIOD"]: raise ValueError("EMA_LONG_PERIOD doit être > EMA_SHORT_PERIOD")

        validated_params["EMA_FILTER_PERIOD"] = int(new_params.get("EMA_FILTER_PERIOD", bot_config["EMA_FILTER_PERIOD"]))
        if validated_params["EMA_FILTER_PERIOD"] <= 0: raise ValueError("EMA_FILTER_PERIOD doit être > 0")

        validated_params["RSI_PERIOD"] = int(new_params.get("RSI_PERIOD", bot_config["RSI_PERIOD"]))
        if validated_params["RSI_PERIOD"] <= 1: raise ValueError("RSI_PERIOD doit être > 1")

        validated_params["RSI_OVERBOUGHT"] = int(new_params.get("RSI_OVERBOUGHT", bot_config["RSI_OVERBOUGHT"]))
        if not (50 < validated_params["RSI_OVERBOUGHT"] <= 100): raise ValueError("RSI_OVERBOUGHT doit être > 50 et <= 100")

        validated_params["RSI_OVERSOLD"] = int(new_params.get("RSI_OVERSOLD", bot_config["RSI_OVERSOLD"]))
        if not (0 <= validated_params["RSI_OVERSOLD"] < 50): raise ValueError("RSI_OVERSOLD doit être >= 0 et < 50")
        if validated_params["RSI_OVERSOLD"] >= validated_params["RSI_OVERBOUGHT"]: raise ValueError("RSI_OVERSOLD doit être < RSI_OVERBOUGHT")

        validated_params["VOLUME_AVG_PERIOD"] = int(new_params.get("VOLUME_AVG_PERIOD", bot_config["VOLUME_AVG_PERIOD"]))
        if validated_params["VOLUME_AVG_PERIOD"] <= 0: raise ValueError("VOLUME_AVG_PERIOD doit être > 0")

        validated_params["USE_EMA_FILTER"] = bool(new_params.get("USE_EMA_FILTER", bot_config["USE_EMA_FILTER"]))
        validated_params["USE_VOLUME_CONFIRMATION"] = bool(new_params.get("USE_VOLUME_CONFIRMATION", bot_config["USE_VOLUME_CONFIRMATION"]))
        # --- Fin Validation ---

    except (ValueError, TypeError) as e:
        logger.error(f"Erreur de validation des paramètres: {e}")
        return jsonify({"success": False, "message": f"Paramètres invalides: {e}"}), 400

    # Appliquer les paramètres validés
    with config_lock:
        bot_config.update(validated_params)
        # Mettre à jour aussi le timeframe dans bot_state pour l'affichage immédiat
        bot_state["timeframe"] = bot_config["TIMEFRAME_STR"]
    logger.info("Paramètres mis à jour avec succès.")

    # Pas besoin de mettre à jour les globales de strategy.py ici

    message = "Paramètres mis à jour."
    if restart_recommended:
        message += " Un redémarrage du bot est conseillé pour appliquer le nouveau timeframe."
    return jsonify({"success": True, "message": message})

@app.route('/start', methods=['POST'])
def start_bot_route():
    """Démarre le thread du bot."""
    global bot_state
    with config_lock: # Vérifier l'état actuel en toute sécurité
        if bot_state["thread"] is not None and bot_state["thread"].is_alive():
            return jsonify({"success": False, "message": "Le bot est déjà en cours."}), 400

    # Initialiser le client seulement si nécessaire (évite réinitialisation si déjà OK)
    if binance_client_wrapper.get_client() is None:
         logger.error("Échec de l'initialisation du client Binance. Vérifiez les clés API et la connexion.")
         return jsonify({"success": False, "message": "Échec de l'initialisation du client Binance."}), 500

    logger.info("Démarrage du bot demandé...")

    # --- Chargement des données persistantes ---
    loaded_data = load_data()
    with config_lock:
        if loaded_data and isinstance(loaded_data, dict):
            loaded_state_data = loaded_data.get("state", {})
            loaded_history_data = loaded_data.get("history", [])
            bot_state["in_position"] = loaded_state_data.get("in_position", False)
            entry_details_loaded = loaded_state_data.get("entry_details", None)
            bot_state["entry_details"] = entry_details_loaded if isinstance(entry_details_loaded, dict) else None
            bot_state["order_history"] = loaded_history_data if isinstance(loaded_history_data, list) else []
            max_len = bot_state.get('max_history_length', 100)
            if len(bot_state['order_history']) > max_len:
                bot_state['order_history'] = bot_state['order_history'][-max_len:]
                logger.info(f"Historique chargé tronqué aux {max_len} derniers ordres.")
            logger.info(f"État et historique restaurés depuis {DATA_FILENAME}.")
            log_pos = f"Oui, Détails: {bot_state['entry_details']}" if bot_state["in_position"] else "Non"
            logger.info(f"  - En position: {log_pos}")
            logger.info(f"  - Nombre d'ordres chargés: {len(bot_state['order_history'])}")
        else:
            bot_state["in_position"] = False
            bot_state["entry_details"] = None
            bot_state["order_history"] = []
            logger.info("Initialisation avec un état et un historique vides.")

        # Mettre à jour l'état avant de démarrer le thread
        bot_state["status"] = "Démarrage..."
        bot_state["stop_requested"] = False
        bot_state["thread"] = threading.Thread(target=run_bot, daemon=True)
        bot_state["thread"].start()
    # --- Fin Chargement ---

    time.sleep(1) # Laisser le temps au thread de démarrer
    return jsonify({"success": True, "message": "Ordre de démarrage envoyé."})

@app.route('/stop', methods=['POST'])
def stop_bot_route():
    """Demande l'arrêt du thread du bot."""
    global bot_state
    with config_lock:
        if bot_state["thread"] is None or not bot_state["thread"].is_alive():
            bot_state["status"] = "Arrêté" # Assurer que le statut est correct
            return jsonify({"success": False, "message": "Le bot n'est pas en cours."}), 400

        logger.info("Arrêt du bot demandé...")
        bot_state["status"] = "Arrêt..."
        bot_state["stop_requested"] = True
        # La sauvegarde se fera dans le finally de run_bot

    return jsonify({"success": True, "message": "Ordre d'arrêt envoyé."})

@app.route('/stream_logs')
def stream_logs():
    """Route pour streamer les logs via Server-Sent Events (SSE)."""
    def generate():
        # Envoyer un message initial pour confirmer la connexion
        yield f"data: Connexion au flux de logs établie.\n\n"
        logger.info("Client connecté au flux de logs SSE.")
        try:
            while True:
                try:
                    # Attendre un log de la queue (avec timeout pour keep-alive)
                    log_entry = log_queue.get(timeout=1)
                    yield f"data: {log_entry}\n\n" # Format SSE
                    log_queue.task_done()
                except queue.Empty:
                    # Envoyer un commentaire keep-alive si pas de log
                    yield ": keep-alive\n\n"
                    continue
        except GeneratorExit:
            # Gérer la déconnexion du client
            logger.info("Client déconnecté du flux de logs SSE.")
        finally:
            # Nettoyage si nécessaire (normalement pas besoin ici)
            pass
    # Retourner une réponse de type text/event-stream
    return Response(generate(), mimetype='text/event-stream')

@app.route('/order_history')
def get_order_history():
    """Retourne l'historique des ordres de la session actuelle (ou chargé)."""
    with config_lock:
        # Retourner une copie pour éviter les modifications concurrentes
        history_copy = list(bot_state['order_history'])
    return jsonify(history_copy)

# --- Boucle Principale du Bot ---
def run_bot():
    """Fonction principale exécutée dans un thread séparé."""
    global bot_state, bot_config # Accès à l'état et config globaux

    # Prendre une copie de la config au démarrage du thread pour cette session
    with config_lock:
        current_run_config = bot_config.copy()
        initial_timeframe_str = current_run_config["TIMEFRAME_STR"]
        # Mettre à jour l'état du bot
        bot_state["status"] = "En cours"
        bot_state["timeframe"] = initial_timeframe_str
        bot_state["symbol"] = SYMBOL # Assurer que le symbole est défini

    logger.info(f"Démarrage effectif du bot pour {SYMBOL} sur {initial_timeframe_str}")

    try:
        # --- Initialisation spécifique au run ---
        symbol_info = binance_client_wrapper.get_symbol_info(SYMBOL)
        if not symbol_info:
            raise Exception(f"Impossible de récupérer les infos pour {SYMBOL}. Arrêt.")

        with config_lock:
            bot_state['base_asset'] = symbol_info.get('baseAsset', '')
            bot_state['quote_asset'] = symbol_info.get('quoteAsset', 'USDT') # Fallback USDT
        if not bot_state['base_asset']:
            raise Exception(f"Impossible de déterminer l'asset de base pour {SYMBOL}. Arrêt.")
        logger.info(f"Assets détectés: Base='{bot_state['base_asset']}', Quote='{bot_state['quote_asset']}'")

        # Récupérer les soldes initiaux (une seule fois au début du run)
        initial_quote = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
        initial_base = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])

        if initial_quote is None: # Erreur critique si on ne peut pas lire le solde principal
             raise Exception(f"Impossible de récupérer le solde initial {bot_state['quote_asset']}. Arrêt.")

        with config_lock:
            bot_state["available_balance"] = initial_quote
            # Mettre à jour la quantité base seulement si on n'est pas déjà en position (état chargé)
            if not bot_state["in_position"]:
                bot_state["symbol_quantity"] = initial_base if initial_base is not None else 0.0
            elif initial_base is not None: # Si en position, juste mettre à jour pour info
                 bot_state["symbol_quantity"] = initial_base
            else: # Si en position et erreur lecture solde base, loguer mais continuer
                 logger.warning(f"Impossible de lire le solde initial de {bot_state['base_asset']} alors qu'en position.")
                 # On utilisera la quantité de entry_details pour la sortie

        logger.info(f"Solde initial {bot_state['quote_asset']}: {bot_state['available_balance']:.4f}")
        logger.info(f"Quantité initiale {bot_state['base_asset']}: {bot_state['symbol_quantity']:.6f}")
        # --- Fin Initialisation ---

        # --- Boucle principale ---
        while not bot_state["stop_requested"]:
            # Recharger la config à chaque itération pour prendre en compte les modifs via UI
            with config_lock:
                current_config = bot_config.copy()
                # Lire l'état actuel nécessaire pour la boucle
                local_in_position = bot_state["in_position"]
                local_available_balance = bot_state["available_balance"]
                local_symbol_quantity = bot_state["symbol_quantity"]
                local_entry_details = bot_state["entry_details"] # Peut être None

            local_timeframe_str = current_config["TIMEFRAME_STR"]
            local_risk = current_config["RISK_PER_TRADE"]
            local_alloc = current_config["CAPITAL_ALLOCATION"]

            # Obtenir la constante Binance pour le timeframe
            binance_interval = TIMEFRAME_CONSTANT_MAP.get(local_timeframe_str)
            if binance_interval is None:
                logger.error(f"Timeframe '{local_timeframe_str}' invalide. Utilisation de 5m par défaut.")
                local_timeframe_str = '5m'
                binance_interval = TIMEFRAME_CONSTANT_MAP['5m']
                # Mettre à jour l'état global pour refléter le changement
                with config_lock:
                    bot_state["timeframe"] = local_timeframe_str
                    bot_config["TIMEFRAME_STR"] = local_timeframe_str # Corriger aussi la config

            try:
                # --- Mise à jour Prix (à chaque cycle) ---
                ticker_info = binance_client_wrapper.get_symbol_ticker(symbol=SYMBOL)
                current_price = None
                if ticker_info and 'price' in ticker_info:
                    try:
                        current_price = float(ticker_info['price'])
                        with config_lock: bot_state["current_price"] = current_price
                        # Logguer moins souvent ? Peut-être en DEBUG
                        logger.debug(f"Prix actuel {SYMBOL}: {current_price:.4f}")
                    except (ValueError, TypeError) as price_err:
                        logger.warning(f"Impossible de convertir le prix '{ticker_info['price']}' en float: {price_err}")
                else:
                    logger.warning(f"Impossible de récupérer le ticker pour {SYMBOL}")
                # --- Fin Mise à jour Prix ---

                # 1. Récupérer Klines
                # Calculer la limite nécessaire en fonction des périodes utilisées
                periods = [current_config["EMA_LONG_PERIOD"], current_config["RSI_PERIOD"]]
                if current_config["USE_EMA_FILTER"]: periods.append(current_config["EMA_FILTER_PERIOD"])
                if current_config["USE_VOLUME_CONFIRMATION"]: periods.append(current_config["VOLUME_AVG_PERIOD"])
                required_limit = max(periods) + 5 # Marge de sécurité

                klines = binance_client_wrapper.get_klines(SYMBOL, binance_interval, limit=required_limit)
                if not klines:
                    logger.warning("Aucune donnée kline reçue, attente...")
                    # Attendre un peu avant de réessayer (adapter selon timeframe)
                    time.sleep(min(interval_to_seconds(local_timeframe_str), 30))
                    continue

                # 2. Calculer Indicateurs/Signaux
                # Passer la configuration actuelle à la fonction de stratégie
                signals_df = strategy.calculate_indicators_and_signals(klines, current_config)
                if signals_df is None or signals_df.empty:
                    logger.warning("Impossible de calculer indicateurs/signaux, attente.")
                    time.sleep(min(interval_to_seconds(local_timeframe_str), 30))
                    continue
                current_data = signals_df.iloc[-1] # Dernière ligne contient les indicateurs/signaux actuels

                # 3. Logique d'Entrée/Sortie
                entry_order_result = None
                exit_order_result = None
                performance_pct = None
                should_save = False # Doit-on sauvegarder l'état après cette itération ?
                balances_updated = False # A-t-on rafraîchi les soldes ?

                if not local_in_position:
                    # Vérifier conditions d'entrée en passant la config
                    entry_order_result = strategy.check_entry_conditions(
                        current_data, SYMBOL, local_risk, local_alloc,
                        local_available_balance, symbol_info, current_config
                    )
                    if entry_order_result: # Ordre d'achat placé avec succès
                        logger.info(f"Ordre d'ACHAT placé pour {SYMBOL}.")
                        try:
                            executed_qty = float(entry_order_result.get('executedQty', 0))
                            cummulative_quote_qty = float(entry_order_result.get('cummulativeQuoteQty', 0))
                            if executed_qty > 0:
                                avg_entry_price = cummulative_quote_qty / executed_qty
                                with config_lock:
                                    bot_state["in_position"] = True
                                    bot_state["entry_details"] = {
                                        "order_id": entry_order_result.get('orderId'),
                                        "avg_price": avg_entry_price,
                                        "quantity": executed_qty,
                                        "timestamp": entry_order_result.get('transactTime', int(time.time() * 1000))
                                    }
                                logger.info(f"Détails d'entrée MAJ: Prix={avg_entry_price:.4f}, Qté={executed_qty}")
                                should_save = True # Sauvegarder le nouvel état
                            else:
                                logger.warning("Quantité exécutée nulle pour l'ordre d'entrée. Pas de changement d'état.")
                                # Ne pas changer bot_state["in_position"]
                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            logger.error(f"Erreur traitement détails d'entrée: {e}. État inchangé.")
                            # Ne pas changer bot_state["in_position"]

                        # Rafraîchir les soldes APRÈS l'ordre
                        logger.info("Rafraîchissement des soldes après tentative d'entrée...")
                        refreshed_quote = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
                        refreshed_base = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
                        with config_lock:
                            if refreshed_quote is not None: bot_state["available_balance"] = refreshed_quote
                            if refreshed_base is not None: bot_state["symbol_quantity"] = refreshed_base
                        balances_updated = True

                elif local_in_position: # Si on est en position
                    # Utiliser la quantité de l'entrée si possible, sinon la quantité actuelle
                    qty_to_sell = local_entry_details.get("quantity") if local_entry_details else local_symbol_quantity

                    if qty_to_sell is None or qty_to_sell <= 0:
                        logger.warning(f"En position mais quantité à vendre ({qty_to_sell}) invalide. Sortie non vérifiée.")
                    else:
                        # Vérifier conditions de sortie en passant la config
                        exit_order_result = strategy.check_exit_conditions(
                            current_data, SYMBOL, qty_to_sell, symbol_info
                        )
                        if exit_order_result: # Ordre de vente placé avec succès
                            logger.info(f"Ordre de VENTE (sortie) placé pour {SYMBOL}.")

                            # Calculer la performance si possible
                            if local_entry_details:
                                try:
                                    exit_executed_qty = float(exit_order_result.get('executedQty', 0))
                                    exit_cummulative_quote_qty = float(exit_order_result.get('cummulativeQuoteQty', 0))
                                    entry_price = local_entry_details.get('avg_price')

                                    if exit_executed_qty > 0 and entry_price is not None and entry_price > 0:
                                        avg_exit_price = exit_cummulative_quote_qty / exit_executed_qty
                                        performance_pct = ((avg_exit_price / entry_price) - 1) * 100
                                        logger.info(f"Performance calculée: {performance_pct:.2f}%")
                                    else:
                                        logger.warning("Impossible de calculer la performance (données sortie/entrée invalides).")
                                except (ValueError, TypeError, ZeroDivisionError) as e:
                                    logger.error(f"Erreur calcul performance: {e}")
                            else:
                                logger.warning("Détails d'entrée non trouvés pour calculer la performance.")

                            # Mettre à jour l'état global
                            with config_lock:
                                bot_state["in_position"] = False
                                bot_state["entry_details"] = None
                            should_save = True # Sauvegarder le nouvel état

                            # Rafraîchir les soldes APRÈS l'ordre
                            logger.info("Rafraîchissement des soldes après sortie...")
                            refreshed_quote = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
                            refreshed_base = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
                            with config_lock:
                                if refreshed_quote is not None: bot_state["available_balance"] = refreshed_quote
                                if refreshed_base is not None: bot_state["symbol_quantity"] = refreshed_base
                            balances_updated = True

                # --- Enregistrer l'ordre dans l'historique (si un ordre a été placé) ---
                order_to_log = entry_order_result or exit_order_result
                if order_to_log:
                    try:
                        simplified_order = {
                            "timestamp": order_to_log.get('transactTime', int(time.time() * 1000)),
                            "orderId": order_to_log.get('orderId'), "symbol": order_to_log.get('symbol'),
                            "side": order_to_log.get('side'), "type": order_to_log.get('type'),
                            "origQty": order_to_log.get('origQty'), "executedQty": order_to_log.get('executedQty'),
                            "cummulativeQuoteQty": order_to_log.get('cummulativeQuoteQty'),
                            "price": order_to_log.get('price'), "status": order_to_log.get('status'),
                            "performance_pct": performance_pct if order_to_log == exit_order_result else None
                        }
                        with config_lock:
                            bot_state['order_history'].append(simplified_order)
                            # Limiter la taille de l'historique
                            current_len = len(bot_state['order_history'])
                            max_len = bot_state['max_history_length']
                            if current_len > max_len:
                                bot_state['order_history'] = bot_state['order_history'][-max_len:]
                        logger.info(f"Ordre {simplified_order.get('orderId', 'N/A')} ({simplified_order['side']}) ajouté à l'historique.")
                        if simplified_order['performance_pct'] is not None:
                            logger.info(f"  Performance enregistrée: {simplified_order['performance_pct']:.2f}%")
                        should_save = True # Sauvegarder car l'historique a changé
                    except Exception as hist_err:
                        logger.error(f"Erreur lors de l'ajout de l'ordre à l'historique: {hist_err}")

                # --- Sauvegarder l'état si nécessaire ---
                if should_save:
                    save_data()

                # 4. Attendre la prochaine bougie
                if bot_state["stop_requested"]: # Vérifier à nouveau après les opérations
                    break
                interval_seconds = interval_to_seconds(local_timeframe_str)
                if interval_seconds > 0:
                    # Calcul précis du temps d'attente jusqu'à la prochaine bougie
                    current_time_s = time.time()
                    time_to_next_candle_s = interval_seconds - (current_time_s % interval_seconds)
                    # Ajouter une petite marge (ex: 1s) pour être sûr d'être DANS la nouvelle bougie
                    wait_time = time_to_next_candle_s + 1

                    logger.debug(f"Attente de {wait_time:.2f}s pour la prochaine bougie {local_timeframe_str}...")
                    # Boucle de sommeil interruptible
                    sleep_interval = 0.5 # Vérifier toutes les 0.5s si stop demandé
                    end_sleep = time.time() + wait_time
                    while time.time() < end_sleep and not bot_state["stop_requested"]:
                        time.sleep(min(sleep_interval, max(0, end_sleep - time.time())))
                else:
                    logger.warning(f"Intervalle de sommeil invalide pour {local_timeframe_str}. Attente 60s.")
                    time.sleep(60) # Fallback

            # --- Gestion des Erreurs de la Boucle ---
            except (BinanceAPIException, BinanceRequestException) as e:
                logger.error(f"Erreur API/Request Binance dans la boucle: {e}")
                if isinstance(e, BinanceAPIException) and e.status_code == 401:
                    logger.error("Erreur d'authentification Binance (clés API invalides?). Arrêt du bot.")
                    with config_lock: bot_state["status"] = "Erreur Auth"; bot_state["stop_requested"] = True
                else:
                    # Erreur API temporaire possible, on continue après une pause
                    with config_lock: bot_state["status"] = "Erreur API/Req"
                    logger.info("Pause de 60s suite à une erreur API/Request...")
                    time.sleep(60)
            except Exception as e:
                logger.exception("Erreur inattendue dans la boucle run_bot.") # Inclut la traceback
                with config_lock: bot_state["status"] = "Erreur Interne"
                logger.info("Pause de 60s suite à une erreur interne...")
                time.sleep(60) # Pause avant de réessayer

    # --- Gestion des Erreurs d'Initialisation ---
    except Exception as e:
        logger.exception("Erreur majeure lors de l'initialisation de run_bot. Le bot ne peut pas démarrer.")
        with config_lock: bot_state["status"] = "Erreur Init"
        # Pas de sauvegarde ici car l'état initial est probablement incorrect

    # --- Nettoyage Final ---
    finally:
        logger.info("Fin de l'exécution de run_bot.")
        with config_lock:
            bot_state["status"] = "Arrêté"
            bot_state["thread"] = None # Marquer le thread comme terminé
            # Ne pas réinitialiser in_position ou entry_details ici pour la sauvegarde
        logger.info("Tentative de sauvegarde finale des données...")
        save_data() # Sauvegarder l'état final (même si arrêté par erreur)
        logger.info("Bot arrêté.")

# --- Démarrage Application Flask ---
if __name__ == "__main__":
    # Désactiver les logs INFO de Werkzeug pour ne pas polluer le frontend/console
    werkzeug_log = logging.getLogger('werkzeug')
    werkzeug_log.setLevel(logging.ERROR)

    logger.info("Démarrage de l'API Flask du Bot...")
    # Note: load_data() est appelé dans la route /start
    # Utiliser debug=False et use_reloader=False pour la stabilité avec les threads
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
