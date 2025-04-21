# /Users/davidmichels/Desktop/trading-bot/backend/websocket_handlers.py
import logging
import json
import queue
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional

# --- MODIFIÉ: Importer depuis websocket_utils ---
from websocket_utils import broadcast_state_update
# --- FIN MODIFIÉ ---

# MODIFIÉ: Importer les instances des managers au lieu des variables globales
from state_manager import state_manager
from config_manager import config_manager

# Importer la logique de stratégie et le wrapper client
import strategy
import binance_client_wrapper
# Importer bot_core pour execute_exit et gestion ordres
import bot_core

logger = logging.getLogger(__name__)

# --- Gestionnaire Book Ticker ---
def process_book_ticker_message(msg: Dict[str, Any]):
    """
    Callback pour @bookTicker. Met à jour l'état et déclenche la logique scalping & SL/TP.
    """
    try:
        if isinstance(msg, dict) and 'e' in msg and msg['e'] == 'bookTicker' and 's' in msg and 'b' in msg and 'a' in msg:
            symbol = msg['s']
            state_manager.update_book_ticker(msg)

            # --- MODIFIÉ: Appel direct de la fonction importée ---
            broadcast_state_update()
            # --- FIN MODIFIÉ ---

            current_book_ticker = state_manager.get_book_ticker()
            current_state = state_manager.get_state()
            current_config = config_manager.get_config()

            # --- 1. Vérification SL/TP (Prioritaire) ---
            check_sl_tp(current_book_ticker, current_state, current_config)

            # --- 2. Déclencher la logique de décision Scalping ---
            strategy_type = current_config.get("STRATEGY_TYPE")
            open_order_id = current_state.get("open_order_id")
            is_in_position = current_state.get("in_position")
            configured_symbol = current_state.get("symbol")
            entry_details = current_state.get("entry_details")
            open_order_timestamp = current_state.get("open_order_timestamp")

            if strategy_type == 'SCALPING' and configured_symbol and symbol == configured_symbol:
                if open_order_id:
                    check_limit_order_timeout(configured_symbol, open_order_id, open_order_timestamp, current_config)
                elif not is_in_position:
                    depth_snapshot = state_manager.get_depth_snapshot()
                    available_balance = current_state.get("available_balance", 0.0)
                    symbol_info = binance_client_wrapper.get_symbol_info(configured_symbol)

                    if symbol_info:
                        entry_order_params = strategy.check_scalping_entry(
                            configured_symbol, current_book_ticker, depth_snapshot,
                            current_config, available_balance, symbol_info
                        )
                        if entry_order_params:
                            logger.info("Scalping Entry Signal détecté. Lancement place_scalping_order...")
                            threading.Thread(target=bot_core.place_scalping_order, args=(entry_order_params,), daemon=True).start()
                    else:
                         logger.error(f"process_book_ticker: Impossible de récupérer symbol_info pour {configured_symbol}, vérification entrée scalping ignorée.")

                else: # En position
                    if entry_details:
                        depth_snapshot = state_manager.get_depth_snapshot()
                        if strategy.check_scalping_exit(
                            configured_symbol, entry_details, current_book_ticker,
                            depth_snapshot, current_config
                        ):
                             logger.info("Scalping Exit Signal (Stratégie) détecté. Lancement execute_exit...")
                             threading.Thread(target=bot_core.execute_exit, args=("Signal Scalping Strategy",), daemon=True).start()

            elif strategy_type == 'SCALPING' and configured_symbol and symbol != configured_symbol:
                 logger.debug(f"process_book_ticker: Message pour {symbol} ignoré (bot configuré pour {configured_symbol}).")
            elif strategy_type == 'SCALPING' and not configured_symbol:
                 logger.warning("process_book_ticker: Symbole non configuré dans l'état, logique scalping ignorée.")

        elif isinstance(msg, dict) and msg.get('e') == 'error':
            logger.error(f"Received WebSocket BookTicker error message: {msg}")

    except Exception as e:
        logger.critical(f"!!! CRITICAL Exception in process_book_ticker_message: {e} !!!", exc_info=True)

# --- Vérification SL/TP ---
def check_sl_tp(
    book_ticker_data: Dict[str, Any],
    current_state: Dict[str, Any],
    current_config: Dict[str, Any]
):
    """Vérifie Stop-Loss et Take-Profit en utilisant les données du book ticker."""
    if not current_state.get("in_position") or not current_state.get("entry_details"):
        return

    entry_details = current_state["entry_details"]
    symbol = current_state.get("symbol")
    sl_percent_config = current_config.get("STOP_LOSS_PERCENTAGE")
    tp_percent_config = current_config.get("TAKE_PROFIT_PERCENTAGE")

    if sl_percent_config is None and tp_percent_config is None: return

    try:
        current_price_str = book_ticker_data.get('b') # Best Bid Price pour vendre
        if not current_price_str: return
        current_price_decimal = Decimal(current_price_str)
        if current_price_decimal <= 0: return

        entry_price_str = entry_details.get("avg_price")
        if entry_price_str is None: return
        entry_price_decimal = Decimal(str(entry_price_str))
        if entry_price_decimal <= 0: return

        # Stop Loss
        if sl_percent_config is not None:
            try:
                sl_percent = Decimal(str(sl_percent_config))
                if sl_percent > 0:
                    stop_loss_level = entry_price_decimal * (Decimal(1) - sl_percent)
                    if current_price_decimal <= stop_loss_level:
                        logger.info(f"!!! STOP-LOSS ATTEINT ({current_price_decimal:.4f} <= {stop_loss_level:.4f}) pour {symbol} !!!")
                        threading.Thread(target=bot_core.execute_exit, args=("Stop-Loss",), daemon=True).start()
                        return
            except (InvalidOperation, ValueError) as e:
                 logger.error(f"check_sl_tp: Erreur calcul Stop Loss (SL %: {sl_percent_config}): {e}")

        # Take Profit (seulement si SL non atteint)
        if tp_percent_config is not None:
            try:
                tp_percent = Decimal(str(tp_percent_config))
                if tp_percent > 0:
                    take_profit_level = entry_price_decimal * (Decimal(1) + tp_percent)
                    if current_price_decimal >= take_profit_level:
                        logger.info(f"!!! TAKE-PROFIT ATTEINT ({current_price_decimal:.4f} >= {take_profit_level:.4f}) pour {symbol} !!!")
                        threading.Thread(target=bot_core.execute_exit, args=("Take-Profit",), daemon=True).start()
                        return
            except (InvalidOperation, ValueError) as e:
                 logger.error(f"check_sl_tp: Erreur calcul Take Profit (TP %: {tp_percent_config}): {e}")

    except (InvalidOperation, TypeError, KeyError) as e:
        logger.error(f"check_sl_tp: Erreur interne (BookTicker): {e}", exc_info=True)
    except Exception as e:
         logger.critical(f"!!! CRITICAL Exception in check_sl_tp: {e} !!!", exc_info=True)

# --- Gestionnaire Depth ---
def process_depth_message(msg: Dict[str, Any]):
    """Callback pour @depth. Met à jour le snapshot de profondeur via StateManager."""
    try:
        if isinstance(msg, dict) and msg.get('e') == 'depthUpdate' and 's' in msg:
            state_manager.update_depth_snapshot(msg)
            # Pas de broadcast ici, c'est trop fréquent. Le ticker le fera.
        elif isinstance(msg, dict) and msg.get('e') == 'error':
            logger.error(f"Received WebSocket Depth error message: {msg}")
    except Exception as e:
        logger.critical(f"!!! CRITICAL Exception in process_depth_message: {e} !!!", exc_info=True)

# --- Gestionnaire AggTrade ---
def process_agg_trade_message(msg: Dict[str, Any]):
    """Callback pour @aggTrade. Stocke les derniers trades via StateManager."""
    try:
        if isinstance(msg, dict) and msg.get('e') == 'aggTrade' and 's' in msg:
            state_manager.append_agg_trade(msg)
            # Pas de broadcast ici.
        elif isinstance(msg, dict) and msg.get('e') == 'error':
            logger.error(f"Received WebSocket AggTrade error message: {msg}")
    except Exception as e:
        logger.critical(f"!!! CRITICAL Exception in process_agg_trade_message: {e} !!!", exc_info=True)

# --- Gestionnaire Kline ---
def process_kline_message(msg: Dict[str, Any]):
    """Callback pour @kline. Met à jour l'historique et déclenche la logique SWING."""
    try:
        if isinstance(msg, dict) and msg.get('e') == 'kline' and 'k' in msg:
            kline_data = msg['k']
            symbol = kline_data.get('s')
            is_closed = kline_data.get('x', False)

            if is_closed:
                logger.debug(f"Bougie {symbol} ({kline_data.get('i')}) FERMÉE reçue.")
                formatted_kline = [
                    kline_data.get('t'), kline_data.get('o'), kline_data.get('h'),
                    kline_data.get('l'), kline_data.get('c'), kline_data.get('v'),
                    kline_data.get('T'), kline_data.get('q'), kline_data.get('n'),
                    kline_data.get('V'), kline_data.get('Q'), kline_data.get('B')
                ]
                state_manager.append_kline(formatted_kline)

                current_state = state_manager.get_state()
                current_config = config_manager.get_config()
                strategy_type = current_config.get("STRATEGY_TYPE")
                configured_symbol = current_state.get("symbol")

                if strategy_type == 'SWING' and configured_symbol and symbol == configured_symbol:
                    history_list = state_manager.get_kline_history()
                    required_len = state_manager.get_required_klines()
                    current_len = len(history_list)

                    if current_len < required_len:
                        logger.info(f"Kline WS (SWING): Historique ({current_len}/{required_len}) insuffisant.")
                        return

                    logger.debug(f"Kline WS (SWING): Calcul stratégie EMA/RSI sur {current_len} bougies...")
                    signals_df = strategy.calculate_indicators_and_signals(history_list, current_config)

                    if signals_df is None or signals_df.empty:
                        logger.warning("Kline WS (SWING): Échec calcul indicateurs/signaux.")
                        return

                    current_data = signals_df.iloc[-1]
                    is_in_position = current_state.get("in_position")

                    if not is_in_position:
                        logger.debug("Kline WS (SWING): Vérification conditions d'entrée...")
                        available_balance = current_state.get("available_balance", 0.0)
                        symbol_info = binance_client_wrapper.get_symbol_info(configured_symbol)
                        if symbol_info:
                            entry_order_params = strategy.check_entry_conditions(
                                current_data, configured_symbol, current_config,
                                available_balance, symbol_info
                            )
                            if entry_order_params:
                                logger.info("Kline WS (SWING): Signal d'entrée détecté. Lancement placement ordre...")
                                # La logique de placement et mise à jour état est maintenant dans bot_core
                                # On pourrait lancer un thread ici pour appeler une fonction dans bot_core
                                # Ou, plus simple pour l'instant, on log juste le signal
                                # Le placement réel se fera via une autre logique ou manuellement
                                logger.warning("Kline WS (SWING): Placement ordre non implémenté directement ici. Signal loggué.")
                                # TODO: Décider comment déclencher l'ordre (ex: via API, autre thread?)
                        else:
                            logger.error(f"Kline WS (SWING): Impossible récupérer symbol_info pour {configured_symbol}.")

                    elif is_in_position:
                        logger.debug("Kline WS (SWING): Vérification conditions sortie (indicateurs)...")
                        if strategy.check_exit_conditions(current_data, configured_symbol):
                            logger.info("Kline WS (SWING): Signal sortie (indicateur) détecté. Lancement execute_exit...")
                            threading.Thread(target=bot_core.execute_exit, args=("Signal Indicateur (Kline WS)",), daemon=True).start()

        elif isinstance(msg, dict) and msg.get('e') == 'error':
            logger.error(f"Received KLINE WebSocket error message: {msg}")

    except Exception as e:
        logger.critical(f"!!! CRITICAL Exception in process_kline_message: {e} !!!", exc_info=True)

# --- Gestionnaire User Data ---
def process_user_data_message(data: Dict[str, Any]):
    """Traite les messages du User Data Stream (ordres, positions)."""
    logger.info(f"--- User Data Message Reçu --- Type: {data.get('e')}") # <--- AJOUTER CE LOG
    event_type = data.get('e')

    if event_type == 'executionReport':
        order_status = data.get('X') # Statut de l'exécution de l'ordre
        order_id = data.get('i') # ID de l'ordre
        client_order_id = data.get('c') # ID client de l'ordre
        order_type = data.get('o') # Type d'ordre (LIMIT, MARKET, etc.)
        side = data.get('S') # Côté (BUY, SELL)
        logger.info(f"Execution Report: OrderID={order_id}, Status={order_status}, Side={side}, Type={order_type}") # <--- AJOUTER LOG DÉTAILLÉ

        # Mettre à jour l'historique
        state_manager.add_order_to_history(data) # add_order_to_history loggue déjà

        # Logique spécifique basée sur le statut
        if order_status == 'FILLED':
            logger.info(f"Order {order_id} FILLED.")
            # Si c'était un ordre d'entrée (BUY pour nous)
            if side == 'BUY':
                try:
                    exec_qty = float(data.get('z', 0)) # Quantité exécutée cumulée
                    quote_qty = float(data.get('Z', 0)) # Montant quote exécuté cumulé
                    if exec_qty > 0:
                        avg_price = quote_qty / exec_qty
                        entry_timestamp = data.get('T', int(time.time() * 1000)) # Timestamp transaction
                        logger.info(f"Calcul entrée: Qty={exec_qty}, QuoteQty={quote_qty}, AvgPrice={avg_price}") # <--- AJOUTER LOG CALCUL
                        state_updates = {
                            "in_position": True,
                            "entry_details": {
                                "order_id": order_id,
                                "avg_price": avg_price,
                                "quantity": exec_qty,
                                "timestamp": entry_timestamp,
                            },
                            "open_order_id": None, # Nettoyer si c'était un LIMIT rempli
                            "open_order_timestamp": None,
                        }
                        state_manager.update_state(state_updates)
                        state_manager.save_persistent_data() # Sauvegarder l'état d'entrée
                        broadcast_state_update() # Diffuser le nouvel état
                        logger.info(f"État mis à jour: EN POSITION @ {avg_price:.4f}, Qty={exec_qty}")
                    else:
                        logger.warning(f"Ordre BUY {order_id} FILLED mais quantité exécutée nulle?")
                except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
                    logger.error(f"Erreur traitement ordre BUY FILLED {order_id}: {e}", exc_info=True)

            # Si c'était un ordre de sortie (SELL pour nous)
            elif side == 'SELL':
                logger.info(f"Ordre SELL {order_id} FILLED. Mise à jour état: HORS POSITION.")
                state_updates = {
                    "in_position": False,
                    "entry_details": None,
                    "open_order_id": None, # Nettoyer si c'était un LIMIT rempli
                    "open_order_timestamp": None,
                }
                state_manager.update_state(state_updates)
                state_manager.save_persistent_data() # Sauvegarder l'état de sortie
                broadcast_state_update() # Diffuser le nouvel état

        elif order_status in ['CANCELED', 'REJECTED', 'EXPIRED']:
            logger.warning(f"Order {order_id} {order_status}.")
            # Si l'ordre annulé/rejeté était notre ordre ouvert
            open_order_id = state_manager.get_state("open_order_id")
            if open_order_id == order_id:
                logger.info(f"Nettoyage de l'ordre ouvert {order_id} suite à {order_status}.")
                state_manager.update_state({"open_order_id": None, "open_order_timestamp": None})
                broadcast_state_update()

        elif order_status == 'NEW':
             logger.info(f"Order {order_id} NEW.")
             # Si c'est un ordre LIMIT, on pourrait vouloir stocker son ID
             if order_type == 'LIMIT':
                  state_manager.update_state({
                       "open_order_id": order_id,
                       "open_order_timestamp": data.get('T', int(time.time() * 1000)),
                  })
                  broadcast_state_update()

        # Ajouter d'autres statuts si nécessaire (PARTIALLY_FILLED, etc.)

    elif event_type == 'outboundAccountPosition':
        # Mise à jour des soldes (optionnel, peut être redondant si executionReport est bien géré)
        logger.debug(f"Account Position Update: {data}")
        # Implémenter la mise à jour des soldes si nécessaire
        pass
    elif event_type == 'balanceUpdate':
        # Mise à jour d'un solde spécifique (ex: suite à un dépôt/retrait)
        logger.debug(f"Balance Update: {data}")
        # Implémenter la mise à jour si nécessaire
        pass
    else:
        logger.warning(f"Type d'événement User Data non géré: {event_type}")
# --- Vérification Timeout Ordre Limit ---
def check_limit_order_timeout(
    symbol: str,
    order_id: int,
    order_timestamp: Optional[int],
    current_config: Dict[str, Any]
):
    """Vérifie si un ordre LIMIT ouvert a dépassé son timeout."""
    if not order_id or not order_timestamp: return

    timeout_ms = current_config.get("SCALPING_LIMIT_ORDER_TIMEOUT_MS", 5000)
    current_time_ms = int(time.time() * 1000)

    if current_time_ms - order_timestamp > timeout_ms:
        logger.warning(f"Ordre LIMIT {order_id} a dépassé le timeout ({timeout_ms}ms). Tentative d'annulation...")
        threading.Thread(target=bot_core.cancel_scalping_order, args=(symbol, order_id), daemon=True).start()

# --- Exports ---
__all__ = [
    'process_book_ticker_message', 'process_depth_message', 'process_agg_trade_message',
    'process_kline_message', 'process_user_data_message'
]
