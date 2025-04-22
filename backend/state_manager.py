# /Users/davidmichels/Desktop/trading-bot/backend/state_manager.py
import threading
import collections
import json
import os
import logging
import time
from typing import Optional, Dict, Any, List, Deque, Tuple, Union
from decimal import Decimal, InvalidOperation

# Gestionnaire de configuration
from config_manager import config_manager, SYMBOL

# Utilitaires WebSocket (pour broadcast)
# Importé ici pour être utilisé dans replace_order_history
from websocket_utils import broadcast_order_history_update

logger = logging.getLogger(__name__) # Utiliser __name__

DATA_FILENAME = "bot_data.json"

class StateManager:
    def __init__(self):
        # Verrous pour la sécurité des threads
        self._config_state_lock = threading.Lock() # État principal, config, historique ordres
        self._kline_lock = threading.Lock()        # Historique Klines
        self._realtime_lock = threading.Lock()     # Ticker, Profondeur, Trades Agg.

        initial_config = config_manager.get_config()
        self._required_klines = self._calculate_required_klines(initial_config)

        # --- Structures de Données ---
        self._kline_history: Deque[List[Any]] = collections.deque(maxlen=self._required_klines)
        self._latest_book_ticker: Dict[str, Any] = {}
        self._latest_depth_snapshot: Dict[str, Any] = {'bids': [], 'asks': [], 'lastUpdateId': 0}
        self._latest_agg_trades: Deque[Dict[str, Any]] = collections.deque(maxlen=50)
        self._symbol_info_cache: Optional[Dict[str, Any]] = None # Cache pour symbol_info

        # État principal du bot (protégé par _config_state_lock)
        self._bot_state: Dict[str, Any] = {
            "status": "Arrêté",
            "in_position": False,
            "available_balance": 0.0,
            "symbol_quantity": 0.0,
            "base_asset": "",
            "quote_asset": "USDT",
            "symbol": initial_config.get("SYMBOL", SYMBOL),
            "timeframe": initial_config.get("TIMEFRAME_STR", "1m"),
            "entry_details": None,
            "order_history": [],
            "max_history_length": 100,
            "open_order_id": None,
            "open_order_timestamp": None,
            "main_thread": None,
            "stop_main_requested": False,
            "websocket_client": None,
            "listen_key": None,
            "keepalive_thread": None,
            "stop_keepalive_requested": False,
        }

        self._load_persistent_data() # Charger l'état sauvegardé
        logger.info("StateManager initialized.")

    def _calculate_required_klines(self, config_dict: Dict[str, Any]) -> int:
        """Calcule le nombre de klines nécessaires basé sur les indicateurs configurés."""
        if config_dict.get("STRATEGY_TYPE") == 'SCALPING':
            return 1 # Scalping n'utilise pas l'historique kline

        periods = []
        indicator_keys = {
            "EMA_SHORT_PERIOD", "EMA_LONG_PERIOD", "RSI_PERIOD",
            "VOLUME_AVG_PERIOD", "EMA_FILTER_PERIOD"
        }
        feature_flags = {
            "EMA_FILTER_PERIOD": "USE_EMA_FILTER",
            "VOLUME_AVG_PERIOD": "USE_VOLUME_CONFIRMATION"
        }

        for key in indicator_keys:
            period = config_dict.get(key)
            if isinstance(period, int) and period > 0:
                 # Vérifier si une feature flag désactive l'indicateur
                 flag_key = feature_flags.get(key)
                 if flag_key and not config_dict.get(flag_key, False):
                     continue # Ne pas ajouter la période si la feature est désactivée
                 periods.append(period)

        return max(periods) + 5 if periods else 50 # +5 pour buffer, min 50

    # --- Accesseurs/Mutateurs État Principal (Thread-Safe) ---

    def get_state(self, key: Optional[str] = None) -> Any:
        """Retourne une copie d'une valeur spécifique ou de l'état complet."""
        with self._config_state_lock:
            if key:
                value = self._bot_state.get(key)
                # Copies pour types mutables
                if isinstance(value, list): return value[:]
                if isinstance(value, dict): return value.copy()
                if isinstance(value, collections.deque): return collections.deque(list(value), maxlen=value.maxlen)
                return value # Types immutables
            else:
                return self._bot_state.copy() # Copie du dict entier

    def update_state(self, updates: Dict[str, Any]):
        """Met à jour l'état du bot de manière thread-safe."""
        with self._config_state_lock:
            if 'status' in updates and self._bot_state.get('status') != updates['status']:
                logger.info(f"StateManager: Status changing -> {updates['status']}")
            if 'in_position' in updates and self._bot_state.get('in_position') != updates['in_position']:
                 logger.info(f"StateManager: Position changing -> {updates['in_position']}")
            self._bot_state.update(updates)

    # --- Gestion Historique Ordres ---

    def _format_order_for_history(self, order_details: Dict[str, Any]) -> Dict[str, Any]:
        """Formate un ordre brut (REST ou WS) pour l'historique."""
        order_id_str = str(order_details.get('orderId') or order_details.get('i', 'N/A'))
        order_side = order_details.get('side') or order_details.get('S')
        order_status = order_details.get('status') or order_details.get('X')

        # Calcul performance désactivé ici pour `replace_order_history`
        # car il nécessiterait l'état `entry_details` au moment de l'ordre SELL,
        # qui n'est pas disponible lors du simple reformatage de l'historique brut.
        # La performance est calculée dans `add_or_update_order_history` si besoin.

        simplified_order = {
            "timestamp": order_details.get('updateTime') or order_details.get('time') or order_details.get('T') or int(time.time() * 1000),
            "orderId": order_id_str,
            "symbol": order_details.get('symbol') or order_details.get('s'),
            "side": order_side,
            "type": order_details.get('orderType') or order_details.get('type') or order_details.get('o'),
            "origQty": str(order_details.get('origQty') or order_details.get('q', '0')),
            "executedQty": str(order_details.get('executedQty') or order_details.get('z', '0')),
            "cummulativeQuoteQty": str(order_details.get('cummulativeQuoteQty') or order_details.get('Z', '0')),
            "price": str(order_details.get('price') or order_details.get('p', '0')),
            "status": order_status,
            "performance_pct": None # Performance non calculée lors du remplacement
        }
        return simplified_order

    def replace_order_history(self, new_raw_history: List[Dict[str, Any]]):
        """Remplace l'historique interne avec les données API et diffuse."""
        simplified_new_history = []
        if isinstance(new_raw_history, list):
             for order in new_raw_history:
                 simplified_new_history.append(self._format_order_for_history(order))
        else:
             logger.error("replace_order_history: Données non-liste reçues.")
             return

        did_save = False
        try:
            with self._config_state_lock:
                logger.info(f"Replacing internal order history with {len(simplified_new_history)} orders.")
                simplified_new_history.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
                max_len = self._bot_state.get('max_history_length', 100)
                self._bot_state['order_history'] = simplified_new_history[:max_len]
                did_save = self.save_persistent_data() # Sauvegarder sous verrou
        except Exception as e:
             logger.error(f"Error during history replacement/saving: {e}", exc_info=True)
             return

        if did_save:
            broadcast_order_history_update() # Diffuser hors verrou si sauvegarde OK
        else:
            logger.error("replace_order_history: Broadcast annulé car sauvegarde échouée.")

    def add_or_update_order_history(self, order_data: Dict[str, Any]):
        """Ajoute ou met à jour un ordre dans l'historique et calcule la performance si SELL FILLED."""
        # Import local pour éviter dépendance circulaire potentielle
        from websocket_utils import broadcast_order_history_update

        order_id_to_update = str(order_data.get('orderId') or order_data.get('i', 'N/A'))
        if order_id_to_update == 'N/A':
            logger.warning("add_or_update_order_history: Order ID manquant, impossible de mettre à jour.")
            return

        performance_pct = None
        entry_details_for_calc = None

        # --- Pré-calcul performance (si applicable) HORS verrou principal ---
        order_side = order_data.get('side') or order_data.get('S')
        order_status = order_data.get('status') or order_data.get('X')

        if order_side == 'SELL' and order_status == 'FILLED':
            # Récupérer entry_details actuel (copie rapide sous verrou)
            with self._config_state_lock:
                if self._bot_state.get("in_position"):
                    entry_details_for_calc = self._bot_state.get("entry_details", {}).copy()

            if entry_details_for_calc:
                try:
                    entry_price = Decimal(str(entry_details_for_calc.get("avg_price", "0")))
                    exec_qty_sell = Decimal(str(order_data.get('executedQty') or order_data.get('z', '0')))
                    quote_qty_sell = Decimal(str(order_data.get('cummulativeQuoteQty') or order_data.get('Z', '0')))

                    if entry_price > 0 and exec_qty_sell > 0:
                        exit_price = quote_qty_sell / exec_qty_sell
                        performance_pct = float((exit_price - entry_price) / entry_price)
                        logger.info(f"Performance calculated for SELL order {order_id_to_update}: {performance_pct:.4%}")
                    else:
                        logger.warning(f"Cannot calculate performance for SELL {order_id_to_update}: Invalid entry price or sell quantity.")
                except (ValueError, TypeError, ZeroDivisionError, InvalidOperation) as e:
                    logger.warning(f"Error calculating performance for SELL order {order_id_to_update}: {e}")

        # --- Mise à jour de l'historique sous verrou ---
        updated = False
        try:
            with self._config_state_lock:
                history = self._bot_state['order_history']
                found_index = -1
                for i, order in enumerate(history):
                    if order.get('orderId') == order_id_to_update:
                        found_index = i
                        break

                formatted_order = self._format_order_for_history(order_data)
                # Ajouter la performance calculée si disponible
                formatted_order['performance_pct'] = performance_pct

                if found_index != -1:
                    # Mettre à jour l'ordre existant
                    history[found_index] = formatted_order
                    logger.debug(f"Order {order_id_to_update} updated in history.")
                else:
                    # Ajouter le nouvel ordre au début (plus récent)
                    history.insert(0, formatted_order)
                    logger.debug(f"Order {order_id_to_update} added to history.")

                # Trier et tronquer
                history.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
                max_len = self._bot_state.get('max_history_length', 100)
                if len(history) > max_len:
                    self._bot_state['order_history'] = history[:max_len]

                updated = True
                # Sauvegarder si un ordre a été ajouté/mis à jour
                self.save_persistent_data()

        except Exception as e:
             logger.error(f"Error during lock acquisition or history update for order {order_id_to_update}: {e}", exc_info=True)
             return

        # --- Diffusion hors verrou ---
        if updated:
            broadcast_order_history_update()

    def get_order_history(self) -> List[Dict[str, Any]]:
        """Retourne une copie triée de l'historique des ordres."""
        with self._config_state_lock:
            history_copy = list(self._bot_state.get('order_history', []))
            return history_copy

    # --- Gestion Configuration ---

    def get_config_value(self, key: str, default: Any = None) -> Any:
        """Récupère une valeur de config via ConfigManager."""
        return config_manager.get_value(key, default)

    def get_full_config(self) -> Dict[str, Any]:
        """Récupère la config complète via ConfigManager."""
        return config_manager.get_config()

    def update_config_values(self, new_params: Dict[str, Any]) -> Tuple[bool, str, bool]:
        """Met à jour la config via ConfigManager et ajuste l'état interne."""
        success, message, restart_recommended = config_manager.update_config(new_params)
        if success:
            updated_config = config_manager.get_config()
            state_updates = {}
            new_tf = updated_config.get("TIMEFRAME_STR")
            if new_tf and self._bot_state.get("timeframe") != new_tf:
                state_updates["timeframe"] = new_tf
                logger.info(f"StateManager: Timeframe updated to {new_tf}.")

            new_required_klines = self._calculate_required_klines(updated_config)
            self.resize_kline_history(new_required_klines)

            if state_updates:
                self.update_state(state_updates)
        return success, message, restart_recommended

    # --- Gestion Historique Klines ---

    def get_kline_history_list(self) -> List[List[Any]]: # Renommé pour clarté
        """Retourne une copie de l'historique kline actuel."""
        with self._kline_lock:
            return list(self._kline_history)

    def add_kline(self, kline: List[Any]): # Renommé pour clarté
        """Ajoute une nouvelle kline à l'historique."""
        with self._kline_lock:
            self._kline_history.append(kline)

    def clear_kline_history(self):
        """Vide l'historique kline."""
        with self._kline_lock:
            self._kline_history.clear()
            logger.info("StateManager: Kline history cleared.")

    def replace_kline_history(self, klines: List[List[Any]]):
         """Remplace l'historique kline complet."""
         with self._kline_lock:
             self._kline_history.clear()
             self._kline_history.extend(klines)
             logger.info(f"StateManager: Kline history replaced ({len(self._kline_history)}/{self._kline_history.maxlen}).")

    def resize_kline_history(self, new_maxlen: int):
        """Redimensionne le deque de l'historique kline."""
        with self._kline_lock:
            if self._kline_history.maxlen != new_maxlen:
                logger.info(f"StateManager: Resizing kline history from {self._kline_history.maxlen} to {new_maxlen}")
                current_data = list(self._kline_history)
                self._kline_history = collections.deque(current_data, maxlen=new_maxlen)

    def get_required_klines(self) -> int:
        """Retourne le nombre de klines requis calculé."""
        current_config = config_manager.get_config()
        return self._calculate_required_klines(current_config)

    # --- Données Marché Temps Réel ---

    def update_book_ticker(self, data: Dict[str, Any]):
        """Met à jour le dernier book ticker."""
        with self._realtime_lock:
            self._latest_book_ticker.update(data)

    def get_book_ticker(self) -> Dict[str, Any]:
        """Retourne une copie du dernier book ticker."""
        with self._realtime_lock:
            return self._latest_book_ticker.copy()

    def update_depth(self, data: Dict[str, Any]): # Renommé pour clarté
        """Met à jour le snapshot de profondeur."""
        with self._realtime_lock:
            if 'bids' in data: self._latest_depth_snapshot['bids'] = data['bids']
            if 'asks' in data: self._latest_depth_snapshot['asks'] = data['asks']
            if 'lastUpdateId' in data: self._latest_depth_snapshot['lastUpdateId'] = data['lastUpdateId']

    def get_depth(self) -> Dict[str, Any]: # Renommé pour clarté
        """Retourne une copie profonde du snapshot de profondeur."""
        with self._realtime_lock:
            return {
                'bids': [bid[:] for bid in self._latest_depth_snapshot.get('bids', [])],
                'asks': [ask[:] for ask in self._latest_depth_snapshot.get('asks', [])],
                'lastUpdateId': self._latest_depth_snapshot.get('lastUpdateId', 0)
            }

    def append_agg_trade(self, trade: Dict[str, Any]):
        """Ajoute un trade agrégé récent."""
        with self._realtime_lock:
            self._latest_agg_trades.append(trade)

    def get_agg_trades(self) -> List[Dict[str, Any]]:
        """Retourne une copie des trades agrégés récents."""
        with self._realtime_lock:
            return list(self._latest_agg_trades)

    def clear_realtime_data(self):
        """Réinitialise les données marché temps réel."""
        with self._realtime_lock:
            self._latest_book_ticker.clear()
            self._latest_depth_snapshot = {'bids': [], 'asks': [], 'lastUpdateId': 0}
            self._latest_agg_trades.clear()
            self._symbol_info_cache = None # Vider aussi le cache symbol_info
            logger.info("StateManager: Real-time market data and symbol_info cache cleared.")

    # --- Symbol Info Cache ---
    def update_symbol_info(self, symbol_info: Dict[str, Any]):
        """Met à jour le cache symbol_info."""
        with self._realtime_lock: # Utiliser le verrou temps réel pour le cache aussi
            self._symbol_info_cache = symbol_info
            logger.debug("StateManager: Symbol info cache updated.")

    def get_symbol_info(self) -> Optional[Dict[str, Any]]:
        """Retourne une copie du cache symbol_info."""
        with self._realtime_lock:
            return self._symbol_info_cache.copy() if self._symbol_info_cache else None

    # --- Persistance ---

    def save_persistent_data(self) -> bool:
        """Sauvegarde l'état pertinent (position, historique) dans un fichier JSON."""
        # Cette fonction est appelée sous _config_state_lock
        state_to_save = {
            "in_position": self._bot_state.get("in_position", False),
            "entry_details": self._bot_state.get("entry_details", None),
        }
        history_to_save = list(self._bot_state.get("order_history", []))
        data_to_save = {"state": state_to_save, "history": history_to_save}

        try:
            with open(DATA_FILENAME, 'w') as f:
                json.dump(data_to_save, f, indent=4, default=str)
            # logger.debug(f"StateManager: Persistent data saved to {DATA_FILENAME}") # Verbeux
            return True
        except IOError as e:
            logger.error(f"StateManager: IO Error saving {DATA_FILENAME}: {e}")
            return False
        except Exception as e:
            logger.exception(f"StateManager: Error saving persistent data: {e}")
            return False

    def _load_persistent_data(self):
        """Charge l'état et l'historique depuis le fichier JSON à l'initialisation."""
        if not os.path.exists(DATA_FILENAME):
            logger.info(f"StateManager: Persistence file {DATA_FILENAME} not found.")
            return

        try:
            with open(DATA_FILENAME, 'r') as f:
                loaded_data = json.load(f)
            logger.info(f"StateManager: Data loaded from {DATA_FILENAME}")

            if isinstance(loaded_data, dict) and "state" in loaded_data and "history" in loaded_data:
                 state_data = loaded_data.get("state", {})
                 history_data = loaded_data.get("history", [])

                 with self._config_state_lock:
                     self._bot_state["in_position"] = state_data.get("in_position", False)
                     loaded_entry_details = state_data.get("entry_details")

                     if self._bot_state["in_position"] and isinstance(loaded_entry_details, dict):
                         try:
                             loaded_entry_details["avg_price"] = float(loaded_entry_details.get("avg_price", 0.0))
                             loaded_entry_details["quantity"] = float(loaded_entry_details.get("quantity", 0.0))
                             loaded_entry_details["timestamp"] = int(loaded_entry_details.get("timestamp", 0))
                             self._bot_state["entry_details"] = loaded_entry_details
                         except (ValueError, TypeError, InvalidOperation) as e:
                              logger.error(f"StateManager: Error converting loaded entry_details: {e}. Resetting position.")
                              self._bot_state["in_position"] = False
                              self._bot_state["entry_details"] = None
                     elif self._bot_state["in_position"]:
                         logger.warning("StateManager: In position state loaded, but entry_details missing/invalid. Resetting position.")
                         self._bot_state["in_position"] = False
                         self._bot_state["entry_details"] = None
                     else:
                          self._bot_state["entry_details"] = None

                     restored_history = []
                     for order in history_data:
                         if isinstance(order, dict) and 'orderId' in order:
                             try:
                                 order['timestamp'] = int(order.get('timestamp', 0))
                                 perf_pct_str = order.get('performance_pct')
                                 order['performance_pct'] = float(perf_pct_str) if perf_pct_str is not None else None
                                 restored_history.append(order)
                             except (ValueError, TypeError, InvalidOperation) as e:
                                  logger.warning(f"StateManager: Error converting fields for order {order.get('orderId')} in history: {e}")
                                  restored_history.append(order)
                         else:
                             logger.warning(f"StateManager: Invalid order format in history ignored: {order}")

                     self._bot_state["order_history"] = restored_history
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
            logger.exception(f"StateManager: Unexpected error loading persistent data: {e}")

        # Vérification finale de cohérence
        with self._config_state_lock:
            if self._bot_state["in_position"] and not self._bot_state["entry_details"]:
                logger.warning("StateManager: Post-load check failed ('in_position' True, 'entry_details' missing). Resetting.")
                self._bot_state["in_position"] = False

# --- Instanciation Singleton ---
state_manager = StateManager()

# --- Exports ---
__all__ = ['state_manager', 'StateManager', 'DATA_FILENAME']
