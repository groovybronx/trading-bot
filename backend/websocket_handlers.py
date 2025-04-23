# /Users/davidmichels/Desktop/trading-bot/backend/websocket_handlers.py
import logging
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import numpy as np  # Import numpy for NaN comparison if needed
from datetime import datetime  # Import datetime for formatting

# --- Gestionnaires et Wrapper ---
from manager.state_manager import state_manager
from manager.config_manager import config_manager
import binance_client_wrapper

# --- Utilitaires ---
from utils.websocket_utils import (
    broadcast_state_update,
    broadcast_ticker_update,
    broadcast_signal_event,
    broadcast_order_history_update,  # Used after DB save
)
from utils.order_utils import (
    format_quantity,
    get_min_notional,
    check_min_notional,
    format_price,
)

# --- Logique Stratégie Spécifique ---
# Import Strategy Classes
from strategies.swing_strategy import SwingStrategy
from strategies.scalping_strategy import ScalpingStrategy
from strategies.scalping_strategy_2 import ScalpingStrategy2

# --- Core (pour refresh ET order_manager) ---
# Import the order_manager instance from its central location
from manager.order_manager import order_manager
# refresh_order_history_via_rest is called from bot_core during startup, no need to import here currently.


# --- MODIFIED: Import DB ---
import db

logger = logging.getLogger(__name__)

# --- Moved Function ---
def cancel_scalping_order(symbol: str, order_id: int):
    """Annule un ordre LIMIT ouvert en utilisant OrderManager."""
    # This function now resides within websocket_handlers
    logger.info(f"Attempting to cancel Order: {order_id} on {symbol} via OrderManager...")
    # Use the imported OrderManager instance to cancel the order
    success = order_manager.cancel_order(symbol=symbol, order_id=order_id)

    if success:
        logger.info(f"OrderManager reported successful cancellation initiation for order {order_id}.")
        # OrderManager handles logging and state updates internally now.
    else:
        logger.error(f"OrderManager reported failure trying to cancel order {order_id}.")

# --- Instantiate Strategies ---
# Instantiate strategy objects - consider loading dynamically based on config in future
swing_strategy_instance = SwingStrategy()
scalping_strategy_instance = ScalpingStrategy()
scalping2_strategy_instance = ScalpingStrategy2()  # Instantiate ScalpingStrategy2


# --- Fonctions d'exécution d'ordre (Encapsulation) ---


def _execute_order_thread(order_params: Dict[str, Any], action: str, **kwargs):
    """Thread pour passer un ordre (entrée ou sortie) via le wrapper ou order_manager."""
    symbol = order_params.get("symbol")
    side = order_params.get("side")
    order_type = order_params.get("order_type")
    qty_info = order_params.get("quantity") or order_params.get("quoteOrderQty")
    price_info = f" @ {order_params.get('price')}" if order_params.get("price") else ""

    log_msg = f"Thread Exec Order ({action}): {side} {qty_info} {symbol} ({order_type}{price_info})"
    logger.info(log_msg)

    current_config = config_manager.get_config()
    cooldown_ms = current_config.get("ORDER_COOLDOWN_MS", 0)
    last_order_ts = state_manager.get_last_order_timestamp() or 0
    now_ms = int(time.time() * 1000)
    if cooldown_ms > 0 and (now_ms - last_order_ts) < cooldown_ms:
        logger.warning(
            f"COOLDOWN GLOBAL ACTIF: {cooldown_ms - (now_ms - last_order_ts)}ms restants avant nouvel ordre. Ordre ignoré."
        )
        return

    sl_price_from_signal = kwargs.get("sl_price")
    tp1_price_from_signal = kwargs.get("tp1_price")
    tp2_price_from_signal = kwargs.get("tp2_price")

    order_result = None
    client_order_id = f"bot_{action.lower()}_{int(time.time()*1000)}"
    order_params_with_cid = order_params.copy()
    order_params_with_cid["newClientOrderId"] = client_order_id

    if action == "ENTRY" and sl_price_from_signal is not None:
        state_manager.store_pending_order_details(
            client_order_id,
            {
                "sl_price": sl_price_from_signal,
                "tp1_price": tp1_price_from_signal,
                "tp2_price": tp2_price_from_signal,
            },
        )
        logger.debug(f"Stored pending SL/TP for clientOrderId {client_order_id}")

    state_manager.set_last_order_timestamp(now_ms)

    try:
        # Use order_manager to place the order
        qty_float = (
            float(order_params_with_cid["quantity"])
            if "quantity" in order_params_with_cid
            else None
        )
        price_float = (
            float(order_params_with_cid["price"])
            if "price" in order_params_with_cid
            and order_params_with_cid["price"] is not None
            else None
        )
        quote_qty_float = (
            float(order_params_with_cid["quoteOrderQty"])
            if "quoteOrderQty" in order_params_with_cid
            else None
        )

        if (
            order_params_with_cid["order_type"] == "MARKET"
            and order_params_with_cid["side"] == "BUY"
            and quote_qty_float is not None
        ):
            logger.warning(
                f"Market BUY with quoteOrderQty detected. Using direct binance_client_wrapper.place_order for ClientID {client_order_id}."
            )
            order_result = binance_client_wrapper.place_order(**order_params_with_cid)
        elif qty_float is not None:
            order_result = order_manager.place_order(
                symbol=order_params_with_cid["symbol"],
                side=order_params_with_cid["side"],
                order_type=order_params_with_cid["order_type"],
                quantity=qty_float,
                price=price_float,
            )
        else:
            logger.error(
                f"Order Placement ({action}): Invalid parameters for OrderManager. Qty: {qty_float}, Price: {price_float}, QuoteQty: {quote_qty_float}"
            )
            order_result = None

        if order_result and order_result.get("orderId"):
            order_id = order_result["orderId"]
            status = order_result.get("status", "UNKNOWN")
            api_client_order_id = order_result.get("clientOrderId")
            logger.info(
                f"Order Placement API Result ({action}): ID {order_id}, ClientID {api_client_order_id}, Status {status}"
            )

            if order_type == "LIMIT" and status == "NEW":
                state_manager.update_state(
                    {
                        "open_order_id": order_id,
                        "open_order_timestamp": int(time.time() * 1000),
                        "status": (
                            "ENTERING"
                            if action == "ENTRY"
                            else state_manager.get_state("status")
                        ),
                    }
                )
            elif status in ["REJECTED", "EXPIRED", "CANCELED"]:
                logger.warning(
                    f"Order {order_id} (ClientID: {api_client_order_id}, Action: {action}) failed immediately via API (Status: {status})."
                )
                if action == "ENTRY" and api_client_order_id:
                    state_manager.clear_pending_order_details(api_client_order_id)
                current_status = state_manager.get_state("status")
                if current_status in ["ENTERING", "EXITING"]:
                    state_updates = {
                        "status": "RUNNING",
                        "open_order_id": None,
                        "open_order_timestamp": None,
                    }
                    state_manager.update_state(state_updates)

        else:
            logger.error(
                f"Order Placement FAILED ({action}) via API for {symbol}. No valid result/orderId. ClientID: {client_order_id}. Response: {order_result}"
            )
            if action == "ENTRY" and client_order_id:
                state_manager.clear_pending_order_details(client_order_id)
            current_status = state_manager.get_state("status")
            if current_status in ["ENTERING", "EXITING"]:
                state_updates = {
                    "status": "RUNNING",
                    "open_order_id": None,
                    "open_order_timestamp": None,
                }
                state_manager.update_state(state_updates)

    except Exception as e:
        logger.error(
            f"CRITICAL Error during {action} order placement thread for {symbol}: {e}",
            exc_info=True,
        )
        client_order_id_on_error = (
            order_params_with_cid.get("newClientOrderId")
            if "order_params_with_cid" in locals()
            else None
        )
        if action == "ENTRY" and client_order_id_on_error:
            state_manager.clear_pending_order_details(client_order_id_on_error)
        state_updates = {
            "status": "ERROR",
            "open_order_id": None,
            "open_order_timestamp": None,
        }
        state_manager.update_state(state_updates)


def execute_entry(order_params: Dict[str, Any], **kwargs):
    """Lance un thread pour passer un ordre d'entrée."""
    if order_params.get("order_type") != "LIMIT":
        state_manager.update_state({"status": "ENTERING"})
    threading.Thread(
        target=_execute_order_thread,
        args=(order_params.copy(), "ENTRY"),
        kwargs=kwargs,
        daemon=True,
    ).start()


def execute_exit(reason: str):
    """Prépare et lance un thread pour passer un ordre MARKET de sortie."""
    current_state = state_manager.get_state()
    symbol = current_state.get("symbol")
    base_asset = current_state.get("base_asset")
    entry_details = current_state.get("entry_details")
    qty_in_details = entry_details.get("quantity") if entry_details else None
    qty_in_state = current_state.get("symbol_quantity", Decimal("0.0"))

    try:
        qty_to_sell_raw = (
            Decimal(str(qty_in_details)) if qty_in_details is not None else qty_in_state
        )
    except (InvalidOperation, TypeError):
        logger.error(
            f"execute_exit: Invalid quantity in state/details. Details: {qty_in_details}, State: {qty_in_state}"
        )
        if current_state.get("in_position"):
            state_manager.update_state(
                {"in_position": False, "entry_details": None, "status": "RUNNING"}
            )
        return

    if (
        not current_state.get("in_position")
        or qty_to_sell_raw <= 0
        or not symbol
        or not base_asset
    ):
        logger.warning(
            f"execute_exit called (Reason: {reason}) but not in valid position for {symbol}. Qty: {qty_to_sell_raw}"
        )
        if current_state.get("in_position"):
            state_manager.update_state({"in_position": False, "entry_details": None})
        return

    logger.info(
        f"Attempting EXIT for {symbol} (Reason: {reason}). Base Qty: {qty_to_sell_raw}"
    )
    state_manager.update_state({"status": "EXITING"})

    try:
        symbol_info = state_manager.get_symbol_info()
        if not symbol_info:
            symbol_info = binance_client_wrapper.get_symbol_info(symbol)
            if symbol_info:
                state_manager.update_symbol_info(symbol_info)
            else:
                logger.error(
                    f"EXIT Order: Failed to get symbol info for {symbol}. Aborting exit."
                )
                state_manager.update_state({"status": "ERROR"})
                return

        formatted_quantity_to_sell = format_quantity(qty_to_sell_raw, symbol_info)

        if formatted_quantity_to_sell is None or formatted_quantity_to_sell <= 0:
            logger.error(
                f"EXIT Order: Calculated quantity to sell invalid ({formatted_quantity_to_sell}) after formatting for {symbol}. Raw: {qty_to_sell_raw}. Aborting."
            )
            state_manager.update_state(
                {
                    "in_position": False,
                    "entry_details": None,
                    "symbol_quantity": Decimal("0.0"),
                    "status": "RUNNING",
                }
            )
            return

        ticker = state_manager.get_book_ticker()
        current_price = Decimal(ticker.get("a", "0"))
        min_notional = get_min_notional(symbol_info)

        if current_price <= 0:
            logger.warning(
                f"EXIT Order: Invalid current price ({current_price}) for min_notional check. Proceeding anyway..."
            )
        elif not check_min_notional(
            formatted_quantity_to_sell, current_price, min_notional
        ):
            logger.error(
                f"EXIT Order: Estimated notional ({formatted_quantity_to_sell * current_price:.4f}) < MIN_NOTIONAL ({min_notional:.4f}). Order might fail. Aborting exit."
            )
            state_manager.update_state({"status": "RUNNING"})
            return

        exit_order_params = {
            "symbol": symbol,
            "side": "SELL",
            "order_type": "MARKET",
            "quantity": formatted_quantity_to_sell,
        }

        threading.Thread(
            target=_execute_order_thread,
            args=(exit_order_params.copy(), "EXIT"),
            daemon=True,
        ).start()

    except Exception as e:
        logger.error(
            f"CRITICAL Error preparing EXIT order for {symbol}: {e}", exc_info=True
        )
        state_manager.update_state({"status": "ERROR"})


# --- Vérification SL/TP Centralisée ---
# TODO: This function might be redundant if SL/TP logic is fully handled by strategies or OrderManager features in the future.
def _check_common_sl_tp(
    entry_details: Dict[str, Any],
    book_ticker: Dict[str, Any],
    current_config: Dict[str, Any],
) -> Optional[str]:
    """Vérifie Stop Loss et Take Profit (basé sur TP1)."""
    if not entry_details or not book_ticker:
        return None
    try:
        entry_price = Decimal(str(entry_details.get("avg_price", "0")))
        if entry_price <= 0:
            return None
        current_price = Decimal(book_ticker.get("b", "0"))
        if current_price <= 0:
            return None

        sl_frac = current_config.get("STOP_LOSS_PERCENTAGE", Decimal("0.005"))
        stop_loss_price = entry_price * (Decimal(1) - sl_frac)
        if current_price <= stop_loss_price:
            logger.info(
                f"SL Hit: Bid {current_price:.4f} <= SL {stop_loss_price:.4f} (Entry: {entry_price:.4f})"
            )
            return "SL"

        tp1_frac = current_config.get("TAKE_PROFIT_1_PERCENTAGE", Decimal("0.01"))
        take_profit_price = entry_price * (Decimal(1) + tp1_frac)
        if current_price >= take_profit_price:
            logger.info(
                f"TP Hit: Bid {current_price:.4f} >= TP1 {take_profit_price:.4f} (Entry: {entry_price:.4f})"
            )
            return "TP"
    except (InvalidOperation, TypeError, KeyError) as e:
        logger.error(f"Check SL/TP Error: {e}", exc_info=True)
    return None


# --- Handlers de Messages WebSocket ---


def process_book_ticker_message(msg: Dict[str, Any]):
    """Callback @bookTicker: Met à jour état, diffuse ticker, vérifie SL/TP, timeout, logique SCALPING."""
    try:
        if not isinstance(msg, dict) or "s" not in msg:
            return

        symbol = msg.get("s")
        current_state = state_manager.get_state()
        current_config = config_manager.get_config()
        configured_symbol = current_state.get("symbol")

        if symbol != configured_symbol:
            return

        state_manager.update_book_ticker(msg)

        strategy_type = current_config.get("STRATEGY_TYPE")
        is_in_position = current_state.get("in_position", False)
        entry_details = current_state.get("entry_details")
        current_status = current_state.get("status")
        open_order_id = current_state.get("open_order_id")
        open_order_timestamp = current_state.get("open_order_timestamp")

        if open_order_id and current_status == "ENTERING":
            check_limit_order_timeout(
                configured_symbol, open_order_id, open_order_timestamp, current_config
            )
            return

        if is_in_position and entry_details and current_status == "RUNNING":
            if strategy_type != "SCALPING2":
                sl_tp_result = _check_common_sl_tp(entry_details, msg, current_config)
                if sl_tp_result:
                    execute_exit(f"Hit ({sl_tp_result})")
                    return

        if current_status == "RUNNING":
            # Use strategy instances based on strategy_type
            if strategy_type == "SCALPING":
                # Pass necessary data via kwargs to the strategy methods
                strategy_kwargs = {
                    "book_ticker": msg,
                    "depth": state_manager.get_depth(),
                }

                if is_in_position and entry_details:
                    exit_reason = scalping_strategy_instance.check_exit_signal(
                        latest_data=pd.Series(),  # Pass empty Series as latest_data is unused
                        position_data=entry_details,
                        **strategy_kwargs,
                    )
                    if exit_reason:
                        execute_exit(f"SCALPING Exit: {exit_reason}")
                        return
                elif not is_in_position:
                    entry_order_params = scalping_strategy_instance.check_entry_signal(
                        latest_data=pd.Series(),  # Pass empty Series as latest_data is unused
                        **strategy_kwargs,
                    )
                    if entry_order_params:
                        # Need to convert quantity/price back to float if they are Decimal in params
                        if "quantity" in entry_order_params and isinstance(
                            entry_order_params["quantity"], Decimal
                        ):
                            entry_order_params["quantity"] = float(
                                entry_order_params["quantity"]
                            )
                        if "price" in entry_order_params and isinstance(
                            entry_order_params["price"], Decimal
                        ):
                            entry_order_params["price"] = float(
                                entry_order_params["price"]
                            )
                        if "quoteOrderQty" in entry_order_params and isinstance(
                            entry_order_params["quoteOrderQty"], Decimal
                        ):
                            entry_order_params["quoteOrderQty"] = float(
                                entry_order_params["quoteOrderQty"]
                            )
                        execute_entry(entry_order_params)
            # Keep other strategy logic (e.g., SCALPING2) as is for now
            # elif strategy_type == "OTHER_STRATEGY":
            #    ...

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
    except Exception as e:
        logger.error(f"Error processing depth message: {e}", exc_info=True)


def process_agg_trade_message(msg: Dict[str, Any]):
    """Callback @aggTrade: Stocke trades récents (si utile)."""
    pass


def process_kline_message(msg: Dict[str, Any]):
    """Callback @kline: Met à jour historique et déclenche logique SWING et SCALPING2."""
    try:
        if not isinstance(msg, dict) or msg.get("e") != "kline" or "k" not in msg:
            return

        kline_data = msg["k"]
        symbol = kline_data.get("s")
        is_closed = kline_data.get("x", False)
        interval = kline_data.get("i")

        current_state = state_manager.get_state()
        current_config = config_manager.get_config()
        configured_symbol = current_state.get("symbol")
        configured_timeframe = current_state.get("timeframe")
        strategy_type = current_config.get("STRATEGY_TYPE")
        current_status = current_state.get("status")

        if symbol != configured_symbol or interval != configured_timeframe:
            return

        if is_closed and current_status == "RUNNING":
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
            required_len = state_manager.get_required_klines()

            if len(full_kline_history) < required_len:
                logger.info(
                    f"Kline WS ({strategy_type}): History ({len(full_kline_history)}/{required_len}) insufficient."
                )
                return

            # --- Convert kline list to DataFrame ---
            df = pd.DataFrame(
                full_kline_history,
                columns=[
                    "timestamp",
                    "Open",
                    "High",
                    "Low",
                    "Close",
                    "Volume",
                    "close_time",
                    "Quote_Asset_Volume",
                    "Number_of_Trades",
                    "Taker_Buy_Base_Asset_Volume",
                    "Taker_Buy_Quote_Asset_Volume",
                    "Ignore",
                ],
            )
            # Convert relevant columns to numeric/Decimal
            numeric_cols = [
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
                "Quote_Asset_Volume",
                "Taker_Buy_Base_Asset_Volume",
                "Taker_Buy_Quote_Asset_Volume",
            ]
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                    if (
                        pd.api.types.is_numeric_dtype(df[col])
                        and not df[col].isnull().all()
                    ):
                        try:
                            new_col_values = [
                                Decimal(str(v)) if pd.notna(v) else None
                                for v in df[col]
                            ]
                            df[col] = new_col_values
                        except (InvalidOperation, TypeError) as conv_err:
                            logger.error(
                                f"Error converting column {col} to Decimal: {conv_err}"
                            )
                            df[col] = None
                    elif df[col].isnull().all():
                        df[col] = df[col].astype(object)

            df.dropna(subset=["Open", "High", "Low", "Close", "Volume"], inplace=True)
            if len(df) < required_len:
                logger.info(
                    f"Kline WS ({strategy_type}): History ({len(df)}/{required_len}) insufficient after cleaning."
                )
                return

            # --- Strategy Logic ---
            if strategy_type == "SWING":
                logger.debug(
                    f"Kline WS (SWING): Calculating indicators on {len(df)} klines..."
                )
                # Use the strategy instance
                df_with_indicators = swing_strategy_instance.calculate_indicators(df)
                if df_with_indicators.empty or len(df_with_indicators) < 1:
                    logger.warning(
                        "Kline WS (SWING): Failed to calculate indicators or empty result."
                    )
                    return

                latest_data = df_with_indicators.iloc[-1]
                is_in_position = current_state.get("in_position")

                if not is_in_position:
                    entry_order_params = swing_strategy_instance.check_entry_signal(
                        latest_data
                    )
                    if entry_order_params:
                        execute_entry(entry_order_params)
                elif is_in_position:
                    exit_reason = swing_strategy_instance.check_exit_signal(
                        latest_data, current_state.get("entry_details", {})
                    )
                    if exit_reason:
                        execute_exit(f"SWING Exit: {exit_reason}")

            elif strategy_type == "SCALPING2":
                 logger.debug(f"Kline WS (SCALPING2): Calculating indicators on {len(df)} klines...")
                 # Use the strategy instance
                 df_with_indicators = scalping2_strategy_instance.calculate_indicators(df)

                 if df_with_indicators.empty or len(df_with_indicators) < 2:
                      logger.warning("Kline WS (SCALPING2): Failed to calculate indicators or not enough data (>=2 rows).")
                      return

                 # Pass latest and previous row to check_entry_signal
                 latest_data = df_with_indicators.iloc[-1]
                 prev_row = df_with_indicators.iloc[-2]
                 is_in_position = current_state.get("in_position")

                 if not is_in_position:
                      entry_order_params = scalping2_strategy_instance.check_entry_signal(latest_data, prev_row=prev_row)
                      if entry_order_params:
                           # Extract SL/TP from params for kwargs if present
                           sl_price = entry_order_params.pop('sl_price', None)
                           tp1_price = entry_order_params.pop('tp1_price', None)
                           tp2_price = entry_order_params.pop('tp2_price', None)
                           execute_entry(entry_order_params, sl_price=sl_price, tp1_price=tp1_price, tp2_price=tp2_price)
                 elif is_in_position:
                      # Need current price and position duration for exit check
                      book_ticker = state_manager.get_book_ticker()
                      current_price_str = book_ticker.get("b") # Use bid price for checking exit on LONG
                      entry_details = current_state.get("entry_details", {})
                      entry_timestamp_ms = entry_details.get("timestamp")

                      if current_price_str and entry_timestamp_ms:
                           try:
                                current_price_dec = Decimal(current_price_str)
                                position_duration_seconds = int(time.time()) - int(entry_timestamp_ms / 1000)

                                exit_kwargs = {
                                     'current_price': current_price_dec,
                                     'position_duration_seconds': position_duration_seconds
                                }
                                # Pass empty Series for latest_data as it's unused in check_exit_signal for SCALPING2
                                exit_reason = scalping2_strategy_instance.check_exit_signal(pd.Series(dtype=float), entry_details, **exit_kwargs)
                                if exit_reason:
                                     execute_exit(f"SCALPING2 Exit: {exit_reason}")
                           except (ValueError, TypeError, InvalidOperation) as e:
                                logger.error(f"SCALPING2 Exit Check: Error preparing data - {e}")
                      else:
                           logger.warning("SCALPING2 Exit Check: Missing current price or entry timestamp.")

    except Exception as e:
        logger.critical(
            f"!!! CRITICAL Exception in process_kline_message: {e} !!!", exc_info=True
        )


# --- Logique Spécifique Stratégie (REMOVED handle_swing_signals and handle_scalping2_signals) ---
# def handle_swing_signals(...): # REMOVED
# def handle_scalping2_signals(...): # REMOVED


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


def _format_execution_report_for_db(exec_report: Dict[str, Any]) -> Dict[str, Any]:
    """Formats the execution report data for saving into the database."""
    order_id = str(exec_report.get("i", "N/A"))
    side = exec_report.get("S")
    status = exec_report.get("X")
    timestamp = exec_report.get("T")

    strategy = config_manager.get_value("STRATEGY_TYPE", "UNKNOWN")
    session_id = state_manager.get_session_id()

    performance_pct = None
    pnl_value = None
    entry_details_hist = (
        state_manager.get_state("entry_details")
        if side == "SELL" and status == "FILLED"
        else None
    )

    if entry_details_hist:
        try:
            entry_price = Decimal(str(entry_details_hist.get("avg_price", "0")))
            exec_qty_sell = Decimal(str(exec_report.get("z", "0")))
            quote_qty_sell = Decimal(str(exec_report.get("Z", "0")))
            if entry_price > 0 and exec_qty_sell > 0:
                exit_price = quote_qty_sell / exec_qty_sell
                perf = (exit_price - entry_price) / entry_price
                performance_pct = f"{perf:.4%}"
                pnl_value = (exit_price - entry_price) * exec_qty_sell
                logger.info(
                    f"Calculated PNL for order {order_id}: {pnl_value:.4f} {state_manager.get_state('quote_asset')}, Perf: {performance_pct}"
                )
        except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
            logger.warning(
                f"Failed to calculate performance/PNL for order {order_id}: {e}",
                exc_info=False,
            )

    formatted_order = {
        "timestamp": int(timestamp) if timestamp else int(time.time() * 1000),
        "orderId": order_id,
        "clientOrderId": exec_report.get("c"),
        "symbol": exec_report.get("s"),
        "strategy": strategy,
        "side": side,
        "type": exec_report.get("o"),
        "timeInForce": exec_report.get("f"),
        "origQty": exec_report.get("q"),
        "executedQty": exec_report.get("z"),
        "cummulativeQuoteQty": exec_report.get("Z"),
        "status": status,
        "price": exec_report.get("p"),
        "stopPrice": exec_report.get("P"),
        "pnl": float(pnl_value) if pnl_value is not None else None,
        "performance_pct": performance_pct,
        "session_id": session_id,
        "created_at": (
            datetime.utcfromtimestamp(timestamp / 1000).isoformat()
            if timestamp
            else datetime.utcnow().isoformat()
        ),
        "closed_at": (
            datetime.utcfromtimestamp(timestamp / 1000).isoformat()
            if timestamp and status in ["FILLED", "CANCELED", "EXPIRED", "REJECTED"]
            else None
        ),
    }
    return formatted_order


def _handle_execution_report(data: dict):
    """Gère les mises à jour d'exécution d'ordre, met à jour DB et état."""
    order_id = data.get("i")
    symbol = data.get("s")
    side = data.get("S")
    order_type = data.get("o")
    status = data.get("X")
    client_order_id = data.get("c")
    reject_reason = data.get("r", "NONE")
    filled_qty_str = data.get("z", "0")
    filled_quote_qty_str = data.get("Z", "0")
    order_time = data.get("T")

    logger.info(
        f"Execution Report: ID={order_id}, ClientID={client_order_id}, Symbol={symbol}, Side={side}, Type={order_type}, Status={status}"
        + (
            f", FilledQty={filled_qty_str}, FilledQuoteQty={filled_quote_qty_str}"
            if status in ["FILLED", "PARTIALLY_FILLED"]
            else ""
        )
        + (f", Reason={reject_reason}" if status == "REJECTED" else "")
    )

    formatted_data_for_db = _format_execution_report_for_db(data)
    save_success = db.save_order(formatted_data_for_db)
    if save_success:
        broadcast_order_history_update()
    else:
        logger.error(
            f"Failed to save order {order_id} to database. History broadcast skipped."
        )

    state_updates = {}
    current_state = state_manager.get_state()
    current_open_order_id = current_state.get("open_order_id")
    current_status = current_state.get("status")
    is_in_position = current_state.get("in_position")

    if status not in ["NEW", "PARTIALLY_FILLED"] and current_open_order_id == order_id:
        logger.info(
            f"ExecutionReport: Clearing open order ID {order_id} (status: {status})."
        )
        state_updates["open_order_id"] = None
        state_updates["open_order_timestamp"] = None
        if status in ["CANCELED", "REJECTED", "EXPIRED"] and current_status in [
            "ENTERING",
            "EXITING",
        ]:
            state_updates["status"] = "RUNNING"
            if current_status == "EXITING":
                state_updates["in_position"] = True
            if current_status == "ENTERING" and client_order_id:
                state_manager.clear_pending_order_details(client_order_id)

    if status == "FILLED":
        try:
            filled_qty = Decimal(filled_qty_str)
            filled_quote_qty = Decimal(filled_quote_qty_str)

            if filled_qty > 0:
                avg_price = filled_quote_qty / filled_qty

                if (
                    side == "BUY"
                    and current_status == "ENTERING"
                    and not is_in_position
                ):
                    logger.info(
                        f"ExecutionReport (FILLED BUY): Entering position. AvgPrice={avg_price:.4f}, Qty={filled_qty}"
                    )
                    pending_details = (
                        state_manager.get_and_clear_pending_order_details(
                            client_order_id
                        )
                        if isinstance(client_order_id, str)
                        else None
                    )
                    sl_price = (
                        pending_details.get("sl_price") if pending_details else None
                    )
                    tp1_price = (
                        pending_details.get("tp1_price") if pending_details else None
                    )
                    tp2_price = (
                        pending_details.get("tp2_price") if pending_details else None
                    )
                    if sl_price is None and client_order_id:
                        logger.warning(
                            f"ExecutionReport (FILLED BUY): Could not retrieve pending SL/TP for ClientID {client_order_id}."
                        )

                    state_updates["in_position"] = True
                    state_updates["entry_details"] = {
                        "order_id": order_id,
                        "avg_price": avg_price,
                        "quantity": filled_qty,
                        "timestamp": order_time,
                        "side": side,
                        "highest_price": avg_price,
                        "lowest_price": avg_price,
                        "sl_price": sl_price,
                        "tp1_price": tp1_price,
                        "tp2_price": tp2_price,
                    }
                    state_updates["status"] = "RUNNING"
                    state_updates["open_order_id"] = None
                    state_updates["open_order_timestamp"] = None
                    logger.info(
                        f"StateManager updated: In Position, Entry Details: {state_updates['entry_details']}"
                    )

                elif side == "SELL" and current_status == "EXITING" and is_in_position:
                    logger.info(
                        f"ExecutionReport (FILLED SELL): Exiting position. AvgPrice={avg_price:.4f}, Qty={filled_qty}"
                    )
                    state_updates["in_position"] = False
                    state_updates["entry_details"] = None
                    state_updates["status"] = "RUNNING"
                    state_updates["open_order_id"] = None
                    state_updates["open_order_timestamp"] = None

            else:
                logger.warning(
                    f"ExecutionReport (FILLED): Order {order_id} (ClientID: {client_order_id}) has zero filled quantity?"
                )
                if current_status == "ENTERING" and client_order_id:
                    state_manager.clear_pending_order_details(client_order_id)
                if current_status in ["ENTERING", "EXITING"]:
                    state_updates["status"] = "RUNNING"
                    if current_status == "EXITING":
                        state_updates["in_position"] = True

        except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
            logger.error(
                f"ExecutionReport (FILLED): Error processing order {order_id} (ClientID: {client_order_id}): {e}",
                exc_info=True,
            )
            if current_status == "ENTERING" and client_order_id:
                state_manager.clear_pending_order_details(client_order_id)
            state_updates["status"] = "ERROR"

    if state_updates:
        state_manager.update_state(state_updates)


def _handle_account_position(data: dict):
    """Gère les mises à jour de balance (événement outboundAccountPosition)."""
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
                free_balance = Decimal(free_balance_str)
                if asset == quote_asset:
                    if abs(current_quote_balance - free_balance) > Decimal("1e-8"):
                        logger.info(
                            f"Account Position: {asset} balance updated to {free_balance:.4f}"
                        )
                        state_updates["available_balance"] = free_balance
                elif asset == base_asset:
                    if abs(current_base_quantity - free_balance) > Decimal("1e-12"):
                        logger.info(
                            f"Account Position: {asset} quantity updated to {free_balance:.8f}"
                        )
                        state_updates["symbol_quantity"] = free_balance
                        if free_balance <= 0 and state_manager.get_state("in_position"):
                            logger.warning(
                                f"Account Position: Base asset {asset} is now {free_balance}, but state was 'in_position'. Correcting state."
                            )
                            state_updates["in_position"] = False
                            state_updates["entry_details"] = None
                            if state_manager.get_state("status") == "EXITING":
                                state_updates["status"] = "RUNNING"
            except (InvalidOperation, TypeError):
                logger.warning(
                    f"Account Position: Could not convert balance for {asset}: '{free_balance_str}'"
                )

    if state_updates:
        state_manager.update_state(state_updates)


def _handle_balance_update(data: dict):
    """Gère les événements 'balanceUpdate' (moins fiable, informatif)."""
    asset = data.get("a")
    delta = data.get("d")
    clear_time = data.get("T")
    logger.debug(
        f"Balance Update Event: Asset={asset}, Delta={delta}, ClearTime={clear_time}"
    )


# --- Timeout pour Ordres LIMIT ---
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
    elapsed_ms = current_time_ms - order_timestamp

    if elapsed_ms > timeout_ms:
        logger.warning(
            f"LIMIT Order {order_id} exceeded timeout ({elapsed_ms}ms > {timeout_ms}ms). Attempting cancellation..."
        )
        threading.Thread(
            target=cancel_scalping_order, args=(symbol, order_id), daemon=True
        ).start()


# --- Exports ---
__all__ = [
    "process_book_ticker_message",
    "process_depth_message",
    "process_agg_trade_message",
    "process_kline_message",
    "process_user_data_message",
    "execute_entry",
    "execute_exit",
]
