# /Users/davidmichels/Desktop/trading-bot/backend/websocket_handlers.py
import logging
import queue
import threading
import time # <-- FIX: Import the time module
from decimal import Decimal, InvalidOperation
from typing import Dict, Any

# Importer l'état, la config, les locks
from state_manager import bot_state, config_lock, kline_history, kline_history_lock, latest_price_queue
from config_manager import bot_config
# Importer la logique de stratégie et le wrapper client
import strategy
import binance_client_wrapper
# Importer la fonction de sortie depuis bot_core (sera créée ensuite)
# Pour éviter une dépendance circulaire potentielle, on importe bot_core ici
# et bot_core importera ce module si nécessaire (mais il ne devrait pas avoir besoin)
import bot_core # Attention à ne pas créer de cycle d'import

logger = logging.getLogger()

# --- Gestionnaire de Messages WebSocket Ticker ---
# (process_ticker_message function remains unchanged)
def process_ticker_message(msg: Dict[str, Any]):
    """
    Callback pour traiter les messages du WebSocket (@miniTicker).
    Met à jour la queue de prix et vérifie SL/TP.
    """
    # logger.debug(f"Raw WS Ticker message: {msg}")
    try:
        if isinstance(msg, dict) and msg.get('e') == '24hrMiniTicker' and 'c' in msg and 's' in msg:
            received_symbol = msg['s']
            current_price_str = msg['c']

            try:
                current_price = float(current_price_str)
                current_price_decimal = Decimal(current_price_str)
            except (ValueError, TypeError, InvalidOperation) as conv_err:
                logger.error(f"Ticker WS: Conversion prix échouée: {current_price_str}, Erreur: {conv_err}")
                return

            # Mise à jour queue de prix
            try:
                latest_price_queue.put_nowait(current_price)
            except queue.Full:
                try: latest_price_queue.get_nowait()
                except queue.Empty: pass
                try: latest_price_queue.put_nowait(current_price)
                except queue.Full: pass
            except Exception as q_err:
                logger.exception(f"Ticker WS: Erreur put_nowait queue prix: {q_err}")

            # Vérification SL/TP
            with config_lock:
                if bot_state.get("in_position") and bot_state.get("entry_details"):
                    entry_details = bot_state["entry_details"]
                    # Utiliser une copie de la config pour éviter modif pendant itération
                    local_config = bot_config.copy()
                    try:
                        entry_price_decimal = Decimal(str(entry_details.get("avg_price", 0.0)))
                        sl_percent = Decimal(str(local_config.get("STOP_LOSS_PERCENTAGE", 0.0)))
                        tp_percent = Decimal(str(local_config.get("TAKE_PROFIT_PERCENTAGE", 0.0)))

                        # Stop Loss
                        if entry_price_decimal > 0 and sl_percent > 0:
                            stop_loss_level = entry_price_decimal * (Decimal(1) - sl_percent)
                            if current_price_decimal <= stop_loss_level:
                                logger.info(f"!!! STOP-LOSS ATTEINT ({current_price_decimal:.4f} <= {stop_loss_level:.4f}) pour {received_symbol} !!!")
                                # Utiliser bot_core.execute_exit
                                threading.Thread(target=bot_core.execute_exit, args=("Stop-Loss",), daemon=True).start()
                                return # Important: sortir après avoir lancé le thread

                        # Take Profit (seulement si SL non atteint)
                        if entry_price_decimal > 0 and tp_percent > 0:
                            take_profit_level = entry_price_decimal * (Decimal(1) + tp_percent)
                            if current_price_decimal >= take_profit_level:
                                logger.info(f"!!! TAKE-PROFIT ATTEINT ({current_price_decimal:.4f} >= {take_profit_level:.4f}) pour {received_symbol} !!!")
                                # Utiliser bot_core.execute_exit
                                threading.Thread(target=bot_core.execute_exit, args=("Take-Profit",), daemon=True).start()
                                return # Important: sortir après avoir lancé le thread

                    except (InvalidOperation, TypeError, KeyError) as sltp_err:
                        logger.error(f"Ticker WS: Erreur interne calcul SL/TP pour {received_symbol}: {sltp_err}")

        elif isinstance(msg, dict) and msg.get('e') == 'error':
            logger.error(f"Received WebSocket Ticker error message: {msg}")
        # else: logger.debug(f"Ignored Ticker WS message: {msg.get('e')}")

    except Exception as outer_e:
        logger.exception(f"!!! CRITICAL Outer Exception in process_ticker_message: {outer_e} !!!")


# --- Gestionnaire de Messages WebSocket Kline ---
def process_kline_message(msg: Dict[str, Any]):
    """
    Callback pour traiter les messages du WebSocket Kline.
    Met à jour l'historique et déclenche la logique de stratégie sur bougie fermée.
    """
    # logger.debug(f"Raw KLINE message: {msg}")
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

                history_list = []
                current_len = 0
                with kline_history_lock:
                    kline_history.append(formatted_kline)
                    history_list = list(kline_history) # Copie pour analyse
                    current_len = len(history_list)

                required_len = bot_state.get("required_klines", 100) # Default

                if current_len < required_len:
                    logger.info(f"Kline WS: Historique ({current_len}/{required_len}) insuffisant.")
                    return

                logger.debug(f"Kline WS: Historique suffisant ({current_len}/{required_len}). Calcul stratégie...")

                with config_lock: current_strategy_config = bot_config.copy()
                signals_df = strategy.calculate_indicators_and_signals(history_list, current_strategy_config)

                if signals_df is None or signals_df.empty:
                    logger.warning("Kline WS: Échec calcul indicateurs/signaux.")
                    return

                current_data = signals_df.iloc[-1]
                current_signal = current_data.get('signal')
                logger.debug(f"Kline WS: Dernier signal calculé: {current_signal}")

                # --- Logique d'Entrée / Sortie ---
                with config_lock: # Protéger l'accès à bot_state et bot_config
                    local_in_pos = bot_state["in_position"]
                    local_symbol = bot_state["symbol"] # Utiliser le symbole de l'état

                    # 1. Vérifier Entrée
                    if not local_in_pos and current_signal == 'BUY':
                        logger.debug("Kline WS: Vérification conditions d'entrée...")
                        local_avail_bal = bot_state["available_balance"]
                        local_risk = current_strategy_config["RISK_PER_TRADE"]
                        local_alloc = current_strategy_config["CAPITAL_ALLOCATION"]
                        symbol_info = binance_client_wrapper.get_symbol_info(local_symbol)

                        if symbol_info:
                            entry_order = strategy.check_entry_conditions(
                                current_data, local_symbol, local_risk, local_alloc,
                                local_avail_bal, symbol_info, current_strategy_config
                            )
                            if entry_order:
                                logger.info(f"Kline WS: Ordre d'ACHAT placé pour {local_symbol}.")
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
                                            # --- FIX for line 169 ---
                                            "timestamp": entry_order.get('transactTime', int(time.time()*1000))
                                            # --- END FIX ---
                                        }
                                        logger.info(f"Kline WS: Détails entrée MAJ: Prix={avg_price:.4f}, Qté={exec_qty}")
                                        logger.info("Kline WS: Mise à jour soldes via User Data Stream attendue.")

                                        # Ajouter à l'historique et sauvegarder
                                        simplified = {
                                            # --- FIX for line 176 ---
                                            "timestamp": entry_order.get('transactTime', int(time.time()*1000)),
                                            # --- END FIX ---
                                            "orderId": entry_order.get('orderId'), "symbol": entry_order.get('symbol'),
                                            "side": entry_order.get('side'), "type": entry_order.get('type'),
                                            "origQty": entry_order.get('origQty'), "executedQty": entry_order.get('executedQty'),
                                            "cummulativeQuoteQty": entry_order.get('cummulativeQuoteQty'),
                                            "price": entry_order.get('price'), "status": entry_order.get('status'),
                                            "performance_pct": None
                                        }
                                        bot_state['order_history'].append(simplified)
                                        # Limiter taille historique
                                        max_len = bot_state.get('max_history_length', 100)
                                        if len(bot_state['order_history']) > max_len:
                                            bot_state['order_history'] = bot_state['order_history'][-max_len:]
                                        logger.info(f"Kline WS: Ordre entrée {simplified.get('orderId','N/A')} ajouté historique.")
                                        # Sauvegarde gérée par state_manager
                                        if not bot_core.save_data(): # Utiliser la fonction importée
                                             logger.error("Kline WS: Echec sauvegarde état après entrée !")
                                    else:
                                        logger.warning("Kline WS: Ordre achat placé mais quantité exécutée nulle.")
                                except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
                                    logger.error(f"Kline WS: Erreur traitement détails ordre entrée: {e}.")
                        else:
                             logger.warning("Kline WS: Impossible vérifier entrée (symbol_info manquant).")

                    # 2. Vérifier Sortie (indicateur)
                    elif local_in_pos and current_signal == 'SELL':
                        logger.debug("Kline WS: En position. Vérification conditions sortie (indicateurs)...")
                        # La fonction check_exit_conditions retourne maintenant juste True/False
                        if strategy.check_exit_conditions(current_data, local_symbol):
                            logger.info("Kline WS: Signal sortie (indicateur) détecté. Lancement execute_exit...")
                            # Utiliser bot_core.execute_exit
                            threading.Thread(target=bot_core.execute_exit, args=("Signal Indicateur (Kline WS)",), daemon=True).start()

        elif isinstance(msg, dict) and msg.get('e') == 'error':
            logger.error(f"Received KLINE WebSocket error message: {msg}")
        # else: logger.debug(f"Ignored Kline WS message: {msg.get('e')}")

    except Exception as e:
        logger.exception(f"!!! CRITICAL Exception in process_kline_message: {e} !!!")


# --- Gestionnaire de Messages WebSocket User Data ---
# (process_user_data_message function remains unchanged)
def process_user_data_message(msg: Dict[str, Any]):
    """
    Callback pour traiter les messages du WebSocket User Data Stream.
    Met à jour les soldes ('outboundAccountPosition') et log les ordres ('executionReport').
    """
    # logger.debug(f"Raw USER DATA message: {msg}")
    try:
        event_type = msg.get('e')

        if event_type == 'outboundAccountPosition':
            balances = msg.get('B', [])
            with config_lock:
                base_asset = bot_state.get('base_asset')
                quote_asset = bot_state.get('quote_asset')
                updated_assets = []
                for balance_info in balances:
                    asset = balance_info.get('a')
                    free_balance_str = balance_info.get('f')
                    if asset and free_balance_str is not None:
                        try:
                            free_balance = float(free_balance_str)
                            if asset == base_asset:
                                current_val = bot_state.get('symbol_quantity')
                                if current_val is None or abs(current_val - free_balance) > 1e-9: # Tolérance float
                                    bot_state['symbol_quantity'] = free_balance
                                    updated_assets.append(f"{asset}={free_balance:.6f}")
                            elif asset == quote_asset:
                                current_val = bot_state.get('available_balance')
                                if current_val is None or abs(current_val - free_balance) > 1e-9: # Tolérance float
                                    bot_state['available_balance'] = free_balance
                                    updated_assets.append(f"{asset}={free_balance:.4f}")
                        except (ValueError, TypeError):
                            logger.error(f"User WS: Impossible convertir solde '{free_balance_str}' pour {asset}.")
                if updated_assets:
                    logger.info(f"User WS: Soldes mis à jour via outboundAccountPosition: {', '.join(updated_assets)}")

        elif event_type == 'executionReport':
            order_id = msg.get('i')
            status = msg.get('X')
            symbol = msg.get('s')
            side = msg.get('S')
            order_type = msg.get('o')
            exec_type = msg.get('x') # NEW, CANCELED, REPLACED, REJECTED, TRADE, EXPIRED
            cum_filled_qty = msg.get('z')
            last_filled_qty = msg.get('l')
            last_quote_qty = msg.get('Y') # Pour TRADE
            avg_price = msg.get('ap') # Pour TRADE (Average Price)

            log_msg = (f"User WS: Ordre {order_id} ({symbol} {side} {order_type}) "
                       f"Status={status} ExecType={exec_type} CumQty={cum_filled_qty}")
            if exec_type == 'TRADE':
                 log_msg += f" LastFillQty={last_filled_qty} AvgPrice={avg_price} LastQuoteQty={last_quote_qty}"

            # Logguer différemment selon le statut/type
            if status in ['REJECTED', 'EXPIRED'] or exec_type == 'REJECTED':
                logger.warning(log_msg + f" Reason: {msg.get('r', 'N/A')}")
            elif status == 'FILLED' or exec_type == 'TRADE':
                 logger.info(log_msg)
            else:
                 logger.debug(log_msg) # Pour NEW, CANCELED, PARTIALLY_FILLED etc.

        elif isinstance(msg, dict) and msg.get('e') == 'error':
            logger.error(f"Received USER DATA WebSocket error message: {msg}")
        # else: logger.debug(f"Ignored User WS message: {msg.get('e')}")

    except Exception as e:
        logger.exception(f"!!! CRITICAL Exception in process_user_data_message: {e} !!!")

# Exporter les handlers
__all__ = ['process_ticker_message', 'process_kline_message', 'process_user_data_message']
