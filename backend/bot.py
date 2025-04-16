import time
import logging
import threading
from flask import Flask, jsonify, request
from flask_cors import CORS
from binance.client import Client as BinanceClient
from binance.exceptions import BinanceAPIException, BinanceRequestException

# Importer les modules locaux
import config
import strategy
import binance_client_wrapper

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Clés API (depuis config.py) ---
try:
    API_KEY = config.BINANCE_API_KEY
    API_SECRET = config.BINANCE_API_SECRET
except AttributeError:
    logging.error("BINANCE_API_KEY ou BINANCE_API_SECRET non trouvées dans config.py.")
    API_KEY = "INVALID_KEY"
    API_SECRET = "INVALID_SECRET"

# --- Paramètres FIXES du Bot ---
SYMBOL = getattr(config, 'SYMBOL', 'BTCUSDT')
# TIMEFRAME_STR et TIMEFRAME_INTERVAL sont maintenant dans bot_config et lus dynamiquement

# --- Liste des Timeframes Valides (pour validation) ---
VALID_TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']

# --- Mapping des Timeframes vers les Constantes Binance ---
TIMEFRAME_CONSTANT_MAP = {
    '1m': 'KLINE_INTERVAL_1MINUTE',
    '3m': 'KLINE_INTERVAL_3MINUTE',
    '5m': 'KLINE_INTERVAL_5MINUTE',
    '15m': 'KLINE_INTERVAL_15MINUTE',
    '30m': 'KLINE_INTERVAL_30MINUTE',
    '1h': 'KLINE_INTERVAL_1HOUR',
    '2h': 'KLINE_INTERVAL_2HOUR',
    '4h': 'KLINE_INTERVAL_4HOUR',
    '6h': 'KLINE_INTERVAL_6HOUR',
    '8h': 'KLINE_INTERVAL_8HOUR',
    '12h': 'KLINE_INTERVAL_12HOUR',
    '1d': 'KLINE_INTERVAL_1DAY',
    '3d': 'KLINE_INTERVAL_3DAY',
    '1w': 'KLINE_INTERVAL_1WEEK',
    '1M': 'KLINE_INTERVAL_1MONTH',
}

# --- État Partagé et Verrou pour la Configuration Dynamique ---
config_lock = threading.Lock()
# Initialiser avec les valeurs de config.py ou des défauts
bot_config = {
    "TIMEFRAME_STR": getattr(config, 'TIMEFRAME', '5m'), # Ajout du Timeframe
    "RISK_PER_TRADE": getattr(config, 'RISK_PER_TRADE', 0.01),
    "CAPITAL_ALLOCATION": getattr(config, 'CAPITAL_ALLOCATION', 0.1),
    # Paramètres de stratégie
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

# --- Initialisation Client Binance ---
client = None
def initialize_binance_client():
    global client
    initialized_client = binance_client_wrapper.get_client()
    if not initialized_client:
        logging.error("Impossible d'initialiser le client Binance via le wrapper.")
        client = None
        return False
    else:
        client = initialized_client
        logging.info("Client Binance initialisé avec succès via le wrapper.")
        return True

# --- Helper Function ---
def interval_to_seconds(interval_str):
    try:
        unit = interval_str[-1].lower()
        value = int(interval_str[:-1])
        if unit == 'm': return value * 60
        elif unit == 'h': return value * 60 * 60
        elif unit == 'd': return value * 60 * 60 * 24
        elif unit == 'w': return value * 60 * 60 * 24 * 7
        elif unit == 'M': return value * 60 * 60 * 24 * 30 # Approximation pour 'M'
        else:
            logging.warning(f"Intervalle non reconnu pour la conversion en secondes: {interval_str}")
            return 0
    except (IndexError, ValueError, TypeError):
         logging.warning(f"Format d'intervalle invalide pour conversion secondes: {interval_str}")
         return 0

# --- État Global du Bot (Statut, Position, etc.) ---
bot_state = {
    "status": "Arrêté",
    "in_position": False,
    "available_balance": 0.0, # Initialiser comme float
    "current_price": 0.0,     # AJOUT: Initialiser le prix
    "symbol": SYMBOL,
    "timeframe": bot_config["TIMEFRAME_STR"], # Initialiser avec la config
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
    # Lire l'état actuel (thread-safe si besoin, mais lecture simple ici)
    status_data = {
        'status': bot_state['status'],
        'symbol': bot_state['symbol'],
        'timeframe': bot_state['timeframe'], # Reflète le timeframe utilisé par le bot en cours
        'in_position': bot_state['in_position'],
        'available_balance': bot_state['available_balance'],
        'current_price': bot_state['current_price'] # AJOUT: Ajouter le prix
    }
    return jsonify(status_data)

@app.route('/parameters', methods=['GET'])
def get_parameters():
    """Retourne les paramètres configurables actuels."""
    with config_lock:
        current_config = bot_config.copy()
    return jsonify(current_config)

@app.route('/parameters', methods=['POST'])
def set_parameters():
    """Met à jour les paramètres configurables."""
    global bot_config
    new_params = request.json
    if not new_params:
        return jsonify({"success": False, "message": "Aucun paramètre fourni."}), 400

    logging.info(f"Tentative de mise à jour des paramètres: {new_params}")
    restart_recommended = False

    # --- Validation Côté Serveur ---
    validated_params = {}
    try:
        # Validation Timeframe
        new_timeframe = str(new_params.get("TIMEFRAME_STR", bot_config["TIMEFRAME_STR"]))
        if new_timeframe not in VALID_TIMEFRAMES:
            raise ValueError(f"TIMEFRAME_STR invalide. Doit être l'un de {VALID_TIMEFRAMES}")
        validated_params["TIMEFRAME_STR"] = new_timeframe
        # Vérifier si le timeframe a changé (pour recommander redémarrage)
        if new_timeframe != bot_config["TIMEFRAME_STR"]:
            restart_recommended = True

        # Validations existantes...
        validated_params["RISK_PER_TRADE"] = float(new_params.get("RISK_PER_TRADE", bot_config["RISK_PER_TRADE"]))
        if not (0 < validated_params["RISK_PER_TRADE"] < 1): raise ValueError("RISK_PER_TRADE doit être entre 0 et 1")

        validated_params["CAPITAL_ALLOCATION"] = float(new_params.get("CAPITAL_ALLOCATION", bot_config["CAPITAL_ALLOCATION"]))
        if not (0 < validated_params["CAPITAL_ALLOCATION"] <= 1): raise ValueError("CAPITAL_ALLOCATION doit être entre 0 et 1")

        validated_params["EMA_SHORT_PERIOD"] = int(new_params.get("EMA_SHORT_PERIOD", bot_config["EMA_SHORT_PERIOD"]))
        if validated_params["EMA_SHORT_PERIOD"] <= 0: raise ValueError("EMA_SHORT_PERIOD doit être > 0")

        validated_params["EMA_LONG_PERIOD"] = int(new_params.get("EMA_LONG_PERIOD", bot_config["EMA_LONG_PERIOD"]))
        if validated_params["EMA_LONG_PERIOD"] <= validated_params["EMA_SHORT_PERIOD"]: raise ValueError("EMA_LONG_PERIOD doit être > EMA_SHORT_PERIOD")

        validated_params["EMA_FILTER_PERIOD"] = int(new_params.get("EMA_FILTER_PERIOD", bot_config["EMA_FILTER_PERIOD"]))
        if validated_params["EMA_FILTER_PERIOD"] <= 0: raise ValueError("EMA_FILTER_PERIOD doit être > 0")

        validated_params["RSI_PERIOD"] = int(new_params.get("RSI_PERIOD", bot_config["RSI_PERIOD"]))
        if validated_params["RSI_PERIOD"] <= 1: raise ValueError("RSI_PERIOD doit être > 1")

        validated_params["RSI_OVERBOUGHT"] = int(new_params.get("RSI_OVERBOUGHT", bot_config["RSI_OVERBOUGHT"]))
        if not (50 < validated_params["RSI_OVERBOUGHT"] <= 100): raise ValueError("RSI_OVERBOUGHT doit être entre 50 et 100")

        validated_params["RSI_OVERSOLD"] = int(new_params.get("RSI_OVERSOLD", bot_config["RSI_OVERSOLD"]))
        if not (0 <= validated_params["RSI_OVERSOLD"] < 50): raise ValueError("RSI_OVERSOLD doit être entre 0 et 50")
        if validated_params["RSI_OVERSOLD"] >= validated_params["RSI_OVERBOUGHT"]: raise ValueError("RSI_OVERSOLD doit être < RSI_OVERBOUGHT")

        validated_params["VOLUME_AVG_PERIOD"] = int(new_params.get("VOLUME_AVG_PERIOD", bot_config["VOLUME_AVG_PERIOD"]))
        if validated_params["VOLUME_AVG_PERIOD"] <= 0: raise ValueError("VOLUME_AVG_PERIOD doit être > 0")

        validated_params["USE_EMA_FILTER"] = bool(new_params.get("USE_EMA_FILTER", bot_config["USE_EMA_FILTER"]))
        validated_params["USE_VOLUME_CONFIRMATION"] = bool(new_params.get("USE_VOLUME_CONFIRMATION", bot_config["USE_VOLUME_CONFIRMATION"]))

    except (ValueError, TypeError) as e:
        logging.error(f"Erreur de validation des paramètres: {e}")
        return jsonify({"success": False, "message": f"Paramètres invalides: {e}"}), 400

    # Appliquer les paramètres validés (thread-safe)
    with config_lock:
        bot_config.update(validated_params)
        logging.info(f"Paramètres mis à jour avec succès: {bot_config}")

    # Mettre à jour les paramètres globaux dans strategy.py (si strategy.py les utilise directement)
    # Note: C'est mieux si strategy.py lit aussi depuis bot_config ou reçoit les params en argument
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
    if restart_recommended:
        message += " Un redémarrage du bot est conseillé pour appliquer le nouveau timeframe."

    return jsonify({"success": True, "message": message})


@app.route('/start', methods=['POST'])
def start_bot_route():
    global bot_state
    if bot_state["thread"] is not None and bot_state["thread"].is_alive():
        logging.warning("Tentative de démarrage du bot alors qu'il est déjà en cours.")
        return jsonify({"success": False, "message": "Le bot est déjà en cours."}), 400

    if not initialize_binance_client():
         return jsonify({"success": False, "message": "Échec de l'initialisation du client Binance."}), 500

    logging.info("Démarrage du bot demandé...")
    bot_state["status"] = "Démarrage..."
    bot_state["stop_requested"] = False
    bot_state["thread"] = threading.Thread(target=run_bot, daemon=True)
    bot_state["thread"].start()

    time.sleep(1)
    return jsonify({"success": True, "message": "Ordre de démarrage envoyé."})

@app.route('/stop', methods=['POST'])
def stop_bot_route():
    global bot_state
    if bot_state["thread"] is None or not bot_state["thread"].is_alive():
        logging.warning("Tentative d'arrêt du bot alors qu'il n'est pas en cours.")
        bot_state["status"] = "Arrêté"
        return jsonify({"success": False, "message": "Le bot n'est pas en cours."}), 400

    logging.info("Arrêt du bot demandé...")
    bot_state["status"] = "Arrêt..."
    bot_state["stop_requested"] = True

    return jsonify({"success": True, "message": "Ordre d'arrêt envoyé."})


# --- Boucle Principale du Bot ---
def run_bot():
    global bot_state, bot_config

    # Lire la config initiale pour le démarrage
    with config_lock:
        initial_config = bot_config.copy()
    initial_timeframe_str = initial_config["TIMEFRAME_STR"]

    logging.info(f"Démarrage effectif du bot pour {SYMBOL} sur {initial_timeframe_str}")
    bot_state["status"] = "En cours"
    bot_state["timeframe"] = initial_timeframe_str # Mettre à jour l'état affiché

    try:
        initial_balance = binance_client_wrapper.get_account_balance('USDT')
        if initial_balance is None: raise Exception("Impossible de récupérer le solde initial.")
        bot_state["available_balance"] = initial_balance
        logging.info(f"Solde USDT initial : {bot_state['available_balance']}")

        symbol_info = binance_client_wrapper.get_symbol_info(SYMBOL)
        if not symbol_info: raise Exception(f"Impossible de récupérer les infos pour {SYMBOL}.")

        # --- Boucle principale ---
        while not bot_state["stop_requested"]:
            # Lire la configuration actuelle au début de chaque cycle
            with config_lock:
                current_config = bot_config.copy()

            # --- Utiliser les paramètres de current_config ---
            local_timeframe_str = current_config["TIMEFRAME_STR"]
            local_risk_per_trade = current_config["RISK_PER_TRADE"]
            local_capital_allocation = current_config["CAPITAL_ALLOCATION"]
            local_ema_short = current_config["EMA_SHORT_PERIOD"]
            local_ema_long = current_config["EMA_LONG_PERIOD"]
            local_rsi_period = current_config["RSI_PERIOD"]
            use_ema_filter = current_config["USE_EMA_FILTER"]
            ema_filter_period = current_config["EMA_FILTER_PERIOD"]
            # ... etc ...

            # Dériver l'intervalle Binance dynamiquement en utilisant le mapping
            binance_constant_name = TIMEFRAME_CONSTANT_MAP.get(local_timeframe_str)
            local_timeframe_interval = getattr(BinanceClient, binance_constant_name, None) if binance_constant_name else None

            # Fallback si la constante n'est pas trouvée
            if local_timeframe_interval is None:
                logging.error(f"Constante Binance non trouvée pour timeframe '{local_timeframe_str}'. Utilisation de 5m par défaut.")
                local_timeframe_str = '5m' # Fallback string
                local_timeframe_interval = BinanceClient.KLINE_INTERVAL_5MINUTE # Fallback interval

            # Mettre à jour l'état pour l'affichage si le timeframe a changé depuis le dernier cycle
            if bot_state["timeframe"] != local_timeframe_str:
                 logging.info(f"Changement de timeframe détecté en cours de route pour {local_timeframe_str}. Un redémarrage est conseillé.")
                 bot_state["timeframe"] = local_timeframe_str # Mettre à jour l'affichage

            try:
                # --- Récupérer le prix actuel ---
                current_price = binance_client_wrapper.get_current_price(SYMBOL)
                if current_price is not None:
                    bot_state["current_price"] = current_price
                    logging.info(f"Prix actuel {SYMBOL}: {current_price}")
                else:
                    logging.info(f"Impossible de récupérer le prix actuel pour {SYMBOL}")
                # --- Fin récupération prix ---

                current_balance = binance_client_wrapper.get_account_balance('USDT')
                if current_balance is not None and current_balance != bot_state["available_balance"]:
                    logging.info(f"Mise à jour solde USDT : {current_balance}")
                    bot_state["available_balance"] = current_balance

                # 1. Récupérer Klines avec le timeframe actuel
                required_limit = max(local_ema_long, ema_filter_period if use_ema_filter else 0, local_rsi_period) + 5
                klines = binance_client_wrapper.get_klines(SYMBOL, local_timeframe_interval, limit=required_limit) # Utiliser l'intervalle local
                if not klines:
                    logging.warning("Aucune donnée kline reçue, attente...")
                    time.sleep(30)
                    continue

                # 2. Calculer Indicateurs/Signaux (strategy.py utilise les globales mises à jour)
                signals_df = strategy.calculate_indicators_and_signals(klines)
                if signals_df is None or signals_df.empty:
                    logging.warning("Impossible de calculer indicateurs/signaux, attente.")
                    time.sleep(30)
                    continue

                current_data = signals_df.iloc[-1]
                # Le log du signal est maintenant dans check_entry_conditions
                # logging.debug(f"Dernière bougie ({current_data['Close time']}): Close={current_data['Close']}, Signal={current_data['signal']}")

                # 3. Logique d'Entrée/Sortie
                if not bot_state["in_position"]:
                    entered = strategy.check_entry_conditions(
                        current_data, SYMBOL, local_risk_per_trade,
                        local_capital_allocation, bot_state["available_balance"], symbol_info
                    )
                    if entered:
                        bot_state["in_position"] = True
                        # Rafraîchir le solde immédiatement après une entrée réussie
                        refreshed_balance = binance_client_wrapper.get_account_balance('USDT')
                        if refreshed_balance is not None: bot_state["available_balance"] = refreshed_balance
                else:
                    logging.debug(f"En position pour {SYMBOL}. Vérification sortie...")
                    # closed = strategy.check_exit_conditions(SYMBOL)
                    # if closed:
                    #     bot_state["in_position"] = False
                    #     refreshed_balance = binance_client_wrapper.get_account_balance('USDT')
                    #     if refreshed_balance is not None: bot_state["available_balance"] = refreshed_balance
                    pass

                # 4. Attendre la prochaine bougie en utilisant le timeframe actuel
                if bot_state["stop_requested"]: break

                logging.debug("Cycle terminé, calcul attente prochaine bougie...")
                interval_seconds = interval_to_seconds(local_timeframe_str) # Utiliser le timeframe local
                if interval_seconds > 0:
                    current_time_s = time.time()
                    # +1 pour s'assurer qu'on attend après la fin de la bougie
                    time_to_next_candle_s = interval_seconds - (current_time_s % interval_seconds) + 1
                    logging.debug(f"Attente de {time_to_next_candle_s:.2f}s...")
                    sleep_interval = 1 # Vérifier l'arrêt toutes les secondes
                    end_sleep = time.time() + time_to_next_candle_s
                    while time.time() < end_sleep and not bot_state["stop_requested"]:
                        # Dormir le minimum entre l'intervalle restant et sleep_interval
                        time.sleep(min(sleep_interval, max(0, end_sleep - time.time())))
                else:
                    logging.warning(f"Intervalle de sommeil invalide calculé pour {local_timeframe_str}. Attente de 60s.")
                    time.sleep(60) # Fallback

            except (BinanceAPIException, BinanceRequestException) as e:
                logging.error(f"Erreur API/Request Binance: {e}")
                if isinstance(e, BinanceAPIException) and e.status_code == 401:
                    logging.error("Erreur d'authentification Binance. Arrêt du bot.")
                    bot_state["status"] = "Erreur Auth"
                    bot_state["stop_requested"] = True
                else:
                    bot_state["status"] = "Erreur API/Req"
                time.sleep(60) # Attendre avant de réessayer en cas d'erreur API
            except Exception as e:
                logging.exception(f"Erreur inattendue dans run_bot")
                bot_state["status"] = "Erreur Interne"
                time.sleep(60) # Attendre aussi en cas d'erreur interne

    except Exception as e:
        logging.exception(f"Erreur majeure lors de l'initialisation de run_bot")
        bot_state["status"] = "Erreur Init"

    finally:
        logging.info("Boucle du bot terminée.")
        bot_state["status"] = "Arrêté"
        bot_state["in_position"] = False
        bot_state["thread"] = None

# --- Démarrage Application ---
if __name__ == "__main__":
    logging.info("Démarrage de l'API Flask...")
    # Utiliser debug=False et use_reloader=False en production et lors de l'utilisation de threads
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

