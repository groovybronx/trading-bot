# /Users/davidmichels/Desktop/trading-bot/backend/bot.py

import logging
import queue
import threading
import time
import json
import os
import collections
from typing import Optional, Dict, Any, List
from decimal import Decimal, InvalidOperation

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
        # Envoyer uniquement INFO et au-dessus au frontend
        if record.levelno >= logging.INFO:
            log_entry = self.format(record)
            self.log_queue.put(log_entry)

log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_level = logging.INFO # Ou logging.DEBUG pour plus de détails
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
latest_price_queue = queue.Queue(maxsize=1) # Pour le prix ticker

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

# --- État du Bot (Avec gestion User Data Stream) ---
# Calcul initial de la limite
_initial_periods = [bot_config["EMA_LONG_PERIOD"], bot_config["RSI_PERIOD"]]
if bot_config["USE_EMA_FILTER"]: _initial_periods.append(bot_config["EMA_FILTER_PERIOD"])
if bot_config["USE_VOLUME_CONFIRMATION"]: _initial_periods.append(bot_config["VOLUME_AVG_PERIOD"])
INITIAL_REQUIRED_LIMIT = max(_initial_periods) + 5

kline_history = collections.deque(maxlen=INITIAL_REQUIRED_LIMIT)
kline_history_lock = threading.Lock()

bot_state = {
    "status": "Arrêté", "in_position": False, "available_balance": 0.0,
    "symbol_quantity": 0.0, "base_asset": "",
    "quote_asset": "USDT", "symbol": SYMBOL, "timeframe": bot_config["TIMEFRAME_STR"],
    "thread": None, "stop_requested": False, "entry_details": None,
    "order_history": [], "max_history_length": 100,
    "websocket_manager": None,
    "ticker_websocket_stream_name": None,
    "kline_websocket_stream_name": None,
    "required_klines": INITIAL_REQUIRED_LIMIT,
    # --- AJOUTS User Data Stream ---
    "listen_key": None,
    "user_data_stream_name": None,
    "keepalive_thread": None,
    "stop_keepalive_requested": False,
    # --- FIN AJOUTS ---
}

# --- Fonctions de Persistance (inchangé) ---
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
        logger.debug(f"Données sauvegardées dans {DATA_FILENAME}")
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

# --- Fonctions Utilitaires (inchangé) ---
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

# --- Flask App (inchangé) ---
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Fonction de Sortie Centralisée (Supprimer refresh balance) ---
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
            # Calcul performance (inchangé)
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

            # Mise à jour état (inchangé)
            bot_state["in_position"] = False
            bot_state["entry_details"] = None
            should_save = True # Sauvegarde toujours nécessaire pour l'état et l'historique

            # Ajout à l'historique (inchangé)
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

            # --- SUPPRIMER Rafraîchissement manuel des soldes ---
            # logger.info("Rafraîchissement des soldes après sortie...")
            # refreshed_quote = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
            # refreshed_base = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
            # if refreshed_quote is not None: bot_state["available_balance"] = refreshed_quote
            # if refreshed_base is not None: bot_state["symbol_quantity"] = refreshed_base
            # --- FIN SUPPRESSION ---
            logger.info("Mise à jour des soldes via User Data Stream attendue.")

        else:
            logger.error(f"Échec placement ordre VENTE (sortie) pour {symbol}.")
            should_save = False # Ne pas sauvegarder si l'ordre échoue

    if should_save:
        save_data()

    return order_details

# --- Gestionnaire de Messages WebSocket Ticker (inchangé) ---
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
                except (ValueError, TypeError, InvalidOperation) as conv_err:
                    logger.error(f"Price conversion FAILED: {msg.get('c')}, Error: {conv_err}")
                    return # Arrêter le traitement de ce message

                # 2. Mise en queue du prix (float)
                try:
                    latest_price_queue.put_nowait(current_price)
                except queue.Full:
                    # Vider la queue avant d'ajouter si elle est pleine (pour toujours avoir le dernier)
                    try: latest_price_queue.get_nowait()
                    except queue.Empty: pass
                    try: latest_price_queue.put_nowait(current_price)
                    except queue.Full: pass # Ignorer si toujours plein (cas très rare)
                except Exception as put_err:
                    logger.exception("!!! UNEXPECTED ERROR during put_nowait !!!")

                # 3. Vérification SL/TP (Réactivée)
                with config_lock: # Utilise le lock principal pour bot_state
                    if bot_state.get("in_position", False) and bot_state.get("entry_details"):
                        entry_details = bot_state["entry_details"]
                        local_config = bot_config.copy() # Copier la config

                        try:
                            entry_price_decimal = Decimal(str(entry_details.get("avg_price", 0.0)))
                            sl_percent = Decimal(str(local_config.get("STOP_LOSS_PERCENTAGE", 0.0)))
                            tp_percent = Decimal(str(local_config.get("TAKE_PROFIT_PERCENTAGE", 0.0)))

                            # Vérifier Stop Loss
                            if entry_price_decimal > 0 and sl_percent > 0:
                                stop_loss_level = entry_price_decimal * (Decimal(1) - sl_percent)
                                if current_price_decimal <= stop_loss_level:
                                    logger.info(f"!!! STOP-LOSS ATTEINT ({current_price_decimal:.4f} <= {stop_loss_level:.4f}) pour {received_symbol} !!!")
                                    threading.Thread(target=execute_exit, args=("Stop-Loss",), daemon=True).start()
                                    return # Sortir après avoir lancé le thread SL

                            # Vérifier Take Profit (seulement si SL non atteint)
                            if entry_price_decimal > 0 and tp_percent > 0:
                                take_profit_level = entry_price_decimal * (Decimal(1) + tp_percent)
                                if current_price_decimal >= take_profit_level:
                                    logger.info(f"!!! TAKE-PROFIT ATTEINT ({current_price_decimal:.4f} >= {take_profit_level:.4f}) pour {received_symbol} !!!")
                                    threading.Thread(target=execute_exit, args=("Take-Profit",), daemon=True).start()
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
            pass
    except Exception as outer_e:
        logger.exception(f"!!! CRITICAL Outer Exception in process_ticker_message: {outer_e} !!!")


# --- Gestionnaire de Messages WebSocket Kline (Supprimer refresh balance) ---
def process_kline_message(msg: Dict[str, Any]):
    global kline_history, bot_state, bot_config, config_lock, kline_history_lock
    # logger.debug(f"Raw KLINE message: {msg}") # DEBUG

    try:
        # Vérifier si c'est un message kline valide
        if isinstance(msg, dict) and msg.get('e') == 'kline' and 'k' in msg:
            kline_data = msg['k']
            symbol = kline_data.get('s')
            is_closed = kline_data.get('x', False) # Le flag important !

            # --- Traiter UNIQUEMENT les bougies fermées ---
            if is_closed:
                logger.debug(f"Bougie {symbol} ({kline_data.get('i')}) FERMÉE reçue.")

                # Formater la bougie
                formatted_kline = [
                    kline_data.get('t'), kline_data.get('o'), kline_data.get('h'),
                    kline_data.get('l'), kline_data.get('c'), kline_data.get('v'),
                    kline_data.get('T'), kline_data.get('q'), kline_data.get('n'),
                    kline_data.get('V'), kline_data.get('Q'), kline_data.get('B')
                ]

                # --- Mise à jour de l'historique ---
                with kline_history_lock:
                    kline_history.append(formatted_kline)
                    history_list = list(kline_history)
                    current_len = len(history_list)

                required_len = bot_state.get("required_klines", INITIAL_REQUIRED_LIMIT)

                # --- Vérifier si assez de données ---
                if current_len < required_len:
                    logger.info(f"Historique klines ({current_len}/{required_len}) insuffisant. Attente...")
                    return

                logger.debug(f"Historique klines suffisant ({current_len}/{required_len}). Calcul stratégie...")

                # --- Calcul des indicateurs et signaux ---
                with config_lock: current_strategy_config = bot_config.copy()
                signals_df = strategy.calculate_indicators_and_signals(history_list, current_strategy_config)

                if signals_df is None or signals_df.empty:
                    logger.warning("Échec calcul indicateurs/signaux sur données WS.")
                    return

                current_data = signals_df.iloc[-1]
                current_signal = current_data.get('signal')
                logger.debug(f"Dernier signal calculé sur bougie fermée: {current_signal}")

                # --- Logique d'Entrée / Sortie ---
                with config_lock:
                    local_in_pos = bot_state["in_position"]
                    local_avail_bal = bot_state["available_balance"]
                    local_symbol = bot_state["symbol"]
                    local_risk = current_strategy_config["RISK_PER_TRADE"]
                    local_alloc = current_strategy_config["CAPITAL_ALLOCATION"]

                    symbol_info = None
                    if not local_in_pos and current_signal == 'BUY':
                         symbol_info = binance_client_wrapper.get_symbol_info(local_symbol)

                    # 1. Vérifier Entrée
                    if not local_in_pos:
                        logger.debug("WS Kline: Vérification conditions d'entrée...")
                        if symbol_info:
                            entry_order = strategy.check_entry_conditions(
                                current_data, local_symbol, local_risk, local_alloc,
                                local_avail_bal, symbol_info, current_strategy_config
                            )
                            if entry_order:
                                logger.info(f"Ordre d'ACHAT placé via WS KLINE pour {local_symbol}.")
                                try:
                                    exec_qty = float(entry_order.get('executedQty', 0))
                                    quote_qty = float(entry_order.get('cummulativeQuoteQty', 0))
                                    if exec_qty > 0:
                                        avg_price = quote_qty / exec_qty
                                        # Mise à jour état après entrée
                                        bot_state["in_position"] = True
                                        bot_state["entry_details"] = {
                                            "order_id": entry_order.get('orderId'),
                                            "avg_price": avg_price, "quantity": exec_qty,
                                            "timestamp": entry_order.get('transactTime', int(time.time()*1000))
                                        }
                                        logger.info(f"Détails d'entrée mis à jour: Prix={avg_price:.4f}, Qté={exec_qty}")

                                        # --- SUPPRIMER Rafraîchissement manuel des soldes ---
                                        # quote = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
                                        # base = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
                                        # if quote is not None: bot_state["available_balance"] = quote
                                        # if base is not None: bot_state["symbol_quantity"] = base
                                        # --- FIN SUPPRESSION ---
                                        logger.info("Mise à jour des soldes via User Data Stream attendue.")

                                        # Ajouter à l'historique et sauvegarder
                                        simplified = {
                                            "timestamp": entry_order.get('transactTime', int(time.time()*1000)),
                                            "orderId": entry_order.get('orderId'), "symbol": entry_order.get('symbol'),
                                            "side": entry_order.get('side'), "type": entry_order.get('type'),
                                            "origQty": entry_order.get('origQty'), "executedQty": entry_order.get('executedQty'),
                                            "cummulativeQuoteQty": entry_order.get('cummulativeQuoteQty'),
                                            "price": entry_order.get('price'), "status": entry_order.get('status'),
                                            "performance_pct": None
                                        }
                                        bot_state['order_history'].append(simplified)
                                        hist_len = len(bot_state['order_history'])
                                        max_len = bot_state['max_history_length']
                                        if hist_len > max_len:
                                            bot_state['order_history'] = bot_state['order_history'][-max_len:]
                                        logger.info(f"Ordre d'entrée {simplified.get('orderId','N/A')} ajouté à l'historique.")
                                        save_data_success = save_data()
                                        if not save_data_success: logger.error("Echec sauvegarde état après entrée !")
                                    else:
                                        logger.warning("Ordre d'achat placé mais quantité exécutée nulle.")
                                except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
                                    logger.error(f"Erreur traitement détails ordre entrée (WS Kline): {e}.")
                        else:
                             logger.warning("WS Kline: Impossible de vérifier entrée (symbol_info manquant).")

                    # 2. Vérifier Sortie (indicateur)
                    elif local_in_pos:
                        logger.debug("WS Kline: En position. Vérification conditions sortie (indicateurs)...")
                        if strategy.check_exit_conditions(current_data, local_symbol):
                            logger.info("WS Kline: Signal sortie (indicateur) détecté. Lancement execute_exit...")
                            threading.Thread(target=execute_exit, args=("Signal Indicateur (Kline WS)",), daemon=True).start()

                # --- Fin section critique (config_lock) ---

        # --- Gestion explicite des messages d'erreur WebSocket ---
        elif isinstance(msg, dict) and msg.get('e') == 'error':
             logger.error(f"Received KLINE WebSocket error message: {msg}")

    except Exception as e:
        logger.exception(f"!!! CRITICAL Exception in process_kline_message: {e} !!!")


# --- NOUVEAU Gestionnaire de Messages WebSocket User Data ---
def process_user_data_message(msg: Dict[str, Any]):
    """
    Callback pour traiter les messages du WebSocket User Data Stream.
    Met à jour les soldes lors de l'événement 'outboundAccountPosition'.
    """
    global bot_state, config_lock
    # logger.debug(f"Raw USER DATA message: {msg}") # DEBUG

    try:
        event_type = msg.get('e')

        # --- Mise à jour des soldes ---
        if event_type == 'outboundAccountPosition':
            balances = msg.get('B', [])
            with config_lock:
                base_asset = bot_state.get('base_asset')
                quote_asset = bot_state.get('quote_asset')
                updated = False
                for balance_info in balances:
                    asset = balance_info.get('a')
                    free_balance_str = balance_info.get('f')
                    if asset and free_balance_str is not None:
                        try:
                            free_balance = float(free_balance_str)
                            if asset == base_asset:
                                current_val = bot_state.get('symbol_quantity')
                                # Comparer avec une tolérance pour éviter les logs inutiles dus aux floats
                                if current_val is None or abs(current_val - free_balance) > 1e-9:
                                    logger.info(f"Solde {asset} mis à jour via WS: {free_balance:.6f} (était {current_val})")
                                    bot_state['symbol_quantity'] = free_balance
                                    updated = True
                            elif asset == quote_asset:
                                current_val = bot_state.get('available_balance')
                                if current_val is None or abs(current_val - free_balance) > 1e-9:
                                    logger.info(f"Solde {asset} mis à jour via WS: {free_balance:.4f} (était {current_val})")
                                    bot_state['available_balance'] = free_balance
                                    updated = True
                        except (ValueError, TypeError):
                            logger.error(f"Impossible de convertir le solde '{free_balance_str}' pour l'asset {asset} depuis User WS.")
                # if updated: logger.debug("Soldes mis à jour depuis outboundAccountPosition.")

        # --- Autres événements (optionnel, ex: suivi ordres) ---
        elif event_type == 'executionReport':
            order_id = msg.get('i')
            status = msg.get('X') # Execution type / Order Status
            symbol = msg.get('s')
            side = msg.get('S')
            last_filled_qty = msg.get('l') # Last executed quantity
            cum_filled_qty = msg.get('z') # Cumulative filled quantity
            last_quote_qty = msg.get('Y') # Last quote asset transacted quantity (i.e. Last price * Last quantity)
            logger.debug(f"User WS: Ordre {order_id} ({symbol} {side}) Status: {status}, LastFillQty: {last_filled_qty}, CumQty: {cum_filled_qty}, LastQuoteQty: {last_quote_qty}")
            # Pourrait déclencher des logiques supplémentaires si nécessaire

        # --- Gestion explicite des messages d'erreur WebSocket ---
        elif isinstance(msg, dict) and msg.get('e') == 'error':
             logger.error(f"Received USER DATA WebSocket error message: {msg}")

    except Exception as e:
        logger.exception(f"!!! CRITICAL Exception in process_user_data_message: {e} !!!")


# --- NOUVEAU Thread Keepalive pour User Data Stream ---
def run_keepalive():
    """
    Boucle pour envoyer périodiquement des keepalives pour le listenKey.
    S'exécute dans un thread séparé.
    """
    global bot_state
    logger.info("Démarrage du thread Keepalive User Data Stream.")

    # Récupérer la clé sous verrou pour être sûr
    with config_lock:
        local_listen_key = bot_state.get('listen_key')

    if not local_listen_key:
        logger.error("Thread Keepalive démarré mais listenKey non trouvé dans bot_state. Arrêt.")
        return

    # Binance dit que la clé expire après 60 min. On rafraîchit toutes les 30 min.
    keepalive_interval_seconds = 30 * 60

    while True: # La boucle est contrôlée par stop_keepalive_requested à l'intérieur
        try:
            # Vérifier si l'arrêt est demandé avant d'envoyer le keepalive
            with config_lock: stop_req = bot_state.get("stop_keepalive_requested", False)
            if stop_req: break

            success = binance_client_wrapper.keepalive_user_data_stream(local_listen_key)
            if not success:
                logger.error("Échec envoi keepalive User Data Stream. La clé a peut-être expiré.")
                # Optionnel: Tenter de redémarrer le stream ici ? Complexe.
                # Pour l'instant, on logue et on attend le prochain cycle.
            else:
                logger.debug("Keepalive User Data Stream réussi.")

            # Attendre l'intervalle (en vérifiant régulièrement si l'arrêt est demandé)
            wait_start_time = time.time()
            while time.time() - wait_start_time < keepalive_interval_seconds:
                with config_lock: stop_req_inner = bot_state.get("stop_keepalive_requested", False)
                if stop_req_inner: break
                time.sleep(1) # Vérifier chaque seconde
            if stop_req_inner: break # Sortir de la boucle while principale

        except Exception as e:
            logger.exception(f"Erreur inattendue dans le thread Keepalive: {e}")
            # Attendre un peu avant de réessayer en cas d'erreur inattendue
            time.sleep(60)
            # Vérifier à nouveau si l'arrêt est demandé après une erreur
            with config_lock: stop_req_err = bot_state.get("stop_keepalive_requested", False)
            if stop_req_err: break

    logger.info("Fin du thread Keepalive User Data Stream.")


# --- Routes API (Modifiées pour /start et /stop) ---
@app.route('/status')
def get_status():
    global latest_price_queue
    status_data_to_send = {}
    latest_price = 0.0 # Valeur par défaut

    # Lire le dernier prix (non bloquant)
    try:
        last_price_item = None
        while not latest_price_queue.empty():
            last_price_item = latest_price_queue.get_nowait()
        if last_price_item is not None:
            latest_price = last_price_item
    except queue.Empty: pass
    except Exception as q_err: logger.error(f"API /status - Erreur lecture queue: {q_err}")

    # Récupérer le reste de l'état
    with config_lock:
        state_copy = bot_state.copy()
        status_data_to_send = {
            k: v for k, v in state_copy.items()
            if k not in ['thread', 'stop_requested', 'websocket_manager', 'keepalive_thread', 'stop_keepalive_requested'] # Exclure les objets non sérialisables/internes
        }

    status_data_to_send["current_price"] = latest_price
    return jsonify(status_data_to_send)

@app.route('/parameters', methods=['GET'])
def get_parameters():
    with config_lock:
        current_config = bot_config.copy()
    return jsonify(current_config)

@app.route('/parameters', methods=['POST'])
def set_parameters():
    global bot_config, bot_state, kline_history, config_lock, kline_history_lock
    new_params = request.json
    if not new_params:
        return jsonify({"success": False, "message": "Aucun paramètre fourni."}), 400

    logger.info(f"Tentative MAJ paramètres: {new_params}")
    restart_recommended = False
    validated_params = {}
    current_tf = bot_config["TIMEFRAME_STR"]
    current_required_limit = bot_state["required_klines"]

    try:
        # Validation (inchangée)
        new_tf = str(new_params.get("TIMEFRAME_STR", current_tf))
        if new_tf not in VALID_TIMEFRAMES: raise ValueError(f"TIMEFRAME_STR invalide: {new_tf}")
        validated_params["TIMEFRAME_STR"] = new_tf
        if new_tf != current_tf: restart_recommended = True
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

        # Recalculer required_limit
        new_periods = [validated_params["EMA_LONG_PERIOD"], validated_params["RSI_PERIOD"]]
        if validated_params["USE_EMA_FILTER"]: new_periods.append(validated_params["EMA_FILTER_PERIOD"])
        if validated_params["USE_VOLUME_CONFIRMATION"]: new_periods.append(validated_params["VOLUME_AVG_PERIOD"])
        new_required_limit = max(new_periods) + 5
        if new_required_limit != current_required_limit: restart_recommended = True

    except (ValueError, TypeError) as e:
        logger.error(f"Erreur validation paramètres: {e}")
        return jsonify({"success": False, "message": f"Paramètres invalides: {e}"}), 400

    with config_lock:
        bot_config.update(validated_params)
        bot_state["timeframe"] = bot_config["TIMEFRAME_STR"]
        bot_state["required_klines"] = new_required_limit
        with kline_history_lock:
            if kline_history.maxlen != new_required_limit:
                logger.info(f"Mise à jour taille historique klines de {kline_history.maxlen} à {new_required_limit}")
                current_data = list(kline_history)
                kline_history = collections.deque(current_data, maxlen=new_required_limit)

    logger.info("Paramètres mis à jour avec succès.")
    message = "Paramètres mis à jour."
    if restart_recommended:
        message += " Redémarrage du bot conseillé pour appliquer changements (timeframe/périodes indicateurs)."
    return jsonify({"success": True, "message": message})


@app.route('/start', methods=['POST'])
def start_bot_route():
    global bot_state, kline_history, config_lock, kline_history_lock

    with config_lock:
        if bot_state.get("thread") is not None and bot_state["thread"].is_alive():
            return jsonify({"success": False, "message": "Bot déjà en cours."}), 400

        # --- Nettoyage Complet avant démarrage ---
        logger.info("Nettoyage état précédent avant démarrage...")
        # 1. Arrêt Thread Keepalive
        bot_state["stop_keepalive_requested"] = True
        old_keepalive_thread = bot_state.get("keepalive_thread")
        if old_keepalive_thread and old_keepalive_thread.is_alive():
            logger.info("Attente arrêt ancien thread Keepalive...")
            old_keepalive_thread.join(timeout=5)
            if old_keepalive_thread.is_alive(): logger.warning("Ancien thread Keepalive n'a pas pu être arrêté.")
        bot_state["keepalive_thread"] = None

        # 2. Arrêt WebSockets
        ws_man = bot_state.get("websocket_manager")
        if ws_man is not None:
             logger.info("Arrêt ancien WebSocket Manager...")
             ticker_stream = bot_state.get("ticker_websocket_stream_name")
             kline_stream = bot_state.get("kline_websocket_stream_name")
             user_stream = bot_state.get("user_data_stream_name")
             try:
                 if ws_man:
                     if ticker_stream: ws_man.stop_socket(ticker_stream)
                     if kline_stream: ws_man.stop_socket(kline_stream)
                     if user_stream: ws_man.stop_socket(user_stream)
                     ws_man.stop()
             except Exception as ws_err: logger.error(f"Erreur arrêt ancien WS Manager: {ws_err}")
             finally:
                 bot_state["websocket_manager"] = None
                 bot_state["ticker_websocket_stream_name"] = None
                 bot_state["kline_websocket_stream_name"] = None
                 bot_state["user_data_stream_name"] = None

        # 3. Fermeture ListenKey
        old_listen_key = bot_state.get("listen_key")
        if old_listen_key:
            logger.info("Fermeture ancien ListenKey...")
            binance_client_wrapper.close_user_data_stream(old_listen_key)
            bot_state["listen_key"] = None
        # --- Fin Nettoyage ---

    # Initialisation Client Binance
    if binance_client_wrapper.get_client() is None:
        logger.error("Échec initialisation client Binance. Démarrage annulé.")
        return jsonify({"success": False, "message": "Échec initialisation client Binance."}), 500

    logger.info("Démarrage du bot demandé...")

    # Chargement Données Persistantes
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
            logger.info(f"État et historique restaurés depuis {DATA_FILENAME}.")
        else:
            bot_state["in_position"] = False; bot_state["entry_details"] = None; bot_state["order_history"] = []
            logger.info("Initialisation avec état et historique vides.")

        # Vider queue ticker
        while not latest_price_queue.empty():
            try: latest_price_queue.get_nowait()
            except queue.Empty: break
        logger.info("Queue de prix ticker vidée.")

        # Vider et Pré-remplir l'historique kline
        with kline_history_lock:
            kline_history.clear()
            logger.info("Historique klines local vidé.")
            current_tf = bot_config["TIMEFRAME_STR"]
            required_limit = bot_state["required_klines"]
            binance_interval = TIMEFRAME_CONSTANT_MAP.get(current_tf)
            if binance_interval:
                logger.info(f"Pré-remplissage historique avec {required_limit} klines ({current_tf})...")
                initial_klines = binance_client_wrapper.get_klines(
                    symbol=bot_state["symbol"], interval=binance_interval, limit=required_limit
                )
                if initial_klines and len(initial_klines) >= required_limit:
                    if kline_history.maxlen != required_limit:
                         kline_history = collections.deque(maxlen=required_limit)
                    kline_history.extend(initial_klines)
                    logger.info(f"Historique klines pré-rempli avec {len(kline_history)} bougies.")
                elif initial_klines:
                     logger.warning(f"N'a pu récupérer que {len(initial_klines)}/{required_limit} klines initiales.")
                     kline_history.extend(initial_klines)
                else:
                    logger.error("Échec récupération klines initiales.")
            else:
                logger.error(f"Timeframe '{current_tf}' invalide pour pré-remplissage klines.")

        # --- Démarrage User Data Stream et Keepalive ---
        logger.info("Obtention du ListenKey pour User Data Stream...")
        new_listen_key = binance_client_wrapper.start_user_data_stream()
        if new_listen_key:
            bot_state["listen_key"] = new_listen_key
            bot_state["stop_keepalive_requested"] = False
            bot_state["keepalive_thread"] = threading.Thread(target=run_keepalive, daemon=True)
            bot_state["keepalive_thread"].start()
        else:
            logger.error("Échec obtention ListenKey. User Data Stream non démarré. MAJ soldes manuelles nécessaires.")
            # Continuer sans User Data Stream pour le moment

        # --- Démarrage WebSocket Manager et Streams ---
        try:
            logger.info("Démarrage WebSocket Manager...")
            use_testnet_ws = getattr(config, 'USE_TESTNET', False)
            bot_state["websocket_manager"] = ThreadedWebsocketManager(
                api_key=config.BINANCE_API_KEY, api_secret=config.BINANCE_API_SECRET,
                testnet=use_testnet_ws
            )
            bot_state["websocket_manager"].start()
            stream_symbol = bot_state["symbol"].lower()

            # 1. Stream Ticker
            ticker_stream_name = bot_state["websocket_manager"].start_symbol_miniticker_socket(
                callback=process_ticker_message, symbol=stream_symbol
            )
            bot_state["ticker_websocket_stream_name"] = ticker_stream_name
            logger.info(f"Connecté au stream Ticker: {ticker_stream_name}")

            # 2. Stream Kline
            kline_interval_ws = TIMEFRAME_CONSTANT_MAP.get(bot_state["timeframe"])
            if kline_interval_ws:
                kline_stream_name = bot_state["websocket_manager"].start_kline_socket(
                    callback=process_kline_message, symbol=stream_symbol, interval=kline_interval_ws
                )
                bot_state["kline_websocket_stream_name"] = kline_stream_name
                logger.info(f"Connecté au stream Kline: {kline_stream_name} (Interval: {kline_interval_ws})")
            else:
                 logger.error(f"Timeframe '{bot_state['timeframe']}' invalide pour stream Kline WS.")

            # 3. Stream User Data (SI listenKey obtenu)
            if bot_state.get("listen_key"):
                # --- FIX: Removed listen_key argument ---
                user_stream_name = bot_state["websocket_manager"].start_user_socket(
                    callback=process_user_data_message
                )
                # --- END FIX ---
                bot_state["user_data_stream_name"] = user_stream_name
                logger.info(f"Connecté au stream User Data: {user_stream_name}")
            else:
                logger.warning("User Data Stream non démarré (ListenKey manquant).")

        except Exception as e:
            logger.exception("Erreur critique démarrage WebSocket Manager/Streams.")
            # Nettoyage en cas d'erreur démarrage WS
            ws_man_err = bot_state.get("websocket_manager")
            # --- FIX: Corrected try/except syntax ---
            if ws_man_err:
                try:
                    ws_man_err.stop()
                except Exception as stop_err:
                    logger.error(f"Erreur arrêt WS Manager après échec: {stop_err}")
            # --- END FIX ---
            bot_state["websocket_manager"] = None; bot_state["ticker_websocket_stream_name"] = None
            bot_state["kline_websocket_stream_name"] = None; bot_state["user_data_stream_name"] = None
            # Arrêter aussi le keepalive
            bot_state["stop_keepalive_requested"] = True
            ka_thread_err = bot_state.get("keepalive_thread")
            if ka_thread_err and ka_thread_err.is_alive(): ka_thread_err.join(timeout=1)
            bot_state["keepalive_thread"] = None
            lk_err = bot_state.get("listen_key")
            if lk_err: binance_client_wrapper.close_user_data_stream(lk_err)
            bot_state["listen_key"] = None
            return jsonify({"success": False, "message": "Erreur démarrage WebSocket."}), 500

        # --- Démarrage Thread Principal (run_bot) ---
        bot_state["status"] = "Démarrage..."
        bot_state["stop_requested"] = False
        bot_state["thread"] = threading.Thread(target=run_bot, daemon=True)
        bot_state["thread"].start()

    time.sleep(1)
    return jsonify({"success": True, "message": "Ordre de démarrage envoyé (Bot et WebSockets)."})


@app.route('/stop', methods=['POST'])
def stop_bot_route():
    global bot_state
    should_stop_ws = False

    with config_lock:
        if bot_state.get("thread") is None or not bot_state["thread"].is_alive():
            bot_state["status"] = "Arrêté"
            if bot_state.get("websocket_manager") is not None or bot_state.get("keepalive_thread") is not None:
                logger.warning("Thread principal inactif mais WS/Keepalive actif? Tentative arrêt.")
                should_stop_ws = True # Tenter d'arrêter WS et Keepalive
            else:
                return jsonify({"success": False, "message": "Bot non en cours d'exécution."}), 400
        else:
            logger.info("Arrêt du bot demandé...")
            bot_state["status"] = "Arrêt en cours..."
            bot_state["stop_requested"] = True # Signal pour run_bot
            bot_state["stop_keepalive_requested"] = True # Signal pour keepalive thread
            should_stop_ws = True

    # --- Arrêt Thread Keepalive (avant arrêt WS Manager) ---
    keepalive_thread_to_stop = bot_state.get("keepalive_thread")
    if keepalive_thread_to_stop and keepalive_thread_to_stop.is_alive():
        logger.info("Attente arrêt thread Keepalive...")
        keepalive_thread_to_stop.join(timeout=5)
        if keepalive_thread_to_stop.is_alive(): logger.warning("Thread Keepalive n'a pas pu être arrêté.")
    with config_lock: bot_state["keepalive_thread"] = None

    # --- Arrêt WebSockets ---
    ws_man_to_stop = bot_state.get("websocket_manager")
    ticker_stream = bot_state.get("ticker_websocket_stream_name")
    kline_stream = bot_state.get("kline_websocket_stream_name")
    user_stream = bot_state.get("user_data_stream_name")

    if should_stop_ws and ws_man_to_stop:
        logger.info("Arrêt du WebSocket Manager...")
        try:
            if ws_man_to_stop:
                if ticker_stream: ws_man_to_stop.stop_socket(ticker_stream); logger.info(f"Stream Ticker arrêté.")
                if kline_stream: ws_man_to_stop.stop_socket(kline_stream); logger.info(f"Stream Kline arrêté.")
                if user_stream: ws_man_to_stop.stop_socket(user_stream); logger.info(f"Stream User arrêté.")
                ws_man_to_stop.stop()
                logger.info("Ordre d'arrêt envoyé au WebSocket Manager.")
        except Exception as e: logger.error(f"Erreur lors de l'arrêt du WebSocket Manager: {e}")
        finally:
             with config_lock:
                 if bot_state.get("websocket_manager") == ws_man_to_stop:
                     bot_state["websocket_manager"] = None
                     bot_state["ticker_websocket_stream_name"] = None
                     bot_state["kline_websocket_stream_name"] = None
                     bot_state["user_data_stream_name"] = None

    # --- Fermeture ListenKey (après arrêt WS Manager) ---
    listen_key_to_close = bot_state.get('listen_key')
    if listen_key_to_close:
        logger.info("Fermeture du ListenKey User Data Stream...")
        binance_client_wrapper.close_user_data_stream(listen_key_to_close)
        with config_lock: bot_state['listen_key'] = None

    # Attendre que le thread run_bot se termine (il devrait voir stop_requested)
    main_thread = bot_state.get("thread")
    if main_thread and main_thread.is_alive():
        logger.info("Attente arrêt thread principal (run_bot)...")
        main_thread.join(timeout=10) # Donner un peu de temps
        if main_thread.is_alive():
            logger.warning("Thread principal (run_bot) n'a pas terminé dans les temps.")
        else:
            logger.info("Thread principal (run_bot) terminé.")

    with config_lock: # Mettre à jour le statut final
        bot_state["status"] = "Arrêté"
        bot_state["thread"] = None

    return jsonify({"success": True, "message": "Ordre d'arrêt envoyé et traité."})


# --- Route pour le flux de logs SSE (inchangé) ---
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
                    yield ": keep-alive\n\n" # Envoyer un commentaire pour maintenir la connexion
                    continue
        except GeneratorExit:
            logger.info("Client déconnecté du flux de logs SSE.")
        finally:
            pass # Nettoyage si nécessaire
    # Headers pour SSE
    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no' # Important pour Nginx
    return response

# --- Route pour l'historique des ordres (inchangé) ---
@app.route('/order_history')
def get_order_history():
    with config_lock:
        # Retourner une copie triée par timestamp descendant
        history_copy = sorted(
            list(bot_state.get('order_history', [])),
            key=lambda x: x.get('timestamp', 0),
            reverse=True
        )
    return jsonify(history_copy)


# --- Boucle Principale du Bot (SIMPLIFIÉE) ---
def run_bot():
    """
    Boucle principale du thread du bot.
    Initialise, puis attend principalement que l'arrêt soit demandé.
    La logique de trading est dans les callbacks WebSocket.
    """
    global bot_state, bot_config
    try:
        with config_lock:
            initial_tf = bot_config["TIMEFRAME_STR"]
            bot_state["status"] = "En cours"
            bot_state["timeframe"] = initial_tf
            bot_state["symbol"] = SYMBOL
        logger.info(f"Démarrage effectif du thread principal pour {SYMBOL} sur {initial_tf}")

        # Récupération initiale des infos symbole
        symbol_info = binance_client_wrapper.get_symbol_info(SYMBOL)
        if not symbol_info:
            raise Exception(f"Impossible de récupérer les informations pour {SYMBOL}. Arrêt.")

        with config_lock:
            bot_state['base_asset'] = symbol_info.get('baseAsset', '')
            bot_state['quote_asset'] = symbol_info.get('quoteAsset', 'USDT')
        if not bot_state['base_asset']:
            raise Exception(f"Asset de base non trouvé pour {SYMBOL}. Arrêt.")
        logger.info(f"Assets détectés: Base='{bot_state['base_asset']}', Quote='{bot_state['quote_asset']}'")

        # Récupération initiale des soldes (via REST, car User Stream ne donne que les MAJ)
        initial_quote = binance_client_wrapper.get_account_balance(asset=bot_state['quote_asset'])
        initial_base = binance_client_wrapper.get_account_balance(asset=bot_state['base_asset'])
        if initial_quote is None:
            logger.error(f"Impossible lire solde initial {bot_state['quote_asset']}. Utilisation 0.")
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

        logger.info(f"Solde initial {bot_state['quote_asset']}: {bot_state.get('available_balance', 0.0):.4f}")
        logger.info(f"Quantité initiale {bot_state['base_asset']}: {bot_state.get('symbol_quantity', 0.0):.6f}")

        # Boucle d'attente principale
        while True:
            with config_lock: stop_req = bot_state.get("stop_requested", False)
            if stop_req:
                logger.info("Arrêt demandé détecté dans run_bot.")
                break
            try:
                # Optionnel: Vérifier périodiquement l'état des WS ou autres tâches de fond
                # Exemple: Vérifier si le WS Manager est toujours actif
                # with config_lock: ws_man_check = bot_state.get("websocket_manager")
                # if ws_man_check is None and not stop_req:
                #     logger.warning("WS Manager semble inactif alors que le bot est en cours. Problème?")
                #     # Tenter de redémarrer ? Complexe.

                time.sleep(1) # Pause pour éviter 100% CPU

            except Exception as loop_err:
                logger.exception(f"Erreur dans la boucle principale simplifiée: {loop_err}")
                time.sleep(5) # Pause après une erreur

    except Exception as e:
        logger.exception("Erreur majeure initialisation/exécution run_bot.")
        with config_lock:
            bot_state["status"] = "Erreur Init/Run"
            bot_state["stop_requested"] = True # Assurer l'arrêt

    finally:
        logger.info("Fin exécution run_bot (thread principal).")
        # --- Nettoyage final (redondant avec /stop mais sécuritaire) ---
        # Le nettoyage est principalement géré par /stop maintenant,
        # mais on s'assure que le statut est bien 'Arrêté'.
        with config_lock:
            bot_state["status"] = "Arrêté"
            bot_state["thread"] = None
            # On ne touche plus aux WS/Keepalive ici, /stop s'en charge.

        logger.info("Sauvegarde finale des données depuis run_bot...")
        save_data()
        logger.info("Thread principal run_bot terminé.")


# --- Démarrage Application Flask ---
if __name__ == "__main__":
    werkzeug_log = logging.getLogger('werkzeug')
    werkzeug_log.setLevel(logging.ERROR) # Réduire verbosité Flask/Werkzeug

    logger.info("Démarrage de l'API Flask du Bot...")
    # Utiliser 'threaded=True' est généralement sûr pour Flask dev server,
    # mais pour la prod, utiliser un serveur WSGI comme Gunicorn.
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)
