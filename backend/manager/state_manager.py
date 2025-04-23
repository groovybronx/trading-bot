# /Users/davidmichels/Desktop/trading-bot/backend/state_manager.py
import threading
import collections
import json
import os
import logging
import time
import uuid
from typing import Optional, Dict, Any, List, Deque, Tuple, Union
from decimal import Decimal, InvalidOperation

# Gestionnaire de configuration
from manager.config_manager import config_manager, SYMBOL

# Utilitaires WebSocket (pour broadcast state)
from utils.websocket_utils import broadcast_state_update

# --- MODIFIED: Import DB functions ---
import db

logger = logging.getLogger(__name__)

DATA_FILENAME = "bot_data.json" # File for non-history state


class StateManager:
    def __init__(self):
        self._config_state_lock = threading.Lock()
        self._kline_lock = threading.Lock()
        self._realtime_lock = threading.Lock()
        self._pending_orders_lock = threading.Lock()

        initial_config = config_manager.get_config()
        self._required_klines = self._calculate_required_klines(initial_config)
        self._session_id = str(uuid.uuid4())

        # --- Structures de Données ---
        self._kline_history: Deque[List[Any]] = collections.deque(
            maxlen=self._required_klines
        )
        self._latest_book_ticker: Dict[str, Any] = {}
        self._latest_depth_snapshot: Dict[str, Any] = {
            "bids": [],
            "asks": [],
            "lastUpdateId": 0,
        }
        self._latest_agg_trades: Deque[Dict[str, Any]] = collections.deque(maxlen=50)
        self._symbol_info_cache: Optional[Dict[str, Any]] = None
        self._pending_order_details: Dict[str, Dict[str, Any]] = {}

        # État principal du bot (REMOVED order_history and max_history_length)
        self._bot_state: Dict[str, Any] = {
            "status": "Arrêté",
            "in_position": False,
            "available_balance": Decimal("0.0"),  # Utiliser Decimal
            "symbol_quantity": Decimal("0.0"),  # Utiliser Decimal
            "base_asset": "",
            "quote_asset": "USDT",
            "symbol": initial_config.get("SYMBOL", SYMBOL),
            "timeframe": initial_config.get("TIMEFRAME", "1m"),
            "entry_details": None,  # { order_id, avg_price, quantity, timestamp, side, sl_price, tp1_price, tp2_price, highest_price, lowest_price }
            # "order_history": [], # REMOVED
            # "max_history_length": 100, # REMOVED
            "open_order_id": None,
            "open_order_timestamp": None,
            "main_thread": None,
            "stop_main_requested": False,
            "websocket_client": None,
            "listen_key": None,
            "keepalive_thread": None,
            "stop_keepalive_requested": False,
            "last_order_timestamp": None,
        }

        self._load_persistent_data() # Loads only position state now
        logger.info("StateManager initialized (History managed by DB).")

    def _calculate_required_klines(self, config_dict: Dict[str, Any]) -> int:
        """Calcule le nombre de klines nécessaires basé sur la stratégie."""
        strategy_type = config_dict.get("STRATEGY_TYPE")

        if strategy_type == "SCALPING":
            return 1

        min_req = 2

        if strategy_type == "SCALPING2":
            periods = [
                config_dict.get("SUPERTREND_ATR_PERIOD", 3) + 1,
                config_dict.get("SCALPING_RSI_PERIOD", 7),
                config_dict.get("STOCH_K_PERIOD", 14) + config_dict.get("STOCH_D_PERIOD", 3),
                config_dict.get("BB_PERIOD", 20),
                config_dict.get("VOLUME_MA_PERIOD", 20),
            ]
            min_req = max(periods) + 5

        elif strategy_type == "SWING":
            periods = [
                config_dict.get("EMA_SHORT_PERIOD", 9),
                config_dict.get("EMA_LONG_PERIOD", 21),
                config_dict.get("RSI_PERIOD", 14),
            ]
            if config_dict.get("USE_EMA_FILTER", False):
                periods.append(config_dict.get("EMA_FILTER_PERIOD", 50))
            if config_dict.get("USE_VOLUME_CONFIRMATION", False):
                periods.append(config_dict.get("VOLUME_AVG_PERIOD", 20))
            min_req = max(periods) + 5 if periods else 50

        return max(min_req, 25)

    # --- Accesseurs/Mutateurs État Principal (Thread-Safe) ---

    def get_state(self, key: Optional[str] = None) -> Any:
        """Retourne une copie d'une valeur spécifique ou de l'état complet (sans historique)."""
        with self._config_state_lock:
            if key:
                value = self._bot_state.get(key)
                if isinstance(value, dict): return value.copy()
                if isinstance(value, list): return value[:]
                if isinstance(value, collections.deque): return collections.deque(list(value), maxlen=value.maxlen)
                return value
            else:
                return self._bot_state.copy()

    def update_state(self, updates: Dict[str, Any]):
        """Met à jour l'état du bot de manière thread-safe."""
        with self._config_state_lock:
            if "status" in updates and self._bot_state.get("status") != updates["status"]:
                logger.info(f"StateManager: Status changing -> {updates['status']}")
            if "in_position" in updates and self._bot_state.get("in_position") != updates["in_position"]:
                logger.info(f"StateManager: Position changing -> {updates['in_position']}")
                if not updates["in_position"]:
                    if self._bot_state.get("entry_details"):
                        logger.debug("StateManager: Clearing entry_details on exiting position.")
                        self._bot_state["entry_details"] = None
                    for temp_key in ["_temp_entry_sl", "_temp_entry_tp1", "_temp_entry_tp2"]:
                        if temp_key in self._bot_state: self._bot_state[temp_key] = None

            # --- Trailing Stop Logic (Highest/Lowest Price Update) ---
            ticker_for_trailing = updates.get("latest_book_ticker")
            if self._bot_state.get("in_position") and ticker_for_trailing:
                current_price_str = ticker_for_trailing.get("c")
                entry_details = self._bot_state.get("entry_details")
                if current_price_str and entry_details:
                    try:
                        current_price = Decimal(current_price_str)
                        if current_price > entry_details.get("highest_price", Decimal("-Infinity")):
                            entry_details["highest_price"] = current_price
                        if current_price < entry_details.get("lowest_price", Decimal("Infinity")):
                            entry_details["lowest_price"] = current_price
                    except (InvalidOperation, TypeError):
                        logger.warning(f"Failed to update highest/lowest price from ticker: {current_price_str}")
                if "latest_book_ticker" in updates: del updates["latest_book_ticker"]
            # --- End Trailing Stop Logic ---

            self._bot_state.update(updates)
            # --- Save state changes (excluding history) ---
            self.save_persistent_data() # Save state changes immediately

    # --- Gestion Historique Ordres (DELEGATED TO DB) ---

    # REMOVED: _format_order_for_history
    # REMOVED: replace_order_history
    # REMOVED: add_or_update_order_history

    def get_order_history(self, strategy: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Récupère l'historique des ordres depuis la base de données.
        """
        # Pas besoin de verrou ici, db.py gère sa propre concurrence.
        return db.get_order_history(strategy=strategy, limit=limit)

    # REMOVED: clear_order_history (Handled by API calling db.reset_orders)

    # --- Gestion Configuration ---

    def get_config_value(self, key: str, default: Any = None) -> Any:
        return config_manager.get_value(key, default)

    def get_full_config(self) -> Dict[str, Any]:
        return config_manager.get_config()

    def update_config_values(self, new_params_input: Dict[str, Any]) -> Tuple[bool, str, bool]:
        success, message, restart_recommended = config_manager.update_config(new_params_input)
        if success:
            updated_config = config_manager.get_config()
            state_updates = {}
            new_tf = updated_config.get("TIMEFRAME")
            if new_tf and self._bot_state.get("timeframe") != new_tf:
                state_updates["timeframe"] = new_tf
                logger.info(f"StateManager: Timeframe updated to {new_tf}.")

            new_required_klines = self._calculate_required_klines(updated_config)
            with self._kline_lock:
                self.resize_kline_history(new_required_klines)

            if state_updates:
                self.update_state(state_updates) # This now also saves persistent data
        return success, message, restart_recommended

    # --- Gestion Historique Klines (Unchanged) ---

    def get_kline_history_list(self) -> List[List[Any]]:
        with self._kline_lock:
            return list(self._kline_history)

    def add_kline(self, kline: List[Any]):
        with self._kline_lock:
            self._kline_history.append(kline)

    def clear_kline_history(self):
        with self._kline_lock:
            self._kline_history.clear()
            logger.info("StateManager: Kline history cleared.")

    def replace_kline_history(self, klines: List[List[Any]]):
        with self._kline_lock:
            current_maxlen = self._kline_history.maxlen
            required_klines = self.get_required_klines()
            if current_maxlen != required_klines:
                logger.warning(f"StateManager: Kline history maxlen ({current_maxlen}) differs from required ({required_klines}) during replace. Resizing.")
                self.resize_kline_history(required_klines)
            self._kline_history.clear()
            self._kline_history.extend(klines)
            logger.info(f"StateManager: Kline history replaced ({len(self._kline_history)}/{self._kline_history.maxlen}).")

    def resize_kline_history(self, new_maxlen: int):
        if self._kline_history.maxlen != new_maxlen:
            logger.info(f"StateManager: Resizing kline history from {self._kline_history.maxlen} to {new_maxlen}")
            current_data = list(self._kline_history)
            self._kline_history = collections.deque(current_data, maxlen=new_maxlen)

    def get_required_klines(self) -> int:
        current_config = config_manager.get_config()
        return self._calculate_required_klines(current_config)

    # --- Données Marché Temps Réel (Unchanged) ---

    def update_book_ticker(self, data: Dict[str, Any]):
        with self._realtime_lock:
            self._latest_book_ticker.update(data)
        self.update_state({"latest_book_ticker": data.copy()}) # Triggers save

    def get_book_ticker(self) -> Dict[str, Any]:
        with self._realtime_lock:
            return self._latest_book_ticker.copy()

    def update_depth(self, data: Dict[str, Any]):
        with self._realtime_lock:
            if "bids" in data: self._latest_depth_snapshot["bids"] = [b[:] for b in data["bids"]]
            if "asks" in data: self._latest_depth_snapshot["asks"] = [a[:] for a in data["asks"]]
            if "lastUpdateId" in data: self._latest_depth_snapshot["lastUpdateId"] = data["lastUpdateId"]

    def get_depth(self) -> Dict[str, Any]:
        with self._realtime_lock:
            return {
                "bids": [bid[:] for bid in self._latest_depth_snapshot.get("bids", [])],
                "asks": [ask[:] for ask in self._latest_depth_snapshot.get("asks", [])],
                "lastUpdateId": self._latest_depth_snapshot.get("lastUpdateId", 0),
            }

    def append_agg_trade(self, trade: Dict[str, Any]):
        with self._realtime_lock:
            self._latest_agg_trades.append(trade)

    def get_agg_trades(self) -> List[Dict[str, Any]]:
        with self._realtime_lock:
            return list(self._latest_agg_trades)

    def clear_realtime_data(self):
        with self._realtime_lock:
            self._latest_book_ticker.clear()
            self._latest_depth_snapshot = {"bids": [], "asks": [], "lastUpdateId": 0}
            self._latest_agg_trades.clear()
            self._symbol_info_cache = None
            logger.info("StateManager: Real-time market data and symbol_info cache cleared.")

    # --- Symbol Info Cache (Unchanged) ---
    def update_symbol_info(self, symbol_info: Dict[str, Any]):
        with self._realtime_lock:
            self._symbol_info_cache = symbol_info
            logger.debug("StateManager: Symbol info cache updated.")

    def get_symbol_info(self) -> Optional[Dict[str, Any]]:
        with self._realtime_lock:
            return self._symbol_info_cache.copy() if self._symbol_info_cache else None

    # --- Gestion des détails d'ordre en attente (Unchanged) ---
    def store_pending_order_details(self, client_order_id: str, details: Dict[str, Any]):
        if not client_order_id: return
        with self._pending_orders_lock:
            self._pending_order_details[client_order_id] = details

    def get_and_clear_pending_order_details(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        if not client_order_id: return None
        with self._pending_orders_lock:
            details = self._pending_order_details.pop(client_order_id, None)
            if details: logger.debug(f"Retrieved and cleared pending details for ClientID {client_order_id}")
            else: logger.warning(f"No pending details found for ClientID {client_order_id} on get_and_clear.")
            return details

    def clear_pending_order_details(self, client_order_id: str):
        if not client_order_id: return
        with self._pending_orders_lock:
            if client_order_id in self._pending_order_details:
                del self._pending_order_details[client_order_id]
                logger.debug(f"Cleared pending details for ClientID {client_order_id} (e.g., due to failure).")

    # --- Persistance (MODIFIED: Excludes history) ---

    def save_persistent_data(self) -> bool:
        """Sauvegarde l'état pertinent (position, entry_details) dans un fichier JSON."""
        # Called under _config_state_lock by update_state
        state_to_save = {
            "in_position": self._bot_state.get("in_position", False),
            "entry_details": (
                {
                    k: str(v) if isinstance(v, Decimal) else v
                    for k, v in self._bot_state.get("entry_details", {}).items()
                }
                if self._bot_state.get("entry_details")
                else None
            ),
        }
        # --- REMOVED history saving ---
        data_to_save = {"state": state_to_save}

        try:
            with open(DATA_FILENAME, "w") as f:
                json.dump(data_to_save, f, indent=4)
            # logger.debug(f"StateManager: Persistent state (excluding history) saved.") # Verbeux
            return True
        except (IOError, TypeError) as e:
            logger.error(f"StateManager: Error saving {DATA_FILENAME}: {e}")
            return False
        except Exception as e:
            logger.exception(f"StateManager: Unexpected error saving persistent data: {e}")
            return False

    def _load_persistent_data(self):
        """Charge l'état (position, entry_details) depuis JSON à l'initialisation."""
        if not os.path.exists(DATA_FILENAME):
            logger.info(f"StateManager: Persistence file {DATA_FILENAME} not found.")
            return

        try:
            with open(DATA_FILENAME, "r") as f:
                loaded_data = json.load(f)
            logger.info(f"StateManager: State data loaded from {DATA_FILENAME}")

            # --- REMOVED history loading ---
            if isinstance(loaded_data, dict) and "state" in loaded_data:
                state_data = loaded_data.get("state", {})

                with self._config_state_lock:
                    self._bot_state["in_position"] = state_data.get("in_position", False)
                    loaded_entry_details_str = state_data.get("entry_details")

                    if self._bot_state["in_position"] and isinstance(loaded_entry_details_str, dict):
                        try:
                            entry_details_reloaded = {}
                            for key, val_str in loaded_entry_details_str.items():
                                if key in ["avg_price", "quantity", "sl_price", "tp1_price", "tp2_price", "highest_price", "lowest_price"]:
                                    entry_details_reloaded[key] = Decimal(val_str)
                                elif key == "timestamp":
                                    entry_details_reloaded[key] = int(val_str)
                                else:
                                    entry_details_reloaded[key] = val_str
                            self._bot_state["entry_details"] = entry_details_reloaded
                        except (ValueError, TypeError, InvalidOperation) as e:
                            logger.error(f"StateManager: Error converting loaded entry_details: {e}. Resetting position.")
                            self._bot_state["in_position"] = False
                            self._bot_state["entry_details"] = None
                    elif self._bot_state["in_position"]:
                        logger.warning("StateManager: In position state loaded, but entry_details missing/invalid. Resetting.")
                        self._bot_state["in_position"] = False
                        self._bot_state["entry_details"] = None
                    else:
                        self._bot_state["entry_details"] = None

                    for temp_key in ["_temp_entry_sl", "_temp_entry_tp1", "_temp_entry_tp2"]:
                        self._bot_state[temp_key] = None

                    logger.info(f"StateManager: State (in_position={self._bot_state['in_position']}) restored from file.")
            else:
                logger.error(f"StateManager: Invalid format in {DATA_FILENAME}. State not restored.")

        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"StateManager: Error loading/decoding {DATA_FILENAME}: {e}.")
        except Exception as e:
            logger.exception(f"StateManager: Unexpected error loading persistent data: {e}")

        with self._config_state_lock:
            if self._bot_state["in_position"] and not self._bot_state["entry_details"]:
                logger.warning("StateManager: Post-load check failed ('in_position' True, 'entry_details' missing). Resetting.")
                self._bot_state["in_position"] = False

    # --- Session and Timestamp (Unchanged) ---
    def get_last_order_timestamp(self) -> Optional[int]:
        with self._config_state_lock:
            return self._bot_state.get("last_order_timestamp")

    def set_last_order_timestamp(self, timestamp_ms: int):
        with self._config_state_lock:
            self._bot_state["last_order_timestamp"] = timestamp_ms

    def get_session_id(self):
        return self._session_id

    def reset_session_id(self):
        self._session_id = str(uuid.uuid4())
        logger.info(f"Nouvelle session_id générée: {self._session_id}")


# --- Instanciation Singleton ---
state_manager = StateManager()

# --- Exports ---
__all__ = ["state_manager", "StateManager", "DATA_FILENAME"]
