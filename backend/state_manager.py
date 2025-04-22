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
from websocket_utils import broadcast_order_history_update, broadcast_state_update

logger = logging.getLogger(__name__)

DATA_FILENAME = "bot_data.json"


class StateManager:
    def __init__(self):
        self._config_state_lock = threading.Lock()
        self._kline_lock = threading.Lock()
        self._realtime_lock = threading.Lock()

        initial_config = config_manager.get_config()
        self._required_klines = self._calculate_required_klines(initial_config)
        self._pending_orders_lock = threading.Lock()
        

        # --- Structures de Données ---
        self._kline_history: Deque[List[Any]] = collections.deque(maxlen=self._required_klines)
        self._latest_book_ticker: Dict[str, Any] = {}
        self._latest_depth_snapshot: Dict[str, Any] = {"bids": [], "asks": [], "lastUpdateId": 0}
        self._latest_agg_trades: Deque[Dict[str, Any]] = collections.deque(maxlen=50)
        self._symbol_info_cache: Optional[Dict[str, Any]] = None
        self._pending_order_details: Dict[str, Dict[str, Any]] = {}

        # État principal du bot
        self._bot_state: Dict[str, Any] = {
            "status": "Arrêté",
            "in_position": False,
            "available_balance": Decimal("0.0"), # Utiliser Decimal
            "symbol_quantity": Decimal("0.0"),   # Utiliser Decimal
            "base_asset": "",
            "quote_asset": "USDT",
            "symbol": initial_config.get("SYMBOL", SYMBOL),
            "timeframe": initial_config.get("TIMEFRAME", "1m"), # Utiliser TIMEFRAME
            "entry_details": None, # { order_id, avg_price, quantity, timestamp, side, sl_price, tp1_price, tp2_price, highest_price, lowest_price }
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

        self._load_persistent_data()
        logger.info("StateManager initialized.")

    def _calculate_required_klines(self, config_dict: Dict[str, Any]) -> int:
        """Calcule le nombre de klines nécessaires basé sur la stratégie."""
        strategy_type = config_dict.get("STRATEGY_TYPE")

        if strategy_type == "SCALPING": return 1 # Pas besoin d'historique kline

        # Minimum requis pour les indicateurs utilisés
        min_req = 2 # Pour avoir prev_row

        if strategy_type == "SCALPING2":
            periods = [
                config_dict.get("SUPERTREND_ATR_PERIOD", 3) + 1, # ST a besoin de +1
                config_dict.get("SCALPING_RSI_PERIOD", 7),
                config_dict.get("STOCH_K_PERIOD", 14) + config_dict.get("STOCH_D_PERIOD", 3), # Approx
                config_dict.get("BB_PERIOD", 20),
                config_dict.get("VOLUME_MA_PERIOD", 20),
            ]
            min_req = max(periods) + 5 # Ajouter buffer

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

        # Assurer un minimum absolu pour pandas_ta
        return max(min_req, 25)


    # --- Accesseurs/Mutateurs État Principal (Thread-Safe) ---

    def get_state(self, key: Optional[str] = None) -> Any:
        """Retourne une copie d'une valeur spécifique ou de l'état complet."""
        with self._config_state_lock:
            if key:
                value = self._bot_state.get(key)
                # Gérer copies pour types mutables (dict, list, deque)
                if isinstance(value, dict): return value.copy()
                if isinstance(value, list): return value[:]
                if isinstance(value, collections.deque): return collections.deque(list(value), maxlen=value.maxlen)
                # Decimal est immutable, pas besoin de copier
                return value
            else:
                # Copie simple suffit généralement, car les méthodes de MAJ utilisent le verrou
                return self._bot_state.copy()

    def update_state(self, updates: Dict[str, Any]):
        """Met à jour l'état du bot de manière thread-safe."""
        with self._config_state_lock:
            # Log changements importants
            if "status" in updates and self._bot_state.get("status") != updates["status"]:
                logger.info(f"StateManager: Status changing -> {updates['status']}")
            if "in_position" in updates and self._bot_state.get("in_position") != updates["in_position"]:
                logger.info(f"StateManager: Position changing -> {updates['in_position']}")
                # Si on sort de position, nettoyer les détails spécifiques à la position
                if not updates["in_position"]:
                     if self._bot_state.get("entry_details"):
                          logger.debug("StateManager: Clearing entry_details on exiting position.")
                          self._bot_state["entry_details"] = None # Assurer nettoyage
                     # Nettoyer aussi les clés temporaires SL/TP si elles existent
                     for temp_key in ["_temp_entry_sl", "_temp_entry_tp1", "_temp_entry_tp2"]:
                          if temp_key in self._bot_state:
                               self._bot_state[temp_key] = None

            # --- AJOUT: Mise à jour highest/lowest price si en position ---
            # Utiliser le ticker passé dans 'updates' s'il existe
            ticker_for_trailing = updates.get("latest_book_ticker")
            if self._bot_state.get("in_position") and ticker_for_trailing:
                 current_price_str = ticker_for_trailing.get("c") # Utiliser le last price du ticker
                 entry_details = self._bot_state.get("entry_details")
                 if current_price_str and entry_details:
                      try:
                           current_price = Decimal(current_price_str)
                           # Utiliser Decimal('-Infinity') et Decimal('Infinity') pour initialisation sûre
                           if current_price > entry_details.get("highest_price", Decimal("-Infinity")):
                                entry_details["highest_price"] = current_price
                                # logger.debug(f"Updated highest_price: {current_price}") # Verbeux
                           if current_price < entry_details.get("lowest_price", Decimal("Infinity")):
                                entry_details["lowest_price"] = current_price
                                # logger.debug(f"Updated lowest_price: {current_price}") # Verbeux
                      except (InvalidOperation, TypeError):
                           logger.warning(f"Failed to update highest/lowest price from ticker: {current_price_str}")
                 # Supprimer le ticker des updates pour ne pas le stocker dans _bot_state
                 if "latest_book_ticker" in updates:
                      del updates["latest_book_ticker"]
            # --- FIN AJOUT ---

            self._bot_state.update(updates)


    # --- Gestion Historique Ordres ---

    def _format_order_for_history(self, order_details: Dict[str, Any]) -> Dict[str, Any]:
        """Formate un ordre brut (REST ou WS) pour l'historique."""
        order_id = str(order_details.get("orderId") or order_details.get("i", "N/A"))
        side = order_details.get("side") or order_details.get("S")
        status = order_details.get("status") or order_details.get("X")
        timestamp = order_details.get("updateTime") or order_details.get("time") or order_details.get("T") or int(time.time() * 1000)

        # Tentative de calcul de performance si SELL FILLED
        performance_pct = None
        # Accès thread-safe à entry_details via get_state (crée une copie)
        entry_details_hist = self.get_state("entry_details")
        if side == "SELL" and status == "FILLED" and entry_details_hist:
             try:
                  entry_price = Decimal(str(entry_details_hist.get("avg_price", "0")))
                  exec_qty_sell = Decimal(str(order_details.get("executedQty") or order_details.get("z", "0")))
                  quote_qty_sell = Decimal(str(order_details.get("cummulativeQuoteQty") or order_details.get("Z", "0")))
                  if entry_price > 0 and exec_qty_sell > 0:
                       exit_price = quote_qty_sell / exec_qty_sell
                       perf = (exit_price - entry_price) / entry_price
                       performance_pct = f"{perf:.4%}" # Formater en string %
             except (ValueError, TypeError, ZeroDivisionError, InvalidOperation):
                  logger.warning(f"Failed to calculate performance for order {order_id}", exc_info=True)

        simplified_order = {
            "timestamp": int(timestamp),
            "orderId": order_id,
            "symbol": order_details.get("symbol") or order_details.get("s"),
            "side": side,
            "type": order_details.get("orderType") or order_details.get("type") or order_details.get("o"),
            "origQty": str(order_details.get("origQty") or order_details.get("q", "0")),
            "executedQty": str(order_details.get("executedQty") or order_details.get("z", "0")),
            "cummulativeQuoteQty": str(order_details.get("cummulativeQuoteQty") or order_details.get("Z", "0")),
            "price": str(order_details.get("price") or order_details.get("p", "0")),
            "status": status,
            "performance_pct": performance_pct, # Stocker comme string ou None
        }
        return simplified_order

    def replace_order_history(self, new_raw_history: List[Dict[str, Any]]):
        """Remplace l'historique interne avec les données API formatées et diffuse."""
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
                simplified_new_history.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
                max_len = self._bot_state.get("max_history_length", 100)
                self._bot_state["order_history"] = simplified_new_history[:max_len]
                did_save = self.save_persistent_data() # Sauvegarder sous verrou
        except Exception as e:
            logger.error(f"Error during history replacement/saving: {e}", exc_info=True)
            return

        if did_save:
            broadcast_order_history_update() # Diffuser hors verrou si sauvegarde OK

    def add_or_update_order_history(self, order_data: Dict[str, Any]):
        """Ajoute ou met à jour un ordre dans l'historique."""
        order_id_to_update = str(order_data.get("orderId") or order_data.get("i", "N/A"))
        if order_id_to_update == "N/A":
            logger.warning("add_or_update_order_history: Order ID manquant.")
            return

        updated = False
        # Formater l'ordre AVANT d'acquérir le verrou
        formatted_order = self._format_order_for_history(order_data)

        try:
            with self._config_state_lock:
                history = self._bot_state["order_history"]
                found_index = next((i for i, order in enumerate(history) if order.get("orderId") == order_id_to_update), -1)

                if found_index != -1:
                    history[found_index] = formatted_order
                    # logger.debug(f"Order {order_id_to_update} updated in history.") # Verbeux
                else:
                    history.insert(0, formatted_order) # Ajouter au début
                    # logger.debug(f"Order {order_id_to_update} added to history.") # Verbeux

                # Trier et tronquer
                history.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
                max_len = self._bot_state.get("max_history_length", 100)
                if len(history) > max_len:
                    self._bot_state["order_history"] = history[:max_len]

                updated = True
                self.save_persistent_data() # Sauvegarder après modif

        except Exception as e:
            logger.error(f"Error updating history for order {order_id_to_update}: {e}", exc_info=True)
            return

        if updated:
            broadcast_order_history_update() # Diffuser hors verrou

    def get_order_history(self) -> List[Dict[str, Any]]:
        """Retourne une copie triée de l'historique des ordres."""
        with self._config_state_lock:
            # Retourner une copie pour éviter modification externe
            return list(self._bot_state.get("order_history", []))

    # --- Gestion Configuration ---

    def get_config_value(self, key: str, default: Any = None) -> Any:
        """Récupère une valeur de config (format interne) via ConfigManager."""
        return config_manager.get_value(key, default)

    def get_full_config(self) -> Dict[str, Any]:
        """Récupère la config complète (format interne) via ConfigManager."""
        return config_manager.get_config()

    def update_config_values(self, new_params_input: Dict[str, Any]) -> Tuple[bool, str, bool]:
        """Met à jour la config via ConfigManager et ajuste l'état interne si besoin."""
        success, message, restart_recommended = config_manager.update_config(new_params_input)
        if success:
            updated_config = config_manager.get_config() # Récupérer la nouvelle config interne
            state_updates = {}
            # Mettre à jour timeframe dans l'état si changé
            new_tf = updated_config.get("TIMEFRAME") # Utiliser TIMEFRAME
            if new_tf and self._bot_state.get("timeframe") != new_tf:
                state_updates["timeframe"] = new_tf
                logger.info(f"StateManager: Timeframe updated to {new_tf}.")

            # Recalculer et redimensionner buffer kline si besoin
            new_required_klines = self._calculate_required_klines(updated_config)
            # Appeler resize sous verrou kline
            with self._kline_lock:
                 self.resize_kline_history(new_required_klines)

            if state_updates:
                self.update_state(state_updates) # Appelle _config_state_lock
        return success, message, restart_recommended

    # --- Gestion Historique Klines ---

    def get_kline_history_list(self) -> List[List[Any]]:
        """Retourne une copie de l'historique kline actuel."""
        with self._kline_lock:
            return list(self._kline_history)

    def add_kline(self, kline: List[Any]):
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
            # Assurer que la taille max est correcte avant d'étendre
            current_maxlen = self._kline_history.maxlen
            required_klines = self.get_required_klines() # Recalculer au cas où
            if current_maxlen != required_klines:
                 logger.warning(f"StateManager: Kline history maxlen ({current_maxlen}) differs from required ({required_klines}) during replace. Resizing.")
                 self.resize_kline_history(required_klines) # Redimensionne sous verrou

            self._kline_history.clear()
            self._kline_history.extend(klines) # Ajouter les nouvelles klines
            logger.info(f"StateManager: Kline history replaced ({len(self._kline_history)}/{self._kline_history.maxlen}).")

    def resize_kline_history(self, new_maxlen: int):
        """Redimensionne le deque de l'historique kline (appelé sous _kline_lock)."""
        # Pas besoin de verrou ici car appelé depuis des méthodes déjà verrouillées (_kline_lock)
        if self._kline_history.maxlen != new_maxlen:
            logger.info(f"StateManager: Resizing kline history from {self._kline_history.maxlen} to {new_maxlen}")
            current_data = list(self._kline_history)
            self._kline_history = collections.deque(current_data, maxlen=new_maxlen)

    def get_required_klines(self) -> int:
        """Retourne le nombre de klines requis calculé."""
        # Pas besoin de verrou pour lire la config ici, ConfigManager est thread-safe
        current_config = config_manager.get_config()
        return self._calculate_required_klines(current_config)

    # --- Données Marché Temps Réel ---

    def update_book_ticker(self, data: Dict[str, Any]):
        """Met à jour le dernier book ticker et notifie update_state pour trailing stop."""
        with self._realtime_lock:
            self._latest_book_ticker.update(data)
        # Notifier update_state pour potentiellement mettre à jour highest/lowest price
        # Passer une copie pour éviter modif concurrente du dict data
        self.update_state({"latest_book_ticker": data.copy()})


    def get_book_ticker(self) -> Dict[str, Any]:
        """Retourne une copie du dernier book ticker."""
        with self._realtime_lock:
            return self._latest_book_ticker.copy()

    def update_depth(self, data: Dict[str, Any]):
        """Met à jour le snapshot de profondeur."""
        with self._realtime_lock:
            # Copier les listes pour éviter modif externe
            if "bids" in data: self._latest_depth_snapshot["bids"] = [b[:] for b in data["bids"]]
            if "asks" in data: self._latest_depth_snapshot["asks"] = [a[:] for a in data["asks"]]
            if "lastUpdateId" in data: self._latest_depth_snapshot["lastUpdateId"] = data["lastUpdateId"]

    def get_depth(self) -> Dict[str, Any]:
        """Retourne une copie profonde du snapshot de profondeur."""
        with self._realtime_lock:
            # Assurer une copie profonde
            return {
                "bids": [bid[:] for bid in self._latest_depth_snapshot.get("bids", [])],
                "asks": [ask[:] for ask in self._latest_depth_snapshot.get("asks", [])],
                "lastUpdateId": self._latest_depth_snapshot.get("lastUpdateId", 0),
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
        """Réinitialise les données marché temps réel et cache symbole."""
        with self._realtime_lock:
            self._latest_book_ticker.clear()
            self._latest_depth_snapshot = {"bids": [], "asks": [], "lastUpdateId": 0}
            self._latest_agg_trades.clear()
            self._symbol_info_cache = None
            logger.info("StateManager: Real-time market data and symbol_info cache cleared.")

    # --- Symbol Info Cache ---
    def update_symbol_info(self, symbol_info: Dict[str, Any]):
        """Met à jour le cache symbol_info."""
        with self._realtime_lock:
            self._symbol_info_cache = symbol_info
            logger.debug("StateManager: Symbol info cache updated.")

    def get_symbol_info(self) -> Optional[Dict[str, Any]]:
        """Retourne une copie du cache symbol_info."""
        with self._realtime_lock:
            return self._symbol_info_cache.copy() if self._symbol_info_cache else None
    
       # --- AJOUT: Gestion des détails d'ordre en attente ---
    def store_pending_order_details(self, client_order_id: str, details: Dict[str, Any]):
        """Stocke les détails (ex: SL/TP) pour un ordre en attente."""
        if not client_order_id: return
        with self._pending_orders_lock:
            self._pending_order_details[client_order_id] = details
            # Optionnel: Ajouter un mécanisme de nettoyage pour les IDs très anciens

    def get_and_clear_pending_order_details(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        """Récupère et supprime les détails pour un ordre."""
        if not client_order_id: return None
        with self._pending_orders_lock:
            # Utiliser pop pour récupérer et supprimer atomiquement
            details = self._pending_order_details.pop(client_order_id, None)
            if details:
                 logger.debug(f"Retrieved and cleared pending details for ClientID {client_order_id}")
            else:
                 logger.warning(f"No pending details found for ClientID {client_order_id} on get_and_clear.")
            return details

    def clear_pending_order_details(self, client_order_id: str):
        """Supprime les détails pour un ordre (si échec avant exécution)."""
        if not client_order_id: return
        with self._pending_orders_lock:
            if client_order_id in self._pending_order_details:
                del self._pending_order_details[client_order_id]
                logger.debug(f"Cleared pending details for ClientID {client_order_id} (e.g., due to failure).")
    # --- FIN AJOUT ---

    # --- Persistance ---

    def save_persistent_data(self) -> bool:
        """Sauvegarde l'état pertinent (position, historique) dans un fichier JSON. Appelé sous _config_state_lock."""
        # Pas besoin de verrou ici car déjà sous _config_state_lock
        state_to_save = {
            "in_position": self._bot_state.get("in_position", False),
            # Convertir Decimal en string pour JSON
            "entry_details": {k: str(v) if isinstance(v, Decimal) else v
                              for k, v in self._bot_state.get("entry_details", {}).items()}
                             if self._bot_state.get("entry_details") else None,
        }
        # L'historique est déjà formaté avec des strings pour les nombres
        history_to_save = list(self._bot_state.get("order_history", []))
        # NE PAS SAUVEGARDER les clés temporaires
        data_to_save = {"state": state_to_save, "history": history_to_save}

        try:
            with open(DATA_FILENAME, "w") as f:
                json.dump(data_to_save, f, indent=4)
            # logger.debug(f"StateManager: Persistent data saved.") # Verbeux
            return True
        except (IOError, TypeError) as e: # Ajouter TypeError pour Decimal non converti
            logger.error(f"StateManager: Error saving {DATA_FILENAME}: {e}")
            return False
        except Exception as e:
            logger.exception(f"StateManager: Unexpected error saving persistent data: {e}")
            return False

    def _load_persistent_data(self):
        """Charge l'état et l'historique depuis JSON à l'initialisation."""
        if not os.path.exists(DATA_FILENAME):
            logger.info(f"StateManager: Persistence file {DATA_FILENAME} not found.")
            return

        try:
            with open(DATA_FILENAME, "r") as f:
                loaded_data = json.load(f)
            logger.info(f"StateManager: Data loaded from {DATA_FILENAME}")

            if isinstance(loaded_data, dict) and "state" in loaded_data and "history" in loaded_data:
                state_data = loaded_data.get("state", {})
                history_data = loaded_data.get("history", [])

                with self._config_state_lock:
                    self._bot_state["in_position"] = state_data.get("in_position", False)
                    loaded_entry_details_str = state_data.get("entry_details")

                    # Reconvertir les strings en Decimal pour entry_details
                    if self._bot_state["in_position"] and isinstance(loaded_entry_details_str, dict):
                        try:
                            entry_details_reloaded = {}
                            for key, val_str in loaded_entry_details_str.items():
                                # Clés connues qui doivent être Decimal
                                if key in ["avg_price", "quantity", "sl_price", "tp1_price", "tp2_price", "highest_price", "lowest_price"]:
                                     entry_details_reloaded[key] = Decimal(val_str)
                                elif key == "timestamp":
                                     entry_details_reloaded[key] = int(val_str)
                                else:
                                     entry_details_reloaded[key] = val_str # order_id, side
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
                        self._bot_state["entry_details"] = None # Assurer None si pas en position

                    # Recharger historique (déjà en strings/int/None)
                    restored_history = []
                    for order in history_data:
                        if isinstance(order, dict) and "orderId" in order:
                             # Assurer que timestamp est int
                             try: order["timestamp"] = int(order.get("timestamp", 0))
                             except: order["timestamp"] = 0
                             restored_history.append(order)
                        else: logger.warning(f"StateManager: Invalid order format in history ignored: {order}")

                    self._bot_state["order_history"] = restored_history
                    self._bot_state["order_history"].sort(key=lambda x: x.get("timestamp", 0), reverse=True)
                    max_len = self._bot_state.get("max_history_length", 100)
                    self._bot_state["order_history"] = self._bot_state["order_history"][:max_len]

                    # Assurer que les clés temporaires sont vides au chargement
                    for temp_key in ["_temp_entry_sl", "_temp_entry_tp1", "_temp_entry_tp2"]:
                         self._bot_state[temp_key] = None

                    logger.info(f"StateManager: State (in_position={self._bot_state['in_position']}) and history ({len(self._bot_state['order_history'])} orders) restored.")
            else:
                logger.error(f"StateManager: Invalid format in {DATA_FILENAME}. State not restored.")

        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"StateManager: Error loading/decoding {DATA_FILENAME}: {e}.")
        except Exception as e:
            logger.exception(f"StateManager: Unexpected error loading persistent data: {e}")

        # Vérification finale cohérence (sous verrou)
        with self._config_state_lock:
            if self._bot_state["in_position"] and not self._bot_state["entry_details"]:
                logger.warning("StateManager: Post-load check failed ('in_position' True, 'entry_details' missing). Resetting.")
                self._bot_state["in_position"] = False

    

# --- Instanciation Singleton ---
state_manager = StateManager()

# --- Exports ---
__all__ = ["state_manager", "StateManager", "DATA_FILENAME"]
