# /Users/davidmichels/Desktop/trading-bot/backend/config_manager.py
import logging
import os
import dotenv
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, Optional, Tuple, List, Union

import config  # Assurez-vous que config.py est importé

dotenv.load_dotenv()
logger = logging.getLogger(__name__)

SYMBOL = getattr(config, "SYMBOL", "BTCUSDT")
VALID_TIMEFRAMES = [
    "1s", "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M",
]
# Clés dont les valeurs sont attendues en % depuis l'UI/config.py mais stockées en fraction
PERCENTAGE_KEYS_INPUT = {
    "RISK_PER_TRADE",
    "CAPITAL_ALLOCATION",
    "STOP_LOSS_PERCENTAGE",
    "TAKE_PROFIT_1_PERCENTAGE",
    "TAKE_PROFIT_2_PERCENTAGE",
    "TRAILING_STOP_PERCENTAGE",
    # Ajoutez d'autres clés si nécessaire
}
# Clés dont les valeurs sont des fractions mais pas issues de pourcentages (ex: seuils)
FRACTION_KEYS_DIRECT = {
    "SCALPING_SPREAD_THRESHOLD",
    # Ajoutez d'autres clés si nécessaire
}

class ConfigManager:
    def __init__(self):
        logger.debug("ConfigManager: Début __init__")
        # 1. Charger les valeurs initiales depuis config.py/env
        initial_config_input = self._load_initial_config()

        # 2. Valider et convertir immédiatement ces valeurs initiales
        validated_initial_config_internal, error_msg, _ = (
            self._validate_and_convert_input_config(initial_config_input, is_initial=True)
        )

        if error_msg:
            logger.critical(
                f"ERREUR CRITIQUE CONFIG INITIALE: {error_msg}. Vérifiez config.py et .env."
            )
            # CORRECTION: Lever l'erreur ici pour arrêter l'initialisation
            raise ValueError(f"Erreur configuration initiale: {error_msg}")
        else:
            # 3. Stocker la configuration validée et convertie (format interne)
            self._config: Dict[str, Any] = validated_initial_config_internal
            logger.info("Configuration initiale validée et convertie au format interne.")

        config_log = {
            k: v for k, v in self._config.items()
            if k not in ["BINANCE_API_KEY", "BINANCE_API_SECRET"]
        }
        logger.info(
            f"ConfigManager initialisé avec (format interne, hors clés API): {config_log}"
        )

    def _load_initial_config(self) -> Dict[str, Any]:
        """Charge la configuration depuis config.py et .env.
        Les valeurs pour les clés dans PERCENTAGE_KEYS_INPUT sont supposées en POURCENTAGES."""
        logger.debug("ConfigManager: Début _load_initial_config")
        config_dict = {}
        # Charger toutes les clés définies dans config.py
        for key in dir(config):
            if key.isupper():
                config_dict[key] = getattr(config, key)

        # Surcharger/Ajouter avec les variables d'environnement si elles existent
        config_dict["BINANCE_API_KEY"] = os.getenv(
            "ENV_API_KEY", config_dict.get("BINANCE_API_KEY")
        )
        config_dict["BINANCE_API_SECRET"] = os.getenv(
            "ENV_API_SECRET", config_dict.get("BINANCE_API_SECRET")
        )
        use_testnet_str = os.getenv(
            "ENV_USE_TESTNET", str(config_dict.get("USE_TESTNET", True))
        )
        config_dict["USE_TESTNET"] = use_testnet_str.lower() in ("true", "1", "t", "yes", "y")

        # Log pour vérifier les valeurs brutes chargées
        log_initial = {
            k: v for k, v in config_dict.items()
            if k not in ["BINANCE_API_KEY", "BINANCE_API_SECRET"]
        }
        logger.debug(f"ConfigManager._load_initial_config: Valeurs brutes chargées = {log_initial}")
        return config_dict

    def get_config(self) -> Dict[str, Any]:
        """Retourne une copie de la configuration interne (format interne, ex: fractions)."""
        return self._config.copy()

    def get_value(self, key: str, default: Any = None) -> Any:
        """Retourne une valeur spécifique de la config interne (format interne)."""
        # Utiliser self._config qui contient le format interne
        return self._config.get(key, default)

    def update_config(
        self, new_params_input: Dict[str, Any]
    ) -> Tuple[bool, str, bool]:
        """
        Valide les nouveaux paramètres (format d'entrée, ex: %), les convertit au format interne,
        et met à jour la configuration interne si valide.
        """
        logger.debug(f"update_config: Reçu new_params_input = {new_params_input}")

        # 1. Créer une config candidate en fusionnant la config actuelle (interne)
        #    avec les nouveaux paramètres (convertis au format interne).
        config_candidate_internal = self._config.copy()
        try:
            converted_new_params = self._convert_input_params_to_internal(new_params_input)
            config_candidate_internal.update(converted_new_params)
        except ValueError as e:
             logger.error(f"Échec conversion params d'entrée: {e}")
             return False, f"Paramètre invalide: {e}", False

        # 2. Valider cette config candidate (qui est au format interne)
        is_valid, error_message, restart_recommended = self._validate_internal_config(
            config_candidate_internal, self._config # Passer l'ancienne config pour comparaison
        )

        if not is_valid:
            logger.error(f"Échec validation config candidate: {error_message}")
            return False, error_message or "Validation échouée", False
        else:
            # 3. Remplacer la config interne par la nouvelle config validée
            self._config = config_candidate_internal
            log_params_saved = {
                k: v for k, v in self._config.items()
                if k not in ["BINANCE_API_KEY", "BINANCE_API_SECRET"]
            }
            logger.info(f"Config MAJ et stockée (format interne): {log_params_saved}")
            message = "Paramètres mis à jour."
            if restart_recommended:
                message += " Redémarrage bot conseillé."
            return True, message, restart_recommended

    def _convert_input_params_to_internal(self, params_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convertit les paramètres reçus (format UI/input) au format interne (ex: fractions).
        Ne valide pas, lève ValueError si conversion impossible.
        """
        converted_params = {}
        for key, value in params_input.items():
            # Ignorer valeurs vides ou None
            if value is None or (isinstance(value, str) and str(value).strip() == ""):
                continue

            try:
                if key in PERCENTAGE_KEYS_INPUT:
                    # Convertir pourcentage en fraction
                    pct_decimal = Decimal(str(value))
                    converted_params[key] = pct_decimal / Decimal(100)
                elif key in FRACTION_KEYS_DIRECT:
                     # Convertir directement en Decimal
                     converted_params[key] = Decimal(str(value))
                elif key in ["SCALPING_DEPTH_LEVELS", "TIME_STOP_MINUTES",
                             "EMA_SHORT_PERIOD", "EMA_LONG_PERIOD", "EMA_FILTER_PERIOD",
                             "RSI_PERIOD", "RSI_OVERBOUGHT", "RSI_OVERSOLD",
                             "VOLUME_AVG_PERIOD", "SCALPING_LIMIT_ORDER_TIMEOUT_MS",
                             "SUPERTREND_ATR_PERIOD", "SCALPING_RSI_PERIOD",
                             "STOCH_K_PERIOD", "STOCH_D_PERIOD", "STOCH_SMOOTH", "BB_PERIOD",
                             "VOLUME_MA_PERIOD"]: # Ajout VOLUME_MA_PERIOD
                    converted_params[key] = int(value) # Convertir en entier
                elif key in ["SUPERTREND_ATR_MULTIPLIER", "BB_STD",
                             "SCALPING_IMBALANCE_THRESHOLD"]: # Ex: Float
                     converted_params[key] = float(value)
                elif key in ["USE_TESTNET", "USE_EMA_FILTER", "USE_VOLUME_CONFIRMATION"]:
                    converted_params[key] = str(value).lower() in ("true", "1", "t", "yes", "y")
                elif key == "TIMEFRAME": # Garder comme string
                    converted_params[key] = str(value)
                else:
                    # Pour les autres clés (str, etc.), garder la valeur telle quelle si non vide
                    if isinstance(value, str) and value.strip():
                        converted_params[key] = value
                    elif not isinstance(value, str): # Garder autres types non vides
                        converted_params[key] = value

            except (InvalidOperation, TypeError, ValueError) as e:
                raise ValueError(f"Impossible de convertir '{key}' (valeur: '{value}', type: {type(value)}): {e}")

        return converted_params

    def _validate_internal_config(
        self,
        config_to_validate: Dict[str, Any],
        previous_config: Dict[str, Any] # Sera {} lors de l'initialisation
    ) -> Tuple[bool, Optional[str], bool]:
        """
        Valide la configuration COMPLÈTE fournie (format interne, ex: fractions).
        Détecte les changements nécessitant un redémarrage.
        Retourne (isValid, errorMessage, restartRecommended).
        """
        errors: List[str] = []
        restart_recommended = False

        # --- Validation des types et plages (format interne) ---
        try:
            # Timeframe
            new_tf = str(config_to_validate.get("TIMEFRAME", "1m")) # Utiliser TIMEFRAME
            if new_tf not in VALID_TIMEFRAMES:
                errors.append(f"TIMEFRAME invalide: {new_tf}")
            # CORRECTION: Vérifier changement de timeframe seulement si ce n'est pas l'initialisation
            if previous_config and new_tf != previous_config.get("TIMEFRAME"):
                restart_recommended = True

            # Risk Per Trade (fraction)
            risk_frac = config_to_validate.get("RISK_PER_TRADE")
            if not isinstance(risk_frac, Decimal) or not (Decimal("0") < risk_frac <= Decimal("1")):
                errors.append(f"RISK_PER_TRADE (fraction) doit être > 0 et <= 1 (reçu: {risk_frac})")

            # Capital Allocation (fraction)
            alloc_frac = config_to_validate.get("CAPITAL_ALLOCATION")
            if not isinstance(alloc_frac, Decimal) or not (Decimal("0") < alloc_frac <= Decimal("1")):
                errors.append(f"CAPITAL_ALLOCATION (fraction) doit être > 0 et <= 1 (reçu: {alloc_frac})")

            # Stop Loss (fraction) - Plage élargie (0.1% à 20%)
            sl_frac = config_to_validate.get("STOP_LOSS_PERCENTAGE")
            if not isinstance(sl_frac, Decimal) or not (Decimal("0.001") <= sl_frac <= Decimal("0.20")):
                 errors.append(f"STOP_LOSS_PERCENTAGE (fraction) doit être entre 0.001 (0.1%) et 0.20 (20%) (reçu: {sl_frac})")

            # Take Profit 1 (fraction) - Plage élargie (0.1% à 50%)
            tp1_frac = config_to_validate.get("TAKE_PROFIT_1_PERCENTAGE")
            if not isinstance(tp1_frac, Decimal) or not (Decimal("0.001") <= tp1_frac <= Decimal("0.50")):
                 errors.append(f"TAKE_PROFIT_1_PERCENTAGE (fraction) doit être entre 0.001 (0.1%) et 0.50 (50%) (reçu: {tp1_frac})")

            # Take Profit 2 (fraction) - Plage élargie (0.1% à 50%)
            tp2_frac = config_to_validate.get("TAKE_PROFIT_2_PERCENTAGE")
            if not isinstance(tp2_frac, Decimal) or not (Decimal("0.001") <= tp2_frac <= Decimal("0.50")):
                 errors.append(f"TAKE_PROFIT_2_PERCENTAGE (fraction) doit être entre 0.001 (0.1%) et 0.50 (50%) (reçu: {tp2_frac})")
            # Vérifier que TP2 > TP1 seulement si TP2 est utilisé/pertinent et les deux sont valides
            if isinstance(tp2_frac, Decimal) and isinstance(tp1_frac, Decimal) and tp2_frac <= tp1_frac:
                 errors.append(f"TAKE_PROFIT_2 doit être > TAKE_PROFIT_1")

            # Trailing Stop (fraction) - Plage élargie (0.1% à 10%)
            tsl_frac = config_to_validate.get("TRAILING_STOP_PERCENTAGE")
            if not isinstance(tsl_frac, Decimal) or not (Decimal("0.001") <= tsl_frac <= Decimal("0.10")):
                 errors.append(f"TRAILING_STOP_PERCENTAGE (fraction) doit être entre 0.001 (0.1%) et 0.10 (10%) (reçu: {tsl_frac})")

            # Time Stop (minutes)
            time_stop = config_to_validate.get("TIME_STOP_MINUTES")
            if not isinstance(time_stop, int) or not (1 <= time_stop <= 240): # Ex: 1min à 4h
                errors.append(f"TIME_STOP_MINUTES doit être un entier entre 1 et 240 (reçu: {time_stop})")

            # Strategy Type
            new_strategy = str(config_to_validate.get("STRATEGY_TYPE", "SWING")).upper()
            if new_strategy not in ["SCALPING", "SCALPING2", "SWING"]:
                errors.append(f"STRATEGY_TYPE invalide: {new_strategy}")
            # CORRECTION: Vérifier changement de stratégie seulement si ce n'est pas l'initialisation
            if previous_config and new_strategy != previous_config.get("STRATEGY_TYPE"):
                restart_recommended = True

            # --- Scalping Params ---
            if new_strategy == "SCALPING":
                order_type = str(config_to_validate.get("SCALPING_ORDER_TYPE", "MARKET")).upper()
                if order_type not in ["MARKET", "LIMIT"]:
                    errors.append("SCALPING_ORDER_TYPE: 'MARKET' ou 'LIMIT'.")
                limit_tif = str(config_to_validate.get("SCALPING_LIMIT_TIF", "GTC")).upper()
                if order_type == "LIMIT" and limit_tif not in ["GTC", "IOC", "FOK"]:
                    errors.append("SCALPING_LIMIT_TIF: 'GTC', 'IOC', ou 'FOK' pour LIMIT.")
                limit_timeout = config_to_validate.get("SCALPING_LIMIT_ORDER_TIMEOUT_MS")
                if not isinstance(limit_timeout, int) or limit_timeout <= 0:
                    errors.append("SCALPING_LIMIT_ORDER_TIMEOUT_MS doit être un entier > 0.")

                depth_levels = config_to_validate.get("SCALPING_DEPTH_LEVELS")
                if not isinstance(depth_levels, int) or depth_levels not in [5, 10, 20]:
                    errors.append("SCALPING_DEPTH_LEVELS: 5, 10, ou 20.")
                # CORRECTION: Vérifier changement seulement si ce n'est pas l'initialisation
                if previous_config and depth_levels != previous_config.get("SCALPING_DEPTH_LEVELS"):
                    restart_recommended = True

                depth_speed = str(config_to_validate.get("SCALPING_DEPTH_SPEED", "1000ms")).lower()
                if depth_speed not in ["100ms", "1000ms"]:
                    errors.append("SCALPING_DEPTH_SPEED: '100ms' ou '1000ms'.")
                # CORRECTION: Vérifier changement seulement si ce n'est pas l'initialisation
                if previous_config and depth_speed != previous_config.get("SCALPING_DEPTH_SPEED"):
                    restart_recommended = True

                spread_thresh = config_to_validate.get("SCALPING_SPREAD_THRESHOLD")
                if not isinstance(spread_thresh, Decimal) or spread_thresh < 0:
                    errors.append("SCALPING_SPREAD_THRESHOLD (fraction) doit être >= 0.")

                imbalance_thresh = config_to_validate.get("SCALPING_IMBALANCE_THRESHOLD")
                # Permettre float ou Decimal ici
                if not isinstance(imbalance_thresh, (float, Decimal)) or Decimal(str(imbalance_thresh)) <= 0:
                     errors.append("SCALPING_IMBALANCE_THRESHOLD doit être un nombre > 0.")

            # --- Scalping 2 Params ---
            elif new_strategy == "SCALPING2":
                # Périodes indicateurs
                if not isinstance(config_to_validate.get("SUPERTREND_ATR_PERIOD", 0), int) or config_to_validate.get("SUPERTREND_ATR_PERIOD", 0) <= 0: errors.append("SUPERTREND_ATR_PERIOD > 0")
                if not isinstance(config_to_validate.get("SUPERTREND_ATR_MULTIPLIER", 0.0), float) or config_to_validate.get("SUPERTREND_ATR_MULTIPLIER", 0.0) <= 0: errors.append("SUPERTREND_ATR_MULTIPLIER > 0")
                if not isinstance(config_to_validate.get("SCALPING_RSI_PERIOD", 0), int) or config_to_validate.get("SCALPING_RSI_PERIOD", 0) <= 1: errors.append("SCALPING_RSI_PERIOD > 1")
                if not isinstance(config_to_validate.get("STOCH_K_PERIOD", 0), int) or config_to_validate.get("STOCH_K_PERIOD", 0) <= 0: errors.append("STOCH_K_PERIOD > 0")
                if not isinstance(config_to_validate.get("STOCH_D_PERIOD", 0), int) or config_to_validate.get("STOCH_D_PERIOD", 0) <= 0: errors.append("STOCH_D_PERIOD > 0")
                if not isinstance(config_to_validate.get("STOCH_SMOOTH", 0), int) or config_to_validate.get("STOCH_SMOOTH", 0) <= 0: errors.append("STOCH_SMOOTH > 0")
                if not isinstance(config_to_validate.get("BB_PERIOD", 0), int) or config_to_validate.get("BB_PERIOD", 0) <= 1: errors.append("BB_PERIOD > 1")
                if not isinstance(config_to_validate.get("BB_STD", 0.0), float) or config_to_validate.get("BB_STD", 0.0) <= 0: errors.append("BB_STD > 0")
                if not isinstance(config_to_validate.get("VOLUME_MA_PERIOD", 0), int) or config_to_validate.get("VOLUME_MA_PERIOD", 0) <= 0: errors.append("VOLUME_MA_PERIOD > 0")

            # --- Swing Params ---
            elif new_strategy == "SWING":
                # Récupérer les valeurs
                ema_s = config_to_validate.get("EMA_SHORT_PERIOD")
                ema_l = config_to_validate.get("EMA_LONG_PERIOD")
                ema_f = config_to_validate.get("EMA_FILTER_PERIOD")
                rsi_p = config_to_validate.get("RSI_PERIOD")
                rsi_ob = config_to_validate.get("RSI_OVERBOUGHT")
                rsi_os = config_to_validate.get("RSI_OVERSOLD")
                vol_p = config_to_validate.get("VOLUME_AVG_PERIOD")

                # Valider types et plages individuelles
                if not isinstance(ema_s, int) or ema_s <= 0: errors.append("EMA_SHORT_PERIOD doit être un entier > 0")
                if not isinstance(ema_l, int) or ema_l <= 0: errors.append("EMA_LONG_PERIOD doit être un entier > 0")
                if not isinstance(ema_f, int) or ema_f <= 0: errors.append("EMA_FILTER_PERIOD doit être un entier > 0")
                if not isinstance(rsi_p, int) or rsi_p <= 1: errors.append("RSI_PERIOD doit être un entier > 1")
                if not isinstance(rsi_ob, int) or not (50 < rsi_ob <= 100): errors.append("RSI_OVERBOUGHT doit être un entier > 50 et <= 100")
                if not isinstance(rsi_os, int) or not (0 <= rsi_os < 50): errors.append("RSI_OVERSOLD doit être un entier >= 0 et < 50")
                if not isinstance(vol_p, int) or vol_p <= 0: errors.append("VOLUME_AVG_PERIOD doit être un entier > 0")

                # Valider les comparaisons SEULEMENT si les deux opérandes sont des entiers valides
                if isinstance(ema_l, int) and isinstance(ema_s, int) and ema_l <= ema_s:
                    errors.append("EMA_LONG_PERIOD doit être > EMA_SHORT_PERIOD")
                if isinstance(rsi_os, int) and isinstance(rsi_ob, int) and rsi_os >= rsi_ob:
                    errors.append("RSI_OVERSOLD doit être < RSI_OVERBOUGHT")

                # Valider les booléens
                if not isinstance(config_to_validate.get("USE_EMA_FILTER"), bool): errors.append("USE_EMA_FILTER doit être booléen")
                if not isinstance(config_to_validate.get("USE_VOLUME_CONFIRMATION"), bool): errors.append("USE_VOLUME_CONFIRMATION doit être booléen")

            # --- Vérification clés non modifiables (SEULEMENT si ce n'est pas l'initialisation) ---
            # CORRECTION: Ajouter la condition 'if previous_config:'
            if previous_config: # Ne vérifier que si on met à jour une config existante
                for key in ["BINANCE_API_KEY", "BINANCE_API_SECRET", "SYMBOL"]:
                     # Vérifier si la clé existe dans la config candidate et si elle est différente de l'ancienne
                     if key in config_to_validate and config_to_validate.get(key) != previous_config.get(key):
                          errors.append(f"La clé '{key}' ne peut pas être modifiée après le démarrage.")
                          restart_recommended = True # Forcer redémarrage si tentative

                if "USE_TESTNET" in config_to_validate and config_to_validate.get("USE_TESTNET") != previous_config.get("USE_TESTNET"):
                     errors.append("Le changement de USE_TESTNET nécessite un redémarrage.")
                     restart_recommended = True

        except (KeyError, TypeError, ValueError, InvalidOperation) as e:
            errors.append(f"Erreur interne validation: {e}")

        if errors:
            return False, " / ".join(errors), False # Ne pas recommander redémarrage si juste invalide
        else:
            # Si la validation est OK, retourner la recommandation de redémarrage calculée
            return True, None, restart_recommended


    def _validate_and_convert_input_config(
        self, params_input: Dict[str, Any], is_initial: bool = False
    ) -> Tuple[Dict[str, Any], Optional[str], bool]:
        """
        Valide les paramètres fournis (format input, ex: %) et les convertit au format interne.
        Utilisé principalement pour l'initialisation.
        Retourne (validatedConfigInternal, errorMessage, restartRecommended).
        """
        try:
            # 1. Charger les défauts et fusionner avec les paramètres d'entrée
            full_input_params = self._load_initial_config() # Charge les défauts
            full_input_params.update(params_input) # Fusionne avec les params fournis

            # 2. Convertir la configuration complète au format interne
            internal_config_candidate = self._convert_input_params_to_internal(full_input_params)

            # 3. Ajouter les clés manquantes qui n'ont pas été converties (ex: clés API, Symbol, UseTestnet)
            #    Ces clés sont gérées spécialement ou n'ont pas de conversion directe.
            for key in ["BINANCE_API_KEY", "BINANCE_API_SECRET", "SYMBOL", "USE_TESTNET"]:
                 if key not in internal_config_candidate and key in full_input_params:
                      internal_config_candidate[key] = full_input_params.get(key)

            # 4. Valider la configuration complète au format interne
            # Pour la validation initiale, previous_config est vide ou non pertinent pour restart_recommended
            # CORRECTION: Passer {} comme previous_config si c'est l'initialisation
            previous_conf_for_validation = {} if is_initial else self._config
            is_valid, error_message, restart_recommended = self._validate_internal_config(
                internal_config_candidate, previous_conf_for_validation
            )

            if not is_valid:
                return {}, error_message, False
            else:
                # Retourner la configuration complète validée et convertie
                # CORRECTION: restart_recommended doit être False pour l'initialisation
                return internal_config_candidate, None, restart_recommended if not is_initial else False

        except (ValueError, TypeError, InvalidOperation) as e:
            error_message = f"Paramètres {'initiaux' if is_initial else 'fournis'} invalides: {e}"
            logger.error(f"Validation/Conversion Config: {error_message}", exc_info=True)
            return {}, error_message, False
        except Exception as e:
            error_message = f"Erreur interne validation/conversion config: {e}"
            logger.error(f"Validation/Conversion Config: {error_message}", exc_info=True)
            return {}, error_message, False


# --- Instanciation ---
config_manager = ConfigManager()

# --- Exports ---
__all__ = ["SYMBOL", "VALID_TIMEFRAMES", "config_manager", "ConfigManager"]
