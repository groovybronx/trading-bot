# /Users/davidmichels/Desktop/trading-bot/backend/config_manager.py
import logging
import os
import dotenv
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, Optional, Tuple

# --- MODIFIÉ: Supprimer import websocket_client ---
# from binance.websocket import websocket_client as BinanceClient

import config

dotenv.load_dotenv()
logger = logging.getLogger()

SYMBOL = getattr(config, 'SYMBOL', 'BTCUSDT')
VALID_TIMEFRAMES = ['1s', '1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']

# --- MODIFIÉ: Supprimer TIMEFRAME_CONSTANT_MAP ---
# TIMEFRAME_CONSTANT_MAP = { ... }

class ConfigManager:
    def __init__(self):
        logger.debug("ConfigManager: Début __init__")
        self._config: Dict[str, Any] = self._load_initial_config()
        self._validate_initial_config()
        config_log = {k: v for k, v in self._config.items() if k not in ["BINANCE_API_KEY", "BINANCE_API_SECRET"]}
        logger.info(f"ConfigManager initialisé avec (hors clés API): {config_log}")

    def _load_initial_config(self) -> Dict[str, Any]:
        logger.debug("ConfigManager: Début _load_initial_config")
        config_dict = {
            "STRATEGY_TYPE": getattr(config, 'STRATEGY_TYPE', 'SWING'),
            "TIMEFRAME_STR": getattr(config, 'TIMEFRAME', '1m'),
            "RISK_PER_TRADE": getattr(config, 'RISK_PER_TRADE', 0.01),
            "CAPITAL_ALLOCATION": getattr(config, 'CAPITAL_ALLOCATION', 1.0),
            "STOP_LOSS_PERCENTAGE": getattr(config, 'STOP_LOSS_PERCENTAGE', 0.02),
            "TAKE_PROFIT_PERCENTAGE": getattr(config, 'TAKE_PROFIT_PERCENTAGE', 0.05),
            "SCALPING_ORDER_TYPE": getattr(config, 'SCALPING_ORDER_TYPE', 'MARKET'),
            "SCALPING_LIMIT_TIF": getattr(config, 'SCALPING_LIMIT_TIF', 'GTC'),
            "SCALPING_LIMIT_ORDER_TIMEOUT_MS": getattr(config, 'SCALPING_LIMIT_ORDER_TIMEOUT_MS', 5000),
            "SCALPING_DEPTH_LEVELS": getattr(config, 'SCALPING_DEPTH_LEVELS', 5),
            "SCALPING_DEPTH_SPEED": getattr(config, 'SCALPING_DEPTH_SPEED', '100ms'),
            "SCALPING_SPREAD_THRESHOLD": getattr(config, 'SCALPING_SPREAD_THRESHOLD', 0.0001),
            "SCALPING_IMBALANCE_THRESHOLD": getattr(config, 'SCALPING_IMBALANCE_THRESHOLD', 1.5),
            "SCALPING_MIN_TRADE_VOLUME": getattr(config, 'SCALPING_MIN_TRADE_VOLUME', 0.1),
            "EMA_SHORT_PERIOD": getattr(config, 'EMA_SHORT_PERIOD', 9),
            "EMA_LONG_PERIOD": getattr(config, 'EMA_LONG_PERIOD', 21),
            "EMA_FILTER_PERIOD": getattr(config, 'EMA_FILTER_PERIOD', 50),
            "RSI_PERIOD": getattr(config, 'RSI_PERIOD', 14),
            "RSI_OVERBOUGHT": getattr(config, 'RSI_OVERBOUGHT', 75),
            "RSI_OVERSOLD": getattr(config, 'RSI_OVERSOLD', 25),
            "VOLUME_AVG_PERIOD": getattr(config, 'VOLUME_AVG_PERIOD', 20),
            "USE_EMA_FILTER": getattr(config, 'USE_EMA_FILTER', True),
            "USE_VOLUME_CONFIRMATION": getattr(config, 'USE_VOLUME_CONFIRMATION', False),
            "SYMBOL": getattr(config, 'SYMBOL', 'BTCUSDT'),
            "USE_TESTNET": getattr(config, 'USE_TESTNET', True),
            "BINANCE_API_KEY": os.getenv('ENV_API_KEY', 'YOUR_API_KEY_PLACEHOLDER'),
            "BINANCE_API_SECRET": os.getenv('ENV_API_SECRET', 'YOUR_SECRET_KEY_PLACEHOLDER'),
        }
        loaded_key = config_dict.get("BINANCE_API_KEY", "NOT_FOUND")
        logger.debug(f"ConfigManager._load_initial_config: Clé chargée via os.getenv = '{loaded_key[:5]}...'")
        return config_dict

    def _validate_initial_config(self):
        validated_params, error_msg, restart_needed = self.validate_config(self._config)
        if error_msg:
            logger.error(f"Erreur config initiale: {error_msg}. Correction ou arrêt nécessaire.")
        else:
            self._config = validated_params
            logger.info("Configuration initiale validée.")
        if self._config["TIMEFRAME_STR"] not in VALID_TIMEFRAMES:
            logger.warning(f"Timeframe initial '{self._config['TIMEFRAME_STR']}' invalide. Utilisation '1m'.")
            self._config["TIMEFRAME_STR"] = '1m'

    def get_config(self) -> Dict[str, Any]:
        return self._config.copy()

    def get_value(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def update_config(self, new_params: Dict[str, Any]) -> Tuple[bool, str, bool]:
        validated_params, error_message, restart_recommended = self.validate_config(new_params)
        if error_message:
            logger.error(f"Échec MAJ config: {error_message}")
            return False, error_message, False
        else:
            self._config.update(validated_params)
            logger.info(f"Config MAJ avec: {validated_params}")
            message = "Paramètres mis à jour."
            if restart_recommended:
                message += " Redémarrage bot conseillé (stratégie/timeframe/streams)."
            return True, message, restart_recommended

    def validate_config(self, params_to_validate: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str], bool]:
        current_config = self.get_config()
        validated_params = {}
        restart_recommended = False
        try:
            new_tf = str(params_to_validate.get("TIMEFRAME_STR", current_config["TIMEFRAME_STR"]))
            if new_tf not in VALID_TIMEFRAMES: raise ValueError(f"TIMEFRAME_STR invalide: {new_tf}")
            validated_params["TIMEFRAME_STR"] = new_tf
            if new_tf != current_config["TIMEFRAME_STR"]: restart_recommended = True

            validated_params["RISK_PER_TRADE"] = float(params_to_validate.get("RISK_PER_TRADE", current_config["RISK_PER_TRADE"]))
            if not (0 < validated_params["RISK_PER_TRADE"] < 1): raise ValueError("RISK_PER_TRADE > 0 et < 1")
            validated_params["CAPITAL_ALLOCATION"] = float(params_to_validate.get("CAPITAL_ALLOCATION", current_config["CAPITAL_ALLOCATION"]))
            if not (0 < validated_params["CAPITAL_ALLOCATION"] <= 1): raise ValueError("CAPITAL_ALLOCATION > 0 et <= 1")

            sl_pct_in = params_to_validate.get("STOP_LOSS_PERCENTAGE", current_config.get("STOP_LOSS_PERCENTAGE"))
            if sl_pct_in is not None:
                sl_pct = float(sl_pct_in)
                if not (0 < sl_pct < 1): raise ValueError("STOP_LOSS_PERCENTAGE > 0 et < 1")
                validated_params["STOP_LOSS_PERCENTAGE"] = sl_pct
            else: validated_params["STOP_LOSS_PERCENTAGE"] = None

            tp_pct_in = params_to_validate.get("TAKE_PROFIT_PERCENTAGE", current_config.get("TAKE_PROFIT_PERCENTAGE"))
            if tp_pct_in is not None:
                tp_pct = float(tp_pct_in)
                if not (0 < tp_pct < 1): raise ValueError("TAKE_PROFIT_PERCENTAGE > 0 et < 1")
                validated_params["TAKE_PROFIT_PERCENTAGE"] = tp_pct
            else: validated_params["TAKE_PROFIT_PERCENTAGE"] = None

            new_strategy_type = str(params_to_validate.get("STRATEGY_TYPE", current_config["STRATEGY_TYPE"])).upper()
            if new_strategy_type not in ['SCALPING', 'SWING']: raise ValueError("STRATEGY_TYPE: 'SCALPING' ou 'SWING'.")
            validated_params["STRATEGY_TYPE"] = new_strategy_type
            if new_strategy_type != current_config["STRATEGY_TYPE"]: restart_recommended = True

            validated_params["SCALPING_ORDER_TYPE"] = str(params_to_validate.get("SCALPING_ORDER_TYPE", current_config["SCALPING_ORDER_TYPE"])).upper()
            if validated_params["SCALPING_ORDER_TYPE"] not in ['MARKET', 'LIMIT']: raise ValueError("SCALPING_ORDER_TYPE: 'MARKET' ou 'LIMIT'.")
            validated_params["SCALPING_LIMIT_TIF"] = str(params_to_validate.get("SCALPING_LIMIT_TIF", current_config["SCALPING_LIMIT_TIF"])).upper()
            if validated_params["SCALPING_ORDER_TYPE"] == 'LIMIT' and validated_params["SCALPING_LIMIT_TIF"] not in ['GTC', 'IOC', 'FOK']: raise ValueError("SCALPING_LIMIT_TIF: 'GTC', 'IOC', ou 'FOK' pour LIMIT.")
            validated_params["SCALPING_LIMIT_ORDER_TIMEOUT_MS"] = int(params_to_validate.get("SCALPING_LIMIT_ORDER_TIMEOUT_MS", current_config["SCALPING_LIMIT_ORDER_TIMEOUT_MS"]))
            if validated_params["SCALPING_LIMIT_ORDER_TIMEOUT_MS"] <= 0: raise ValueError("SCALPING_LIMIT_ORDER_TIMEOUT_MS > 0.")
            validated_params["SCALPING_DEPTH_LEVELS"] = int(params_to_validate.get("SCALPING_DEPTH_LEVELS", current_config["SCALPING_DEPTH_LEVELS"]))
            if validated_params["SCALPING_DEPTH_LEVELS"] not in [5, 10, 20]: raise ValueError("SCALPING_DEPTH_LEVELS: 5, 10, ou 20.")
            if validated_params["SCALPING_DEPTH_LEVELS"] != current_config["SCALPING_DEPTH_LEVELS"]: restart_recommended = True
            validated_params["SCALPING_DEPTH_SPEED"] = str(params_to_validate.get("SCALPING_DEPTH_SPEED", current_config["SCALPING_DEPTH_SPEED"])).lower()
            if validated_params["SCALPING_DEPTH_SPEED"] not in ['100ms', '1000ms']: raise ValueError("SCALPING_DEPTH_SPEED: '100ms' ou '1000ms'.")
            if validated_params["SCALPING_DEPTH_SPEED"] != current_config["SCALPING_DEPTH_SPEED"]: restart_recommended = True
            try: validated_params["SCALPING_SPREAD_THRESHOLD"] = float(Decimal(str(params_to_validate.get("SCALPING_SPREAD_THRESHOLD", current_config["SCALPING_SPREAD_THRESHOLD"]))))
            except: raise ValueError("SCALPING_SPREAD_THRESHOLD doit être nombre >= 0.")
            if validated_params["SCALPING_SPREAD_THRESHOLD"] < 0: raise ValueError("SCALPING_SPREAD_THRESHOLD >= 0.")
            try: validated_params["SCALPING_IMBALANCE_THRESHOLD"] = float(Decimal(str(params_to_validate.get("SCALPING_IMBALANCE_THRESHOLD", current_config["SCALPING_IMBALANCE_THRESHOLD"]))))
            except: raise ValueError("SCALPING_IMBALANCE_THRESHOLD doit être nombre > 0.")
            if validated_params["SCALPING_IMBALANCE_THRESHOLD"] <= 0: raise ValueError("SCALPING_IMBALANCE_THRESHOLD > 0.")
            try: validated_params["SCALPING_MIN_TRADE_VOLUME"] = float(Decimal(str(params_to_validate.get("SCALPING_MIN_TRADE_VOLUME", current_config["SCALPING_MIN_TRADE_VOLUME"]))))
            except: raise ValueError("SCALPING_MIN_TRADE_VOLUME doit être nombre >= 0.")
            if validated_params["SCALPING_MIN_TRADE_VOLUME"] < 0: raise ValueError("SCALPING_MIN_TRADE_VOLUME >= 0.")

            validated_params["EMA_SHORT_PERIOD"] = int(params_to_validate.get("EMA_SHORT_PERIOD", current_config["EMA_SHORT_PERIOD"]))
            if validated_params["EMA_SHORT_PERIOD"] <= 0: raise ValueError("EMA_SHORT_PERIOD > 0")
            validated_params["EMA_LONG_PERIOD"] = int(params_to_validate.get("EMA_LONG_PERIOD", current_config["EMA_LONG_PERIOD"]))
            if validated_params["EMA_LONG_PERIOD"] <= validated_params["EMA_SHORT_PERIOD"]: raise ValueError("EMA_LONG_PERIOD > EMA_SHORT_PERIOD")
            validated_params["EMA_FILTER_PERIOD"] = int(params_to_validate.get("EMA_FILTER_PERIOD", current_config["EMA_FILTER_PERIOD"]))
            if validated_params["EMA_FILTER_PERIOD"] <= 0: raise ValueError("EMA_FILTER_PERIOD > 0")
            validated_params["RSI_PERIOD"] = int(params_to_validate.get("RSI_PERIOD", current_config["RSI_PERIOD"]))
            if validated_params["RSI_PERIOD"] <= 1: raise ValueError("RSI_PERIOD > 1")
            validated_params["RSI_OVERBOUGHT"] = int(params_to_validate.get("RSI_OVERBOUGHT", current_config["RSI_OVERBOUGHT"]))
            if not (50 < validated_params["RSI_OVERBOUGHT"] <= 100): raise ValueError("RSI_OB > 50 et <= 100")
            validated_params["RSI_OVERSOLD"] = int(params_to_validate.get("RSI_OVERSOLD", current_config["RSI_OVERSOLD"]))
            if not (0 <= validated_params["RSI_OVERSOLD"] < 50): raise ValueError("RSI_OS >= 0 et < 50")
            if validated_params["RSI_OVERSOLD"] >= validated_params["RSI_OVERBOUGHT"]: raise ValueError("RSI_OS < RSI_OB")
            validated_params["VOLUME_AVG_PERIOD"] = int(params_to_validate.get("VOLUME_AVG_PERIOD", current_config["VOLUME_AVG_PERIOD"]))
            if validated_params["VOLUME_AVG_PERIOD"] <= 0: raise ValueError("VOL_AVG > 0")
            validated_params["USE_EMA_FILTER"] = bool(params_to_validate.get("USE_EMA_FILTER", current_config["USE_EMA_FILTER"]))
            validated_params["USE_VOLUME_CONFIRMATION"] = bool(params_to_validate.get("USE_VOLUME_CONFIRMATION", current_config["USE_VOLUME_CONFIRMATION"]))

            return validated_params, None, restart_recommended
        except (ValueError, TypeError, InvalidOperation) as e:
            error_message = f"Paramètres invalides: {e}"
            logger.error(f"Validation Config: {error_message}")
            return {}, error_message, False

config_manager = ConfigManager()

__all__ = [
    'SYMBOL', 'VALID_TIMEFRAMES', # Supprimer TIMEFRAME_CONSTANT_MAP
    'config_manager',
    'ConfigManager'
]
