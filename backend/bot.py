import logging
import queue # Importer queue
import threading
import time
import json
import os
from typing import Optional, Dict, Any, List
from decimal import Decimal, InvalidOperation # Garder Decimal pour SL/TP

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from binance.client import Client as BinanceClient
from binance import ThreadedWebsocketManager
from binance.exceptions import BinanceAPIException, BinanceRequestException

import config
import strategy
import binance_client_wrapper

# --- Configuration du Logging ---
log_queue = queue.Queue()
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
    def emit(self, record):
        # Envoyer INFO et plus au frontend
        if record.levelno >= logging.INFO:
            log_entry = self.format(record)
            self.log_queue.put(log_entry)

log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
# !! Niveau de log normal (peut être remis à DEBUG si besoin) !!
# log_level = logging.DEBUG
log_level = logging.INFO # <-- Niveau normal
stream_handler = logging.StreamHandler(); stream_handler.setFormatter(log_formatter)
queue_handler = QueueHandler(log_queue); queue_handler.setFormatter(log_formatter)
logger = logging.getLogger(); logger.setLevel(log_level)
if logger.hasHandlers(): logger.handlers.clear()
logger.addHandler(stream_handler); logger.addHandler(queue_handler)


# --- Constantes et Configuration ---
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
config_lock = threading.Lock()
# Queue pour le prix uniquement (le compteur n'est plus nécessaire)
latest_price_queue = queue.Queue(maxsize=1)

bot_config = {
    "TIMEFRAME_STR": getattr(config, 'TIMEFRAME', '1m'),
    "RISK_PER_TRADE": getattr(config, 'RISK_PER_TRADE', 0.01),
    "CAPITAL_ALLOCATION": getattr(config, 'CAPITAL_ALLOCATION', 1.0),
    "STOP_LOSS_PERCENTAGE": getattr(config, 'STOP_LOSS_PERCENTAGE', 0.02),
    "TAKE_PROFIT_PERCENTAGE": getattr(config, 'TAKE_PROFIT_PERCENTAGE', 0.05),
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
DATA_FILENAME = "bot_data.json"
bot_state = {
    "status": "Arrêté", "in_position": False, "available_balance": 0.0,
    # current_price sera lu depuis la queue dans /status
    "symbol_quantity": 0.0, "base_asset": "",
    "quote_asset": "USDT", "symbol": SYMBOL, "timeframe": bot_config["TIMEFRAME_STR"],
    "thread": None, "stop_requested": False, "entry_details": None,
    "order_history": [], "max_history_length": 100,
    "websocket_manager": None, "websocket_stream_name": None,
}

# --- Fonctions de Persistance ---
def save_data():
    with config_lock:
        state_copy = {
            "in_position": bot_state.get("in_position", False),
            "entry_details": bot_state.get("entry_details", None)
        }
        history_copy = list(bot_state.get("order_history", []))
    data_to_save = {"state": state_copy, "history": history_copy}
    try:
        with open(DATA_FILENAME, 'w') as f:
            json.dump(data_to_save, f, indent=4)
        logger.debug(f"Données sauvegardées dans {DATA_FILENAME}") # Garder DEBUG ici peut être utile
        return True
    except IOError as e:
        logger.error(f"Erreur IO sauvegarde {DATA_FILENAME}: {e}")
        return False
    except Exception as e:
        logger.exception(f"Erreur inattendue sauvegarde données: {e}")
        return False

def load_data() -> Optional[Dict[str, Any]]:
    if not os.path.exists(DATA_FILENAME):
        logger.info(f"{DATA_FILENAME} non trouvé.")
        return None
    try:
        with open(DATA_FILENAME, 'r') as f:
            loaded_data = json.load(f)
        logger.info(f"Données chargées depuis {DATA_FILENAME}")
        return loaded_data
    except (IOError, json.JSONDecodeError) as e:
        logger.error(f"Erreur chargement/décodage {DATA_FILENAME}: {e}.")
        return None
    except Exception as e:
        logger.exception(f"Erreur inattendue chargement données: {e}")
        return None

# --- Fonctions Utilitaires ---
def interval_to_seconds(interval_str: str) -> int:
    try:
        unit = interval_str[-1].lower()
        value = int(interval_str[:-1])
        if unit == 's': return value
        elif unit == 'm': return value * 60
        elif unit == 'h': return value * 3600
        elif unit == 'd': return value * 86400
        elif unit == 'w': return value * 604800
        elif unit == 'M': return value * 2592000 # Approx 30j
        else: logger.warning(f"Intervalle non reconnu: {interval_str}"); return 0
    except (IndexError, ValueError, TypeError):
        logger.warning(f"Format intervalle invalide: {interval_str}")
        return 0

# --- Flask App ---
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Fonction de Sortie Centralisée ---
def execute_exit(reason: str) -> Optional[Dict[str, Any]]:
    global bot_state
    order_details = None
    performance_pct = None
    should_save = False
    symbol = bot_state.get("symbol", SYMBOL)

    with config_lock:
        if not bot_state.get("in_position", False):
            logger.debug(f"Tentative de sortie ({reason}) ignorée car déjà hors position.")
            return None

        logger.info(f"Déclenchement de la sortie pour raison: {reason}")
        entry_details_copy = bot_state.get("entry_details")
        qty_to_sell = entry_details_copy.get("quantity") if entry_details_copy else bot_state.get("symbol_quantity", 0.0)

        if qty_to_sell is None or qty_to_sell <= 0:
            logger.error(f"Erreur critique: En position mais qté à vendre ({qty_to_sell}) invalide. Sortie annulée.")
            return None

        symbol_info = binance_client_wrapper.get_symbol_info(symbol)
        if not symbol_info:
             logger.error(f"Impossible de récupérer symbol_info pour {symbol} lors de la sortie. Sortie annulée.")
             return None

        formatted_qty_to_sell = strategy.format_quantity(qty_to_sell, symbol_info)
        if formatted_qty_to_sell <= 0:
            logger.error(f"Qté à vendre ({qty_to_sell}) formatée à 0 ou invalide. Sortie annulée.")
            return None

        logger.info(f"Tentative de vente MARKET de {formatted_qty_to_sell} {symbol}...")
        order_details = binance_client_wrapper.place_order(
            symbol=symbol, side='SELL', quantity=formatted_qty_to_sell, order_type='MARKET'
        )

        if order_details:
            logger.info(f"Ordre de VENTE (sortie) placé. OrderId: {order_details.get('orderId')}")
            if entry_details_copy:
                try:
                    exit_qty = float(order_details.get('executedQty', 0))
                    exit_quote_qty = float(order_details.get('cummulativeQuoteQty', 0))
                    entry_price = entry_details_copy.get('avg_price')
                    if exit_qty > 0 and entry_price is not None and entry_price > 0:
                        avg_exit_price = exit_quote_qty / exit_qty
                        performance_pct = ((avg_exit_price / entry_price) - 1) * 100
                        logger.info(f"Performance calculée: {performance_pct:.2f}%")
                    else:
                        logger.warning("Impossible de calculer perf (données sortie/entrée invalides).")
                except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
                    logger.error(f"Erreur calcul perf sortie: {e}")
            else:
                logger.warning("Détails entrée non trouvés pour calcul perf sortie.")

            bot_state["in_position"] = False
            bot_state["entry_details"] = None
            should_save = True

            try:
                simplified_order = {
                    "timestamp": order_details.get('transactTime', int(time.time() * 1000)),
                    "orderId": order_details.get('orderId'), "symbol": order_details.get('symbol'),
                    "side": order_details.get('side'), "type": order_details.get('type'),
                    "origQty": order_details.get('origQty'), "executedQty": order_details.get('executedQty'),
                    "cummulativeQuoteQty": order_details.get('cummulativeQuoteQty'),
                    "price": order_details.get('price'), "status": order_details.get('status'),
                    "performance_pct": performance_pct
                }
                bot_state['order_history'].append(simplified_order)
                current_len = len(bot_state['order_history'])
                max_len = bot_state['max_history_length']
                if current_len > max_len:
                    bot_state['order_history'] = bot_state['order_history'][-max_len:]
                logger.info(f"Ordre sortie {simplified_order.get('orderId', 'N/A')} ajouté à l'historique.")
                if performance_pct is not None:
                    logger.info(f"  Performance enregistrée: {performance_pct:.2f}%")
            except Exception as hist_err:
                logger.error(f"Erreur ajout ordre sortie à historique: {hist_err}")

            logger.info("Rafraîchissement des soldes après sortie...")
            refreshed_quote = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
            refreshed_base = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
            if refreshed_quote is not None:
                bot_state["available_balance"] = refreshed_quote
            if refreshed_base is not None:
                bot_state["symbol_quantity"] = refreshed_base
        else:
            logger.error(f"Échec placement ordre VENTE (sortie) pour {symbol}.")
            should_save = False

    if should_save:
        save_data()

    return order_details

# --- Gestionnaire de Messages WebSocket ---
def process_ticker_message(msg: Dict[str, Any]):
    """
    Callback pour traiter les messages du WebSocket (@miniTicker - format direct).
    Met à jour la queue de prix et vérifie SL/TP.
    """
    global latest_price_queue, bot_state, bot_config # Accès global nécessaire
    # logger.debug(f"Raw WS message: {msg}") # Garder commenté sauf si besoin absolu

    try:
        # --- Vérification pour Stream Unique (@miniTicker) ---
        if isinstance(msg, dict) and 'e' in msg and msg.get('e') == '24hrMiniTicker' and 'c' in msg and 's' in msg:
            received_symbol = msg['s']
            # logger.debug(f"Processing miniTicker for {received_symbol}") # Log DEBUG optionnel

            # --- Logique principale de traitement ---
            try:
                # 1. Conversion du prix (float pour la queue, Decimal pour SL/TP)
                try:
                    current_price_str = msg['c']
                    current_price = float(current_price_str)
                    current_price_decimal = Decimal(current_price_str) # Pour précision SL/TP
                    # logger.debug(f"Price conversion OK: {current_price}") # Log DEBUG optionnel
                except (ValueError, TypeError, InvalidOperation) as conv_err:
                    logger.error(f"Price conversion FAILED: {msg.get('c')}, Error: {conv_err}")
                    return # Arrêter le traitement de ce message

                # 2. Mise en queue du prix (float)
                try:
                    # logger.debug(f"Attempting put_nowait with price {current_price}") # Log DEBUG optionnel
                    latest_price_queue.put_nowait(current_price)
                    # logger.debug(f"--- SUCCESS: put_nowait DONE ---") # Log DEBUG optionnel
                except queue.Full:
                    # Normal avec maxsize=1, l'ancienne valeur est juste écrasée
                    pass
                except Exception as put_err:
                    # Erreur inattendue lors de la mise en queue
                    logger.exception("!!! UNEXPECTED ERROR during put_nowait !!!")

                # 3. Vérification SL/TP (Réactivée)
                # Nécessite de lire l'état (sous verrou)
                with config_lock:
                    # Vérifier si on est en position et si les détails d'entrée existent
                    if bot_state.get("in_position", False) and bot_state.get("entry_details"):
                        entry_details = bot_state["entry_details"]
                        local_config = bot_config.copy() # Copier la config pour éviter modif concurrente

                        try:
                            entry_price_decimal = Decimal(str(entry_details.get("avg_price", 0.0)))
                            sl_percent = Decimal(str(local_config.get("STOP_LOSS_PERCENTAGE", 0.0)))
                            tp_percent = Decimal(str(local_config.get("TAKE_PROFIT_PERCENTAGE", 0.0)))

                            # Vérifier Stop Loss
                            if entry_price_decimal > 0 and sl_percent > 0:
                                stop_loss_level = entry_price_decimal * (Decimal(1) - sl_percent)
                                if current_price_decimal <= stop_loss_level:
                                    logger.info(f"!!! STOP-LOSS ATTEINT ({current_price_decimal:.4f} <= {stop_loss_level:.4f}) pour {received_symbol} !!!")
                                    # Lancer la sortie dans un thread séparé pour ne pas bloquer le WS
                                    threading.Thread(target=execute_exit, args=("Stop-Loss",), daemon=True).start()
                                    # Important: Ne pas vérifier TP si SL est atteint dans le même message
                                    return # Sortir après avoir lancé le thread SL

                            # Vérifier Take Profit (seulement si SL non atteint)
                            if entry_price_decimal > 0 and tp_percent > 0:
                                take_profit_level = entry_price_decimal * (Decimal(1) + tp_percent)
                                if current_price_decimal >= take_profit_level:
                                    logger.info(f"!!! TAKE-PROFIT ATTEINT ({current_price_decimal:.4f} >= {take_profit_level:.4f}) pour {received_symbol} !!!")
                                    # Lancer la sortie dans un thread séparé
                                    threading.Thread(target=execute_exit, args=("Take-Profit",), daemon=True).start()
                                    # Sortir après avoir lancé le thread TP
                                    return

                        except (InvalidOperation, TypeError, KeyError) as sltp_err:
                             logger.error(f"Erreur interne (SL/TP) pour {received_symbol}: {sltp_err}")
                # --- Fin Vérification SL/TP ---

            except Exception as inner_e:
                 logger.exception(f"Error during core processing for {received_symbol}: {inner_e}")
            # --- Fin Logique principale ---

        # --- Gestion explicite des messages d'erreur WebSocket ---
        elif isinstance(msg, dict) and msg.get('e') == 'error':
             logger.error(f"Received WebSocket error message: {msg}")

        # --- Message non reconnu ou non pertinent ---
        else:
            # Ne pas logger tous les messages non reconnus si trop verbeux
            # logger.warning(f"Unrecognized/Irrelevant WS message format or type: {msg}")
            pass

    except Exception as outer_e:
        # Intercepte toute autre erreur inattendue dans la fonction
        logger.exception(f"!!! CRITICAL Outer Exception in process_ticker_message: {outer_e} !!!")


# --- Routes API ---
@app.route('/status')
def get_status():
    global latest_price_queue
    status_data_to_send = {}
    latest_price = 0.0 # Valeur par défaut si queue vide

    # 1. Lire le dernier prix depuis la queue (non bloquant)
    try:
        last_price_item = None
        while not latest_price_queue.empty():
            last_price_item = latest_price_queue.get_nowait()
        if last_price_item is not None:
            latest_price = last_price_item
            # logger.debug(f"API /status - Got price from queue: {latest_price}") # DEBUG optionnel
        # else:
            # logger.debug("API /status - Price queue was empty.") # DEBUG optionnel
    except queue.Empty:
        # logger.debug("API /status - Price queue was empty (caught exception).") # DEBUG optionnel
        pass # Garder latest_price à 0.0
    except Exception as q_err:
        logger.error(f"API /status - Erreur lecture queue: {q_err}")
        # Garder latest_price à 0.0

    # 2. Récupérer le reste de l'état (moins volatile) sous verrou
    with config_lock:
        state_copy = bot_state.copy()
        status_data_to_send = {
            k: v for k, v in state_copy.items()
            if k not in ['thread', 'stop_requested', 'websocket_manager']
        }

    # 3. Ajouter le dernier prix lu
    status_data_to_send["current_price"] = latest_price

    # 4. Log final (optionnel) et envoi
    # logger.debug(f"API /status - Final data being sent: {status_data_to_send}") # DEBUG optionnel
    return jsonify(status_data_to_send)

@app.route('/parameters', methods=['GET'])
def get_parameters():
    with config_lock:
        current_config = bot_config.copy()
    return jsonify(current_config)

@app.route('/parameters', methods=['POST'])
def set_parameters():
    global bot_config
    new_params = request.json
    if not new_params:
        return jsonify({"success": False, "message": "Aucun paramètre fourni."}), 400

    logger.info(f"Tentative MAJ paramètres: {new_params}")
    restart_recommended = False
    validated_params = {}
    current_tf = bot_config["TIMEFRAME_STR"]

    try:
        new_tf = str(new_params.get("TIMEFRAME_STR", current_tf))
        if new_tf not in VALID_TIMEFRAMES:
            raise ValueError(f"TIMEFRAME_STR invalide: {new_tf}")
        validated_params["TIMEFRAME_STR"] = new_tf
        if new_tf != current_tf:
            restart_recommended = True

        validated_params["RISK_PER_TRADE"] = float(new_params.get("RISK_PER_TRADE", bot_config["RISK_PER_TRADE"]))
        if not (0 < validated_params["RISK_PER_TRADE"] < 1): raise ValueError("RISK_PER_TRADE doit être > 0 et < 1")

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

    except (ValueError, TypeError) as e:
        logger.error(f"Erreur validation paramètres: {e}")
        return jsonify({"success": False, "message": f"Paramètres invalides: {e}"}), 400

    with config_lock:
        bot_config.update(validated_params)
        bot_state["timeframe"] = bot_config["TIMEFRAME_STR"]

    logger.info("Paramètres mis à jour avec succès.")
    message = "Paramètres mis à jour."
    if restart_recommended:
        message += " Redémarrage du bot conseillé pour appliquer le changement de timeframe."
    return jsonify({"success": True, "message": message})

@app.route('/start', methods=['POST'])
def start_bot_route():
    global bot_state # Pas besoin de ws_internal_counter
    with config_lock:
        if bot_state.get("thread") is not None and bot_state["thread"].is_alive():
            return jsonify({"success": False, "message": "Bot déjà en cours."}), 400

        ws_man = bot_state.get("websocket_manager")
        if ws_man is not None:
             logger.warning("Ancien WS Manager détecté au démarrage. Tentative d'arrêt...")
             stream_name = bot_state.get("websocket_stream_name")
             try:
                 if ws_man:
                     if stream_name: ws_man.stop_socket(stream_name)
                     ws_man.stop()
             except Exception as ws_err:
                 logger.error(f"Erreur lors de l'arrêt forcé de l'ancien WS Manager: {ws_err}")
             finally:
                 bot_state["websocket_manager"] = None
                 bot_state["websocket_stream_name"] = None

    if binance_client_wrapper.get_client() is None:
        logger.error("Échec initialisation client Binance. Démarrage annulé.")
        return jsonify({"success": False, "message": "Échec initialisation client Binance."}), 500

    logger.info("Démarrage du bot demandé...")

    loaded_data = load_data()
    with config_lock:
        if loaded_data and isinstance(loaded_data, dict):
            state_data = loaded_data.get("state", {})
            history_data = loaded_data.get("history", [])
            bot_state["in_position"] = state_data.get("in_position", False)
            entry_d = state_data.get("entry_details", None)
            bot_state["entry_details"] = entry_d if isinstance(entry_d, dict) else None
            bot_state["order_history"] = history_data if isinstance(history_data, list) else []
            max_len = bot_state.get('max_history_length', 100)
            if len(bot_state['order_history']) > max_len:
                bot_state['order_history'] = bot_state['order_history'][-max_len:]
                logger.info(f"Historique tronqué à {max_len} éléments.")
            logger.info(f"État et historique restaurés depuis {DATA_FILENAME}.")
            log_pos = f"Oui, Détails: {bot_state['entry_details']}" if bot_state["in_position"] else "Non"
            logger.info(f"  - En position: {log_pos}")
            logger.info(f"  - Ordres chargés: {len(bot_state['order_history'])}")
        else:
            bot_state["in_position"] = False
            bot_state["entry_details"] = None
            bot_state["order_history"] = []
            logger.info("Initialisation avec état et historique vides.")

        # Vider la queue de prix au démarrage
        while not latest_price_queue.empty():
            try:
                latest_price_queue.get_nowait()
            except queue.Empty:
                break
        logger.info("Queue de prix vidée au démarrage.")

        try:
            logger.info("Démarrage WebSocket Manager...")
            use_testnet_ws = getattr(config, 'USE_TESTNET', False)
            bot_state["websocket_manager"] = ThreadedWebsocketManager(
                api_key=config.BINANCE_API_KEY,
                api_secret=config.BINANCE_API_SECRET,
                testnet=use_testnet_ws
            )
            bot_state["websocket_manager"].start()

            stream_symbol = bot_state["symbol"].lower()
            stream_name = bot_state["websocket_manager"].start_symbol_miniticker_socket(
                callback=process_ticker_message,
                symbol=stream_symbol
            )
            bot_state["websocket_stream_name"] = stream_name
            logger.info(f"Connecté au stream WebSocket: {stream_name}")

        except Exception as e:
            logger.exception("Erreur critique lors du démarrage du WebSocket Manager.")
            ws_man_err = bot_state.get("websocket_manager")
            if ws_man_err:
                try: ws_man_err.stop()
                except Exception as stop_err: logger.error(f"Erreur arrêt WS Manager après échec: {stop_err}")
            bot_state["websocket_manager"] = None
            bot_state["websocket_stream_name"] = None
            return jsonify({"success": False, "message": "Erreur démarrage WebSocket."}), 500

        bot_state["status"] = "Démarrage..."
        bot_state["stop_requested"] = False
        bot_state["thread"] = threading.Thread(target=run_bot, daemon=True)
        bot_state["thread"].start()

    time.sleep(1)
    return jsonify({"success": True, "message": "Ordre de démarrage envoyé (Bot et WebSocket)."})

@app.route('/stop', methods=['POST'])
def stop_bot_route():
    global bot_state
    should_stop_ws = False

    with config_lock:
        if bot_state.get("thread") is None or not bot_state["thread"].is_alive():
            bot_state["status"] = "Arrêté"
            if bot_state.get("websocket_manager") is not None:
                logger.warning("Thread inactif mais WS Manager actif? Tentative arrêt WS.")
                should_stop_ws = True
            else:
                return jsonify({"success": False, "message": "Bot non en cours d'exécution."}), 400
        else:
            logger.info("Arrêt du bot demandé...")
            bot_state["status"] = "Arrêt en cours..."
            bot_state["stop_requested"] = True
            should_stop_ws = True

    ws_man_to_stop = bot_state.get("websocket_manager")
    stream_name_to_stop = bot_state.get("websocket_stream_name")

    if should_stop_ws and ws_man_to_stop:
        logger.info("Arrêt du WebSocket Manager...")
        try:
            if ws_man_to_stop:
                if stream_name_to_stop:
                    ws_man_to_stop.stop_socket(stream_name_to_stop)
                    logger.info(f"Stream WebSocket {stream_name_to_stop} arrêté.")
                ws_man_to_stop.stop()
                logger.info("Ordre d'arrêt envoyé au WebSocket Manager.")
        except Exception as e:
            logger.error(f"Erreur lors de l'arrêt du WebSocket Manager: {e}")
        finally:
             with config_lock:
                 if bot_state.get("websocket_manager") == ws_man_to_stop:
                     bot_state["websocket_manager"] = None
                     bot_state["websocket_stream_name"] = None

    return jsonify({"success": True, "message": "Ordre d'arrêt envoyé."})

@app.route('/stream_logs')
def stream_logs():
    def generate():
        yield f"data: Connexion au flux de logs établie.\n\n"
        logger.info("Client connecté au flux de logs SSE.")
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
            logger.info("Client déconnecté du flux de logs SSE.")
        finally:
            pass
    return Response(generate(), mimetype='text/event-stream')

@app.route('/order_history')
def get_order_history():
    with config_lock:
        history_copy = list(bot_state.get('order_history', []))
    return jsonify(history_copy)

# --- Boucle Principale du Bot ---
def run_bot():
    global bot_state, bot_config
    try:
        with config_lock:
            current_run_config = bot_config.copy()
            initial_tf = current_run_config["TIMEFRAME_STR"]
            bot_state["status"] = "En cours"
            bot_state["timeframe"] = initial_tf
            bot_state["symbol"] = SYMBOL
        logger.info(f"Démarrage effectif du bot pour {SYMBOL} sur timeframe {initial_tf}")

        symbol_info = binance_client_wrapper.get_symbol_info(SYMBOL)
        if not symbol_info:
            raise Exception(f"Impossible de récupérer les informations pour {SYMBOL}. Arrêt.")

        with config_lock:
            bot_state['base_asset'] = symbol_info.get('baseAsset', '')
            bot_state['quote_asset'] = symbol_info.get('quoteAsset', 'USDT')
        if not bot_state['base_asset']:
            raise Exception(f"Asset de base non trouvé pour {SYMBOL}. Arrêt.")
        logger.info(f"Assets détectés: Base='{bot_state['base_asset']}', Quote='{bot_state['quote_asset']}'")

        initial_quote = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
        initial_base = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
        if initial_quote is None:
            logger.error(f"Impossible de lire solde initial {bot_state['quote_asset']}. Utilisation 0.")
            initial_quote = 0.0

        with config_lock:
            bot_state["available_balance"] = initial_quote
            if initial_base is not None:
                 bot_state["symbol_quantity"] = initial_base
            elif bot_state["in_position"]:
                 logger.warning(f"Impossible lire solde initial {bot_state['base_asset']} (en position). Utilisation qté entry_details.")
                 bot_state["symbol_quantity"] = bot_state.get("entry_details", {}).get("quantity", 0.0)
            else:
                 logger.warning(f"Impossible lire solde initial {bot_state['base_asset']} (pas en position). Utilisation 0.")
                 bot_state["symbol_quantity"] = 0.0

        logger.info(f"Solde initial {bot_state['quote_asset']}: {bot_state['available_balance']:.4f}")
        logger.info(f"Quantité initiale {bot_state['base_asset']}: {bot_state['symbol_quantity']:.6f}")

        while not bot_state.get("stop_requested", False):
            try:
                with config_lock:
                    current_config = bot_config.copy()
                    local_in_pos = bot_state["in_position"]
                    local_avail_bal = bot_state["available_balance"]

                local_tf = current_config["TIMEFRAME_STR"]
                local_risk = current_config["RISK_PER_TRADE"]
                local_alloc = current_config["CAPITAL_ALLOCATION"]
                binance_interval = TIMEFRAME_CONSTANT_MAP.get(local_tf)

                if binance_interval is None:
                    logger.error(f"Timeframe '{local_tf}' invalide. Utilisation '1m'.")
                    local_tf = '1m'
                    binance_interval = TIMEFRAME_CONSTANT_MAP['1m']
                    with config_lock:
                        bot_state["timeframe"] = local_tf
                        bot_config["TIMEFRAME_STR"] = local_tf

                periods = [current_config["EMA_LONG_PERIOD"], current_config["RSI_PERIOD"]]
                if current_config["USE_EMA_FILTER"]: periods.append(current_config["EMA_FILTER_PERIOD"])
                if current_config["USE_VOLUME_CONFIRMATION"]: periods.append(current_config["VOLUME_AVG_PERIOD"])
                required_limit = max(periods) + 5
                logger.debug(f"Récupération de {required_limit} klines pour {SYMBOL} ({binance_interval})...")
                klines = binance_client_wrapper.get_klines(SYMBOL, binance_interval, limit=required_limit)

                if not klines:
                    logger.warning("Aucune kline reçue, attente...")
                    time.sleep(min(interval_to_seconds(local_tf) / 2, 30))
                    continue

                logger.debug("Calcul des indicateurs et signaux...")
                signals_df = strategy.calculate_indicators_and_signals(klines, current_config)

                if signals_df is None or signals_df.empty:
                    logger.warning("Échec calcul indicateurs/signaux, attente...")
                    time.sleep(min(interval_to_seconds(local_tf) / 2, 30))
                    continue

                current_data = signals_df.iloc[-1]

                if not local_in_pos:
                    logger.debug("Vérification des conditions d'entrée (indicateurs)...")
                    entry_order = strategy.check_entry_conditions(
                        current_data, SYMBOL, local_risk, local_alloc, local_avail_bal, symbol_info, current_config
                    )
                    if entry_order:
                        logger.info(f"Ordre d'ACHAT placé via indicateur pour {SYMBOL}.")
                        try:
                            exec_qty = float(entry_order.get('executedQty', 0))
                            quote_qty = float(entry_order.get('cummulativeQuoteQty', 0))
                            if exec_qty > 0:
                                avg_price = quote_qty / exec_qty
                                with config_lock:
                                    bot_state["in_position"] = True
                                    bot_state["entry_details"] = {
                                        "order_id": entry_order.get('orderId'),
                                        "avg_price": avg_price,
                                        "quantity": exec_qty,
                                        "timestamp": entry_order.get('transactTime', int(time.time()*1000))
                                        # Ajouter SL/TP calculés ici si besoin pour la vérif WS
                                        # "stop_loss_price": calculated_sl,
                                        # "take_profit_price": calculated_tp
                                    }
                                logger.info(f"Détails d'entrée mis à jour: Prix={avg_price:.4f}, Qté={exec_qty}")

                                logger.info("Rafraîchissement des soldes après entrée...")
                                quote = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
                                base = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
                                with config_lock:
                                    if quote is not None: bot_state["available_balance"] = quote
                                    if base is not None: bot_state["symbol_quantity"] = base

                                simplified = {
                                    "timestamp": entry_order.get('transactTime', int(time.time()*1000)),
                                    "orderId": entry_order.get('orderId'), "symbol": entry_order.get('symbol'),
                                    "side": entry_order.get('side'), "type": entry_order.get('type'),
                                    "origQty": entry_order.get('origQty'), "executedQty": entry_order.get('executedQty'),
                                    "cummulativeQuoteQty": entry_order.get('cummulativeQuoteQty'),
                                    "price": entry_order.get('price'), "status": entry_order.get('status'),
                                    "performance_pct": None
                                }
                                with config_lock:
                                    bot_state['order_history'].append(simplified)
                                    hist_len = len(bot_state['order_history'])
                                    max_len = bot_state['max_history_length']
                                    if hist_len > max_len:
                                        bot_state['order_history'] = bot_state['order_history'][-max_len:]
                                logger.info(f"Ordre d'entrée {simplified.get('orderId','N/A')} ajouté à l'historique.")
                                save_data()
                            else:
                                logger.warning("Ordre d'achat placé mais quantité exécutée nulle.")
                        except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
                            logger.error(f"Erreur traitement détails ordre entrée: {e}.")
                elif local_in_pos:
                    logger.debug("En position. Vérification conditions sortie (indicateurs)...")
                    if strategy.check_exit_conditions(current_data, SYMBOL):
                        logger.info("Signal sortie (indicateur) détecté. Lancement execute_exit...")
                        threading.Thread(target=execute_exit, args=("Signal Indicateur",), daemon=True).start()

                if bot_state.get("stop_requested", False):
                    break

                interval_sec = interval_to_seconds(local_tf)
                if interval_sec > 0:
                    current_time_sec = time.time()
                    next_candle_start_sec = (current_time_sec // interval_sec + 1) * interval_sec
                    wait_time = next_candle_start_sec - current_time_sec + 1
                    logger.debug(f"Attente de {wait_time:.2f}s pour la prochaine bougie {local_tf}...")

                    end_sleep = time.time() + wait_time
                    sleep_interval = 0.5
                    while time.time() < end_sleep and not bot_state.get("stop_requested", False):
                        time.sleep(min(sleep_interval, max(0, end_sleep - time.time())))
                else:
                    logger.warning(f"Intervalle sommeil invalide pour {local_tf}. Attente 60s.")
                    time.sleep(60)

            except (BinanceAPIException, BinanceRequestException) as e:
                logger.error(f"Erreur API/Requête Binance dans boucle principale: {e}")
                if isinstance(e, BinanceAPIException) and e.status_code == 401:
                    logger.error("Erreur Auth Binance. Arrêt bot.")
                    with config_lock:
                        bot_state["status"] = "Erreur Auth"
                        bot_state["stop_requested"] = True
                else:
                    with config_lock: bot_state["status"] = "Erreur API/Req"
                    logger.info("Pause 60s suite erreur API/Requête...")
                    time.sleep(60)
            except Exception as e:
                logger.exception("Erreur inattendue dans boucle run_bot.")
                with config_lock: bot_state["status"] = "Erreur Interne"
                logger.info("Pause 60s suite erreur interne...")
                time.sleep(60)

    except Exception as e:
        logger.exception("Erreur majeure initialisation run_bot.")
        with config_lock:
            bot_state["status"] = "Erreur Init"
            bot_state["stop_requested"] = True

    finally:
        logger.info("Fin exécution run_bot (thread principal).")
        ws_man_final = None
        stream_name_final = None
        with config_lock:
            bot_state["status"] = "Arrêté"
            bot_state["thread"] = None
            ws_man_final = bot_state.get("websocket_manager")
            stream_name_final = bot_state.get("websocket_stream_name")

        if ws_man_final:
            logger.info("Arrêt final WS Manager depuis run_bot...")
            try:
                if ws_man_final:
                    if stream_name_final: ws_man_final.stop_socket(stream_name_final)
                    ws_man_final.stop()
            except Exception as e:
                logger.error(f"Erreur arrêt final WS Manager: {e}")
            finally:
                with config_lock:
                    if bot_state.get("websocket_manager") == ws_man_final:
                         bot_state["websocket_manager"] = None
                         bot_state["websocket_stream_name"] = None

        logger.info("Sauvegarde finale des données...")
        save_data()
        logger.info("Bot complètement arrêté.")

# --- Démarrage Application Flask ---
if __name__ == "__main__":
    werkzeug_log = logging.getLogger('werkzeug')
    werkzeug_log.setLevel(logging.ERROR)

    logger.info("Démarrage de l'API Flask du Bot...")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
