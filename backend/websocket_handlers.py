# /Users/davidmichels/Desktop/trading-bot/backend/websocket_handlers.py
import logging
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional
import pandas as pd  # Pour traitement données SCALPING2

# --- Gestionnaires et Wrapper ---
from state_manager import state_manager
from config_manager import config_manager
import binance_client_wrapper  # Pour get_symbol_info si non mis en cache

# --- Utilitaires ---
from websocket_utils import (
    broadcast_state_update,
    broadcast_ticker_update,
)  # Assurez-vous que broadcast_ticker_update existe bien ici
from utils.order_utils import format_quantity, get_min_notional

# --- Logique Stratégie Spécifique ---
from strategies.swing_strategy import (
    calculate_indicators_and_signals as swing_calculate,
    check_entry_conditions as swing_check_entry,
    check_exit_conditions as swing_check_exit,
)
from strategies.scalping_strategy import (
    check_entry_conditions as scalping_check_entry,
    check_strategy_exit_conditions as scalping_check_strategy_exit,
    check_sl_tp as scalping_check_sl_tp,
)

from strategies.scalping_strategy_2 import (
    calculate_indicators,
    check_long_conditions,
    check_short_conditions,
    calculate_dynamic_sl_tp,
    check_exit_conditions as scalping_2_check_exit,
)

# --- Core (pour annulation/refresh) ---
import bot_core

logger = logging.getLogger(__name__)

# --- Fonctions d'exécution d'ordre (Encapsulation) ---


def execute_entry(order_params: Dict[str, Any]):
    """
    Passe un ordre d'entrée via le wrapper Binance et gère les logs/erreurs de base.
    Exécuté dans un thread séparé pour ne pas bloquer le handler WS.
    """
    symbol = order_params.get("symbol")
    side = order_params.get("side")
    order_type = order_params.get("order_type")
    quantity = order_params.get("quantity")
    price = order_params.get("price")  # Pour LIMIT

    log_msg = f"Attempting ENTRY: {side} {quantity} {symbol} ({order_type})"
    if order_type == "LIMIT":
        log_msg += f" @ {price}"
    logger.info(log_msg)

    try:
        # MODIFIÉ: Utilisation de ** pour déballer le dictionnaire
        order_result = binance_client_wrapper.place_order(**order_params)
        # --- FIN MODIFIÉ ---

        if order_result and order_result.get("orderId"):
            order_id = order_result["orderId"]
            logger.info(f"ENTRY Order Placement successful (via API): ID {order_id}")
            if order_type == "LIMIT":
                # MODIFIÉ: Appel update_state avec un dictionnaire
                state_manager.update_state(
                    {
                        "open_order_id": order_id,
                        "open_order_timestamp": int(time.time() * 1000),
                        "status": "ENTERING",
                    }
                )
                # --- FIN MODIFIÉ ---
                broadcast_state_update()
        else:
            logger.error(
                f"ENTRY Order Placement FAILED (via API) for {symbol}. No valid result/orderId."
            )
            if state_manager.get_state("status") == "ENTERING":
                # MODIFIÉ: Appel update_state avec un dictionnaire
                state_manager.update_state(
                    {
                        "status": "RUNNING",
                        "open_order_id": None,
                        "open_order_timestamp": None,
                    }
                )
                # --- FIN MODIFIÉ ---
                broadcast_state_update()

    except Exception as e:
        logger.error(
            f"CRITICAL Error during ENTRY order placement for {symbol}: {e}",
            exc_info=True,
        )
        # MODIFIÉ: Appel update_state avec un dictionnaire
        state_manager.update_state(
            {"status": "ERROR", "open_order_id": None, "open_order_timestamp": None}
        )
        # --- FIN MODIFIÉ ---
        broadcast_state_update()


def execute_exit(reason: str):
    """
    Passe un ordre MARKET de sortie pour fermer la position actuelle.
    Exécuté dans un thread séparé.
    """
    current_state = state_manager.get_state()
    symbol = current_state.get("symbol")
    base_asset = current_state.get("base_asset")
    symbol_quantity_held = current_state.get("symbol_quantity", 0.0)
    is_in_position = current_state.get("in_position", False)

    if not is_in_position or symbol_quantity_held <= 0 or not symbol or not base_asset:
        logger.warning(
            f"execute_exit called (Reason: {reason}) but state indicates not in position or invalid quantity for {symbol}."
        )
        return

    logger.info(
        f"Attempting EXIT for {symbol} (Reason: {reason}). Held Qty: {symbol_quantity_held}"
    )

    try:
        symbol_info = state_manager.get_symbol_info()
        if not symbol_info:
            symbol_info = binance_client_wrapper.get_symbol_info(symbol)
            if symbol_info:
                state_manager.update_symbol_info(symbol_info)
            else:
                logger.error(
                    f"EXIT Order: Failed to get symbol info for {symbol}. Cannot format quantity. Aborting exit."
                )
                return

        quantity_to_sell = format_quantity(symbol_quantity_held, symbol_info)

        if quantity_to_sell <= 0:
            logger.error(
                f"EXIT Order: Calculated quantity to sell is zero or negative ({quantity_to_sell}) after formatting for {symbol}. Held: {symbol_quantity_held}. Aborting exit."
            )
            # MODIFIÉ: Appel update_state avec un dictionnaire
            state_manager.update_state(
                {"in_position": False, "entry_details": None, "symbol_quantity": 0.0}
            )
            # --- FIN MODIFIÉ ---
            broadcast_state_update()
            return

        exit_order_params = {
            "symbol": symbol,
            "side": "SELL",
            "order_type": "MARKET",
            "quantity": str(quantity_to_sell),
        }

        # MODIFIÉ: Utilisation de ** pour déballer le dictionnaire
        order_result = binance_client_wrapper.place_order(**exit_order_params)
        # --- FIN MODIFIÉ ---

        if order_result and order_result.get("orderId"):
            logger.info(
                f"EXIT Order Placement successful (via API): ID {order_result['orderId']}. Reason: {reason}"
            )
            # MODIFIÉ: Appel update_state avec un dictionnaire
            state_manager.update_state({"status": "EXITING"})
            # --- FIN MODIFIÉ ---
            broadcast_state_update()
        else:
            logger.error(
                f"EXIT Order Placement FAILED (via API) for {symbol}. Reason: {reason}"
            )
            # MODIFIÉ: Appel update_state avec un dictionnaire
            state_manager.update_state({"status": "ERROR"})  # Ou RUNNING ?
            # --- FIN MODIFIÉ ---
            broadcast_state_update()

    except Exception as e:
        logger.error(
            f"CRITICAL Error during EXIT order placement for {symbol}: {e}",
            exc_info=True,
        )
        # MODIFIÉ: Appel update_state avec un dictionnaire
        state_manager.update_state({"status": "ERROR"})
        # --- FIN MODIFIÉ ---
        broadcast_state_update()


# --- Handlers de Messages WebSocket ---


def process_book_ticker_message(msg: Dict[str, Any]):
    """Callback @bookTicker: Met à jour état, diffuse ticker, vérifie SL/TP, déclenche logique SCALPING."""
    try:
        if isinstance(msg, dict) and "s" in msg and "b" in msg and "a" in msg:
            symbol = msg["s"]

            current_state = state_manager.get_state()
            current_config = config_manager.get_config()
            configured_symbol = current_state.get("symbol")

            if symbol != configured_symbol:
                return

            state_manager.update_book_ticker(msg)
            broadcast_ticker_update(
                msg
            )  # Assurez-vous que cette fonction existe dans websocket_utils

            strategy_type = current_config.get("STRATEGY_TYPE")
            is_in_position = current_state.get("in_position", False)
            entry_details = current_state.get("entry_details")
            open_order_id = current_state.get("open_order_id")
            open_order_timestamp = current_state.get("open_order_timestamp")

            if strategy_type == "SCALPING":
                if open_order_id:
                    # MODIFIÉ: Appel de la fonction locale check_limit_order_timeout
                    check_limit_order_timeout(
                        configured_symbol,
                        open_order_id,
                        open_order_timestamp,
                        current_config,
                    )
                    # --- FIN MODIFIÉ ---
                    return
                elif is_in_position and entry_details:
                    sl_tp_result = scalping_check_sl_tp(
                        configured_symbol, entry_details, msg, current_config
                    )
                    if sl_tp_result:  # Si SL ou TP est retourné
                        threading.Thread(
                            target=execute_exit,
                            args=(f"Hit ({sl_tp_result})",),
                            daemon=True,
                        ).start()
                        return
                    depth_data = state_manager.get_depth()
                    if depth_data and scalping_check_strategy_exit(
                        configured_symbol,
                        entry_details,
                        msg,
                        depth_data,
                        current_config,
                    ):
                        threading.Thread(
                            target=execute_exit,
                            args=("Signal Scalping Strategy Exit",),
                            daemon=True,
                        ).start()
                        return
                elif not is_in_position:
                    depth_data = state_manager.get_depth()
                    if not depth_data:
                        return
                    symbol_info = state_manager.get_symbol_info()
                    if not symbol_info:
                        logger.warning(
                            "SCALPING Entry Check: Symbol info non disponible."
                        )
                        return
                    entry_order_params = scalping_check_entry(
                        configured_symbol,
                        msg,
                        depth_data,
                        current_config,
                        current_state.get("available_balance", 0.0),
                        symbol_info,
                    )
                    if entry_order_params:
                        threading.Thread(
                            target=execute_entry,
                            args=(entry_order_params,),
                            daemon=True,
                        ).start()

            elif strategy_type == "SWING":
                if is_in_position and entry_details:
                    sl_tp_result = scalping_check_sl_tp(
                        configured_symbol, entry_details, msg, current_config
                    )
                    if sl_tp_result:  # Si SL ou TP est retourné
                        threading.Thread(
                            target=execute_exit,
                            args=(f"Hit ({sl_tp_result})",),
                            daemon=True,
                        ).start()
                        return

        elif isinstance(msg, dict) and msg.get("e") == "error":
            logger.error(f"Received WebSocket BookTicker error message: {msg}")

    except Exception as e:
        logger.critical(
            f"!!! CRITICAL Exception in process_book_ticker_message: {e} !!!",
            exc_info=True,
        )


def process_depth_message(msg: Dict[str, Any]):
    """Callback @depth: Met à jour snapshot de profondeur."""
    try:
        if (
            isinstance(msg, dict)
            and "lastUpdateId" in msg
            and "bids" in msg
            and "asks" in msg
        ):
            state_manager.update_depth(msg)
        else:
            logger.warning(f"Received unrecognized depth message format: {msg}")
    except Exception as e:
        logger.error(f"Error processing depth message: {e}", exc_info=True)


def process_agg_trade_message(msg: Dict[str, Any]):
    """Callback @aggTrade: Stocke trades récents (si utile)."""
    try:
        if isinstance(msg, dict) and msg.get("e") == "aggTrade" and "s" in msg:
            # state_manager.append_agg_trade(msg) # Décommenter si nécessaire
            pass
        elif isinstance(msg, dict) and msg.get("e") == "error":
            logger.error(f"Received WebSocket AggTrade error message: {msg}")
    except Exception as e:
        logger.critical(
            f"!!! CRITICAL Exception in process_agg_trade_message: {e} !!!",
            exc_info=True,
        )


def process_kline_message(msg: Dict[str, Any]):
    """Callback @kline: Met à jour historique et déclenche logique SWING et Scalping 2."""
    try:
        if isinstance(msg, dict) and msg.get("e") == "kline" and "k" in msg:
            kline_data = msg["k"]
            symbol = kline_data.get("s")
            is_closed = kline_data.get("x", False)
            interval = kline_data.get("i")

            current_state = state_manager.get_state()
            current_config = config_manager.get_config()
            configured_symbol = current_state.get("symbol")
            configured_timeframe = current_state.get("timeframe")
            strategy_type = current_config.get("STRATEGY_TYPE")

            if symbol != configured_symbol or interval != configured_timeframe:
                return

            if is_closed:
                logger.debug(f"Kline {symbol} ({interval}) CLOSED received.")
                formatted_kline = [
                    kline_data.get("t"),
                    kline_data.get("o"),
                    kline_data.get("h"),
                    kline_data.get("l"),
                    kline_data.get("c"),
                    kline_data.get("v"),
                    kline_data.get("T"),
                    kline_data.get("q"),
                    kline_data.get("n"),
                    kline_data.get("V"),
                    kline_data.get("Q"),
                    kline_data.get("B"),
                ]
                state_manager.add_kline(formatted_kline)

                full_kline_history = state_manager.get_kline_history_list()

                if strategy_type == "SWING":
                    required_len = state_manager.get_required_klines()
                    if len(full_kline_history) < required_len:
                        logger.info(
                            f"Kline WS (SWING): History ({len(full_kline_history)}/{required_len}) insufficient."
                        )
                        return

                    logger.debug(
                        f"Kline WS (SWING): Calculating signals on {len(full_kline_history)} klines..."
                    )
                    signals_df = swing_calculate(full_kline_history, current_config)
                    if signals_df is None or signals_df.empty:
                        logger.warning("Kline WS (SWING): Failed to calculate signals.")
                        return
                    handle_swing_signals(
                        signals_df.iloc[-1], current_state, current_config
                    )

                elif strategy_type == "SCALPING2":
                    if (
                        len(full_kline_history) < 20
                    ):  # Minimum requis pour les indicateurs
                        logger.info(
                            f"Kline WS (SCALPING2): History ({len(full_kline_history)}) insufficient."
                        )
                        return

                    # Convertir l'historique en DataFrame
                    df = pd.DataFrame(
                        full_kline_history,
                        columns=[
                            "timestamp",
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            "close_time",
                            "quote_volume",
                            "trades_count",
                            "taker_buy_volume",
                            "taker_buy_quote_volume",
                            "ignore",
                        ],
                    )
                    df = df.astype(
                        {"close": float, "high": float, "low": float, "volume": float}
                    )

                    # Calculer les indicateurs
                    df = calculate_indicators(df, current_config)

                    # Vérifier les conditions d'entrée et de sortie
                    handle_scalping2_signals(
                        df.iloc[-2:], current_state, current_config
                    )

        elif isinstance(msg, dict) and msg.get("e") == "error":
            logger.error(f"Received KLINE WebSocket error message: {msg}")

    except Exception as e:
        logger.critical(
            f"!!! CRITICAL Exception in process_kline_message: {e} !!!", exc_info=True
        )


def handle_swing_signals(latest_data, current_state, current_config):
    """Gère les signaux pour la stratégie SWING."""
    is_in_position = current_state.get("in_position")
    configured_symbol = current_state.get("symbol")

    if not is_in_position:
        logger.debug("Kline WS (SWING): Checking entry conditions...")
        symbol_info = state_manager.get_symbol_info()
        if not symbol_info:
            logger.warning("SWING Entry Check: Symbol info non disponible.")
            return
        entry_order_params = swing_check_entry(
            latest_data,
            configured_symbol,
            current_config,
            current_state.get("available_balance", 0.0),
            symbol_info,
        )
        if entry_order_params:
            threading.Thread(
                target=execute_entry, args=(entry_order_params,), daemon=True
            ).start()

    elif is_in_position:
        logger.debug("Kline WS (SWING): Checking indicator exit conditions...")
        if swing_check_exit(latest_data, configured_symbol):
            threading.Thread(
                target=execute_exit, args=("Signal Indicateur SWING",), daemon=True
            ).start()


def handle_scalping2_signals(last_two_rows, current_state, current_config):
    """Gère les signaux pour la stratégie SCALPING2."""
    is_in_position = current_state.get("in_position")
    configured_symbol = current_state.get("symbol")
    current_row = last_two_rows.iloc[-1]
    prev_row = last_two_rows.iloc[-2]

    if not is_in_position:
        # Vérifier les conditions d'entrée long et short
        long_signal, long_reason = check_long_conditions(current_row, prev_row)
        short_signal, short_reason = check_short_conditions(current_row, prev_row)

        if long_signal or short_signal:
            symbol_info = state_manager.get_symbol_info()
            if not symbol_info:
                logger.warning("SCALPING2 Entry Check: Symbol info non disponible.")
                return

            # Calculer le prix d'entrée (utiliser le prix de clôture comme approximation)
            entry_price = float(current_row["close"])
            side = "BUY" if long_signal else "SELL"

            # Calculer les niveaux SL/TP dynamiques
            sl_price, tp1_price, tp2_price = calculate_dynamic_sl_tp(
                entry_price=entry_price,
                side=side,
                config=current_config,
                recent_low=float(current_row["low"]),
                recent_high=float(current_row["high"]),
                atr_value=float(current_row["atr"]),
            )

            # Calculer la taille de la position en fonction du risque
            risk_amount = current_state.get(
                "available_balance", 0.0
            ) * current_config.get("RISK_PER_TRADE_PERCENTAGE", 0.01)
            risk_per_unit = abs(entry_price - sl_price)
            position_size = risk_amount / risk_per_unit

            # Créer les paramètres d'ordre
            entry_order_params = {
                "symbol": configured_symbol,
                "side": side,
                "type": "MARKET",
                "quantity": format_quantity(position_size, symbol_info),
                "sl_price": sl_price,
                "tp_price": tp1_price,
            }

            threading.Thread(
                target=execute_entry, args=(entry_order_params,), daemon=True
            ).start()
            logger.info(
                f"SCALPING2 Entry Signal: {side} @ {entry_price:.8f} (SL: {sl_price:.8f}, TP1: {tp1_price:.8f})"
            )

    elif is_in_position:
        position_data = current_state.get("entry_details", {})
        current_price = float(current_row["close"])
        position_duration = int(time.time()) - int(
            position_data.get("timestamp", time.time()) / 1000
        )

        should_exit, exit_reason = scalping_2_check_exit(
            current_price=current_price,
            position_data=position_data,
            config=current_config,
            position_duration=position_duration,
        )

        if should_exit:
            threading.Thread(
                target=execute_exit,
                args=(f"SCALPING2 Exit: {exit_reason}",),
                daemon=True,
            ).start()


# --- User Data Handler ---
def process_user_data_message(data: Dict[str, Any]):
    """Traite les messages User Data Stream (ordres, balance)."""
    event_type = data.get("e")
    try:
        if event_type == "executionReport":
            _handle_execution_report(data)
        elif event_type == "outboundAccountPosition":
            _handle_account_position(data)
        elif event_type == "balanceUpdate":
            _handle_balance_update(data)
    except Exception as e:
        logger.error(
            f"Error processing User Data message (Type: {event_type}): {e}",
            exc_info=True,
        )


def _handle_execution_report(data: dict):
    """Gère les mises à jour d'exécution d'ordre."""
    order_id = data.get("i")
    symbol = data.get("s")
    side = data.get("S")
    order_type = data.get("o")
    status = data.get("X")
    client_order_id = data.get("c")
    reject_reason = data.get("r", "NONE")

    logger.info(
        f"Execution Report: ID={order_id}, ClientID={client_order_id}, Status={status}, Side={side}, Type={order_type}"
        + (f", Reason={reject_reason}" if status == "REJECTED" else "")
    )

    if symbol:
        logger.debug(
            f"ExecutionReport: Triggering history refresh for {symbol} via REST..."
        )
        threading.Thread(
            target=bot_core.refresh_order_history_via_rest,
            args=(symbol, 50),
            daemon=True,
        ).start()
    else:
        logger.warning(
            "ExecutionReport: Cannot trigger history refresh, symbol missing."
        )

    state_updates = {}
    current_state = state_manager.get_state()
    current_open_order_id = current_state.get("open_order_id")

    if status not in ["NEW", "PARTIALLY_FILLED"] and current_open_order_id == order_id:
        logger.info(
            f"ExecutionReport: Clearing open order ID {order_id} (status: {status})."
        )
        state_updates["open_order_id"] = None
        state_updates["open_order_timestamp"] = None
        if status in ["CANCELED", "REJECTED", "EXPIRED"] and current_state.get(
            "status"
        ) in ["ENTERING", "EXITING"]:
            state_updates["status"] = "RUNNING"

    if status == "FILLED":
        try:
            exec_qty = float(data.get("z", 0))
            quote_qty = float(data.get("Z", 0))
            if exec_qty > 0:
                avg_price = quote_qty / exec_qty
                order_time = data.get("T")

                if side == "BUY" and not current_state.get("in_position"):
                    logger.info(
                        f"ExecutionReport (FILLED BUY): Entering position via WS. OrderID={order_id}, AvgPrice={avg_price:.4f}, Qty={exec_qty}"
                    )
                    state_updates["in_position"] = True
                    state_updates["entry_details"] = {
                        "order_id": order_id,
                        "avg_price": avg_price,
                        "quantity": exec_qty,
                        "timestamp": order_time,
                    }
                    state_updates["status"] = "RUNNING"
                elif side == "SELL" and current_state.get("in_position"):
                    logger.info(
                        f"ExecutionReport (FILLED SELL): Exiting position via WS. OrderID={order_id}, AvgPrice={avg_price:.4f}, Qty={exec_qty}"
                    )
                    state_updates["in_position"] = False
                    state_updates["entry_details"] = None
                    state_updates["status"] = "RUNNING"
            else:
                logger.warning(
                    f"ExecutionReport (FILLED): Order {order_id} has zero executed quantity?"
                )
        except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
            logger.error(
                f"ExecutionReport (FILLED): Error processing order {order_id}: {e}",
                exc_info=True,
            )

    if state_updates:
        # MODIFIÉ: Appel update_state avec un dictionnaire
        state_manager.update_state(state_updates)
        # --- FIN MODIFIÉ ---
        broadcast_state_update()


def _handle_account_position(data: dict):
    """Gère les mises à jour de balance."""
    balances = data.get("B", [])
    state_updates = {}
    quote_asset = state_manager.get_state("quote_asset")
    base_asset = state_manager.get_state("base_asset")
    current_quote_balance = state_manager.get_state("available_balance")
    current_base_quantity = state_manager.get_state("symbol_quantity")

    for balance_info in balances:
        asset = balance_info.get("a")
        free_balance_str = balance_info.get("f")

        if asset and free_balance_str is not None:
            try:
                free_balance = float(free_balance_str)
                if asset == quote_asset:
                    if abs(current_quote_balance - free_balance) > 1e-9:
                        logger.info(
                            f"Account Position: {asset} balance updated to {free_balance:.4f}"
                        )
                        state_updates["available_balance"] = free_balance
                elif asset == base_asset:
                    if abs(current_base_quantity - free_balance) > 1e-9:
                        logger.info(
                            f"Account Position: {asset} quantity updated to {free_balance:.8f}"
                        )
                        state_updates["symbol_quantity"] = free_balance
            except (ValueError, TypeError):
                logger.warning(
                    f"Account Position: Could not convert balance for {asset}: '{free_balance_str}'"
                )

    if state_updates:
        # MODIFIÉ: Appel update_state avec un dictionnaire
        state_manager.update_state(state_updates)
        # --- FIN MODIFIÉ ---
        broadcast_state_update()


def _handle_balance_update(data: dict):
    """Gère les événements 'balanceUpdate'."""
    asset = data.get("a")
    delta = data.get("d")
    clear_time = data.get("T")
    logger.info(
        f"Balance Update Event: Asset={asset}, Delta={delta}, ClearTime={clear_time}"
    )


# --- Limit Order Timeout Check (Fonction Locale) ---
def check_limit_order_timeout(
    symbol: str,
    order_id: Optional[int],
    order_timestamp: Optional[int],
    current_config: Dict[str, Any],
):
    """Vérifie si un ordre LIMIT ouvert a dépassé son timeout."""
    if not order_id or not order_timestamp:
        return

    timeout_ms = current_config.get("SCALPING_LIMIT_ORDER_TIMEOUT_MS")
    if timeout_ms is None or timeout_ms <= 0:
        return

    current_time_ms = int(time.time() * 1000)

    if current_time_ms - order_timestamp > timeout_ms:
        logger.warning(
            f"LIMIT Order {order_id} exceeded timeout ({timeout_ms}ms). Attempting cancellation..."
        )
        threading.Thread(
            target=bot_core.cancel_scalping_order, args=(symbol, order_id), daemon=True
        ).start()


# --- Exports ---
__all__ = [
    "process_book_ticker_message",
    "process_depth_message",
    "process_agg_trade_message",
    "process_kline_message",
    "process_user_data_message",
]
