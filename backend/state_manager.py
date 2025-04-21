# /Users/davidmichels/Desktop/trading-bot/backend/state_manager.py
import threading
import queue
import collections
import json
import os
import logging
import time
from typing import Optional, Dict, Any, List, Deque, Tuple, Union
from decimal import Decimal, InvalidOperation

from config_manager import config_manager, SYMBOL
# REMOVED import from top:
# from websocket_utils import broadcast_order_history_update

logger = logging.getLogger(__name__) # Use __name__ for module-specific logger

DATA_FILENAME = "bot_data.json"

class StateManager:
    def __init__(self):
        # Lock for core bot state (status, position, balances, config-related) and order history
        self._config_state_lock = threading.Lock()
        # Lock specifically for kline history deque modifications
        self._kline_lock = threading.Lock()
        # Lock for other real-time market data (ticker, depth, trades)
        self._realtime_lock = threading.Lock()

        initial_config = config_manager.get_config()
        self._required_klines = self._calculate_required_klines(initial_config)

        # --- Data Structures ---
        # Kline history (protected by _kline_lock)
        self._kline_history: Deque[List[Any]] = collections.deque(maxlen=self._required_klines)

        # Real-time market data (protected by _realtime_lock)
        self._latest_book_ticker: Dict[str, Any] = {}
        self._latest_depth_snapshot: Dict[str, Any] = {'bids': [], 'asks': [], 'lastUpdateId': 0}
        self._latest_agg_trades: Deque[Dict[str, Any]] = collections.deque(maxlen=50) # Store last 50 agg trades

        # Core bot state (protected by _config_state_lock)
        self._bot_state: Dict[str, Any] = {
            "status": "Arrêté", # e.g., Arrêté, STARTING, RUNNING, STOPPING, STOPPED, ERROR
            "in_position": False, # Is the bot currently holding the base asset?
            "available_balance": 0.0, # Quote asset balance (e.g., USDT)
            "symbol_quantity": 0.0, # Base asset quantity (e.g., BTC)
            "base_asset": "", # e.g., BTC (set during startup)
            "quote_asset": "USDT", # Default, can be overridden by symbol info
            "symbol": initial_config.get("SYMBOL", SYMBOL), # Trading pair
            "timeframe": initial_config.get("TIMEFRAME_STR", "1m"), # Current timeframe
            "entry_details": None, # Dict with {order_id, avg_price, quantity, timestamp} if in_position
            "order_history": [], # List of simplified order dicts
            "max_history_length": 100, # Max orders to keep in history
            "open_order_id": None, # ID of an open LIMIT order (if any)
            "open_order_timestamp": None, # Timestamp when the open order was placed
            "main_thread": None, # Reference to the main bot thread
            "stop_main_requested": False, # Flag to signal main thread stop
            "websocket_client": None, # Instance of the WebSocket client
            "listen_key": None, # Current REST API listenKey for User Data Stream
            "keepalive_thread": None, # Reference to the keepalive thread
            "stop_keepalive_requested": False, # Flag to signal keepalive thread stop
        }
        # --- End Core Bot State ---

        self._load_persistent_data() # Load saved state on initialization
        logger.info("StateManager initialized.")

    def _calculate_required_klines(self, config_dict: Dict[str, Any]) -> int:
        """Calculates the number of klines needed based on indicator periods in config."""
        if config_dict.get("STRATEGY_TYPE") == 'SCALPING':
            return 1 # Scalping might not need history, or just the latest

        # For SWING or other strategies using indicators
        periods = []
        # Add periods from config, ensuring they are integers > 0
        for key in ["EMA_SHORT_PERIOD", "EMA_LONG_PERIOD", "RSI_PERIOD", "VOLUME_AVG_PERIOD", "EMA_FILTER_PERIOD"]:
            period = config_dict.get(key)
            if isinstance(period, int) and period > 0:
                 # Add only if the corresponding feature is enabled (if applicable)
                 if key == "EMA_FILTER_PERIOD" and not config_dict.get("USE_EMA_FILTER"): continue
                 if key == "VOLUME_AVG_PERIOD" and not config_dict.get("USE_VOLUME_CONFIRMATION"): continue
                 periods.append(period)

        # Return max period + buffer, or a default minimum
        return max(periods) + 5 if periods else 50

    # --- State Accessors/Mutators (Thread-Safe) ---

    def get_state(self, key: Optional[str] = None) -> Any:
        """Returns a copy of a specific state value or the entire state dict."""
        with self._config_state_lock:
            if key:
                value = self._bot_state.get(key)
                # Return copies of mutable types to prevent external modification
                if isinstance(value, list): return value[:]
                if isinstance(value, dict): return value.copy()
                if isinstance(value, collections.deque): return collections.deque(list(value), maxlen=value.maxlen)
                return value # Return immutable types directly
            else:
                # Return a shallow copy of the entire state dict
                return self._bot_state.copy()

    def update_state(self, updates: Dict[str, Any]):
        """Updates the bot state dictionary thread-safely."""
        with self._config_state_lock:
            # Log significant changes before updating
            if 'status' in updates and self._bot_state.get('status') != updates['status']:
                logger.info(f"StateManager: Status changing -> {updates['status']}")
            if 'in_position' in updates and self._bot_state.get('in_position') != updates['in_position']:
                 logger.info(f"StateManager: Position changing -> {updates['in_position']}")

            self._bot_state.update(updates)

    # --- Order History Management ---

    def add_order_to_history(self, order_details: Dict[str, Any]):
        """Adds or updates an order in the history (thread-safe) and broadcasts."""
        # --- MOVED IMPORT HERE ---
        from websocket_utils import broadcast_order_history_update
        # --- END MOVED IMPORT ---

        should_broadcast = False
        # Use 'i' (Binance WS order ID) as fallback for 'orderId' (REST)
        order_id_str = str(order_details.get('orderId') or order_details.get('i', 'N/A'))
        order_side = order_details.get('side') or order_details.get('S')
        order_status = order_details.get('status') or order_details.get('X')
        history_before_update = [] # For logging comparison

        with self._config_state_lock:
            try:
                # --- ADDED LOGGING ---
                # Log history *before* potential modification for debugging
                history_before_update = list(self._bot_state.get('order_history', []))
                # --- END ADDED LOGGING ---

                entry_details = self._bot_state.get("entry_details")
                performance_pct = None

                # Calculate performance only for filled SELL orders if we have entry details
                if order_side == 'SELL' and order_status == 'FILLED' and entry_details:
                     try:
                         # Use 'z' (WS executed qty) as fallback for 'executedQty' (REST)
                         # Use 'Z' (WS cummulative quote qty) as fallback for 'cummulativeQuoteQty' (REST)
                         exit_qty = float(order_details.get('executedQty', order_details.get('z', 0)))
                         exit_quote_qty = float(order_details.get('cummulativeQuoteQty', order_details.get('Z', 0)))
                         entry_price = float(entry_details.get('avg_price', 0))

                         if exit_qty > 0 and entry_price > 0:
                             avg_exit_price = exit_quote_qty / exit_qty
                             performance_pct = ((avg_exit_price / entry_price) - 1) # Simple percentage change
                     except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
                         logger.warning(f"StateManager: Error calculating performance for order {order_id_str}: {e}")

                # Create a simplified, consistent order structure for history
                simplified_order = {
                    "timestamp": order_details.get('transactTime') or order_details.get('T') or int(time.time() * 1000),
                    "orderId": order_id_str,
                    "symbol": order_details.get('symbol') or order_details.get('s'),
                    "side": order_side,
                    "type": order_details.get('orderType') or order_details.get('type') or order_details.get('o'), # REST vs WS naming
                    "origQty": str(order_details.get('origQty') or order_details.get('q', '0')), # Keep as string
                    "executedQty": str(order_details.get('executedQty') or order_details.get('z', '0')), # Keep as string
                    "cummulativeQuoteQty": str(order_details.get('cummulativeQuoteQty') or order_details.get('Z', '0')), # Keep as string
                    "price": str(order_details.get('price') or order_details.get('p', '0')), # Price for LIMIT orders
                    "status": order_status,
                    "performance_pct": performance_pct # Will be None if not calculated
                }

                # Find if order already exists in history
                existing_order_index = next((i for i, order in enumerate(self._bot_state['order_history']) if str(order.get('orderId')) == order_id_str), None)

                if existing_order_index is not None:
                    # Update existing order (e.g., status from NEW to FILLED)
                    self._bot_state['order_history'][existing_order_index].update(simplified_order)
                    logger.info(f"StateManager: Order {order_id_str} updated in history (Status: {order_status}).")
                else:
                    # Add new order
                    self._bot_state['order_history'].append(simplified_order)
                    logger.info(f"StateManager: Order {order_id_str} ({simplified_order['side']}) added to history (Status: {order_status}).")

                # Sort history by timestamp (newest first) and truncate
                self._bot_state['order_history'].sort(key=lambda x: x.get('timestamp', 0), reverse=True)
                max_len = self._bot_state.get('max_history_length', 100)
                if len(self._bot_state['order_history']) > max_len:
                    self._bot_state['order_history'] = self._bot_state['order_history'][:max_len]

                should_broadcast = True
                # Save persistent data whenever history changes
                self.save_persistent_data() # Call save method within the lock context

            except Exception as e:
                 logger.error(f"StateManager: Error adding/updating order history for {order_id_str}: {e}", exc_info=True)

        # Broadcast outside the lock to avoid holding it during network I/O
        if should_broadcast:
            logger.info(f"EVENT:ORDER_HISTORY_UPDATED:{order_id_str}:{order_status}")
            # --- ADDED LOGGING ---
            # Log the history *just before* broadcasting it
            current_history = self.get_order_history() # Get the updated history
            logger.debug(f"Broadcasting order history update. History contains {len(current_history)} orders. First few: {current_history[:3]}")
            # Optional: Log history before update for comparison
            # logger.debug(f"History before update had {len(history_before_update)} orders.")
            # --- END ADDED LOGGING ---
            broadcast_order_history_update() # Call the imported function

    def get_order_history(self) -> List[Dict[str, Any]]:
        """Returns a sorted copy of the order history."""
        with self._config_state_lock:
            # Return a copy of the list
            history_copy = list(self._bot_state.get('order_history', []))
            return history_copy

    # --- Config Management ---

    def get_config_value(self, key: str, default: Any = None) -> Any:
        """Retrieves a configuration value via ConfigManager."""
        return config_manager.get_value(key, default)

    def get_full_config(self) -> Dict[str, Any]:
        """Retrieves the full configuration via ConfigManager."""
        return config_manager.get_config()

    def update_config_values(self, new_params: Dict[str, Any]) -> Tuple[bool, str, bool]:
        """Updates configuration via ConfigManager and adjusts internal state if necessary."""
        # Delegate validation and update to ConfigManager
        success, message, restart_recommended = config_manager.update_config(new_params)
        if success:
            updated_config = config_manager.get_config()
            state_updates = {}
            # Update state if relevant config changed (e.g., timeframe)
            new_tf = updated_config.get("TIMEFRAME_STR")
            if new_tf and self._bot_state.get("timeframe") != new_tf:
                state_updates["timeframe"] = new_tf
                logger.info(f"StateManager: Timeframe updated to {new_tf} based on config change.")

            # Recalculate required klines and resize deque
            new_required_klines = self._calculate_required_klines(updated_config)
            self.resize_kline_history(new_required_klines) # Handles resizing deque

            if state_updates:
                self.update_state(state_updates)
        return success, message, restart_recommended

    # --- Kline History Management ---

    def get_kline_history(self) -> List[List[Any]]:
        """Returns a copy of the current kline history."""
        with self._kline_lock:
            return list(self._kline_history)

    def append_kline(self, kline: List[Any]):
        """Appends a new kline to the history (thread-safe)."""
        with self._kline_lock:
            self._kline_history.append(kline)

    def clear_kline_history(self):
        """Clears the kline history (thread-safe)."""
        with self._kline_lock:
            self._kline_history.clear()
            logger.info("StateManager: Kline history cleared.")

    def replace_kline_history(self, klines: List[List[Any]]):
         """Replaces the entire kline history (thread-safe)."""
         with self._kline_lock:
             self._kline_history.clear()
             self._kline_history.extend(klines)
             logger.info(f"StateManager: Kline history replaced ({len(self._kline_history)}/{self._kline_history.maxlen}).")

    def resize_kline_history(self, new_maxlen: int):
        """Resizes the kline history deque (thread-safe)."""
        with self._kline_lock:
            if self._kline_history.maxlen != new_maxlen:
                logger.info(f"StateManager: Resizing kline history from {self._kline_history.maxlen} to {new_maxlen}")
                # Create a new deque with the new maxlen and existing data
                current_data = list(self._kline_history)
                self._kline_history = collections.deque(current_data, maxlen=new_maxlen)

    def get_required_klines(self) -> int:
        """Returns the calculated number of required klines based on current config."""
        # Recalculate based on the *current* config
        current_config = config_manager.get_config()
        return self._calculate_required_klines(current_config)

    # --- Real-time Market Data ---

    def update_book_ticker(self, data: Dict[str, Any]):
        """Updates the latest book ticker data (thread-safe)."""
        with self._realtime_lock:
            self._latest_book_ticker.update(data)

    def get_book_ticker(self) -> Dict[str, Any]:
        """Returns a copy of the latest book ticker data."""
        with self._realtime_lock:
            return self._latest_book_ticker.copy()

    def update_depth_snapshot(self, data: Dict[str, Any]):
        """Updates the depth snapshot (thread-safe)."""
        with self._realtime_lock:
            # Update only if keys exist to avoid errors
            if 'bids' in data: self._latest_depth_snapshot['bids'] = data['bids']
            if 'asks' in data: self._latest_depth_snapshot['asks'] = data['asks']
            if 'lastUpdateId' in data: self._latest_depth_snapshot['lastUpdateId'] = data['lastUpdateId']

    def get_depth_snapshot(self) -> Dict[str, Any]:
        """Returns a copy of the latest depth snapshot."""
        with self._realtime_lock:
            # Return deep copies of lists to prevent modification
            return {
                'bids': [bid[:] for bid in self._latest_depth_snapshot.get('bids', [])],
                'asks': [ask[:] for ask in self._latest_depth_snapshot.get('asks', [])],
                'lastUpdateId': self._latest_depth_snapshot.get('lastUpdateId', 0)
            }

    def append_agg_trade(self, trade: Dict[str, Any]):
        """Appends a recent aggregated trade (thread-safe)."""
        with self._realtime_lock:
            self._latest_agg_trades.append(trade)

    def get_agg_trades(self) -> List[Dict[str, Any]]:
        """Returns a copy of the recent aggregated trades."""
        with self._realtime_lock:
            return list(self._latest_agg_trades)

    def clear_realtime_data(self):
        """Resets all real-time market data (thread-safe)."""
        with self._realtime_lock:
            self._latest_book_ticker.clear()
            self._latest_depth_snapshot = {'bids': [], 'asks': [], 'lastUpdateId': 0}
            self._latest_agg_trades.clear()
            logger.info("StateManager: Real-time market data cleared.")

    # --- Persistence ---

    def save_persistent_data(self) -> bool:
        """Saves relevant state (position, history) to a JSON file."""
        # Acquire lock to safely read the state to be saved
        with self._config_state_lock:
            state_to_save = {
                "in_position": self._bot_state.get("in_position", False),
                "entry_details": self._bot_state.get("entry_details", None),
                # Add other persistent state variables here if needed in the future
            }
            # Get a copy of the history list under the lock
            history_to_save = list(self._bot_state.get("order_history", []))

        # Prepare data structure for JSON
        data_to_save = {"state": state_to_save, "history": history_to_save}

        # Perform file I/O outside the lock
        try:
            with open(DATA_FILENAME, 'w') as f:
                # Use default=str to handle potential non-serializable types gracefully
                json.dump(data_to_save, f, indent=4, default=str)
            logger.debug(f"StateManager: Persistent data saved to {DATA_FILENAME}")
            return True
        except IOError as e:
            logger.error(f"StateManager: IO Error saving {DATA_FILENAME}: {e}")
            return False
        except Exception as e:
            # Catch broader exceptions during file writing/JSON encoding
            logger.exception(f"StateManager: Error saving persistent data: {e}")
            return False

    def _load_persistent_data(self):
        """Loads state and history from the JSON file on initialization."""
        if not os.path.exists(DATA_FILENAME):
            logger.info(f"StateManager: Persistence file {DATA_FILENAME} not found. Starting fresh.")
            return

        try:
            # Read file outside lock
            with open(DATA_FILENAME, 'r') as f:
                loaded_data = json.load(f)
            logger.info(f"StateManager: Data loaded from {DATA_FILENAME}")

            if isinstance(loaded_data, dict) and "state" in loaded_data and "history" in loaded_data:
                 state_data = loaded_data.get("state", {})
                 history_data = loaded_data.get("history", [])

                 # Update internal state under lock
                 with self._config_state_lock:
                     self._bot_state["in_position"] = state_data.get("in_position", False)
                     loaded_entry_details = state_data.get("entry_details")

                     # Validate and restore entry_details only if in position
                     if self._bot_state["in_position"] and isinstance(loaded_entry_details, dict):
                         try:
                             # Attempt to convert price/qty back to float for internal use
                             loaded_entry_details["avg_price"] = float(loaded_entry_details.get("avg_price", 0.0))
                             loaded_entry_details["quantity"] = float(loaded_entry_details.get("quantity", 0.0))
                             # Ensure timestamp is int
                             loaded_entry_details["timestamp"] = int(loaded_entry_details.get("timestamp", 0))
                             self._bot_state["entry_details"] = loaded_entry_details
                         except (ValueError, TypeError, InvalidOperation) as e:
                              logger.error(f"StateManager: Error converting loaded entry_details: {e}. Resetting position.")
                              self._bot_state["in_position"] = False
                              self._bot_state["entry_details"] = None
                     elif self._bot_state["in_position"]:
                         # In position but entry_details missing or invalid
                         logger.warning("StateManager: In position state loaded, but entry_details missing/invalid. Resetting position.")
                         self._bot_state["in_position"] = False
                         self._bot_state["entry_details"] = None
                     else:
                          # Not in position, ensure entry_details is None
                          self._bot_state["entry_details"] = None

                     # Restore and validate order history
                     restored_history = []
                     for order in history_data:
                         # Basic validation: check if it's a dict with an orderId
                         if isinstance(order, dict) and 'orderId' in order:
                             # Attempt to convert numeric fields back, handle potential errors
                             try:
                                 # Keep quantities/prices as strings for consistency with Binance API? Or convert?
                                 # Let's keep them as strings as loaded, conversion happens on use if needed.
                                 # Ensure timestamp is int
                                 order['timestamp'] = int(order.get('timestamp', 0))
                                 # Convert performance back to float if present
                                 perf_pct_str = order.get('performance_pct')
                                 order['performance_pct'] = float(perf_pct_str) if perf_pct_str is not None else None
                                 restored_history.append(order)
                             except (ValueError, TypeError, InvalidOperation) as e:
                                  logger.warning(f"StateManager: Error converting fields for order {order.get('orderId')} in history, skipping conversion: {e}")
                                  restored_history.append(order) # Add anyway? Or skip? Let's add.
                         else:
                             logger.warning(f"StateManager: Invalid order format in history ignored: {order}")

                     self._bot_state["order_history"] = restored_history

                     # Sort and truncate loaded history
                     self._bot_state['order_history'].sort(key=lambda x: x.get('timestamp', 0), reverse=True)
                     max_len = self._bot_state.get('max_history_length', 100)
                     if len(self._bot_state['order_history']) > max_len:
                         self._bot_state['order_history'] = self._bot_state['order_history'][:max_len]

                     logger.info(f"StateManager: State (in_position={self._bot_state['in_position']}) and history ({len(self._bot_state['order_history'])} orders) restored.")
            else:
                 logger.error(f"StateManager: Invalid format in {DATA_FILENAME}. State not restored.")

        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"StateManager: Error loading/decoding {DATA_FILENAME}: {e}.")
        except Exception as e:
            # Catch any other unexpected errors during loading
            logger.exception(f"StateManager: Unexpected error loading persistent data: {e}")

        # Final consistency check after loading
        with self._config_state_lock:
            if self._bot_state["in_position"] and not self._bot_state["entry_details"]:
                logger.warning("StateManager: Post-load consistency check failed ('in_position' is True but 'entry_details' is missing). Resetting position.")
                self._bot_state["in_position"] = False

# --- Instantiate the Singleton ---
state_manager = StateManager()

# --- Exports ---
__all__ = [
    'state_manager',
    'StateManager', # Export class for type hinting if needed elsewhere
    'DATA_FILENAME'
]
