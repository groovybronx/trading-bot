import time
import logging
import threading
import queue  # Ajout pour la file d'attente
from flask import Flask, jsonify, request, Response  # Ajout de Response
from flask_cors import CORS
from binance.client import Client as BinanceClient
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
        if record.levelno >= logging.INFO: # CORRECTION: >= au lieu de &gt;=
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
VALID_TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']
TIMEFRAME_CONSTANT_MAP = {
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
client = None
def initialize_binance_client():
    global client
    initialized_client = binance_client_wrapper.get_client()
    if not initialized_client: logging.error("Impossible d'initialiser le client Binance via le wrapper."); client = None; return False
    else: client = initialized_client; logging.info("Client Binance initialisé avec succès via le wrapper."); return True
def interval_to_seconds(interval_str):
    try:
        unit = interval_str[-1].lower(); value = int(interval_str[:-1])
        if unit == 'm': return value * 60
        elif unit == 'h': return value * 60 * 60
        elif unit == 'd': return value * 60 * 60 * 24
        elif unit == 'w': return value * 60 * 60 * 24 * 7
        elif unit == 'M': return value * 60 * 60 * 24 * 30
        else: logging.warning(f"Intervalle non reconnu pour conversion secondes: {interval_str}"); return 0
    except (IndexError, ValueError, TypeError): logging.warning(f"Format d'intervalle invalide pour conversion secondes: {interval_str}"); return 0
# --- État Global du Bot (Statut, Position, etc.) ---
bot_state = {
    "status": "Arrêté",
    "in_position": False,
    "available_balance": 0.0, # Solde USDT
    "current_price": 0.0,
    "symbol_quantity": 0.0,   # AJOUT: Quantité du symbole possédée
    "base_asset": "",         # AJOUT: Nom de l'asset de base (ex: BTC)
    "quote_asset": "USDT",    # Nom de l'asset de cotation (ex: USDT)
    "symbol": SYMBOL,
    "timeframe": bot_config["TIMEFRAME_STR"],
    "thread": None,
    "stop_requested": False
}

# --- Flask App ---
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Routes API ---
@app.route('/status')
def get_status():
    """Retourne le statut actuel du bot."""
    status_data = {
        'status': bot_state['status'],
        'symbol': bot_state['symbol'],
        'timeframe': bot_state['timeframe'],
        'in_position': bot_state['in_position'],
        'available_balance': bot_state['available_balance'], # Solde USDT
        'current_price': bot_state['current_price'],
        'symbol_quantity': bot_state['symbol_quantity'],     # AJOUT
        'base_asset': bot_state['base_asset'],               # AJOUT
        'quote_asset': bot_state['quote_asset'],             # AJOUT (pour info)
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
    logging.info(f"Tentative de mise à jour des paramètres: {new_params}") # Ce log ira au frontend
    restart_recommended = False
    validated_params = {}
    try:
        new_timeframe = str(new_params.get("TIMEFRAME_STR", bot_config["TIMEFRAME_STR"]))
        if new_timeframe not in VALID_TIMEFRAMES: raise ValueError(f"TIMEFRAME_STR invalide.")
        validated_params["TIMEFRAME_STR"] = new_timeframe
        if new_timeframe != bot_config["TIMEFRAME_STR"]: restart_recommended = True

        # --- CORRECTIONS DES COMPARAISONS ---
        validated_params["RISK_PER_TRADE"] = float(new_params.get("RISK_PER_TRADE", bot_config["RISK_PER_TRADE"]))
        if not (0 < validated_params["RISK_PER_TRADE"] < 1): raise ValueError("RISK_PER_TRADE") # &lt; devient <

        validated_params["CAPITAL_ALLOCATION"] = float(new_params.get("CAPITAL_ALLOCATION", bot_config["CAPITAL_ALLOCATION"]))
        if not (0 < validated_params["CAPITAL_ALLOCATION"] <= 1): raise ValueError("CAPITAL_ALLOCATION") # &lt; devient <

        validated_params["EMA_SHORT_PERIOD"] = int(new_params.get("EMA_SHORT_PERIOD", bot_config["EMA_SHORT_PERIOD"]))
        if validated_params["EMA_SHORT_PERIOD"] <= 0: raise ValueError("EMA_SHORT_PERIOD") # &lt; devient <

        validated_params["EMA_LONG_PERIOD"] = int(new_params.get("EMA_LONG_PERIOD", bot_config["EMA_LONG_PERIOD"]))
        if validated_params["EMA_LONG_PERIOD"] <= validated_params["EMA_SHORT_PERIOD"]: raise ValueError("EMA_LONG_PERIOD <= EMA_SHORT_PERIOD") # &lt; devient <

        validated_params["EMA_FILTER_PERIOD"] = int(new_params.get("EMA_FILTER_PERIOD", bot_config["EMA_FILTER_PERIOD"]))
        if validated_params["EMA_FILTER_PERIOD"] <= 0: raise ValueError("EMA_FILTER_PERIOD") # &lt; devient <

        validated_params["RSI_PERIOD"] = int(new_params.get("RSI_PERIOD", bot_config["RSI_PERIOD"]))
        if validated_params["RSI_PERIOD"] <= 1: raise ValueError("RSI_PERIOD") # &lt; devient <

        validated_params["RSI_OVERBOUGHT"] = int(new_params.get("RSI_OVERBOUGHT", bot_config["RSI_OVERBOUGHT"]))
        if not (50 < validated_params["RSI_OVERBOUGHT"] <= 100): raise ValueError("RSI_OVERBOUGHT") # &lt; devient <

        validated_params["RSI_OVERSOLD"] = int(new_params.get("RSI_OVERSOLD", bot_config["RSI_OVERSOLD"]))
        if not (0 <= validated_params["RSI_OVERSOLD"] < 50): raise ValueError("RSI_OVERSOLD") # &lt; devient <

        if validated_params["RSI_OVERSOLD"] >= validated_params["RSI_OVERBOUGHT"]: raise ValueError("RSI_OVERSOLD >= RSI_OVERBOUGHT") # &gt; devient >

        validated_params["VOLUME_AVG_PERIOD"] = int(new_params.get("VOLUME_AVG_PERIOD", bot_config["VOLUME_AVG_PERIOD"]))
        if validated_params["VOLUME_AVG_PERIOD"] <= 0: raise ValueError("VOLUME_AVG_PERIOD") # &lt; devient <
        # --- FIN CORRECTIONS ---

        validated_params["USE_EMA_FILTER"] = bool(new_params.get("USE_EMA_FILTER", bot_config["USE_EMA_FILTER"]))
        validated_params["USE_VOLUME_CONFIRMATION"] = bool(new_params.get("USE_VOLUME_CONFIRMATION", bot_config["USE_VOLUME_CONFIRMATION"]))
    except (ValueError, TypeError) as e:
        logging.error(f"Erreur de validation des paramètres: {e}") # Ce log ira au frontend
        return jsonify({"success": False, "message": f"Paramètres invalides: {e}"}), 400
    with config_lock: bot_config.update(validated_params); logging.info(f"Paramètres mis à jour avec succès.") # Ce log ira au frontend
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
    logging.info("Démarrage du bot demandé...") # Ce log ira au frontend
    bot_state["status"] = "Démarrage..."; bot_state["stop_requested"] = False
    bot_state["thread"] = threading.Thread(target=run_bot, daemon=True); bot_state["thread"].start()
    time.sleep(1); return jsonify({"success": True, "message": "Ordre de démarrage envoyé."})

@app.route('/stop', methods=['POST'])
def stop_bot_route():
    global bot_state
    if bot_state["thread"] is None or not bot_state["thread"].is_alive(): bot_state["status"] = "Arrêté"; return jsonify({"success": False, "message": "Le bot n'est pas en cours."}), 400
    logging.info("Arrêt du bot demandé...") # Ce log ira au frontend
    bot_state["status"] = "Arrêt..."; bot_state["stop_requested"] = True
    return jsonify({"success": True, "message": "Ordre d'arrêt envoyé."})

# --- NOUVELLE ROUTE POUR LE STREAMING DES LOGS ---
@app.route('/stream_logs')
def stream_logs():
    def generate():
        # Envoyer un message initial pour confirmer la connexion au frontend
        yield f"data: Connexion au flux de logs établie.\n\n"
        logging.info("Client connecté au flux de logs.") # Log pour le backend uniquement
        try:
            while True:
                # Attendre un message de la file d'attente (bloquant)
                try:
                    log_entry = log_queue.get(timeout=1) # Timeout pour vérifier périodiquement
                    # Envoyer au format SSE: "data: message\n\n"
                    yield f"data: {log_entry}\n\n"
                    log_queue.task_done() # Marquer la tâche comme terminée
                except queue.Empty:
                    # Envoyer un commentaire keep-alive pour maintenir la connexion ouverte
                    # si aucun log n'est généré pendant un certain temps
                    yield ": keep-alive\n\n"
                    continue
        except GeneratorExit:
            # Se produit lorsque le client se déconnecte
            logging.info("Client déconnecté du flux de logs.")
        finally:
            # Nettoyage si nécessaire
            pass
    # Retourner une réponse en streaming avec le bon mimetype
    return Response(generate(), mimetype='text/event-stream')
# --- FIN NOUVELLE ROUTE ---


# --- Boucle Principale du Bot ---
def run_bot():
    global bot_state, bot_config
    with config_lock: initial_config = bot_config.copy()
    initial_timeframe_str = initial_config["TIMEFRAME_STR"]
    # Ce log ira au frontend via le QueueHandler
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
        if initial_base_quantity is None: initial_base_quantity = 0.0 # Considérer 0 si erreur
        bot_state["symbol_quantity"] = initial_base_quantity
        logging.info(f"Quantité {bot_state['base_asset']} initiale : {bot_state['symbol_quantity']}") # Frontend
        # --- Fin récupération soldes initiaux ---

        while not bot_state["stop_requested"]:
            with config_lock: current_config = bot_config.copy()
            local_timeframe_str = current_config["TIMEFRAME_STR"]
            local_risk_per_trade = current_config["RISK_PER_TRADE"]
            local_capital_allocation = current_config["CAPITAL_ALLOCATION"]
            local_ema_short = current_config["EMA_SHORT_PERIOD"]; local_ema_long = current_config["EMA_LONG_PERIOD"]
            local_rsi_period = current_config["RSI_PERIOD"]; use_ema_filter = current_config["USE_EMA_FILTER"]
            ema_filter_period = current_config["EMA_FILTER_PERIOD"]
            binance_constant_name = TIMEFRAME_CONSTANT_MAP.get(local_timeframe_str)
            local_timeframe_interval = getattr(BinanceClient, binance_constant_name, None) if binance_constant_name else None
            if local_timeframe_interval is None:
                logging.error(f"Constante Binance non trouvée pour timeframe '{local_timeframe_str}'. Utilisation de 5m par défaut.") # Frontend
                local_timeframe_str = '5m'; local_timeframe_interval = BinanceClient.KLINE_INTERVAL_5MINUTE
            if bot_state["timeframe"] != local_timeframe_str:
                 logging.info(f"Changement de timeframe détecté pour {local_timeframe_str}. Redémarrage conseillé.") # Frontend
                 bot_state["timeframe"] = local_timeframe_str
            try:
                # --- Mise à jour Prix et Soldes ---
                current_price = binance_client_wrapper.get_current_price(SYMBOL)
                if current_price is not None: bot_state["current_price"] = current_price; logging.info(f"Prix actuel {SYMBOL}: {current_price}") # Frontend
                else: logging.warning(f"Impossible de récupérer le prix actuel pour {SYMBOL}") # Frontend

                current_quote_balance = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
                if current_quote_balance is not None and current_quote_balance != bot_state["available_balance"]:
                    logging.info(f"Mise à jour solde {bot_state['quote_asset']} : {current_quote_balance}"); bot_state["available_balance"] = current_quote_balance # Frontend

                current_base_quantity = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
                if current_base_quantity is not None and current_base_quantity != bot_state["symbol_quantity"]:
                    logging.info(f"Mise à jour quantité {bot_state['base_asset']} : {current_base_quantity}"); bot_state["symbol_quantity"] = current_base_quantity # Frontend
                # --- Fin Mise à jour ---

                required_limit = max(local_ema_long, ema_filter_period if use_ema_filter else 0, local_rsi_period) + 5
                klines = binance_client_wrapper.get_klines(SYMBOL, local_timeframe_interval, limit=required_limit)
                if not klines: logging.warning("Aucune donnée kline reçue, attente..."); time.sleep(30); continue # Frontend
                signals_df = strategy.calculate_indicators_and_signals(klines)
                if signals_df is None or signals_df.empty: logging.warning("Impossible de calculer indicateurs/signaux, attente."); time.sleep(30); continue # Frontend
                current_data = signals_df.iloc[-1]

                if not bot_state["in_position"]:
                    # check_entry_conditions logue le signal et le placement d'ordre
                    entered = strategy.check_entry_conditions(current_data, SYMBOL, local_risk_per_trade, local_capital_allocation, bot_state["available_balance"], symbol_info)
                    if entered:
                        bot_state["in_position"] = True
                        # Rafraîchir les deux soldes après une entrée réussie
                        refreshed_quote_balance = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
                        if refreshed_quote_balance is not None: bot_state["available_balance"] = refreshed_quote_balance
                        refreshed_base_quantity = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
                        if refreshed_base_quantity is not None: bot_state["symbol_quantity"] = refreshed_base_quantity
                else:
                    # logging.debug(f"En position pour {SYMBOL}. Vérification sortie...") # DEBUG
                    # closed = strategy.check_exit_conditions(SYMBOL)
                    # if closed: ...
                    pass
                if bot_state["stop_requested"]: break
                interval_seconds = interval_to_seconds(local_timeframe_str)
                if interval_seconds > 0:
                    current_time_s = time.time(); time_to_next_candle_s = interval_seconds - (current_time_s % interval_seconds) + 1
                    sleep_interval = 1; end_sleep = time.time() + time_to_next_candle_s
                    while time.time() < end_sleep and not bot_state["stop_requested"]:
                        time.sleep(min(sleep_interval, max(0, end_sleep - time.time())))
                else: logging.warning(f"Intervalle de sommeil invalide pour {local_timeframe_str}. Attente 60s."); time.sleep(60) # Frontend
            except (BinanceAPIException, BinanceRequestException) as e:
                logging.error(f"Erreur API/Request Binance: {e}") # Frontend
                if isinstance(e, BinanceAPIException) and e.status_code == 401: logging.error("Erreur Auth Binance. Arrêt."); bot_state["status"] = "Erreur Auth"; bot_state["stop_requested"] = True # Frontend
                else: bot_state["status"] = "Erreur API/Req"
                time.sleep(60)
            except Exception as e: logging.exception(f"Erreur inattendue dans run_bot"); bot_state["status"] = "Erreur Interne"; time.sleep(60) # Frontend (avec traceback)
    except Exception as e: logging.exception(f"Erreur majeure lors de l'initialisation de run_bot"); bot_state["status"] = "Erreur Init" # Frontend (avec traceback)
    finally: logging.info("Boucle du bot terminée."); bot_state["status"] = "Arrêté"; bot_state["in_position"] = False; bot_state["thread"] = None # Frontend

# --- Démarrage Application ---
if __name__ == "__main__":
    # Désactiver les logs INFO de Werkzeug (ne pas envoyer au frontend)
    werkzeug_log = logging.getLogger('werkzeug')
    werkzeug_log.setLevel(logging.ERROR)

    logging.info("Démarrage de l'API Flask...") # Ce log ira au frontend
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
