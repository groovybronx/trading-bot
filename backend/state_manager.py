# /Users/davidmichels/Desktop/trading-bot/backend/state_manager.py
import threading
import queue
import collections
import json
import os
import logging
from typing import Optional, Dict, Any

# Importer depuis config_manager pour les valeurs initiales
from config_manager import bot_config, SYMBOL

logger = logging.getLogger()

# --- Verrous Partagés ---
# Lock pour protéger bot_config ET bot_state (simplification, pourrait être séparé si contention)
config_lock = threading.Lock()
# Lock spécifique pour l'historique des klines
kline_history_lock = threading.Lock()

# --- État du Bot ---
# Calcul initial de la limite de l'historique kline
_initial_periods = [bot_config["EMA_LONG_PERIOD"], bot_config["RSI_PERIOD"]]
if bot_config["USE_EMA_FILTER"]: _initial_periods.append(bot_config["EMA_FILTER_PERIOD"])
if bot_config["USE_VOLUME_CONFIRMATION"]: _initial_periods.append(bot_config["VOLUME_AVG_PERIOD"])
INITIAL_REQUIRED_LIMIT = max(_initial_periods) + 5

# Historique des klines (deque thread-safe implicitement via kline_history_lock)
kline_history = collections.deque(maxlen=INITIAL_REQUIRED_LIMIT)

# Queue pour le dernier prix ticker (thread-safe par nature)
latest_price_queue = queue.Queue(maxsize=1)

# Dictionnaire principal de l'état du bot
bot_state = {
    "status": "Arrêté",
    "in_position": False,
    "available_balance": 0.0,
    "symbol_quantity": 0.0,
    "base_asset": "",
    "quote_asset": "USDT", # Default, sera mis à jour
    "symbol": SYMBOL,
    "timeframe": bot_config["TIMEFRAME_STR"],
    "required_klines": INITIAL_REQUIRED_LIMIT,
    "entry_details": None, # { "order_id": ..., "avg_price": ..., "quantity": ..., "timestamp": ... }
    "order_history": [], # Liste des ordres simplifiés
    "max_history_length": 100, # Max ordres à garder en mémoire

    # Gestion des threads et WebSockets
    "main_thread": None, # Référence au thread run_bot
    "stop_main_requested": False, # Flag pour arrêter run_bot
    "websocket_manager": None, # Instance de ThreadedWebsocketManager
    "ticker_websocket_stream_name": None,
    "kline_websocket_stream_name": None,

    # Gestion User Data Stream
    "listen_key": None,
    "user_data_stream_name": None,
    "keepalive_thread": None,
    "stop_keepalive_requested": False,
}

# --- Persistance ---
DATA_FILENAME = "bot_data.json"

def save_data():
    """Sauvegarde l'état pertinent (position, historique) dans un fichier JSON."""
    # Utiliser config_lock car on lit bot_state
    with config_lock:
        # Copier uniquement les données nécessaires pour éviter les problèmes de sérialisation
        state_to_save = {
            "in_position": bot_state.get("in_position", False),
            "entry_details": bot_state.get("entry_details", None)
        }
        # Copier l'historique pour éviter les modifications pendant l'écriture
        history_to_save = list(bot_state.get("order_history", []))

    data_to_save = {"state": state_to_save, "history": history_to_save}
    try:
        with open(DATA_FILENAME, 'w') as f:
            json.dump(data_to_save, f, indent=4)
        logger.debug(f"Données sauvegardées dans {DATA_FILENAME}")
        return True
    except IOError as e:
        logger.error(f"Erreur IO lors de la sauvegarde dans {DATA_FILENAME}: {e}")
        return False
    except Exception as e:
        logger.exception(f"Erreur inattendue lors de la sauvegarde des données: {e}")
        return False

def load_data() -> Optional[Dict[str, Any]]:
    """Charge l'état et l'historique depuis le fichier JSON."""
    if not os.path.exists(DATA_FILENAME):
        logger.info(f"Fichier de données {DATA_FILENAME} non trouvé. Initialisation à vide.")
        return None
    try:
        with open(DATA_FILENAME, 'r') as f:
            loaded_data = json.load(f)
        logger.info(f"Données chargées depuis {DATA_FILENAME}")
        # Validation simple
        if isinstance(loaded_data, dict) and "state" in loaded_data and "history" in loaded_data:
             return loaded_data
        else:
             logger.error(f"Format de données invalide dans {DATA_FILENAME}.")
             return None
    except (IOError, json.JSONDecodeError) as e:
        logger.error(f"Erreur lors du chargement/décodage de {DATA_FILENAME}: {e}.")
        return None
    except Exception as e:
        logger.exception(f"Erreur inattendue lors du chargement des données: {e}")
        return None

# Exporter les variables et fonctions nécessaires
__all__ = [
    'config_lock', 'kline_history_lock', 'kline_history', 'latest_price_queue',
    'bot_state', 'save_data', 'load_data', 'DATA_FILENAME'
]
