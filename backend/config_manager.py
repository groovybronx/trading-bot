# /Users/davidmichels/Desktop/trading-bot/backend/config_manager.py
import logging
import os
import dotenv
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, Optional, Tuple

import config  # Assurez-vous que config.py est importé

dotenv.load_dotenv()
logger = logging.getLogger(__name__)  # Utiliser __name__

SYMBOL = getattr(config, "SYMBOL", "BTCUSDT")
VALID_TIMEFRAMES = [
    "1s",
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "6h",
    "8h",
    "12h",
    "1d",
    "3d",
    "1w",
    "1M",
]


class ConfigManager:
    def __init__(self):
        logger.debug("ConfigManager: Début __init__")
        # 1. Charger les valeurs initiales (supposées en % pour certains) depuis config.py/env
        initial_config_percent = self._load_initial_config()

        # 2. Valider et convertir immédiatement ces valeurs initiales en fractions
        validated_initial_config_fractions, error_msg, _ = (
            self._validate_and_convert_config(initial_config_percent, is_initial=True)
        )

        if error_msg:
            logger.critical(
                f"ERREUR CRITIQUE CONFIG INITIALE: {error_msg}. Vérifiez config.py et .env."
            )
            # Lever une exception pour arrêter le démarrage si la config initiale est invalide
            raise ValueError(f"Erreur configuration initiale: {error_msg}")
        else:
            # 3. Stocker la configuration validée et convertie (fractions)
            self._config: Dict[str, Any] = validated_initial_config_fractions
            logger.info("Configuration initiale validée et convertie en fractions.")

        config_log = {
            k: v
            for k, v in self._config.items()
            if k not in ["BINANCE_API_KEY", "BINANCE_API_SECRET"]
        }
        logger.info(
            f"ConfigManager initialisé avec (fractions, hors clés API): {config_log}"
        )

    def _load_initial_config(self) -> Dict[str, Any]:
        """Charge la configuration depuis config.py et .env.
        Suppose que RISK, ALLOCATION, SL, TP dans config.py sont en POURCENTAGES."""
        logger.debug("ConfigManager: Début _load_initial_config")
        config_dict = {}
        # Charger toutes les clés définies dans config.py
        for key in dir(config):
            if key.isupper():  # Convention pour les constantes de config
                config_dict[key] = getattr(config, key)

        # Surcharger/Ajouter avec les variables d'environnement si elles existent
        config_dict["BINANCE_API_KEY"] = os.getenv(
            "ENV_API_KEY",
            config_dict.get("BINANCE_API_KEY", "YOUR_API_KEY_PLACEHOLDER"),
        )
        config_dict["BINANCE_API_SECRET"] = os.getenv(
            "ENV_API_SECRET",
            config_dict.get("BINANCE_API_SECRET", "YOUR_SECRET_KEY_PLACEHOLDER"),
        )
        use_testnet_str = os.getenv(
            "ENV_USE_TESTNET", str(config_dict.get("USE_TESTNET", True))
        )
        config_dict["USE_TESTNET"] = use_testnet_str.lower() in (
            "true",
            "1",
            "t",
            "yes",
            "y",
        )

        # Log pour vérifier les valeurs chargées (avant conversion)
        log_initial = {
            k: v
            for k, v in config_dict.items()
            if k not in ["BINANCE_API_KEY", "BINANCE_API_SECRET"]
        }
        logger.debug(
            f"ConfigManager._load_initial_config: Valeurs brutes chargées = {log_initial}"
        )
        return config_dict

    def get_config(self) -> Dict[str, Any]:
        """Retourne une copie de la configuration interne (fractions, sans conversion %)."""
        return self._config.copy()

    def get_value(self, key: str, default: Any = None) -> Any:
        """Retourne une valeur spécifique de la config interne (avec fractions)."""
        return self._config.get(key, default)

    def update_config(
        self, new_params_input_percent: Dict[str, Any]
    ) -> Tuple[bool, str, bool]:
        """
        Valide les nouveaux paramètres (supposés en %), les convertit en fractions,
        et met à jour la configuration interne.
        """
        logger.debug(
            f"update_config: Reçu new_params_input_percent = {new_params_input_percent}"
        )

        # 1. Créer une config candidate en fusionnant les params reçus (%)
        #    avec la config actuelle (convertie temporairement en % pour la validation)
        config_candidate_percent = {}
        # Convertir la config actuelle (fractions) en %
        for key, value in self._config.items():
            if (
                key
                in [
                    "RISK_PER_TRADE",
                    "CAPITAL_ALLOCATION",
                    "STOP_LOSS_PERCENTAGE",
                ]
                and value is not None
            ):
                try:
                    config_candidate_percent[key] = float(Decimal(str(value)) * 100)
                except (InvalidOperation, TypeError):
                    config_candidate_percent[key] = (
                        value  # Garder la valeur si conversion échoue
                    )
            else:
                config_candidate_percent[key] = value
        # Fusionner les nouveaux paramètres (%)
        config_candidate_percent.update(new_params_input_percent)
        logger.debug(
            f"update_config: config_candidate_percent (pour validation) = {config_candidate_percent}"
        )

        # 2. Valider et convertir cette config candidate (qui est en %)
        validated_config_fractions, error_message, restart_recommended = (
            self._validate_and_convert_config(config_candidate_percent)
        )

        if error_message:
            logger.error(f"Échec MAJ config: {error_message}")
            return False, error_message, False
        else:
            # 3. Remplacer complètement la config interne par la nouvelle config validée/convertie
            self._config = validated_config_fractions
            log_params_saved = {
                k: v
                for k, v in self._config.items()
                if k not in ["BINANCE_API_KEY", "BINANCE_API_SECRET"]
            }
            logger.info(f"Config MAJ et stockée (fractions): {log_params_saved}")
            message = "Paramètres mis à jour."
            if restart_recommended:
                message += " Redémarrage bot conseillé."
            return True, message, restart_recommended

    def _validate_and_convert_config(
        self, params_in_percent: Dict[str, Any], is_initial: bool = False
    ) -> Tuple[Dict[str, Any], Optional[str], bool]:
        """
        Valide les paramètres fournis (supposés être en % pour RISK, ALLOC, SL, TP)
        et les convertit en fractions décimales.
        Retourne la configuration COMPLÈTE validée/convertie en fractions.
        """
        validated_config_fractions = {}  # Stockera la config complète avec fractions
        restart_recommended = False
        error_prefix = "Validation Config"

        # Récupérer les valeurs actuelles (avant modification) pour comparaison si ce n'est pas l'initialisation
        current_strategy = self._config.get("STRATEGY_TYPE") if not is_initial else None
        current_tf = self._config.get("TIMEFRAME_STR") if not is_initial else None
        current_depth_levels = (
            self._config.get("SCALPING_DEPTH_LEVELS") if not is_initial else None
        )
        current_depth_speed = (
            self._config.get("SCALPING_DEPTH_SPEED") if not is_initial else None
        )

        try:
            # --- Copier/Valider les clés non modifiables ou non converties ---
            for key in [
                "BINANCE_API_KEY",
                "BINANCE_API_SECRET",
                "USE_TESTNET",
                "SYMBOL",
            ]:
                validated_config_fractions[key] = params_in_percent.get(key)

            # --- Timeframe ---
            new_tf = str(
                params_in_percent.get(
                    "TIMEFRAME_STR", getattr(config, "TIMEFRAME", "1m")
                )
            )
            if new_tf not in VALID_TIMEFRAMES:
                raise ValueError(f"TIMEFRAME_STR invalide: {new_tf}")
            validated_config_fractions["TIMEFRAME_STR"] = new_tf
            if not is_initial and new_tf != current_tf:
                restart_recommended = True

            # --- Risk Per Trade (%) -> fraction ---
            risk_pct_in = params_in_percent.get(
                "RISK_PER_TRADE", getattr(config, "RISK_PER_TRADE", 1)
            )
            try:
                risk_pct = Decimal(str(risk_pct_in))
                if not (Decimal("0") < risk_pct <= Decimal("100")):
                    raise ValueError("RISK_PER_TRADE doit être > 0% et <= 100%")
                validated_config_fractions["RISK_PER_TRADE"] = float(
                    risk_pct / Decimal(100)
                )
            except InvalidOperation:
                raise ValueError("RISK_PER_TRADE doit être un nombre.")

            # --- Capital Allocation (%) -> fraction ---
            alloc_pct_in = params_in_percent.get(
                "CAPITAL_ALLOCATION", getattr(config, "CAPITAL_ALLOCATION", 50)
            )
            try:
                alloc_pct = Decimal(str(alloc_pct_in))
                if not (Decimal("0") < alloc_pct <= Decimal("100")):
                    raise ValueError("CAPITAL_ALLOCATION doit être > 0% et <= 100%")
                validated_config_fractions["CAPITAL_ALLOCATION"] = float(
                    alloc_pct / Decimal(100)
                )
            except InvalidOperation:
                raise ValueError("CAPITAL_ALLOCATION doit être un nombre.")

            # --- Stop Loss (%) -> fraction or None ---
            sl_pct_in = params_in_percent.get(
                "STOP_LOSS_PERCENTAGE", getattr(config, "STOP_LOSS_PERCENTAGE", 0.01)
            )
            if sl_pct_in is not None and str(sl_pct_in).strip() != "":
                try:
                    sl_pct = Decimal(str(sl_pct_in))
                    if not (Decimal("0.001") <= sl_pct <= Decimal("0.05")):
                        raise ValueError(
                            "STOP_LOSS_PERCENTAGE doit être entre 0.1% et 5%"
                        )
                    validated_config_fractions["STOP_LOSS_PERCENTAGE"] = float(sl_pct)
                except InvalidOperation:
                    raise ValueError("STOP_LOSS_PERCENTAGE doit être un nombre.")
            else:
                validated_config_fractions["STOP_LOSS_PERCENTAGE"] = float(
                    getattr(config, "STOP_LOSS_PERCENTAGE", 0.01)
                )

            # --- Take Profit 1 (%) -> fraction or None ---
            tp1_pct_in = params_in_percent.get(
                "TAKE_PROFIT_1_PERCENTAGE",
                getattr(config, "TAKE_PROFIT_1_PERCENTAGE", 0.01),
            )
            if tp1_pct_in is not None and str(tp1_pct_in).strip() != "":
                try:
                    tp1_pct = Decimal(str(tp1_pct_in))
                    if not (Decimal("0.001") <= tp1_pct <= Decimal("0.05")):
                        raise ValueError(
                            "TAKE_PROFIT_1_PERCENTAGE doit être entre 0.1% et 5%"
                        )
                    validated_config_fractions["TAKE_PROFIT_1_PERCENTAGE"] = float(
                        tp1_pct
                    )
                except InvalidOperation:
                    raise ValueError("TAKE_PROFIT_1_PERCENTAGE doit être un nombre.")
            else:
                validated_config_fractions["TAKE_PROFIT_1_PERCENTAGE"] = float(
                    getattr(config, "TAKE_PROFIT_1_PERCENTAGE", 0.01)
                )

            # --- Take Profit 2 (%) -> fraction or None ---
            tp2_pct_in = params_in_percent.get(
                "TAKE_PROFIT_2_PERCENTAGE",
                getattr(config, "TAKE_PROFIT_2_PERCENTAGE", 0.01),
            )
            if tp2_pct_in is not None and str(tp2_pct_in).strip() != "":
                try:
                    tp2_pct = Decimal(str(tp2_pct_in))
                    if not (Decimal("0.001") <= tp2_pct <= Decimal("0.05")):
                        raise ValueError(
                            "TAKE_PROFIT_2_PERCENTAGE doit être entre 0.1% et 5%"
                        )
                    validated_config_fractions["TAKE_PROFIT_2_PERCENTAGE"] = float(
                        tp2_pct
                    )
                except InvalidOperation:
                    raise ValueError("TAKE_PROFIT_2_PERCENTAGE doit être un nombre.")
            else:
                validated_config_fractions["TAKE_PROFIT_2_PERCENTAGE"] = float(
                    getattr(config, "TAKE_PROFIT_2_PERCENTAGE", 0.01)
                )

            # --- Trailing Stop (%) -> fraction ---
            trailing_pct_in = params_in_percent.get(
                "TRAILING_STOP_PERCENTAGE",
                getattr(config, "TRAILING_STOP_PERCENTAGE", 0.003),
            )
            if trailing_pct_in is not None and str(trailing_pct_in).strip() != "":
                try:
                    trailing_pct = Decimal(str(trailing_pct_in))
                    if not (Decimal("0.001") <= trailing_pct <= Decimal("0.05")):
                        raise ValueError(
                            "TRAILING_STOP_PERCENTAGE doit être entre 0.1% et 5%"
                        )
                    validated_config_fractions["TRAILING_STOP_PERCENTAGE"] = float(
                        trailing_pct
                    )
                except InvalidOperation:
                    raise ValueError("TRAILING_STOP pourcentage doit être un nombre.")
            else:
                validated_config_fractions["TRAILING_STOP_PERCENTAGE"] = float(
                    getattr(config, "TRAILING_STOP_PERCENTAGE", 0.003)
                )

            # --- Time Stop ---
            try:
                validated_config_fractions["TIME_STOP_MINUTES"] = int(
                    params_in_percent.get(
                        "TIME_STOP_MINUTES", getattr(config, "TIME_STOP_MINUTES", 15)
                    )
                )
            except (ValueError, TypeError):
                raise ValueError("TIME_STOP_MINUTES doit être un entier.")
            if validated_config_fractions["TIME_STOP_MINUTES"] <= 0:
                raise ValueError("TIME_STOP_MINUTES > 0")

            # --- Strategy Type ---
            new_strategy_type = str(
                params_in_percent.get(
                    "STRATEGY_TYPE", getattr(config, "STRATEGY_TYPE", "SWING")
                )
            ).upper()
            if new_strategy_type not in ["SCALPING", "SCALPING2", "SWING"]:
                raise ValueError("STRATEGY_TYPE: 'SCALPING', 'SCALPING2' ou 'SWING'.")
            validated_config_fractions["STRATEGY_TYPE"] = new_strategy_type
            if not is_initial and new_strategy_type != current_strategy:
                restart_recommended = True

            # --- Scalping Params (Validation seulement, pas de conversion %) ---
            validated_config_fractions["SCALPING_ORDER_TYPE"] = str(
                params_in_percent.get(
                    "SCALPING_ORDER_TYPE",
                    getattr(config, "SCALPING_ORDER_TYPE", "MARKET"),
                )
            ).upper()
            if validated_config_fractions["SCALPING_ORDER_TYPE"] not in [
                "MARKET",
                "LIMIT",
            ]:
                raise ValueError("SCALPING_ORDER_TYPE: 'MARKET' ou 'LIMIT'.")
            validated_config_fractions["SCALPING_LIMIT_TIF"] = str(
                params_in_percent.get(
                    "SCALPING_LIMIT_TIF", getattr(config, "SCALPING_LIMIT_TIF", "GTC")
                )
            ).upper()
            if validated_config_fractions[
                "SCALPING_ORDER_TYPE"
            ] == "LIMIT" and validated_config_fractions["SCALPING_LIMIT_TIF"] not in [
                "GTC",
                "IOC",
                "FOK",
            ]:
                raise ValueError(
                    "SCALPING_LIMIT_TIF: 'GTC', 'IOC', ou 'FOK' pour LIMIT."
                )
            try:
                validated_config_fractions["SCALPING_LIMIT_ORDER_TIMEOUT_MS"] = int(
                    params_in_percent.get(
                        "SCALPING_LIMIT_ORDER_TIMEOUT_MS",
                        getattr(config, "SCALPING_LIMIT_ORDER_TIMEOUT_MS", 5000),
                    )
                )
            except (ValueError, TypeError):
                raise ValueError("SCALPING_LIMIT_ORDER_TIMEOUT_MS doit être un entier.")
            if validated_config_fractions["SCALPING_LIMIT_ORDER_TIMEOUT_MS"] <= 0:
                raise ValueError("SCALPING_LIMIT_ORDER_TIMEOUT_MS > 0.")
            try:
                validated_config_fractions["SCALPING_DEPTH_LEVELS"] = int(
                    params_in_percent.get(
                        "SCALPING_DEPTH_LEVELS",
                        getattr(config, "SCALPING_DEPTH_LEVELS", 5),
                    )
                )
            except (ValueError, TypeError):
                raise ValueError("SCALPING_DEPTH_LEVELS doit être un entier.")
            if validated_config_fractions["SCALPING_DEPTH_LEVELS"] not in [5, 10, 20]:
                raise ValueError("SCALPING_DEPTH_LEVELS: 5, 10, ou 20.")
            if (
                not is_initial
                and validated_config_fractions["SCALPING_DEPTH_LEVELS"]
                != current_depth_levels
            ):
                restart_recommended = True
            validated_config_fractions["SCALPING_DEPTH_SPEED"] = str(
                params_in_percent.get(
                    "SCALPING_DEPTH_SPEED",
                    getattr(config, "SCALPING_DEPTH_SPEED", "100ms"),
                )
            ).lower()
            if validated_config_fractions["SCALPING_DEPTH_SPEED"] not in [
                "100ms",
                "1000ms",
            ]:
                raise ValueError("SCALPING_DEPTH_SPEED: '100ms' ou '1000ms'.")
            if (
                not is_initial
                and validated_config_fractions["SCALPING_DEPTH_SPEED"]
                != current_depth_speed
            ):
                restart_recommended = True
            # --- Scalping Thresholds ---
            spread_in = params_in_percent.get(
                "SCALPING_SPREAD_THRESHOLD",
                getattr(config, "SCALPING_SPREAD_THRESHOLD", 0.0001),
            )
            try:
                validated_config_fractions["SCALPING_SPREAD_THRESHOLD"] = float(
                    Decimal(str(spread_in))
                )
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError("SCALPING_SPREAD_THRESHOLD doit être un nombre >= 0.")
            if validated_config_fractions["SCALPING_SPREAD_THRESHOLD"] < 0:
                raise ValueError("SCALPING_SPREAD_THRESHOLD >= 0.")
            imbalance_in = params_in_percent.get(
                "SCALPING_IMBALANCE_THRESHOLD",
                getattr(config, "SCALPING_IMBALANCE_THRESHOLD", 1.5),
            )
            try:
                validated_config_fractions["SCALPING_IMBALANCE_THRESHOLD"] = float(
                    Decimal(str(imbalance_in))
                )
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError(
                    "SCALPING_IMBALANCE_THRESHOLD doit être un nombre > 0."
                )
            if validated_config_fractions["SCALPING_IMBALANCE_THRESHOLD"] <= 0:
                raise ValueError("SCALPING_IMBALANCE_THRESHOLD > 0.")
            volume_in = params_in_percent.get(
                "SCALPING_MIN_TRADE_VOLUME",
                getattr(config, "SCALPING_MIN_TRADE_VOLUME", 0.1),
            )
            try:
                validated_config_fractions["SCALPING_MIN_TRADE_VOLUME"] = float(
                    Decimal(str(volume_in))
                )
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError("SCALPING_MIN_TRADE_VOLUME doit être un nombre >= 0.")
            if validated_config_fractions["SCALPING_MIN_TRADE_VOLUME"] < 0:
                raise ValueError("SCALPING_MIN_TRADE_VOLUME >= 0.")

            # --- Swing Params (Validation seulement) ---
            try:
                validated_config_fractions["EMA_SHORT_PERIOD"] = int(
                    params_in_percent.get(
                        "EMA_SHORT_PERIOD", getattr(config, "EMA_SHORT_PERIOD", 9)
                    )
                )
            except (ValueError, TypeError):
                raise ValueError("EMA_SHORT_PERIOD doit être un entier.")
            if validated_config_fractions["EMA_SHORT_PERIOD"] <= 0:
                raise ValueError("EMA_SHORT_PERIOD > 0")
            try:
                validated_config_fractions["EMA_LONG_PERIOD"] = int(
                    params_in_percent.get(
                        "EMA_LONG_PERIOD", getattr(config, "EMA_LONG_PERIOD", 21)
                    )
                )
            except (ValueError, TypeError):
                raise ValueError("EMA_LONG_PERIOD doit être un entier.")
            if (
                validated_config_fractions["EMA_LONG_PERIOD"]
                <= validated_config_fractions["EMA_SHORT_PERIOD"]
            ):
                raise ValueError("EMA_LONG_PERIOD > EMA_SHORT_PERIOD")
            try:
                validated_config_fractions["EMA_FILTER_PERIOD"] = int(
                    params_in_percent.get(
                        "EMA_FILTER_PERIOD", getattr(config, "EMA_FILTER_PERIOD", 50)
                    )
                )
            except (ValueError, TypeError):
                raise ValueError("EMA_FILTER_PERIOD doit être un entier.")
            if validated_config_fractions["EMA_FILTER_PERIOD"] <= 0:
                raise ValueError("EMA_FILTER_PERIOD > 0")
            try:
                validated_config_fractions["RSI_PERIOD"] = int(
                    params_in_percent.get(
                        "RSI_PERIOD", getattr(config, "RSI_PERIOD", 14)
                    )
                )
            except (ValueError, TypeError):
                raise ValueError("RSI_PERIOD doit être un entier.")
            if validated_config_fractions["RSI_PERIOD"] <= 1:
                raise ValueError("RSI_PERIOD > 1")
            try:
                validated_config_fractions["RSI_OVERBOUGHT"] = int(
                    params_in_percent.get(
                        "RSI_OVERBOUGHT", getattr(config, "RSI_OVERBOUGHT", 75)
                    )
                )
            except (ValueError, TypeError):
                raise ValueError("RSI_OVERBOUGHT doit être un entier.")
            if not (50 < validated_config_fractions["RSI_OVERBOUGHT"] <= 100):
                raise ValueError("RSI_OB > 50 et <= 100")
            try:
                validated_config_fractions["RSI_OVERSOLD"] = int(
                    params_in_percent.get(
                        "RSI_OVERSOLD", getattr(config, "RSI_OVERSOLD", 25)
                    )
                )
            except (ValueError, TypeError):
                raise ValueError("RSI_OVERSOLD doit être un entier.")
            if not (0 <= validated_config_fractions["RSI_OVERSOLD"] < 50):
                raise ValueError("RSI_OS >= 0 et < 50")
            if (
                validated_config_fractions["RSI_OVERSOLD"]
                >= validated_config_fractions["RSI_OVERBOUGHT"]
            ):
                raise ValueError("RSI_OS < RSI_OB")
            try:
                validated_config_fractions["VOLUME_AVG_PERIOD"] = int(
                    params_in_percent.get(
                        "VOLUME_AVG_PERIOD", getattr(config, "VOLUME_AVG_PERIOD", 20)
                    )
                )
            except (ValueError, TypeError):
                raise ValueError("VOLUME_AVG_PERIOD doit être un entier.")
            if validated_config_fractions["VOLUME_AVG_PERIOD"] <= 0:
                raise ValueError("VOL_AVG > 0")
            validated_config_fractions["USE_EMA_FILTER"] = bool(
                params_in_percent.get(
                    "USE_EMA_FILTER", getattr(config, "USE_EMA_FILTER", True)
                )
            )
            validated_config_fractions["USE_VOLUME_CONFIRMATION"] = bool(
                params_in_percent.get(
                    "USE_VOLUME_CONFIRMATION",
                    getattr(config, "USE_VOLUME_CONFIRMATION", False),
                )
            )

            # Retourner la configuration COMPLÈTE validée et convertie en fractions
            return validated_config_fractions, None, restart_recommended

        except (ValueError, TypeError, InvalidOperation) as e:
            error_message = f"Paramètres invalides: {e}"
            logger.error(f"{error_prefix}: {error_message}")
            return {}, error_message, False
        except Exception as e:  # Attraper d'autres erreurs potentielles
            error_message = f"Erreur interne validation: {e}"
            logger.error(f"{error_prefix}: {error_message}", exc_info=True)
            return {}, error_message, False


# --- Instanciation ---
config_manager = ConfigManager()

# --- Exports ---
__all__ = ["SYMBOL", "VALID_TIMEFRAMES", "config_manager", "ConfigManager"]
