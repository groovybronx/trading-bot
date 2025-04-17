import time
import logging
import threading
import queue  # Ajout pour la file d'attente
from flask import Flask, jsonify, request, Response  # Ajout de Response
from flask_cors import CORS
from binance.client import Client as BinanceClient # Assurez-vous que c'est importé
from binance.exceptions import BinanceAPIException, BinanceRequestException

# Importer les modules locaux
import config
import strategy
import binance_client_wrapper

# --- Configuration du Logging ---
# Créer une file d'attente pour les logs destinés au frontend
log_queue = queue.Queue()

# Gestionnaire de logging personnalisé pour mettre les messages dans la file d'attente
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        # Formater le message et le mettre dans la file d'attente
        # Ignorer les messages DEBUG pour ne pas surcharger le frontend
        if record.levelno >= logging.INFO: # Utiliser >= pour la comparaison
            log_entry = self.format(record)
            self.log_queue.put(log_entry)

# Configurer le logging principal
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_level = logging.INFO # Définir le niveau de log principal (INFO et supérieur)

# Configurer le handler pour la console
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(log_formatter)

# Configurer le handler pour la file d'attente SSE
queue_handler = QueueHandler(log_queue)
queue_handler.setFormatter(log_formatter)

# Obtenir le logger racine et ajouter les handlers
# Important: Ne pas utiliser basicConfig si on configure les handlers manuellement
logger = logging.getLogger()
logger.setLevel(log_level)
# Nettoyer les handlers existants potentiels (si basicConfig a été appelé avant)
if logger.hasHandlers():
    logger.handlers.clear()
logger.addHandler(stream_handler) # Ajouter le handler console
logger.addHandler(queue_handler)  # Ajouter le handler pour SSE

# --- Clés API, Paramètres, Mapping, États ---
try:
    API_KEY = config.BINANCE_API_KEY
    API_SECRET = config.BINANCE_API_SECRET
except AttributeError:
    logging.error("BINANCE_API_KEY ou BINANCE_API_SECRET non trouvées dans config.py.")
    API_KEY = "INVALID_KEY"
    API_SECRET = "INVALID_SECRET"
SYMBOL = getattr(config, 'SYMBOL', 'BTCUSDT')

# MODIFIER VALID_TIMEFRAMES: Ajouter '1s'
VALID_TIMEFRAMES = ['1s', '1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']

# MODIFIER TIMEFRAME_CONSTANT_MAP: Ajouter le mapping pour '1s'
TIMEFRAME_CONSTANT_MAP = {
    '1s': 'KLINE_INTERVAL_1SECOND', # <-- AJOUTÉ
    '1m': 'KLINE_INTERVAL_1MINUTE', '3m': 'KLINE_INTERVAL_3MINUTE', '5m': 'KLINE_INTERVAL_5MINUTE',
    '15m': 'KLINE_INTERVAL_15MINUTE', '30m': 'KLINE_INTERVAL_30MINUTE', '1h': 'KLINE_INTERVAL_1HOUR',
    '2h': 'KLINE_INTERVAL_2HOUR', '4h': 'KLINE_INTERVAL_4HOUR', '6h': 'KLINE_INTERVAL_6HOUR',
    '8h': 'KLINE_INTERVAL_8HOUR', '12h': 'KLINE_INTERVAL_12HOUR', '1d': 'KLINE_INTERVAL_1DAY',
    '3d': 'KLINE_INTERVAL_3DAY', '1w': 'KLINE_INTERVAL_1WEEK', '1M': 'KLINE_INTERVAL_1MONTH',
}

config_lock = threading.Lock()
bot_config = {
    "TIMEFRAME_STR": getattr(config, 'TIMEFRAME', '5m'), "RISK_PER_TRADE": getattr(config, 'RISK_PER_TRADE', 0.01),
    "CAPITAL_ALLOCATION": getattr(config, 'CAPITAL_ALLOCATION', 0.1), "EMA_SHORT_PERIOD": getattr(config, 'EMA_SHORT_PERIOD', 9),
    "EMA_LONG_PERIOD": getattr(config, 'EMA_LONG_PERIOD', 21), "EMA_FILTER_PERIOD": getattr(config, 'EMA_FILTER_PERIOD', 50),
    "RSI_PERIOD": getattr(config, 'RSI_PERIOD', 14), "RSI_OVERBOUGHT": getattr(config, 'RSI_OVERBOUGHT', 75),
    "RSI_OVERSOLD": getattr(config, 'RSI_OVERSOLD', 25), "VOLUME_AVG_PERIOD": getattr(config, 'VOLUME_AVG_PERIOD', 20),
    "USE_EMA_FILTER": getattr(config, 'USE_EMA_FILTER', True), "USE_VOLUME_CONFIRMATION": getattr(config, 'USE_VOLUME_CONFIRMATION', False),
}
client = None # Le client global est géré par le wrapper
def initialize_binance_client():
    global client
    initialized_client = binance_client_wrapper.get_client()
    if not initialized_client: logging.error("Impossible d'initialiser le client Binance via le wrapper."); client = None; return False
    else: client = initialized_client; logging.info("Client Binance initialisé avec succès via le wrapper."); return True

# MODIFIER interval_to_seconds: Ajouter la condition pour 's'
def interval_to_seconds(interval_str):
    try:
        unit = interval_str[-1].lower(); value = int(interval_str[:-1])
        if unit == 's': return value * 1 # <-- AJOUTÉ
        elif unit == 'm': return value * 60
        elif unit == 'h': return value * 60 * 60
        elif unit == 'd': return value * 60 * 60 * 24
        elif unit == 'w': return value * 60 * 60 * 24 * 7
        elif unit == 'M': return value * 60 * 60 * 24 * 30 # Approximation pour mois
        else: logging.warning(f"Intervalle non reconnu pour conversion secondes: {interval_str}"); return 0
    except (IndexError, ValueError, TypeError): logging.warning(f"Format d'intervalle invalide pour conversion secondes: {interval_str}"); return 0

# --- État Global du Bot (Statut, Position, etc.) ---
bot_state = {
    "status": "Arrêté",
    "in_position": False,
    "available_balance": 0.0, # Solde Quote Asset (ex: USDT)
    "current_price": 0.0,
    "symbol_quantity": 0.0,   # Quantité Base Asset (ex: BTC)
    "base_asset": "",         # Nom de l'asset de base (ex: BTC)
    "quote_asset": "USDT",    # Nom de l'asset de cotation (ex: USDT)
    "symbol": SYMBOL,
    "timeframe": bot_config["TIMEFRAME_STR"],
    "thread": None,
    "stop_requested": False,
    "entry_details": None, # Sera un dict: {'order_id': ..., 'avg_price': ..., 'quantity': ..., 'timestamp': ...}
    "order_history": [],      # Historique des ordres de la session
    "max_history_length": 100 # Limite de l'historique en mémoire
}

# --- Flask App ---
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Routes API ---
@app.route('/status')
def get_status():
    """Retourne le statut actuel du bot."""
    with config_lock:
        status_data = {
            'status': bot_state['status'],
            'symbol': bot_state['symbol'],
            'timeframe': bot_state['timeframe'],
            'in_position': bot_state['in_position'],
            'available_balance': bot_state['available_balance'],
            'current_price': bot_state['current_price'],
            'symbol_quantity': bot_state['symbol_quantity'],
            'base_asset': bot_state['base_asset'],
            'quote_asset': bot_state['quote_asset'],
        }
    return jsonify(status_data)

@app.route('/parameters', methods=['GET'])
def get_parameters():
    with config_lock: current_config = bot_config.copy()
    return jsonify(current_config)

@app.route('/parameters', methods=['POST'])
def set_parameters():
    global bot_config
    new_params = request.json
    if not new_params: return jsonify({"success": False, "message": "Aucun paramètre fourni."}), 400
    logging.info(f"Tentative de mise à jour des paramètres: {new_params}")
    restart_recommended = False
    validated_params = {}
    try:
        # Validation utilise maintenant VALID_TIMEFRAMES mis à jour
        new_timeframe = str(new_params.get("TIMEFRAME_STR", bot_config["TIMEFRAME_STR"]))
        if new_timeframe not in VALID_TIMEFRAMES: raise ValueError(f"TIMEFRAME_STR invalide.")
        validated_params["TIMEFRAME_STR"] = new_timeframe
        if new_timeframe != bot_config["TIMEFRAME_STR"]: restart_recommended = True

        validated_params["RISK_PER_TRADE"] = float(new_params.get("RISK_PER_TRADE", bot_config["RISK_PER_TRADE"]))
        if not (0 < validated_params["RISK_PER_TRADE"] < 1): raise ValueError("RISK_PER_TRADE doit être entre 0 et 1 (exclus)")
        validated_params["CAPITAL_ALLOCATION"] = float(new_params.get("CAPITAL_ALLOCATION", bot_config["CAPITAL_ALLOCATION"]))
        if not (0 < validated_params["CAPITAL_ALLOCATION"] <= 1): raise ValueError("CAPITAL_ALLOCATION doit être entre 0 (exclus) et 1 (inclus)")
        validated_params["EMA_SHORT_PERIOD"] = int(new_params.get("EMA_SHORT_PERIOD", bot_config["EMA_SHORT_PERIOD"]))
        if validated_params["EMA_SHORT_PERIOD"] <= 0: raise ValueError("EMA_SHORT_PERIOD doit être > 0")
        validated_params["EMA_LONG_PERIOD"] = int(new_params.get("EMA_LONG_PERIOD", bot_config["EMA_LONG_PERIOD"]))
        if validated_params["EMA_LONG_PERIOD"] <= validated_params["EMA_SHORT_PERIOD"]: raise ValueError("EMA_LONG_PERIOD doit être > EMA_SHORT_PERIOD")
        validated_params["EMA_FILTER_PERIOD"] = int(new_params.get("EMA_FILTER_PERIOD", bot_config["EMA_FILTER_PERIOD"]))
        if validated_params["EMA_FILTER_PERIOD"] <= 0: raise ValueError("EMA_FILTER_PERIOD doit être > 0")
        validated_params["RSI_PERIOD"] = int(new_params.get("RSI_PERIOD", bot_config["RSI_PERIOD"]))
        if validated_params["RSI_PERIOD"] <= 1: raise ValueError("RSI_PERIOD doit être > 1")
        validated_params["RSI_OVERBOUGHT"] = int(new_params.get("RSI_OVERBOUGHT", bot_config["RSI_OVERBOUGHT"]))
        if not (50 < validated_params["RSI_OVERBOUGHT"] <= 100): raise ValueError("RSI_OVERBOUGHT doit être entre 50 (exclus) et 100 (inclus)")
        validated_params["RSI_OVERSOLD"] = int(new_params.get("RSI_OVERSOLD", bot_config["RSI_OVERSOLD"]))
        if not (0 <= validated_params["RSI_OVERSOLD"] < 50): raise ValueError("RSI_OVERSOLD doit être entre 0 (inclus) et 50 (exclus)")
        if validated_params["RSI_OVERSOLD"] >= validated_params["RSI_OVERBOUGHT"]: raise ValueError("RSI_OVERSOLD doit être < RSI_OVERBOUGHT")
        validated_params["VOLUME_AVG_PERIOD"] = int(new_params.get("VOLUME_AVG_PERIOD", bot_config["VOLUME_AVG_PERIOD"]))
        if validated_params["VOLUME_AVG_PERIOD"] <= 0: raise ValueError("VOLUME_AVG_PERIOD doit être > 0")
        validated_params["USE_EMA_FILTER"] = bool(new_params.get("USE_EMA_FILTER", bot_config["USE_EMA_FILTER"]))
        validated_params["USE_VOLUME_CONFIRMATION"] = bool(new_params.get("USE_VOLUME_CONFIRMATION", bot_config["USE_VOLUME_CONFIRMATION"]))

    except (ValueError, TypeError) as e:
        logging.error(f"Erreur de validation des paramètres: {e}")
        return jsonify({"success": False, "message": f"Paramètres invalides: {e}"}), 400
    with config_lock: bot_config.update(validated_params); logging.info(f"Paramètres mis à jour avec succès.")
    # Mettre à jour les variables globales de la stratégie
    strategy.EMA_SHORT_PERIOD = bot_config["EMA_SHORT_PERIOD"]
    strategy.EMA_LONG_PERIOD = bot_config["EMA_LONG_PERIOD"]
    strategy.EMA_FILTER_PERIOD = bot_config["EMA_FILTER_PERIOD"]
    strategy.RSI_PERIOD = bot_config["RSI_PERIOD"]
    strategy.RSI_OVERBOUGHT = bot_config["RSI_OVERBOUGHT"]
    strategy.RSI_OVERSOLD = bot_config["RSI_OVERSOLD"]
    strategy.VOLUME_AVG_PERIOD = bot_config["VOLUME_AVG_PERIOD"]
    strategy.USE_EMA_FILTER = bot_config["USE_EMA_FILTER"]
    strategy.USE_VOLUME_CONFIRMATION = bot_config["USE_VOLUME_CONFIRMATION"]
    message = "Paramètres mis à jour."
    if restart_recommended: message += " Un redémarrage du bot est conseillé pour appliquer le nouveau timeframe."
    return jsonify({"success": True, "message": message})

@app.route('/start', methods=['POST'])
def start_bot_route():
    global bot_state
    if bot_state["thread"] is not None and bot_state["thread"].is_alive(): return jsonify({"success": False, "message": "Le bot est déjà en cours."}), 400
    if not initialize_binance_client(): return jsonify({"success": False, "message": "Échec de l'initialisation du client Binance."}), 500
    logging.info("Démarrage du bot demandé...")
    with config_lock:
        bot_state["order_history"] = []
        bot_state["entry_details"] = None
    bot_state["status"] = "Démarrage..."; bot_state["stop_requested"] = False
    bot_state["thread"] = threading.Thread(target=run_bot, daemon=True); bot_state["thread"].start()
    time.sleep(1); return jsonify({"success": True, "message": "Ordre de démarrage envoyé."})

@app.route('/stop', methods=['POST'])
def stop_bot_route():
    global bot_state
    if bot_state["thread"] is None or not bot_state["thread"].is_alive(): bot_state["status"] = "Arrêté"; return jsonify({"success": False, "message": "Le bot n'est pas en cours."}), 400
    logging.info("Arrêt du bot demandé...")
    bot_state["status"] = "Arrêt..."; bot_state["stop_requested"] = True
    return jsonify({"success": True, "message": "Ordre d'arrêt envoyé."})

# --- ROUTE POUR LE STREAMING DES LOGS ---
@app.route('/stream_logs')
def stream_logs():
    def generate():
        yield f"data: Connexion au flux de logs établie.\n\n"
        logging.info("Client connecté au flux de logs.")
        try:
            while True:
                try:
                    log_entry = log_queue.get(timeout=1)
                    yield f"data: {log_entry}\n\n"
                    log_queue.task_done()
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    continue
        except GeneratorExit:
            logging.info("Client déconnecté du flux de logs.")
        finally:
            pass
    return Response(generate(), mimetype='text/event-stream')

# --- ROUTE POUR L'HISTORIQUE DES ORDRES ---
@app.route('/order_history')
def get_order_history():
    """Retourne l'historique des ordres de la session actuelle."""
    with config_lock:
        history_copy = list(bot_state['order_history'])
    return jsonify(history_copy)
# --- FIN ROUTE HISTORIQUE ---


# --- Boucle Principale du Bot ---
def run_bot():
    global bot_state, bot_config
    with config_lock: initial_config = bot_config.copy()
    initial_timeframe_str = initial_config["TIMEFRAME_STR"]
    logging.info(f"Démarrage effectif du bot pour {SYMBOL} sur {initial_timeframe_str}")
    bot_state["status"] = "En cours"; bot_state["timeframe"] = initial_timeframe_str
    try:
        # --- Récupérer infos symbole et assets ---
        symbol_info = binance_client_wrapper.get_symbol_info(SYMBOL)
        if not symbol_info: raise Exception(f"Impossible de récupérer les infos pour {SYMBOL}.")
        bot_state['base_asset'] = symbol_info.get('baseAsset', '')
        bot_state['quote_asset'] = symbol_info.get('quoteAsset', 'USDT')
        if not bot_state['base_asset']: raise Exception(f"Impossible de déterminer l'asset de base pour {SYMBOL}.")
        logging.info(f"Asset de base: {bot_state['base_asset']}, Asset de cotation: {bot_state['quote_asset']}") # Frontend
        # --- Fin récupération infos symbole ---

        # --- Récupérer soldes initiaux ---
        initial_quote_balance = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
        if initial_quote_balance is None: raise Exception(f"Impossible de récupérer le solde initial {bot_state['quote_asset']}.")
        bot_state["available_balance"] = initial_quote_balance
        logging.info(f"Solde {bot_state['quote_asset']} initial : {bot_state['available_balance']}") # Frontend

        initial_base_quantity = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
        if initial_base_quantity is None: initial_base_quantity = 0.0 # Considérer 0 si erreur ou non possédé
        bot_state["symbol_quantity"] = initial_base_quantity
        logging.info(f"Quantité {bot_state['base_asset']} initiale : {bot_state['symbol_quantity']}") # Frontend
        # --- Fin récupération soldes initiaux ---

        while not bot_state["stop_requested"]:
            with config_lock: current_config = bot_config.copy()
            local_timeframe_str = current_config["TIMEFRAME_STR"]
            local_risk_per_trade = current_config["RISK_PER_TRADE"]
            local_capital_allocation = current_config["CAPITAL_ALLOCATION"]
            # Récupérer les paramètres de stratégie actuels
            local_ema_short = current_config["EMA_SHORT_PERIOD"]; local_ema_long = current_config["EMA_LONG_PERIOD"]
            local_rsi_period = current_config["RSI_PERIOD"]; use_ema_filter = current_config["USE_EMA_FILTER"]
            ema_filter_period = current_config["EMA_FILTER_PERIOD"]

            # Obtenir la constante Binance pour le timeframe (utilise TIMEFRAME_CONSTANT_MAP mis à jour)
            binance_constant_name = TIMEFRAME_CONSTANT_MAP.get(local_timeframe_str)
            local_timeframe_interval = getattr(BinanceClient, binance_constant_name, None) if binance_constant_name else None
            if local_timeframe_interval is None:
                logging.error(f"Constante Binance non trouvée pour timeframe '{local_timeframe_str}'. Utilisation de 5m par défaut.") # Frontend
                local_timeframe_str = '5m'; local_timeframe_interval = BinanceClient.KLINE_INTERVAL_5MINUTE
            # Mettre à jour l'état si le timeframe a changé (pour affichage)
            if bot_state["timeframe"] != local_timeframe_str:
                 logging.info(f"Changement de timeframe détecté pour {local_timeframe_str}. Redémarrage conseillé.") # Frontend
                 bot_state["timeframe"] = local_timeframe_str
            try:
                 # --- Mise à jour Prix et Soldes ---
                ticker_info = binance_client_wrapper.get_symbol_ticker(symbol=SYMBOL)
                current_price = None # Default to None
                if ticker_info and 'price' in ticker_info:
                    try:
                        current_price = float(ticker_info['price'])
                        bot_state["current_price"] = current_price
                        logging.info(f"Prix actuel {SYMBOL}: {current_price}") # Frontend
                    except (ValueError, TypeError) as price_err:
                        logging.warning(f"Impossible de convertir le prix '{ticker_info['price']}' en float: {price_err}") # Frontend
                else:
                    logging.warning(f"Impossible de récupérer les informations de ticker ou le prix pour {SYMBOL}") # Frontend
                    if ticker_info: logging.warning(f"Ticker info reçu: {ticker_info}") # Log pour débogage

                current_quote_balance = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
                if current_quote_balance is not None and current_quote_balance != bot_state["available_balance"]:
                    logging.info(f"Mise à jour solde {bot_state['quote_asset']} : {current_quote_balance}"); bot_state["available_balance"] = current_quote_balance # Frontend

                current_base_quantity = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
                if current_base_quantity is not None and current_base_quantity != bot_state["symbol_quantity"]:
                    logging.info(f"Mise à jour quantité {bot_state['base_asset']} : {current_base_quantity}"); bot_state["symbol_quantity"] = current_base_quantity # Frontend
                # --- Fin Mise à jour ---

                # 1. Récupérer Klines
                required_limit = max(local_ema_long, ema_filter_period if use_ema_filter else 0, local_rsi_period) + 5
                klines = binance_client_wrapper.get_klines(SYMBOL, local_timeframe_interval, limit=required_limit)
                if not klines: logging.warning("Aucune donnée kline reçue, attente..."); time.sleep(30); continue # Frontend

                # 2. Calculer Indicateurs/Signaux
                signals_df = strategy.calculate_indicators_and_signals(klines)
                if signals_df is None or signals_df.empty: logging.warning("Impossible de calculer indicateurs/signaux, attente."); time.sleep(30); continue # Frontend
                current_data = signals_df.iloc[-1]

                # 3. Logique d'Entrée/Sortie
                entry_order_result = None # Pour l'ordre d'achat
                exit_order_result = None  # Pour l'ordre de vente
                performance_pct = None    # Pour stocker la performance calculée

                if not bot_state["in_position"]:
                    entry_order_result = strategy.check_entry_conditions(current_data, SYMBOL, local_risk_per_trade, local_capital_allocation, bot_state["available_balance"], symbol_info)
                    if entry_order_result: # Si un ordre d'achat a été placé avec succès
                        bot_state["in_position"] = True
                        logging.info(f"Position OUVERTE pour {SYMBOL}.") # Frontend

                        # --- Mémoriser les détails de l'entrée ---
                        try:
                            executed_qty = float(entry_order_result.get('executedQty', 0))
                            cummulative_quote_qty = float(entry_order_result.get('cummulativeQuoteQty', 0))
                            if executed_qty > 0:
                                avg_entry_price = cummulative_quote_qty / executed_qty
                                with config_lock:
                                    bot_state["entry_details"] = {
                                        "order_id": entry_order_result.get('orderId'),
                                        "avg_price": avg_entry_price,
                                        "quantity": executed_qty,
                                        "timestamp": entry_order_result.get('transactTime', int(time.time() * 1000))
                                    }
                                logging.info(f"Détails d'entrée mémorisés: Prix={avg_entry_price:.4f}, Qté={executed_qty}") # Frontend
                            else:
                                logging.warning("Quantité exécutée nulle pour l'ordre d'entrée, impossible de mémoriser les détails.") # Frontend
                                with config_lock: bot_state["entry_details"] = None
                        except (ValueError, TypeError, ZeroDivisionError) as e:
                            logging.error(f"Erreur lors du calcul/mémorisation des détails d'entrée: {e}") # Frontend
                            with config_lock: bot_state["entry_details"] = None
                        # --- FIN Mémorisation ---

                        # Rafraîchir les soldes après l'entrée
                        refreshed_quote_balance = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
                        if refreshed_quote_balance is not None: bot_state["available_balance"] = refreshed_quote_balance
                        refreshed_base_quantity = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
                        if refreshed_base_quantity is not None: bot_state["symbol_quantity"] = refreshed_base_quantity

                elif bot_state["in_position"]:
                    exit_order_result = strategy.check_exit_conditions(current_data, SYMBOL, bot_state["symbol_quantity"], symbol_info)
                    if exit_order_result: # Si un ordre de vente a été placé avec succès
                        bot_state["in_position"] = False
                        logging.info(f"Position FERMÉE pour {SYMBOL}.") # Frontend

                        # --- Calculer la performance ---
                        with config_lock:
                            entry_details_copy = bot_state["entry_details"]

                        if entry_details_copy:
                            try:
                                exit_executed_qty = float(exit_order_result.get('executedQty', 0))
                                exit_cummulative_quote_qty = float(exit_order_result.get('cummulativeQuoteQty', 0))
                                entry_price = entry_details_copy.get('avg_price')

                                if exit_executed_qty > 0 and entry_price is not None and entry_price > 0:
                                    avg_exit_price = exit_cummulative_quote_qty / exit_executed_qty
                                    performance_pct = ((avg_exit_price / entry_price) - 1) * 100
                                    logging.info(f"Performance calculée: {performance_pct:.2f}% (Entrée: {entry_price:.4f}, Sortie: {avg_exit_price:.4f})") # Frontend
                                else:
                                    logging.warning("Impossible de calculer la performance (données manquantes ou invalides).") # Frontend
                            except (ValueError, TypeError, ZeroDivisionError) as e:
                                logging.error(f"Erreur lors du calcul de la performance: {e}") # Frontend
                        else:
                            logging.warning("Détails d'entrée non trouvés pour calculer la performance.") # Frontend

                        # Réinitialiser les détails d'entrée
                        with config_lock: bot_state["entry_details"] = None
                        # --- FIN Calcul Performance ---

                        # Rafraîchir les soldes après la sortie
                        refreshed_quote_balance = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
                        if refreshed_quote_balance is not None: bot_state["available_balance"] = refreshed_quote_balance
                        refreshed_base_quantity = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
                        if refreshed_base_quantity is not None: bot_state["symbol_quantity"] = refreshed_base_quantity


                # --- Enregistrer l'ordre dans l'historique ---
                order_to_log = entry_order_result if entry_order_result else exit_order_result
                if order_to_log:
                    try:
                        simplified_order = {
                            "timestamp": order_to_log.get('transactTime', int(time.time() * 1000)),
                            "orderId": order_to_log.get('orderId'),
                            "symbol": order_to_log.get('symbol'),
                            "side": order_to_log.get('side'),
                            "type": order_to_log.get('type'),
                            "origQty": order_to_log.get('origQty'),
                            "executedQty": order_to_log.get('executedQty'),
                            "cummulativeQuoteQty": order_to_log.get('cummulativeQuoteQty'),
                            "price": order_to_log.get('price'),
                            "status": order_to_log.get('status'),
                            "performance_pct": performance_pct if order_to_log == exit_order_result else None
                        }
                        with config_lock:
                            bot_state['order_history'].append(simplified_order)
                            current_history_len = len(bot_state['order_history'])
                            max_len = bot_state['max_history_length']
                            if current_history_len > max_len:
                                bot_state['order_history'] = bot_state['order_history'][-max_len:]
                        logging.info(f"Ordre {simplified_order.get('orderId', 'N/A')} ({simplified_order['side']}) ajouté à l'historique.") # Frontend
                        if simplified_order['performance_pct'] is not None:
                             logging.info(f"  Performance enregistrée: {simplified_order['performance_pct']:.2f}%") # Frontend

                    except Exception as hist_err:
                        logging.error(f"Erreur lors de l'ajout de l'ordre à l'historique: {hist_err}") # Frontend
                # --- FIN Enregistrement ---


                # 4. Attendre la prochaine bougie
                if bot_state["stop_requested"]: break
                interval_seconds = interval_to_seconds(local_timeframe_str) # Utilise la fonction mise à jour
                if interval_seconds > 0:
                    current_time_s = time.time(); time_to_next_candle_s = interval_seconds - (current_time_s % interval_seconds) + 1
                    sleep_interval = 1; end_sleep = time.time() + time_to_next_candle_s
                    while time.time() < end_sleep and not bot_state["stop_requested"]:
                        time.sleep(min(sleep_interval, max(0, end_sleep - time.time())))
                else:
                    logging.warning(f"Intervalle de sommeil invalide pour {local_timeframe_str}. Attente 60s."); time.sleep(60) # Frontend
            except (BinanceAPIException, BinanceRequestException) as e:
                logging.error(f"Erreur API/Request Binance: {e}") # Frontend
                if isinstance(e, BinanceAPIException) and e.status_code == 401:
                    logging.error("Erreur Auth Binance (clés API invalides?). Arrêt."); bot_state["status"] = "Erreur Auth"; bot_state["stop_requested"] = True # Frontend
                else:
                    bot_state["status"] = "Erreur API/Req"
                time.sleep(60) # Attendre avant de réessayer en cas d'erreur API
            except Exception as e:
                logging.exception(f"Erreur inattendue dans run_bot"); bot_state["status"] = "Erreur Interne"; time.sleep(60) # Frontend (avec traceback)
    except Exception as e:
        logging.exception(f"Erreur majeure lors de l'initialisation de run_bot"); bot_state["status"] = "Erreur Init" # Frontend (avec traceback)
    finally:
        logging.info("Boucle du bot terminée."); bot_state["status"] = "Arrêté"; bot_state["in_position"] = False; bot_state["thread"] = None; bot_state["entry_details"] = None # Frontend

# --- Démarrage Application ---
if __name__ == "__main__":
    # Désactiver les logs INFO de Werkzeug (ne pas envoyer au frontend)
    werkzeug_log = logging.getLogger('werkzeug')
    werkzeug_log.setLevel(logging.ERROR)

    logging.info("Démarrage de l'API Flask...") # Ce log ira au frontend

    # Utiliser debug=False et use_reloader=False pour éviter les problèmes avec les threads
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

