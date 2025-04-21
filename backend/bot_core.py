 # /Users/davidmichels/Desktop/trading-bot/backend/bot_core.py
import logging
import os
import threading
import time
import collections
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any, Tuple, List # Added List
import dotenv
import json

dotenv.load_dotenv()

from binance.websocket.spot.websocket_stream import SpotWebsocketStreamClient
from binance.error import ClientError, ServerError

# --- Imports ---
from state_manager import state_manager
from config_manager import config_manager, SYMBOL
import binance_client_wrapper # Ensure it's imported
import strategy # Assuming strategy.py contains format_quantity etc.
import websocket_handlers
from websocket_utils import broadcast_state_update

logger = logging.getLogger(__name__)

# Keepalive interval in seconds (e.g., 30 minutes)
KEEPALIVE_INTERVAL_SECONDS = 30 * 60

# --- Helper Functions for Exit Logic ---

def _calculate_exit_quantity(
    reason: str,
) -> Optional[Tuple[float, str, Dict[str, Any]]]:
    """Checks if in position and returns the formatted quantity to sell."""
    current_state = state_manager.get_state()
    if not current_state.get("in_position"):
        logger.debug(f"execute_exit ({reason}): Ignored because not in position.")
        return None

    logger.info(f"execute_exit: Triggering exit for reason: {reason}")
    entry_details = current_state.get("entry_details")
    symbol_to_exit = current_state.get("symbol", SYMBOL) # Use current symbol from state

    # Prioritize quantity from entry_details if available
    qty_to_sell_raw = (
        entry_details.get("quantity")
        if entry_details and entry_details.get("quantity") is not None
        else current_state.get("symbol_quantity", 0.0)
    )

    try:
        qty_to_sell_float = float(qty_to_sell_raw)
        if qty_to_sell_float <= 0:
            logger.error(
                f"execute_exit: Invalid quantity to sell ({qty_to_sell_raw}). Exit cancelled."
            )
            return None
    except (ValueError, TypeError):
        logger.error(
            f"execute_exit: Non-numeric quantity to sell ({qty_to_sell_raw}). Exit cancelled."
        )
        return None

    symbol_info = binance_client_wrapper.get_symbol_info(symbol_to_exit)
    if not symbol_info:
        logger.error(
            f"execute_exit: Cannot retrieve symbol_info for {symbol_to_exit}. Exit cancelled."
        )
        return None

    # Use strategy module to format quantity according to symbol rules
    formatted_qty_to_sell = strategy.format_quantity(qty_to_sell_float, symbol_info)
    if formatted_qty_to_sell <= 0:
        logger.error(
            f"execute_exit: Invalid formatted quantity ({formatted_qty_to_sell} from {qty_to_sell_float}). Exit cancelled."
        )
        return None

    entry_details_copy = entry_details.copy() if entry_details else {}
    return formatted_qty_to_sell, symbol_to_exit, entry_details_copy


def _place_exit_order(
    symbol: str, quantity: float, config: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Places the exit order (LIMIT or MARKET) based on config."""
    # Determine exit order type based on strategy type in config
    strategy_type = config.get("STRATEGY_TYPE")
    exit_order_type = "MARKET" # Default to MARKET
    if strategy_type == "SCALPING":
        exit_order_type = config.get("SCALPING_ORDER_TYPE", "MARKET")

    order_details = None

    try:
        if exit_order_type == "LIMIT":
            # For LIMIT sell, try to place at the current best bid
            current_book_ticker = state_manager.get_book_ticker()
            best_bid_price = current_book_ticker.get("b")
            if best_bid_price:
                limit_price_str = str(best_bid_price)
                tif = config.get("SCALPING_LIMIT_TIF", "GTC")
                logger.info(
                    f"execute_exit: Attempting LIMIT sell of {quantity} {symbol} at price {limit_price_str} (TIF: {tif})..."
                )
                order_details = binance_client_wrapper.place_order(
                    symbol=symbol, side="SELL", quantity=quantity,
                    order_type="LIMIT", price=limit_price_str,
                    time_in_force=tif,
                )
            else:
                logger.warning("execute_exit: Cannot get best_bid for LIMIT sell. Falling back to MARKET.")
                exit_order_type = "MARKET" # Fallback

        # Place MARKET order if required or if LIMIT failed
        if exit_order_type == "MARKET":
            logger.info(f"execute_exit: Attempting MARKET sell of {quantity} {symbol}...")
            order_details = binance_client_wrapper.place_order(
                symbol=symbol, side="SELL", quantity=quantity, order_type="MARKET"
            )
        return order_details
    except Exception as e:
        logger.error(f"execute_exit: Error placing {exit_order_type} exit order: {e}", exc_info=True)
        return None


def _handle_exit_order_result(
    order_details: Optional[Dict[str, Any]],
    entry_details_before_exit: Optional[Dict[str, Any]], # Keep for potential future PnL calc here
):
    """Handles the result of the exit order and updates state if filled."""
    if not order_details:
        logger.error("execute_exit: Failed to place SELL order (order_details is None). State unchanged.")
        return

    order_id = order_details.get("orderId", "N/A")
    status = order_details.get("status")
    should_save = False
    state_updates = {}

    logger.info(f"execute_exit: Result for SELL order {order_id}: Status={status}")

    # --- REMOVED REDUNDANT CALL ---
    # History update is now triggered by refresh_order_history_via_rest
    # state_manager.add_order_to_history(order_details)
    # --- END REMOVED ---

    # Update core state only if the order is confirmed filled (fully or partially)
    if status in ["FILLED", "PARTIALLY_FILLED"]:
        # Assuming partial fill also means we are effectively out for this simple model
        logger.info(f"execute_exit: SELL order {order_id} confirmed {status}. Updating state: Exiting position.")
        state_updates["in_position"] = False
        state_updates["entry_details"] = None
        should_save = True # Save state change
    elif status == "NEW":
        logger.warning(f"execute_exit: SELL LIMIT order {order_id} opened. Waiting for fill/cancel via WebSocket.")
        # Store open order ID if needed for timeout logic (already handled in place_scalping_order if applicable)
    elif status in ["CANCELED", "REJECTED", "EXPIRED", "UNKNOWN_OR_ALREADY_COMPLETED"]:
        logger.warning(f"execute_exit: SELL order {order_id} failed/expired/cancelled (Status={status}). State 'in_position' remains True.")
    else:
        logger.error(f"execute_exit: SELL order {order_id} has unexpected status: {status}. State not modified.")

    # Apply state updates if any
    if state_updates:
        state_manager.update_state(state_updates)
        broadcast_state_update() # Broadcast the change

    # Save persistent data if position state changed
    if should_save:
        if not state_manager.save_persistent_data():
            logger.error("execute_exit: Failed to save state after exiting position!")


def execute_exit(reason: str) -> Optional[Dict[str, Any]]:
    """Main function to execute an exit from the current position."""
    exit_info = _calculate_exit_quantity(reason)
    if not exit_info:
        return None # Not in position or invalid quantity

    quantity_to_sell, symbol, entry_details_copy = exit_info
    current_config = config_manager.get_config()

    # Place the order
    order_details = _place_exit_order(symbol, quantity_to_sell, current_config)

    # Handle the result (updates state, broadcasts, saves)
    _handle_exit_order_result(order_details, entry_details_copy)

    # Trigger history refresh after handling the immediate result
    if order_details and order_details.get('symbol'):
        logger.debug(f"execute_exit: Triggering history refresh for {order_details['symbol']} via REST...")
        threading.Thread(target=refresh_order_history_via_rest, args=(order_details['symbol'], 50), daemon=True).start()

    return order_details # Return the raw order details from the API call


# --- Functions for Strategy Orders (Entry/Cancel) ---

def place_scalping_order(order_params: Dict[str, Any]):
    """Places a scalping entry order and handles initial state updates."""
    symbol = order_params.get("symbol")
    side = order_params.get("side")
    order_type = order_params.get("order_type")
    quantity = order_params.get("quantity") # Can be base or quote depending on type/side

    if not all([symbol, side, order_type, quantity]):
        logger.error(f"place_scalping_order: Incomplete parameters: {order_params}")
        return

    logger.info(f"Placing Scalping Order: {side} {order_type} {quantity} {symbol}...")
    order_details = binance_client_wrapper.place_order(**order_params)

    if order_details:
        order_id = order_details.get("orderId")
        status = order_details.get("status")
        logger.info(f"Scalping Order {order_id} placed. Initial API Status: {status}")

        # --- REMOVED REDUNDANT CALL ---
        # History update is now triggered by refresh_order_history_via_rest
        # state_manager.add_order_to_history(order_details)
        # --- END REMOVED ---

        # Trigger history refresh after placing the order
        if symbol:
            logger.debug(f"place_scalping_order: Triggering history refresh for {symbol} via REST...")
            threading.Thread(target=refresh_order_history_via_rest, args=(symbol, 50), daemon=True).start()

        if order_type == "LIMIT" and status == "NEW" and order_id:
            # Store open LIMIT order ID for potential timeout cancellation
            state_manager.update_state({
                "open_order_id": order_id,
                "open_order_timestamp": order_details.get("transactTime", int(time.time() * 1000)),
            })
            broadcast_state_update()
            logger.info(f"Scalping LIMIT order {order_id} opened. Waiting for fill/cancel.")

        elif order_type == "MARKET" and status == "FILLED":
            logger.info(f"Scalping MARKET order {order_id} filled according to API response.")
            try:
                exec_qty = float(order_details.get("executedQty", 0))
                quote_qty = float(order_details.get("cummulativeQuoteQty", 0))
                if exec_qty > 0:
                    avg_price = quote_qty / exec_qty
                    entry_timestamp = order_details.get("transactTime", int(time.time() * 1000))
                    if side == "BUY":
                        state_updates = {
                            "in_position": True,
                            "entry_details": {
                                "order_id": order_id, "avg_price": avg_price,
                                "quantity": exec_qty, "timestamp": entry_timestamp,
                            },
                            "open_order_id": None, # Clear any previous open order
                            "open_order_timestamp": None,
                        }
                        state_manager.update_state(state_updates)
                        state_manager.save_persistent_data() # Save entry state
                        broadcast_state_update()
                        logger.info(f"Scalping MARKET: Entered position @ {avg_price:.4f}, Qty={exec_qty} (via direct call)")
                else:
                    logger.warning("Scalping MARKET: API reported FILLED but executed quantity is zero?")
            except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
                 logger.error(f"Scalping MARKET: Error processing filled order {order_id}: {e}", exc_info=True)

        elif status == "REJECTED":
            logger.error(f"Scalping Order {order_id} REJECTED by API. Reason: {order_details.get('rejectReason', 'N/A')}")
        else:
            logger.warning(f"Scalping Order {order_id} has unexpected initial status: {status}")
    else:
        logger.error(f"Failed to place scalping order (API returned None): {order_params}")


def cancel_scalping_order(symbol: str, order_id: int):
    """Cancels an open scalping LIMIT order."""
    logger.info(f"Attempting to cancel Scalping Order: {order_id} on {symbol}...")
    result = binance_client_wrapper.cancel_order(symbol=symbol, orderId=order_id)

    if result:
        status = result.get("status")
        logger.info(f"API Cancel Result for order {order_id}: Status={status}")

        # --- REMOVED REDUNDANT CALL ---
        # History update is now triggered by refresh_order_history_via_rest
        # state_manager.add_order_to_history(result)
        # --- END REMOVED ---

        # Trigger history refresh after attempting cancellation
        logger.debug(f"cancel_scalping_order: Triggering history refresh for {symbol} via REST...")
        threading.Thread(target=refresh_order_history_via_rest, args=(symbol, 50), daemon=True).start()

        # Clear open order state if cancellation confirmed or order already done
        if status in ["CANCELED", "UNKNOWN_OR_ALREADY_COMPLETED"]:
            current_open_order = state_manager.get_state("open_order_id")
            if current_open_order == order_id:
                state_manager.update_state({"open_order_id": None, "open_order_timestamp": None})
                broadcast_state_update()
    else:
        logger.error(f"Failed API request to cancel order {order_id}.")

# --- Main Bot Thread ---

def run_bot():
    """Main bot thread executing the trading strategy."""
    try:
        current_state = state_manager.get_state()
        strategy_type = config_manager.get_value("STRATEGY_TYPE")
        symbol = current_state.get("symbol")
        tf = current_state.get("timeframe") # Used by SWING
        logger.info(f"Run Bot Thread: Started ({strategy_type}) for {symbol}" + (f" on {tf}" if strategy_type == "SWING" else ""))

        while True:
            if state_manager.get_state("stop_main_requested"):
                logger.info("Run Bot Thread: Stop requested.")
                break

            # --- STRATEGY LOGIC GOES HERE ---
            # Example placeholder:
            # current_config = config_manager.get_config()
            # if strategy_type == "SCALPING":
            #     # Get latest depth, trades, ticker from state_manager
            #     depth = state_manager.get_depth_snapshot()
            #     trades = state_manager.get_agg_trades()
            #     ticker = state_manager.get_book_ticker()
            #     # Call strategy.scalping_logic(depth, trades, ticker, current_config)
            #     # Which might call place_scalping_order or execute_exit
            #     pass
            # elif strategy_type == "SWING":
            #     # Get kline history from state_manager
            #     klines = state_manager.get_kline_history()
            #     # Call strategy.swing_logic(klines, current_config)
            #     # Which might call place_order or execute_exit
            #     pass

            # Avoid busy-waiting
            time.sleep(1) # Adjust sleep time as needed for strategy frequency

    except Exception as e:
        logger.critical("Run Bot Thread: Major error!", exc_info=True)
        state_manager.update_state({"status": "ERROR", "stop_main_requested": True})
        broadcast_state_update() # Notify UI of error state
    finally:
        logger.info("Run Bot Thread: Execution finished.")
        # Ensure state reflects stopped status if not already stopping/error
        current_status = state_manager.get_state("status")
        if current_status not in ["STOPPING", "STOPPED", "ERROR"]:
            state_manager.update_state({"status": "STOPPED"})
            broadcast_state_update()
        # Clean up thread reference in state
        current_thread_ref = state_manager.get_state("main_thread")
        if current_thread_ref == threading.current_thread():
            state_manager.update_state({"main_thread": None})


# --- Keepalive Thread ---

def run_keepalive():
    """Thread to send HTTP keepalive requests for the listenKey."""
    logger.info("Keepalive Thread: Started.")
    while True:
        # Check for stop signal early
        if state_manager.get_state("stop_keepalive_requested"):
            break

        listen_key = state_manager.get_state("listen_key")
        if listen_key:
            logger.debug(f"Keepalive Thread: Sending HTTP keepalive for {listen_key[:5]}...")
            success = binance_client_wrapper.renew_listen_key(listen_key)
            if success:
                logger.info(f"Keepalive Thread: HTTP keepalive successful for {listen_key[:5]}.")
            else:
                # If renewal fails (e.g., key expired), stop trying and clear key
                logger.error(f"Keepalive Thread: Failed HTTP keepalive for {listen_key[:5]}. Stopping keepalive thread.")
                state_manager.update_state({"listen_key": None}) # Clear invalid key
                # Consider notifying main thread or attempting to restart WS if critical
                break # Exit the keepalive loop
        else:
            # If no listen key, wait longer before checking again
            logger.warning("Keepalive Thread: No listen_key found in state. Waiting 60s.")
            wait_time = 60
            # Still check for stop signal during the longer wait
            for _ in range(wait_time):
                 if state_manager.get_state("stop_keepalive_requested"): break
                 time.sleep(1)
            if state_manager.get_state("stop_keepalive_requested"): break
            continue # Go back to start of loop to check for key again

        # Wait for the KEEPALIVE_INTERVAL_SECONDS, checking for stop signal periodically
        wait_interval = KEEPALIVE_INTERVAL_SECONDS
        for _ in range(wait_interval):
            if state_manager.get_state("stop_keepalive_requested"): break
            time.sleep(1)
        # Check stop signal one last time before next iteration
        if state_manager.get_state("stop_keepalive_requested"): break


    logger.info("Keepalive Thread: Stop requested or error occurred. Finishing.")
    # Clean up thread reference in state
    current_thread_ref = state_manager.get_state("keepalive_thread")
    if current_thread_ref == threading.current_thread():
         state_manager.update_state({"keepalive_thread": None})

# --- ADDED: Function to Refresh History via REST ---
def refresh_order_history_via_rest(symbol: Optional[str] = None, limit: int = 50):
    """Fetches recent order history via REST API and updates StateManager."""
    if not symbol:
        symbol = state_manager.get_state("symbol") # Get current symbol if not provided
    if not symbol:
        logger.error("refresh_order_history_via_rest: Cannot refresh, symbol not available.")
        return

    logger.info(f"Refreshing order history for {symbol} via REST API (limit={limit})...")
    try:
        # Call the new wrapper function
        all_orders_data = binance_client_wrapper.get_all_orders(symbol=symbol, limit=limit)

        if all_orders_data is None: # Wrapper handles errors and returns None on failure
            logger.error("Failed to fetch order history via REST.")
            return

        # Call StateManager to replace the internal history and broadcast
        state_manager.replace_order_history(all_orders_data)
        logger.info(f"Order history for {symbol} refreshed successfully via REST.")

    except Exception as e:
        logger.error(f"Error during REST order history refresh: {e}", exc_info=True)

# --- Control Functions (Start/Stop Orchestration) ---

def _initialize_client_and_config() -> bool:
    """Initializes the Binance client and loads config."""
    logger.info("Start Core: Initializing Binance Client...")
    if binance_client_wrapper.get_client() is None:
        # get_client() logs the critical error
        state_manager.update_state({"status": "ERROR"})
        broadcast_state_update()
        return False
    logger.info("Start Core: Binance Client initialized.")
    logger.info("Start Core: Configuration loaded.") # Assumed loaded by config_manager
    return True


def _load_and_prepare_state() -> bool:
    """Loads persistent data and retrieves initial symbol info/balances."""
    logger.info("Start Core: Loading previous state...")
    # StateManager loads automatically during init, just log confirmation
    current_state = state_manager.get_state()
    logger.info(
        f"Start Core: State restored/initialized (in_position={current_state.get('in_position')}, history={len(current_state.get('order_history', []))} orders)."
    )

    logger.info("Start Core: Retrieving symbol info and balances...")
    current_symbol = config_manager.get_value("SYMBOL", SYMBOL)
    symbol_info = binance_client_wrapper.get_symbol_info(current_symbol)
    if not symbol_info:
        msg = f"Cannot retrieve info for symbol {current_symbol}."
        logger.error(f"Start Core: {msg}")
        state_manager.update_state({"status": "ERROR"})
        broadcast_state_update()
        return False

    base_asset = symbol_info.get("baseAsset")
    quote_asset = symbol_info.get("quoteAsset")
    if not base_asset or not quote_asset:
        msg = f"Base/Quote asset not found for {current_symbol} in symbol info."
        logger.error(f"Start Core: {msg}")
        state_manager.update_state({"status": "ERROR"})
        broadcast_state_update()
        return False

    # Get initial balances
    initial_quote = binance_client_wrapper.get_account_balance(asset=quote_asset)
    initial_base = binance_client_wrapper.get_account_balance(asset=base_asset)

    # Prepare state updates based on fetched data
    state_updates = {
        "symbol": current_symbol,
        "base_asset": base_asset,
        "quote_asset": quote_asset,
        "available_balance": 0.0, # Default
        "symbol_quantity": 0.0,   # Default
    }

    if initial_quote is not None:
        state_updates["available_balance"] = initial_quote
    else:
        logger.warning(
            f"Start Core: Could not read {quote_asset} balance. Using 0.0"
        )

    # Determine initial base quantity, handling potential None from API
    if initial_base is not None:
        state_updates["symbol_quantity"] = initial_base
    else:
        logger.warning(
            f"Start Core: Could not read {base_asset} balance. Using 0.0"
        )
        # If we couldn't read base balance but state says we are in position, it's an inconsistency
        if current_state.get("in_position"):
             logger.error("Start Core: CRITICAL INCONSISTENCY - In position but cannot read base asset balance!")
             # Decide how to handle: force out of position? Halt?
             state_updates["in_position"] = False # Safer default?
             state_updates["entry_details"] = None

    # --- Refined Consistency Check ---
    # Use the potentially updated values
    current_in_position = current_state.get("in_position", False)
    current_entry_details = current_state.get("entry_details")
    calculated_base_qty = state_updates.get("symbol_quantity", 0.0)

    final_in_position = current_in_position # Start with loaded state
    final_entry_details = current_entry_details

    if current_in_position and calculated_base_qty <= 0:
        logger.warning(
            "Start Core: Consistency Check - 'in_position'=True but base quantity <= 0. Forcing 'in_position'=False."
        )
        final_in_position = False
        final_entry_details = None
    elif not current_in_position and calculated_base_qty > 0:
        # This might happen if bot stopped mid-trade or after manual trade
        logger.warning(
            f"Start Core: Consistency Check - 'in_position'=False but base quantity {base_asset} ({calculated_base_qty}) > 0. Keeping 'in_position'=False as per saved state."
        )
        final_in_position = False # Trust saved state over balance unless logic dictates otherwise
        final_entry_details = None
    elif current_in_position and not current_entry_details:
         logger.warning(
            "Start Core: Consistency Check - 'in_position'=True but no entry_details found. Forcing 'in_position'=False."
        )
         final_in_position = False
         final_entry_details = None

    state_updates["in_position"] = final_in_position
    state_updates["entry_details"] = final_entry_details
    # --- End Refined Consistency Check ---

    # Apply all updates
    state_manager.update_state(state_updates)

    # Log final initial state
    logger.info(
        f"Start Core: Symbol: {current_symbol}, Base: {base_asset}, Quote: {quote_asset}"
    )
    logger.info(
        f"Start Core: Initial {quote_asset} Balance: {state_manager.get_state('available_balance'):.4f}"
    )
    logger.info(
        f"Start Core: Initial {base_asset} Quantity: {state_manager.get_state('symbol_quantity'):.8f}"
    )
    logger.info(
        f"Start Core: Initial Position State (final): {'IN POSITION' if final_in_position else 'OUT OF POSITION'}"
    )
    return True


def _prefetch_kline_history() -> bool:
    """Prefetches kline history if needed (SWING strategy)."""
    strategy_type = config_manager.get_value("STRATEGY_TYPE")
    if strategy_type == "SCALPING":
        logger.info("Start Core (SCALPING): Kline prefetch skipped.")
        state_manager.clear_kline_history() # Ensure it's empty for scalping
        return True

    # For SWING or other strategies needing history
    current_tf = config_manager.get_value("TIMEFRAME_STR", "1m") # Use config value
    required_limit = state_manager.get_required_klines()
    symbol = state_manager.get_state("symbol")

    logger.info(
        f"Start Core ({strategy_type}): Prefetching {required_limit} klines ({symbol} {current_tf})..."
    )
    initial_klines = binance_client_wrapper.get_klines(
        symbol=symbol, interval=current_tf, limit=required_limit
    )

    if initial_klines:
        # Ensure deque has the correct maxlen before replacing
        state_manager.resize_kline_history(required_limit)
        state_manager.replace_kline_history(initial_klines)
        logger.info(
            f"Start Core ({strategy_type}): Kline history prefetched ({len(initial_klines)}/{required_limit})."
        )
        return True
    else:
        logger.error(f"Start Core ({strategy_type}): Failed to prefetch initial klines.")
        state_manager.clear_kline_history() # Clear if fetch failed
        return False # Indicate failure


def _start_main_thread() -> bool:
    """Starts the main bot thread (run_bot)."""
    logger.info("Start Core: Starting main bot thread (run_bot)...")
    main_thread = state_manager.get_state("main_thread")
    if main_thread and main_thread.is_alive():
        logger.error("Start Core: Conflict - Main thread is already running.")
        return False # Avoid starting multiple main threads

    new_main_thread = threading.Thread(target=run_bot, daemon=True, name="BotCoreThread")
    state_manager.update_state(
        {"main_thread": new_main_thread, "stop_main_requested": False}
    )
    new_main_thread.start()
    time.sleep(0.5) # Give the thread a moment to actually start

    if new_main_thread.is_alive():
        logger.info("Start Core: Main bot thread (run_bot) started successfully.")
        return True
    else:
        logger.error("Start Core: Failed to start main bot thread.")
        state_manager.update_state({"main_thread": None, "status": "ERROR"})
        broadcast_state_update()
        return False


def _stop_main_thread(timeout: int = 5) -> bool:
    """Stops the main bot thread (run_bot)."""
    main_thread = state_manager.get_state("main_thread")
    if main_thread and main_thread.is_alive():
        logger.info("Stop Core: Sending stop signal to main thread...")
        state_manager.update_state({"stop_main_requested": True})
        main_thread.join(timeout=timeout) # Wait for thread to finish
        if main_thread.is_alive():
            # Thread didn't stop in time
            logger.warning(
                f"Stop Core: Main thread did not stop within {timeout} seconds."
            )
            # Consider if more drastic action is needed (though daemon=True helps)
            return False
        else:
            logger.info("Stop Core: Main thread stopped.")
            state_manager.update_state({"main_thread": None}) # Clean up reference
            return True
    elif main_thread:
        # Thread object exists but is not alive
        logger.info("Stop Core: Main thread was already stopped.")
        state_manager.update_state({"main_thread": None}) # Clean up reference
        return True
    else:
        # No thread object found
        logger.info("Stop Core: No main thread found to stop.")
        return True


# --- WebSocket Handling ---

def _handle_websocket_message(ws_client_instance, raw_msg: str):
    """
    Callback for all WebSocket messages (Combined Stream).
    Decodes JSON, extracts data, and routes to specific handlers.
    """
    #logger.debug(f"Raw Combined WS message received: {raw_msg}") # Keep commented unless deep debugging needed

    try:
        combined_data = json.loads(raw_msg)
        if not isinstance(combined_data, dict):
             logger.warning(f"Decoded combined message is not a dict: {combined_data}")
             return

        stream_name = combined_data.get('stream')
        data = combined_data.get('data')

        # Handle ACKs (which are not in the combined format)
        if "result" in combined_data and "id" in combined_data:
             logger.info(f"WebSocket ACK received (ID: {combined_data['id']}): {combined_data['result']}")
             return

        # Ensure we have valid stream data
        if not stream_name or not isinstance(data, dict):
             logger.warning(f"Invalid or non-combined WebSocket message received: {combined_data}")
             return

    except json.JSONDecodeError:
        logger.warning(f"Failed to decode combined WebSocket JSON message: {raw_msg}")
        return
    except Exception as e:
        logger.error(f"Unexpected error during combined WS message pre-processing: {e} - Message: {raw_msg}", exc_info=True)
        return

    # --- Routing Logic (using extracted 'data') ---
    try:
        event_type = data.get('e') # Event type is within the 'data' payload

        # Route based on event type 'e' if present
        if event_type:
            if event_type == 'aggTrade':
                websocket_handlers.process_agg_trade_message(data)
            elif event_type == 'kline':
                websocket_handlers.process_kline_message(data)
            elif event_type in ['executionReport', 'outboundAccountPosition', 'balanceUpdate']:
                 # Log routing for user data events
                 logger.debug(f"Routing to process_user_data_message for event_type='{event_type}' (Stream: {stream_name})...")
                 websocket_handlers.process_user_data_message(data)
            elif event_type == 'error': # Handle stream-specific errors
                 logger.error(f"Application error received via WebSocket: {data.get('m', 'Unknown error')}")
            # else: # Log unhandled event types if needed
            #     logger.debug(f"Unhandled combined WS event type '{event_type}' on stream '{stream_name}'")

        # Route based on stream name if 'e' is absent
        else:
            if 'bookTicker' in stream_name and all(k in data for k in ('u', 's', 'b', 'a')):
                websocket_handlers.process_book_ticker_message(data)
            elif 'depth' in stream_name and all(k in data for k in ('lastUpdateId', 'bids', 'asks')):
                 websocket_handlers.process_depth_message(data)
            else:
                 logger.warning(f"Unrecognized combined message without 'e' (Stream: {stream_name}): {data}")

    except Exception as e:
        logger.error(f"Error processing routed combined WS message: {e} - Stream: {stream_name} - Data: {data}", exc_info=True)


def _stop_keepalive_thread(timeout: int = 5) -> bool:
    """Stops the keepalive thread."""
    keepalive_thread = state_manager.get_state("keepalive_thread")
    if keepalive_thread and keepalive_thread.is_alive():
        logger.info("Stop Core: Sending stop signal to Keepalive thread...")
        state_manager.update_state({"stop_keepalive_requested": True})
        keepalive_thread.join(timeout=timeout)
        if keepalive_thread.is_alive():
            logger.warning(f"Stop Core: Keepalive thread did not stop within {timeout}s.")
            return False
        else:
            logger.info("Stop Core: Keepalive thread stopped.")
            state_manager.update_state({"keepalive_thread": None}) # Clean up reference
            return True
    elif keepalive_thread:
         logger.info("Stop Core: Keepalive thread was already stopped.")
         state_manager.update_state({"keepalive_thread": None}) # Clean up reference
         return True
    else:
        logger.info("Stop Core: No Keepalive thread found to stop.")
        return True


def _start_websockets() -> bool:
    """Starts the WebSocket client and subscribes to streams (Combined Mode)."""
    logger.info("Start Core: Starting WebSocket Client and Streams (Combined Mode)...")
    ws_client_instance = state_manager.get_state("websocket_client")
    if ws_client_instance:
        logger.warning("Start Core: Existing WebSocket client found. Stopping it first...")
        _stop_websockets(is_partial_stop=True) # Stop WS and Keepalive

    listen_key = None # Ensure listen_key is defined in this scope

    try:
        use_testnet = config_manager.get_value("USE_TESTNET", True)
        current_symbol = state_manager.get_state("symbol")
        strategy_type = config_manager.get_value("STRATEGY_TYPE")
        current_config = config_manager.get_config()

        if not current_symbol:
            raise ValueError("Symbol missing in state. Cannot start WebSockets.")

        # Correct base URL for combined streams (no path)
        ws_stream_url = "wss://testnet.binance.vision" if use_testnet else "wss://stream.binance.com:9443"

        # Create the client instance
        ws_client = SpotWebsocketStreamClient(
            stream_url=ws_stream_url,
            on_message=_handle_websocket_message,
            on_close=lambda *args: logger.info("WebSocket Client: Connection closed."),
            on_error=lambda _, e: logger.error(f"WebSocket Client: Error: {e}"),
            #on_ping=lambda *args: logger.debug("WebSocket Client: Ping received"),
            #on_pong=lambda *args: logger.debug("WebSocket Client: Pong received"),
            is_combined=True # Explicitly True
        )
        state_manager.update_state({"websocket_client": ws_client})
        logger.info(f"WebSocket Client created (Base URL: {ws_stream_url}) - Combined Mode")

        stream_symbol_lower = current_symbol.lower()
        streams_to_subscribe = []

        # 1. Get Listen Key via REST API
        logger.info("Start Core: Obtaining ListenKey via REST API...")
        listen_key = binance_client_wrapper.create_listen_key()
        if not listen_key:
            # Error logged by create_listen_key
            raise ConnectionError("Failed to obtain ListenKey via REST API.")
        state_manager.update_state({"listen_key": listen_key})
        logger.info(f"Start Core: ListenKey obtained: {listen_key[:5]}...")
        streams_to_subscribe.append(listen_key) # Add key itself for combined user stream
        logger.info("Start Core: User Data Stream added to subscription list.")

        # 2. Add Market Data Streams based on strategy
        logger.info("Start Core: Adding Book Ticker Stream...")
        streams_to_subscribe.append(f"{stream_symbol_lower}@bookTicker")
        logger.info("Start Core: Book Ticker Stream added.")

        if strategy_type == 'SCALPING':
            depth_levels = current_config.get("SCALPING_DEPTH_LEVELS", 5)
            depth_speed_str = current_config.get("SCALPING_DEPTH_SPEED", "100ms")
            depth_stream_name = f"{stream_symbol_lower}@depth{depth_levels}@{depth_speed_str}"
            logger.info(f"Start Core (SCALPING): Adding Depth Stream ({depth_stream_name})...")
            streams_to_subscribe.append(depth_stream_name)
            logger.info("Start Core (SCALPING): Depth Stream added.")

            logger.info("Start Core (SCALPING): Adding AggTrade Stream...")
            streams_to_subscribe.append(f"{stream_symbol_lower}@aggTrade")
            logger.info("Start Core (SCALPING): AggTrade Stream added.")

        elif strategy_type == 'SWING':
            current_tf = state_manager.get_state("timeframe") # Get current timeframe
            kline_stream_name = f"{stream_symbol_lower}@kline_{current_tf}"
            logger.info(f"Start Core (SWING): Adding Kline Stream ({kline_stream_name})...")
            streams_to_subscribe.append(kline_stream_name)
            logger.info(f"Start Core (SWING): Kline Stream added.")

        # 3. Subscribe to all streams at once
        if streams_to_subscribe:
            logger.info(f"Start Core: Subscribing to combined streams: {streams_to_subscribe}")
            ws_client.subscribe(stream=streams_to_subscribe, id=1) # Use a single ID for the batch
            logger.info("Start Core: Combined subscription request sent.")
            time.sleep(1) # Allow time for ACK
        else:
            logger.warning("Start Core: No streams identified for subscription?")

        # 4. Start the HTTP Keepalive Thread for the listenKey
        logger.info("Start Core: Starting HTTP Keepalive Thread...")
        keepalive_thread_ref = state_manager.get_state("keepalive_thread")
        if keepalive_thread_ref and keepalive_thread_ref.is_alive():
             logger.warning("Start Core: Keepalive thread already running? Stopping it first...")
             _stop_keepalive_thread() # Ensure only one keepalive thread runs

        new_keepalive_thread = threading.Thread(target=run_keepalive, daemon=True, name="KeepaliveThread")
        state_manager.update_state({"keepalive_thread": new_keepalive_thread, "stop_keepalive_requested": False})
        new_keepalive_thread.start()
        if not new_keepalive_thread.is_alive():
             # If thread failed to start, it's a critical error
             raise ConnectionError("Failed to start HTTP Keepalive thread!")
        logger.info("Start Core: HTTP Keepalive thread started.")

        logger.info("Start Core: All WebSocket streams (combined) and Keepalive started.")
        return True

    # Catch specific expected errors during startup
    except (ValueError, ConnectionError, ClientError, ServerError) as e:
        logger.critical(f"Start Core: Critical error during WS/Keepalive startup: {e}", exc_info=True)
        # Attempt cleanup
        if listen_key:
             logger.info("Attempting to close ListenKey after startup error...")
             binance_client_wrapper.close_listen_key(listen_key)
        _stop_websockets(is_partial_stop=True) # Stop WS client if created
        state_manager.update_state({"status": "ERROR", "listen_key": None})
        broadcast_state_update()
        return False
    # Catch any other unexpected errors
    except Exception as e:
         logger.critical(f"Start Core: Unexpected error during WS/Keepalive startup: {e}", exc_info=True)
         if listen_key: binance_client_wrapper.close_listen_key(listen_key)
         _stop_websockets(is_partial_stop=True)
         state_manager.update_state({"status": "ERROR", "listen_key": None})
         broadcast_state_update()
         return False


def _stop_websockets(is_partial_stop: bool = False) -> bool:
    """Stops the WebSocket client AND the keepalive thread."""
    log_prefix = "Stop Core (Partial):" if is_partial_stop else "Stop Core:"

    # Stop keepalive thread first to prevent further renewals/errors
    _stop_keepalive_thread()

    ws_client = state_manager.get_state("websocket_client")
    if ws_client:
        logger.info(f"{log_prefix} Stopping WebSocket Client...")
        try:
            # The stop() method should handle closing the connection
            ws_client.stop()
            # Wait briefly for the on_close callback to potentially fire
            time.sleep(0.5)
            logger.info(f"{log_prefix} WebSocket Client stop initiated.")
        except Exception as e:
            logger.error(f"{log_prefix} Error stopping WS Client: {e}", exc_info=True)
        finally:
            # Always clear the reference in the state manager
            state_manager.update_state({"websocket_client": None})
            logger.info(f"{log_prefix} WebSocket Client reference cleared.")
        return True
    else:
        logger.info(f"{log_prefix} No active WebSocket Client found to stop.")
        return True


# --- Public Control Functions ---

def start_bot_core() -> tuple[bool, str]:
    """Main function to start the bot's core processes."""
    logger.info("=" * 10 + " BOT START REQUESTED " + "=" * 10)
    current_status = state_manager.get_state("status")
    main_thread = state_manager.get_state("main_thread")

    # Prevent starting if already running or starting/stopping
    if current_status not in ["Arrêté", "STOPPED", "ERROR"] or (main_thread and main_thread.is_alive()):
        logger.warning(f"Start Core: Attempted start while bot status is '{current_status}'.")
        return False, f"Bot is already {current_status}."

    # --- Start Sequence ---
    state_manager.update_state({"status": "STARTING"})
    broadcast_state_update()
    state_manager.clear_realtime_data() # Clear old market data

    if not _initialize_client_and_config():
        return False, "Failed to initialize Binance client or config."
    if not _load_and_prepare_state():
        return False, "Failed to load state or retrieve initial balances/info."
    if not _prefetch_kline_history():
        # Allow starting even if klines fail, but log warning
        logger.warning("Start Core: Failed to prefetch kline history. Continuing...")
    if not _start_websockets():
        # Error handling inside _start_websockets sets status to ERROR
        return False, "Failed to start WebSocket connections."
    if not _start_main_thread():
        # If main thread fails, stop websockets cleanly
        _stop_websockets(is_partial_stop=True)
        return False, "Failed to start main bot thread."

    # --- Success ---
    state_manager.update_state({"status": "RUNNING"})
    broadcast_state_update()
    final_status = state_manager.get_state("status") # Should be RUNNING
    logger.info(f"Start Core: Bot startup sequence completed. Final Status: {final_status}")
    return True, "Bot started successfully."


def stop_bot_core(partial_cleanup: bool = False) -> tuple[bool, str]:
    """Main function to stop the bot's core processes."""
    log_prefix = "Stop Core (Partial):" if partial_cleanup else "Stop Core:"
    logger.info(f"{log_prefix} Stop requested...")
    current_status = state_manager.get_state("status")

    # Prevent stopping if already stopped (unless it's partial cleanup)
    if not partial_cleanup and current_status in ["Arrêté", "STOPPED"]:
        logger.info(f"{log_prefix} Bot is already stopped.")
        return False, "Bot is already stopped."

    # --- Stop Sequence ---
    if not partial_cleanup:
        state_manager.update_state({"status": "STOPPING"})
        broadcast_state_update()

    # Stop threads first
    _stop_main_thread()
    # _stop_websockets also stops the keepalive thread
    _stop_websockets(is_partial_stop=partial_cleanup)

    # Close the REST listen key if it exists
    listen_key_to_close = state_manager.get_state("listen_key")
    if listen_key_to_close:
        logger.info(f"{log_prefix} Closing ListenKey {listen_key_to_close[:5]}...")
        binance_client_wrapper.close_listen_key(listen_key_to_close)
        # Clear it from state immediately after attempting close
        state_manager.update_state({"listen_key": None})

    # Determine final status and clean up state variables
    final_status = "STOPPED" if not partial_cleanup else state_manager.get_state("status")
    state_manager.update_state({
        "status": final_status,
        "stop_main_requested": False, # Reset flag
        "open_order_id": None,
        "open_order_timestamp": None,
        "listen_key": None, # Ensure cleared
        "websocket_client": None, # Ensure cleared
        "keepalive_thread": None, # Ensure cleared
        "stop_keepalive_requested": False, # Reset flag
    })
    broadcast_state_update() # Broadcast final state

    # Save state only on a full stop
    if not partial_cleanup:
        logger.info(f"{log_prefix} Saving final state...")
        state_manager.save_persistent_data()

    logger.info(f"{log_prefix} Stop sequence completed. Final Status: {final_status}")
    return True, f"Bot stopped (Status: {final_status})."

# --- Exports ---
__all__ = [
    'execute_exit', 'run_bot', 'start_bot_core', 'stop_bot_core',
    'place_scalping_order', 'cancel_scalping_order',
    'refresh_order_history_via_rest' # Export the new function
]
