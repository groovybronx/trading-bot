import time
import logging
import threading
from flask import Flask, jsonify, request # Added request
from flask_cors import CORS
from binance.client import Client as BinanceClient # Renommer pour éviter conflit
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

# --- Paramètres du Bot ---
SYMBOL = getattr(config, 'SYMBOL', 'BTCUSDT')
TIMEFRAME_STR = getattr(config, 'TIMEFRAME', '5m')
TIMEFRAME_INTERVAL = getattr(BinanceClient, f'KLINE_INTERVAL_{TIMEFRAME_STR.upper()}', BinanceClient.KLINE_INTERVAL_5MINUTE)
RISK_PER_TRADE = getattr(config, 'RISK_PER_TRADE', 0.01)
CAPITAL_ALLOCATION = getattr(config, 'CAPITAL_ALLOCATION', 0.1)

# --- Initialisation Client Binance ---
# Client variable is likely managed *within* binance_client_wrapper after initialization
client = None # This global might not even be strictly necessary if wrapper handles all access
def initialize_binance_client():
    global client
    # Assuming binance_client_wrapper.get_client() initializes and potentially stores
    # the client instance internally within the wrapper module.
    # It might return the client instance or just True/False for success.
    initialized_client = binance_client_wrapper.get_client() # Appel sans arguments
    if not initialized_client:
        logging.error("Impossible d'initialiser le client Binance via le wrapper.")
        client = None # Ensure global client is None on failure
        return False
    else:
        # If the wrapper returns the client, store it globally (optional, depends on wrapper design)
        # If the wrapper just returns True/None, this line might not be needed.
        client = initialized_client # Store the client if returned by wrapper
        logging.info("Client Binance initialisé avec succès via le wrapper.")
        return True

# --- Helper Function ---
def interval_to_seconds(interval_str):
    """Converts Binance interval string to seconds."""
    try:
        unit = interval_str[-1].lower()
        value = int(interval_str[:-1])
        if unit == 'm':
            return value * 60
        elif unit == 'h':
            return value * 60 * 60
        elif unit == 'd':
            return value * 60 * 60 * 24
        elif unit == 'w':
            return value * 60 * 60 * 24 * 7
        else:
            logging.warning(f"Intervalle non reconnu pour la conversion en secondes: {interval_str}")
            return 0
    except (IndexError, ValueError):
         logging.warning(f"Format d'intervalle invalide: {interval_str}")
         return 0

# --- État Global du Bot ---
bot_state = {
    "status": "Arrêté",
    "in_position": False,
    "available_balance": 0,
    "symbol": SYMBOL,
    "timeframe": TIMEFRAME_STR,
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
    # Optionally update balance here, assuming wrapper uses its internal client
    # if bot_state["status"] == "En cours":
    #     try:
    #         balance = binance_client_wrapper.get_account_balance('USDT') # No client passed
    #         if balance is not None:
    #              bot_state["available_balance"] = balance
    #     except Exception as e:
    #         logging.error(f"Erreur MAJ solde dans /status: {e}")
    #         bot_state["status"] = "Erreur Solde"

    status_data = {
        'status': bot_state['status'],
        'symbol': bot_state['symbol'],
        'timeframe': bot_state['timeframe'],
        'in_position': bot_state['in_position'],
        'available_balance': bot_state['available_balance']
    }
    return jsonify(status_data)

@app.route('/start', methods=['POST'])
def start_bot_route():
    """Démarre le thread du bot s'il n'est pas déjà en cours."""
    global bot_state
    if bot_state["thread"] is not None and bot_state["thread"].is_alive():
        logging.warning("Tentative de démarrage du bot alors qu'il est déjà en cours.")
        return jsonify({"success": False, "message": "Le bot est déjà en cours."}), 400

    # Attempt to initialize client via wrapper
    if not initialize_binance_client():
         return jsonify({"success": False, "message": "Échec de l'initialisation du client Binance."}), 500

    # No need to check global client if wrapper manages it internally,
    # initialize_binance_client returning True is enough confirmation.

    logging.info("Démarrage du bot demandé...")
    bot_state["status"] = "Démarrage..."
    bot_state["stop_requested"] = False
    # PYLANCE ERROR FIX: Removed args=(client,) as run_bot no longer takes client
    bot_state["thread"] = threading.Thread(target=run_bot, daemon=True)
    bot_state["thread"].start()

    time.sleep(1)
    return jsonify({"success": True, "message": "Ordre de démarrage envoyé."})

@app.route('/stop', methods=['POST'])
def stop_bot_route():
    """Demande l'arrêt du thread du bot."""
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
# PYLANCE ERROR FIX: Removed bot_client parameter
def run_bot():
    global bot_state

    # No need to check bot_client parameter anymore.
    # Assume initialize_binance_client() succeeded if we got here.

    logging.info(f"Démarrage effectif du bot pour {SYMBOL} sur {TIMEFRAME_STR}")
    bot_state["status"] = "En cours"

    try:
        # Récupérer le solde initial et les infos symbole using wrapper's internal client
        # PYLANCE ERROR FIX (Line 185): Removed bot_client argument
        initial_balance = binance_client_wrapper.get_account_balance('USDT')
        if initial_balance is None: # Handle potential failure from wrapper
             raise Exception("Impossible de récupérer le solde initial.")
        bot_state["available_balance"] = initial_balance
        logging.info(f"Solde USDT initial : {bot_state['available_balance']}")

        # PYLANCE ERROR FIX (Line 187): Removed bot_client argument
        symbol_info = binance_client_wrapper.get_symbol_info(SYMBOL)
        if not symbol_info:
            raise Exception(f"Impossible de récupérer les infos pour {SYMBOL}.")

        # --- Boucle principale ---
        while not bot_state["stop_requested"]:
            try:
                # Mettre à jour le solde périodiquement
                # PYLANCE ERROR FIX (Line 195): Removed bot_client argument
                current_balance = binance_client_wrapper.get_account_balance('USDT')
                if current_balance is not None and current_balance != bot_state["available_balance"]:
                    logging.info(f"Mise à jour solde USDT : {current_balance}")
                    bot_state["available_balance"] = current_balance

                # 1. Récupérer Klines
                required_limit = max(strategy.EMA_LONG_PERIOD, strategy.EMA_FILTER_PERIOD if strategy.USE_EMA_FILTER else 0, strategy.RSI_PERIOD) + 5
                # PYLANCE ERROR FIX (Line 202): Removed client=bot_client keyword argument
                klines = binance_client_wrapper.get_klines(SYMBOL, TIMEFRAME_INTERVAL, limit=required_limit)
                if not klines:
                    logging.warning("Aucune donnée kline reçue, attente...")
                    time.sleep(30)
                    continue

                # 2. Calculer Indicateurs/Signaux
                signals_df = strategy.calculate_indicators_and_signals(klines)
                if signals_df is None or signals_df.empty:
                    logging.warning("Impossible de calculer indicateurs/signaux, attente.")
                    time.sleep(30)
                    continue

                current_data = signals_df.iloc[-1]
                logging.debug(f"Dernière bougie ({current_data['Close time']}): Close={current_data['Close']}, Signal={current_data['signal']}")

                # 3. Logique d'Entrée/Sortie
                if not bot_state["in_position"]:
                    # PYLANCE ERROR FIX (Line 217): Removed bot_client argument
                    # Assume strategy function calls wrapper if it needs client interaction
                    entered = strategy.check_entry_conditions(current_data, SYMBOL, RISK_PER_TRADE, CAPITAL_ALLOCATION, bot_state["available_balance"], symbol_info)
                    if entered:
                        bot_state["in_position"] = True
                        logging.info(f"Entrée en position pour {SYMBOL}.")
                        # Refresh balance after entry
                        # PYLANCE ERROR FIX (Line 226): Removed bot_client argument
                        refreshed_balance = binance_client_wrapper.get_account_balance('USDT')
                        if refreshed_balance is not None:
                             bot_state["available_balance"] = refreshed_balance
                else:
                    logging.debug(f"En position pour {SYMBOL}. Vérification sortie...")
                    # Assume strategy function calls wrapper if it needs client interaction
                    # closed = strategy.check_and_manage_exit(SYMBOL, current_data, bot_state) # No client passed
                    # if closed:
                    #     bot_state["in_position"] = False
                    #     logging.info("Position clôturée.")
                    #     # Refresh balance after exit
                    #     refreshed_balance = binance_client_wrapper.get_account_balance('USDT') # No client passed
                    #     if refreshed_balance is not None:
                    #          bot_state["available_balance"] = refreshed_balance
                    pass # Placeholder

                # 4. Attendre la prochaine bougie
                if bot_state["stop_requested"]: break

                logging.debug("Cycle terminé, calcul attente prochaine bougie...")
                interval_seconds = interval_to_seconds(TIMEFRAME_STR)
                if interval_seconds > 0:
                    current_time_s = time.time()
                    time_to_next_candle_s = interval_seconds - (current_time_s % interval_seconds) + 1
                    logging.debug(f"Attente de {time_to_next_candle_s:.2f}s...")
                    sleep_interval = 1
                    end_sleep = time.time() + time_to_next_candle_s
                    while time.time() < end_sleep and not bot_state["stop_requested"]:
                        time.sleep(min(sleep_interval, end_sleep - time.time()))
                else:
                    time.sleep(60)

            except (BinanceAPIException, BinanceRequestException) as e:
                logging.error(f"Erreur API/Request Binance: {e}")
                if isinstance(e, BinanceAPIException) and e.status_code == 401:
                    logging.error("Erreur d'authentification Binance (clés API invalides?). Arrêt du bot.")
                    bot_state["status"] = "Erreur Auth"
                    bot_state["stop_requested"] = True
                else:
                    bot_state["status"] = "Erreur API/Req"
                time.sleep(60)
            except Exception as e:
                logging.exception(f"Erreur inattendue dans run_bot")
                bot_state["status"] = "Erreur Interne"
                time.sleep(60)

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
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
