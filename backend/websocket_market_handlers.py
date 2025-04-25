import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, Optional, Tuple
import pandas as pd
import numpy as np

# --- Gestionnaires et Wrapper ---
from manager.state_manager import state_manager
from manager.config_manager import config_manager
import binance_client_wrapper

# --- Utilitaires ---
from utils.websocket_utils import (
    broadcast_ticker_update,
    broadcast_signal_event, # Not used here, but might be useful later
)

# --- Logique Stratégie Spécifique ---
# Import Strategy Classes
from strategies.swing_strategy import SwingStrategy
from strategies.scalping_strategy import ScalpingStrategy
from strategies.scalping_strategy_2 import ScalpingStrategy2

# --- Import des fonctions d'exécution d'ordre ---
from order_execution_handlers import execute_entry, execute_exit, check_limit_order_timeout

logger = logging.getLogger(__name__)

# --- Instantiate Strategies ---
# Instantiate strategy objects - consider loading dynamically based on config in future
swing_strategy_instance = SwingStrategy()
scalping_strategy_instance = ScalpingStrategy()
scalping2_strategy_instance = ScalpingStrategy2()  # Instantiate ScalpingStrategy2

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


# --- Handlers de Messages WebSocket pour les données de marché ---

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
        broadcast_ticker_update(
            msg
        )  # <-- Diffuser la mise à jour du ticker au frontend

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
            # logger.debug(f"Kline {symbol} ({interval}) CLOSED received.") # Commented out - frequent log
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
                # logger.debug(f"Kline WS (SWING): Calculating indicators on {len(df)} klines...") # Commented out
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
                # logger.debug(f"Kline WS (SCALPING2): Calculating indicators on {len(df)} klines...") # Commented out
                # Use the strategy instance
                df_with_indicators = scalping2_strategy_instance.calculate_indicators(
                    df
                )

                if df_with_indicators.empty or len(df_with_indicators) < 2:
                    logger.warning(
                        "Kline WS (SCALPING2): Failed to calculate indicators or not enough data (>=2 rows)."
                    )
                    return

                # Pass latest and previous row to check_entry_signal
                latest_data = df_with_indicators.iloc[-1]
                prev_row = df_with_indicators.iloc[-2]
                is_in_position = current_state.get("in_position")

                if not is_in_position:
                    entry_order_params = scalping2_strategy_instance.check_entry_signal(
                        latest_data, prev_row=prev_row
                    )
                    if entry_order_params:
                        # Extract SL/TP from params for kwargs if present
                        sl_price = entry_order_params.pop("sl_price", None)
                        tp1_price = entry_order_params.pop("tp1_price", None)
                        tp2_price = entry_order_params.pop("tp2_price", None)
                        execute_entry(
                            entry_order_params,
                            sl_price=sl_price,
                            tp1_price=tp1_price,
                            tp2_price=tp2_price,
                        )
                elif is_in_position:
                    # Need current price and position duration for exit check
                    book_ticker = state_manager.get_book_ticker()
                    current_price_str = book_ticker.get(
                        "b"
                    )  # Use bid price for checking exit on LONG
                    entry_details = current_state.get("entry_details", {})
                    entry_timestamp_ms = entry_details.get("timestamp")

                    if current_price_str and entry_timestamp_ms:
                        try:
                            current_price_dec = Decimal(current_price_str)
                            position_duration_seconds = int(time.time()) - int(
                                entry_timestamp_ms / 1000
                            )

                            exit_kwargs = {
                                "current_price": current_price_dec,
                                "position_duration_seconds": position_duration_seconds,
                            }
                            # Pass empty Series for latest_data as it's unused in check_exit_signal for SCALPING2
                            exit_reason = scalping2_strategy_instance.check_exit_signal(
                                pd.Series(dtype=float), entry_details, **exit_kwargs
                            )
                            if exit_reason:
                                execute_exit(f"SCALPING2 Exit: {exit_reason}")
                        except (ValueError, TypeError, InvalidOperation) as e:
                            logger.error(
                                f"SCALPING2 Exit Check: Error preparing data - {e}"
                            )
                    else:
                        logger.warning(
                            "SCALPING2 Exit Check: Missing current price or entry timestamp."
                        )

    except Exception as e:
        logger.critical(
            f"!!! CRITICAL Exception in process_kline_message: {e} !!!", exc_info=True
        )

# --- Exports ---
__all__ = [
    "process_book_ticker_message",
    "process_depth_message",
    "process_agg_trade_message",
    "process_kline_message",
]
