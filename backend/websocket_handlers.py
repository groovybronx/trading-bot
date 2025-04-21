# /Users/davidmichels/Desktop/trading-bot/backend/websocket_handlers.py
import logging
import json
import queue
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional

# --- ADDED: Import broadcast_state_update ---
from websocket_utils import broadcast_state_update
# --- END ADDED ---

# Import the instances of managers
from state_manager import state_manager
from config_manager import config_manager

# Import strategy logic and client wrapper
import strategy
import binance_client_wrapper
# Import bot_core for execute_exit, order management, AND history refresh
import bot_core

logger = logging.getLogger(__name__)

# --- Book Ticker Handler ---
def process_book_ticker_message(msg: Dict[str, Any]):
    """
    Callback for @bookTicker. Updates state and triggers scalping logic & SL/TP.
    """
    try:
        # Validate message structure
        if isinstance(msg, dict) and 's' in msg and 'b' in msg and 'a' in msg:
            logger.debug(f"process_book_ticker_message: Processing valid ticker for {msg.get('s')}")
            symbol = msg['s']
            # Update the latest ticker in the state manager
            state_manager.update_book_ticker(msg)

            # --- Broadcast state update after ticker update ---
            logger.debug(f"process_book_ticker_message: Broadcasting state update after ticker update for {symbol}")
            broadcast_state_update()
            # --- End Broadcast ---

            # Get current data for logic checks
            current_book_ticker = state_manager.get_book_ticker() # Get the data just updated
            current_state = state_manager.get_state()
            current_config = config_manager.get_config()
            configured_symbol = current_state.get("symbol")

            # Ignore messages for symbols other than the configured one
            if configured_symbol and symbol != configured_symbol:
                # logger.debug(f"process_book_ticker: Message for {symbol} ignored (bot configured for {configured_symbol}).")
                return
            elif not configured_symbol:
                logger.warning("process_book_ticker: Symbol not configured in state, logic skipped.")
                return

            # --- 1. Check SL/TP (Priority) ---
            check_sl_tp(current_book_ticker, current_state, current_config)

            # --- 2. Trigger Scalping Logic (if applicable) ---
            strategy_type = current_config.get("STRATEGY_TYPE")
            if strategy_type == 'SCALPING':
                open_order_id = current_state.get("open_order_id")
                is_in_position = current_state.get("in_position")
                entry_details = current_state.get("entry_details")
                open_order_timestamp = current_state.get("open_order_timestamp")

                if open_order_id:
                    # Check if an open LIMIT order should be cancelled due to timeout
                    check_limit_order_timeout(configured_symbol, open_order_id, open_order_timestamp, current_config)
                elif not is_in_position:
                    # Check for entry conditions if not in position and no open order
                    depth_snapshot = state_manager.get_depth_snapshot()
                    available_balance = current_state.get("available_balance", 0.0)
                    symbol_info = binance_client_wrapper.get_symbol_info(configured_symbol)

                    if symbol_info:
                        entry_order_params = strategy.check_scalping_entry(
                            configured_symbol, current_book_ticker, depth_snapshot,
                            current_config, available_balance, symbol_info
                        )
                        if entry_order_params:
                            logger.info("Scalping Entry Signal detected. Launching place_scalping_order...")
                            # Place order in a separate thread to avoid blocking the WS handler
                            threading.Thread(target=bot_core.place_scalping_order, args=(entry_order_params,), daemon=True).start()
                    else:
                         logger.error(f"process_book_ticker: Cannot retrieve symbol_info for {configured_symbol}, skipping scalping entry check.")

                else: # In position
                    # Check for exit conditions if in position
                    if entry_details:
                        depth_snapshot = state_manager.get_depth_snapshot()
                        if strategy.check_scalping_exit(
                            configured_symbol, entry_details, current_book_ticker,
                            depth_snapshot, current_config
                        ):
                             logger.info("Scalping Exit Signal (Strategy) detected. Launching execute_exit...")
                             # Execute exit in a separate thread
                             threading.Thread(target=bot_core.execute_exit, args=("Signal Scalping Strategy",), daemon=True).start()

        elif isinstance(msg, dict) and msg.get('e') == 'error':
            # Handle specific WebSocket errors if needed
            logger.error(f"Received WebSocket BookTicker error message: {msg}")

    except Exception as e:
        # Catch-all for unexpected errors in this handler
        logger.critical(f"!!! CRITICAL Exception in process_book_ticker_message: {e} !!!", exc_info=True)

# --- SL/TP Check ---
def check_sl_tp(
    book_ticker_data: Dict[str, Any],
    current_state: Dict[str, Any],
    current_config: Dict[str, Any]
):
    """Checks Stop-Loss and Take-Profit using book ticker data."""
    # Only check if in position and entry details are available
    if not current_state.get("in_position") or not current_state.get("entry_details"):
        return

    entry_details = current_state["entry_details"]
    symbol = current_state.get("symbol")
    # Get SL/TP percentages from config
    sl_percent_config = current_config.get("STOP_LOSS_PERCENTAGE")
    tp_percent_config = current_config.get("TAKE_PROFIT_PERCENTAGE")

    # Skip if neither SL nor TP is configured
    if sl_percent_config is None and tp_percent_config is None:
        return

    try:
        # Use best bid price for checking sell conditions (SL/TP)
        current_price_str = book_ticker_data.get('b')
        if not current_price_str:
            logger.warning("check_sl_tp: Missing 'b' (best bid) in book ticker data.")
            return
        current_price_decimal = Decimal(current_price_str)
        if current_price_decimal <= 0:
            logger.warning(f"check_sl_tp: Invalid current price {current_price_decimal}.")
            return

        # Get entry price from state
        entry_price_str = entry_details.get("avg_price")
        if entry_price_str is None:
            logger.error("check_sl_tp: Missing 'avg_price' in entry_details.")
            return
        entry_price_decimal = Decimal(str(entry_price_str)) # Ensure it's Decimal
        if entry_price_decimal <= 0:
            logger.error(f"check_sl_tp: Invalid entry price {entry_price_decimal}.")
            return

        # --- Stop Loss Check ---
        if sl_percent_config is not None:
            try:
                sl_percent = Decimal(str(sl_percent_config)) # Ensure Decimal
                if sl_percent > 0:
                    stop_loss_level = entry_price_decimal * (Decimal(1) - sl_percent)
                    if current_price_decimal <= stop_loss_level:
                        logger.info(f"!!! STOP-LOSS TRIGGERED ({current_price_decimal:.4f} <= {stop_loss_level:.4f}) for {symbol} !!!")
                        # Execute exit in a separate thread
                        threading.Thread(target=bot_core.execute_exit, args=("Stop-Loss",), daemon=True).start()
                        return # Exit function after triggering SL
            except (InvalidOperation, ValueError, TypeError) as e:
                 logger.error(f"check_sl_tp: Error calculating Stop Loss (SL %: {sl_percent_config}): {e}")

        # --- Take Profit Check (only if SL was not triggered) ---
        if tp_percent_config is not None:
            try:
                tp_percent = Decimal(str(tp_percent_config)) # Ensure Decimal
                if tp_percent > 0:
                    take_profit_level = entry_price_decimal * (Decimal(1) + tp_percent)
                    # Use best bid price for TP check as well (price we can sell at)
                    if current_price_decimal >= take_profit_level:
                        logger.info(f"!!! TAKE-PROFIT TRIGGERED ({current_price_decimal:.4f} >= {take_profit_level:.4f}) for {symbol} !!!")
                        # Execute exit in a separate thread
                        threading.Thread(target=bot_core.execute_exit, args=("Take-Profit",), daemon=True).start()
                        return # Exit function after triggering TP
            except (InvalidOperation, ValueError, TypeError) as e:
                 logger.error(f"check_sl_tp: Error calculating Take Profit (TP %: {tp_percent_config}): {e}")

    except (InvalidOperation, TypeError, KeyError) as e:
        # Catch errors related to Decimal conversion or missing keys
        logger.error(f"check_sl_tp: Internal error processing prices: {e}", exc_info=True)
    except Exception as e:
         # Catch any other unexpected errors
         logger.critical(f"!!! CRITICAL Exception in check_sl_tp: {e} !!!", exc_info=True)

# --- Depth Handler ---
def process_depth_message(msg: Dict[str, Any]):
    """Callback for @depth. Updates depth snapshot via StateManager."""
    try:
        # Validate message structure
        if isinstance(msg, dict) and msg.get('e') == 'depthUpdate' and 's' in msg:
            state_manager.update_depth_snapshot(msg)
            # No broadcast here, ticker broadcast is sufficient and less frequent
        elif isinstance(msg, dict) and msg.get('e') == 'error':
            logger.error(f"Received WebSocket Depth error message: {msg}")
    except Exception as e:
        logger.critical(f"!!! CRITICAL Exception in process_depth_message: {e} !!!", exc_info=True)

# --- AggTrade Handler ---
def process_agg_trade_message(msg: Dict[str, Any]):
    """Callback for @aggTrade. Stores recent trades via StateManager."""
    try:
        # Validate message structure
        if isinstance(msg, dict) and msg.get('e') == 'aggTrade' and 's' in msg:
            state_manager.append_agg_trade(msg)
            # No broadcast here
        elif isinstance(msg, dict) and msg.get('e') == 'error':
            logger.error(f"Received WebSocket AggTrade error message: {msg}")
    except Exception as e:
        logger.critical(f"!!! CRITICAL Exception in process_agg_trade_message: {e} !!!", exc_info=True)

# --- Kline Handler ---
def process_kline_message(msg: Dict[str, Any]):
    """Callback for @kline. Updates history and triggers SWING logic."""
    try:
        # Validate message structure
        if isinstance(msg, dict) and msg.get('e') == 'kline' and 'k' in msg:
            kline_data = msg['k']
            symbol = kline_data.get('s')
            is_closed = kline_data.get('x', False) # Check if kline is closed

            if is_closed:
                logger.debug(f"Kline {symbol} ({kline_data.get('i')}) CLOSED received.")
                # Format kline data into the list structure expected by TA libraries/strategy
                formatted_kline = [
                    kline_data.get('t'), kline_data.get('o'), kline_data.get('h'),
                    kline_data.get('l'), kline_data.get('c'), kline_data.get('v'),
                    kline_data.get('T'), kline_data.get('q'), kline_data.get('n'),
                    kline_data.get('V'), kline_data.get('Q'), kline_data.get('B')
                ]
                # Append the closed kline to the history deque
                state_manager.append_kline(formatted_kline)

                # Get current state and config for strategy check
                current_state = state_manager.get_state()
                current_config = config_manager.get_config()
                strategy_type = current_config.get("STRATEGY_TYPE")
                configured_symbol = current_state.get("symbol")

                # Trigger SWING strategy logic only if configured and symbol matches
                if strategy_type == 'SWING' and configured_symbol and symbol == configured_symbol:
                    kline_history = state_manager.get_kline_history()
                    required_len = state_manager.get_required_klines()
                    current_len = len(kline_history)

                    # Ensure enough history is available for calculations
                    if current_len < required_len:
                        logger.info(f"Kline WS (SWING): History ({current_len}/{required_len}) insufficient for analysis.")
                        return

                    logger.debug(f"Kline WS (SWING): Calculating strategy indicators/signals on {current_len} klines...")
                    # Calculate indicators and signals using the strategy module
                    signals_df = strategy.calculate_indicators_and_signals(kline_history, current_config)

                    if signals_df is None or signals_df.empty:
                        logger.warning("Kline WS (SWING): Failed to calculate indicators/signals.")
                        return

                    # Get the latest signal data
                    current_data = signals_df.iloc[-1]
                    is_in_position = current_state.get("in_position")

                    if not is_in_position:
                        # Check entry conditions if not currently in a position
                        logger.debug("Kline WS (SWING): Checking entry conditions...")
                        available_balance = current_state.get("available_balance", 0.0)
                        symbol_info = binance_client_wrapper.get_symbol_info(configured_symbol)
                        if symbol_info:
                            entry_order_params = strategy.check_entry_conditions(
                                current_data, configured_symbol, current_config,
                                available_balance, symbol_info
                            )
                            if entry_order_params:
                                logger.info("Kline WS (SWING): Entry signal detected. Triggering order placement...")
                                # TODO: Implement actual order placement, likely via bot_core or API call
                                logger.warning("Kline WS (SWING): Order placement not implemented here. Signal logged.")
                        else:
                            logger.error(f"Kline WS (SWING): Cannot retrieve symbol_info for {configured_symbol}.")

                    elif is_in_position:
                        # Check exit conditions based on indicators if in a position
                        logger.debug("Kline WS (SWING): Checking indicator-based exit conditions...")
                        if strategy.check_exit_conditions(current_data, configured_symbol):
                            logger.info("Kline WS (SWING): Indicator exit signal detected. Launching execute_exit...")
                            # Execute exit in a separate thread
                            threading.Thread(target=bot_core.execute_exit, args=("Signal Indicateur (Kline WS)",), daemon=True).start()

        elif isinstance(msg, dict) and msg.get('e') == 'error':
            logger.error(f"Received KLINE WebSocket error message: {msg}")

    except Exception as e:
        logger.critical(f"!!! CRITICAL Exception in process_kline_message: {e} !!!", exc_info=True)

# --- User Data Handler ---
def process_user_data_message(data: Dict[str, Any]):
    """Processes messages from the User Data Stream (orders, positions)."""
    event_type = data.get('e')
    logger.info(f"--- User Data Message Received --- Type: {event_type}")

    try:
        if event_type == 'executionReport':
            _handle_execution_report(data)
        elif event_type == 'outboundAccountPosition':
            _handle_account_position(data)
        elif event_type == 'balanceUpdate':
             _handle_balance_update(data)
        else:
            logger.debug(f"User Data: Unhandled event type '{event_type}': {data}")
    except Exception as e:
        logger.error(f"Error processing User Data message (Type: {event_type}): {e} - Data: {data}", exc_info=True)


def _handle_execution_report(data: dict):
    """Handles order execution updates."""
    order_id = data.get('i') # Order ID
    symbol = data.get('s') # Symbol
    side = data.get('S') # Side (BUY/SELL)
    order_type = data.get('o') # Order Type (LIMIT, MARKET, etc.)
    status = data.get('X') # Execution Status (NEW, FILLED, CANCELED, etc.)

    logger.info(f"Execution Report: OrderID={order_id}, Status={status}, Side={side}, Type={order_type}")

    # --- *** MODIFIED: Trigger history refresh via REST in background *** ---
    if symbol:
        logger.debug(f"ExecutionReport: Triggering history refresh for {symbol} via REST...")
        # Run the refresh in a background thread
        threading.Thread(target=bot_core.refresh_order_history_via_rest, args=(symbol, 50), daemon=True).start()
    else:
        logger.warning("ExecutionReport: Cannot trigger history refresh, symbol missing in data.")
    # --- *** END MODIFIED *** ---

    # --- Update Core Bot State Based on Order Status ---
    # This logic is still useful for updating the 'in_position' status based on WS confirmation
    # It acts as a fallback/confirmation if the REST update was missed or state diverged.
    state_updates = {}
    current_state = state_manager.get_state() # Get current state for checks

    # Clear open order ID if this report confirms it's no longer NEW/PARTIALLY_FILLED
    if status not in ['NEW', 'PARTIALLY_FILLED'] and current_state.get("open_order_id") == order_id:
        logger.debug(f"ExecutionReport: Clearing open order ID {order_id} due to status {status}.")
        state_updates["open_order_id"] = None
        state_updates["open_order_timestamp"] = None

    # Update position state ONLY if the order is FILLED
    if status == 'FILLED':
        if side == 'BUY' and not current_state.get("in_position"):
            # Enter position based on WS confirmation (redundant if REST worked, but safe)
            try:
                exec_qty = float(data.get('z', 0)) # Cumulative filled quantity
                quote_qty = float(data.get('Z', 0)) # Cumulative quote asset transacted amount
                if exec_qty > 0:
                    avg_price = quote_qty / exec_qty
                    entry_timestamp = data.get('T', int(time.time() * 1000)) # Transaction time
                    logger.info(f"ExecutionReport: Entering position via WS confirmation for order {order_id}.")
                    logger.info(f"Calculated Entry: Qty={exec_qty}, QuoteQty={quote_qty}, AvgPrice={avg_price}")
                    state_updates["in_position"] = True
                    state_updates["entry_details"] = {
                        "order_id": order_id, "avg_price": avg_price,
                        "quantity": exec_qty, "timestamp": entry_timestamp,
                    }
                    # Save persistent state for entry (redundant if REST worked, but safe)
                    state_manager.save_persistent_data()
                else:
                     logger.warning(f"ExecutionReport: BUY order {order_id} FILLED but executed quantity is zero?")
            except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
                 logger.error(f"ExecutionReport: Error processing FILLED BUY order {order_id}: {e}", exc_info=True)

        elif side == 'SELL' and current_state.get("in_position"):
            # Exit position based on WS confirmation
            logger.info(f"ExecutionReport: Exiting position via WS confirmation for order {order_id}.")
            state_updates["in_position"] = False
            state_updates["entry_details"] = None
            # Save persistent state for exit (redundant if REST worked, but safe)
            state_manager.save_persistent_data()

    # Apply state updates if any were determined
    if state_updates:
        state_manager.update_state(state_updates)
        broadcast_state_update() # Broadcast the state change (position, open order ID)


def _handle_account_position(data: dict):
    """Handles account position updates (balance changes)."""
    balances = data.get('B', []) # List of balances that changed
    state_updates = {}
    quote_asset = state_manager.get_state("quote_asset")
    base_asset = state_manager.get_state("base_asset")

    for balance_info in balances:
        asset = balance_info.get('a') # Asset symbol
        free_balance_str = balance_info.get('f') # Free balance

        if asset and free_balance_str is not None:
            try:
                free_balance = float(free_balance_str)
                # Update quote asset balance if changed
                if asset == quote_asset:
                    if abs(state_manager.get_state("available_balance") - free_balance) > 1e-9: # Float comparison
                        logger.info(f"Account Position: {asset} balance updated to {free_balance:.4f}")
                        state_updates["available_balance"] = free_balance
                # Update base asset quantity if changed
                elif asset == base_asset:
                     if abs(state_manager.get_state("symbol_quantity") - free_balance) > 1e-9: # Float comparison
                        logger.info(f"Account Position: {asset} quantity updated to {free_balance:.8f}")
                        state_updates["symbol_quantity"] = free_balance
            except (ValueError, TypeError):
                logger.warning(f"Account Position: Could not convert balance for {asset}: '{free_balance_str}'")

    # Apply and broadcast if any balances were updated
    if state_updates:
        state_manager.update_state(state_updates)
        broadcast_state_update()


def _handle_balance_update(data: dict):
    """Handles specific balance updates (deposits, withdrawals)."""
    asset = data.get('a')
    delta = data.get('d') # Change in balance
    clear_time = data.get('T') # Event time
    logger.info(f"Balance Update Event: Asset={asset}, Delta={delta}, ClearTime={clear_time}")
    # This event is less critical for trading logic but good to log.
    # Optionally, trigger a full balance refresh if needed, but might be overkill.


# --- Limit Order Timeout Check ---
def check_limit_order_timeout(
    symbol: str,
    order_id: int,
    order_timestamp: Optional[int],
    current_config: Dict[str, Any]
):
    """Checks if an open LIMIT order has exceeded its timeout."""
    if not order_id or not order_timestamp:
        return # No open order or timestamp to check

    timeout_ms = current_config.get("SCALPING_LIMIT_ORDER_TIMEOUT_MS", 5000) # Get timeout from config
    current_time_ms = int(time.time() * 1000)

    # Check if the elapsed time exceeds the timeout
    if current_time_ms - order_timestamp > timeout_ms:
        logger.warning(f"LIMIT Order {order_id} exceeded timeout ({timeout_ms}ms). Attempting cancellation...")
        # Cancel the order in a separate thread
        threading.Thread(target=bot_core.cancel_scalping_order, args=(symbol, order_id), daemon=True).start()

# --- Exports ---
__all__ = [
    'process_book_ticker_message', 'process_depth_message', 'process_agg_trade_message',
    'process_kline_message', 'process_user_data_message'
]
