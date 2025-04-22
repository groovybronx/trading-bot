# /Users/davidmichels/Desktop/trading-bot/backend/strategies/scalping_strategy_2.py
import pandas as pd
import numpy as np
import pandas_ta as ta
from typing import Dict, Tuple, Optional, Any, Union
import logging
from decimal import Decimal, InvalidOperation

# Importer les utilitaires partagés mis à jour
from utils.order_utils import (
    format_quantity,
    get_min_notional,
    check_min_notional,
    format_price, # Ajouté si on veut formater le prix SL/TP
)


logger = logging.getLogger(__name__)

def calculate_supertrend(
    df: pd.DataFrame, atr_period: int = 3, atr_multiplier: float = 1.5
) -> pd.DataFrame:
    """Calcule le Supertrend."""
    try:
        # Calculer l'ATR
        atr = ta.atr(df["high"], df["low"], df["close"], length=atr_period)
        if atr is None: raise ValueError("ATR calculation failed")
        df["atr"] = atr

        # Calculer les bandes
        # Vérifier si les colonnes existent et sont numériques avant le calcul
        if not all(col in df.columns and pd.api.types.is_numeric_dtype(df[col]) for col in ["high", "low", "atr"]):
             logger.error("Supertrend: Colonnes 'high', 'low' ou 'atr' manquantes ou non numériques.")
             # Remplir avec NaN si les colonnes de base manquent
             df["upperband"] = np.nan
             df["lowerband"] = np.nan
             df["supertrend"] = np.nan
             df["supertrend_direction"] = 0
             return df

        hl2 = (df["high"] + df["low"]) / 2
        df["upperband"] = hl2 + (atr_multiplier * df["atr"])
        df["lowerband"] = hl2 - (atr_multiplier * df["atr"])

        # Initialiser le Supertrend et la direction
        df["supertrend"] = np.nan # Initialiser avec NaN
        df["supertrend_direction"] = 0  # 1 pour haussier, -1 pour baissier

        # Itérer pour déterminer la direction et la valeur du Supertrend
        for i in range(1, len(df)):
            # Utiliser .get() avec défaut pour éviter KeyError si index n'existe pas (peu probable ici)
            # et pd.isna pour vérifier les valeurs
            prev_st = df["supertrend"].iloc[i-1] if i > 0 else np.nan
            prev_st_dir = df["supertrend_direction"].iloc[i-1] if i > 0 else 0
            prev_close = df["close"].iloc[i-1] if i > 0 else np.nan
            curr_close = df["close"].iloc[i]
            curr_upper = df["upperband"].iloc[i]
            curr_lower = df["lowerband"].iloc[i]

            # Vérifier si les valeurs nécessaires sont valides
            if pd.isna(curr_close) or pd.isna(curr_upper) or pd.isna(curr_lower):
                # Si les données actuelles sont invalides, propager l'état précédent ou rester neutre
                df.loc[df.index[i], "supertrend_direction"] = prev_st_dir
                df.loc[df.index[i], "supertrend"] = prev_st
                continue

            # Gestion des NaN initiaux pour prev_st
            if pd.isna(prev_st):
                 if curr_close > curr_upper:
                      df.loc[df.index[i], "supertrend_direction"] = 1
                      df.loc[df.index[i], "supertrend"] = curr_lower
                 else:
                      df.loc[df.index[i], "supertrend_direction"] = -1
                      df.loc[df.index[i], "supertrend"] = curr_upper
                 continue

            # Logique Supertrend standard
            st_dir = 0
            st_val = np.nan

            if prev_st_dir == 1: # Tendance haussière précédente
                if curr_close > prev_st: # Reste au-dessus
                    st_dir = 1
                    # Utiliser max seulement si les deux sont valides
                    st_val = max(prev_st, curr_lower) if pd.notna(prev_st) and pd.notna(curr_lower) else (prev_st if pd.notna(prev_st) else curr_lower)
                else: # Croise en dessous
                    st_dir = -1
                    st_val = curr_upper # Le ST devient la bande supérieure
            elif prev_st_dir == -1: # Tendance baissière précédente
                 if curr_close < prev_st: # Reste en dessous
                      st_dir = -1
                      # Utiliser min seulement si les deux sont valides
                      st_val = min(prev_st, curr_upper) if pd.notna(prev_st) and pd.notna(curr_upper) else (prev_st if pd.notna(prev_st) else curr_upper)
                 else: # Croise au-dessus
                      st_dir = 1
                      st_val = curr_lower # Le ST devient la bande inférieure
            else: # Direction précédente neutre (0) - devrait être géré par le cas initial NaN
                 st_dir = prev_st_dir
                 st_val = prev_st


            df.loc[df.index[i], "supertrend_direction"] = st_dir
            df.loc[df.index[i], "supertrend"] = st_val

        # CORRECTION: Utiliser .bfill() directement et supprimer # type: ignore
        df["supertrend"] = df["supertrend"].bfill()
        df["supertrend_direction"] = df["supertrend_direction"].bfill()

    except Exception as e:
        logger.error(f"Erreur calcul Supertrend: {e}", exc_info=True)
        # Remplir avec des valeurs neutres en cas d'erreur?
        df["atr"] = np.nan
        df["upperband"] = np.nan
        df["lowerband"] = np.nan
        df["supertrend"] = np.nan
        df["supertrend_direction"] = 0
    return df

# Le reste du fichier (calculate_indicators, check_long_conditions, etc.) reste inchangé...
# ... (code des autres fonctions) ...

# calculate_indicators reste globalement inchangé mais utilise les noms de config
def calculate_indicators(
    klines_df: pd.DataFrame, config: Dict[str, Any]
) -> pd.DataFrame:
    """Calcule tous les indicateurs techniques nécessaires pour SCALPING2."""
    try:
        # Vérifier si les colonnes nécessaires existent et sont numériques
        required_numeric_cols = ["high", "low", "close", "volume"]
        for col in required_numeric_cols:
            # Vérifier si la colonne existe et si elle est numérique OU peut être convertie
            if col not in klines_df.columns:
                 logger.error(f"SCALPING2 Indicators: Colonne requise '{col}' manquante.")
                 # Ajouter des colonnes NaN et retourner
                 cols_to_add = ["atr", "upperband", "lowerband", "supertrend", "supertrend_direction",
                                "rsi", "stoch_k", "stoch_d", "bb_upper", "bb_middle", "bb_lower", "volume_sma"]
                 for c in cols_to_add: klines_df[c] = np.nan
                 return klines_df
            # Tenter la conversion si ce n'est pas déjà numérique
            if not pd.api.types.is_numeric_dtype(klines_df[col]):
                 klines_df[col] = pd.to_numeric(klines_df[col], errors='coerce')
                 # Re-vérifier après conversion
                 if not pd.api.types.is_numeric_dtype(klines_df[col]):
                      logger.error(f"SCALPING2 Indicators: Colonne '{col}' non numérique même après conversion.")
                      cols_to_add = ["atr", "upperband", "lowerband", "supertrend", "supertrend_direction",
                                     "rsi", "stoch_k", "stoch_d", "bb_upper", "bb_middle", "bb_lower", "volume_sma"]
                      for c in cols_to_add: klines_df[c] = np.nan
                      return klines_df

        required_len = max(
            config.get("BB_PERIOD", 20),
            config.get("VOLUME_MA_PERIOD", 20),
            config.get("STOCH_K_PERIOD", 14) + config.get("STOCH_D_PERIOD", 3), # Approximatif
            config.get("SCALPING_RSI_PERIOD", 7),
            config.get("SUPERTREND_ATR_PERIOD", 3) + 1 # Besoin d'une période de plus pour ST
        )

        if len(klines_df) < required_len:
            logger.warning(f"SCALPING2: Données insuffisantes ({len(klines_df)}/{required_len}) pour indicateurs.")
            # Retourner le DF avec des colonnes NaN pour éviter KeyError plus tard
            cols = ["atr", "upperband", "lowerband", "supertrend", "supertrend_direction",
                    "rsi", "stoch_k", "stoch_d", "bb_upper", "bb_middle", "bb_lower", "volume_sma"]
            for col in cols: klines_df[col] = np.nan
            return klines_df

        # Supertrend
        klines_df = calculate_supertrend(
            klines_df,
            atr_period=config.get("SUPERTREND_ATR_PERIOD", 3),
            atr_multiplier=config.get("SUPERTREND_ATR_MULTIPLIER", 1.5)
        )

        # RSI
        rsi_series = ta.rsi(klines_df["close"], length=config.get("SCALPING_RSI_PERIOD", 7))
        klines_df["rsi"] = rsi_series if rsi_series is not None else np.nan

        # Stochastic
        stoch = ta.stoch(
            klines_df["high"], klines_df["low"], klines_df["close"],
            k=config.get("STOCH_K_PERIOD", 14),
            d=config.get("STOCH_D_PERIOD", 3),
            smooth_k=config.get("STOCH_SMOOTH", 3),
        )
        if stoch is not None and not stoch.empty:
             # Les noms de colonnes peuvent varier légèrement avec pandas_ta versions
             k_col = next((col for col in stoch.columns if col.startswith('STOCHk')), None)
             d_col = next((col for col in stoch.columns if col.startswith('STOCHd')), None)
             klines_df["stoch_k"] = stoch[k_col] if k_col and k_col in stoch.columns else np.nan
             klines_df["stoch_d"] = stoch[d_col] if d_col and d_col in stoch.columns else np.nan
        else:
            klines_df["stoch_k"] = np.nan
            klines_df["stoch_d"] = np.nan

        # Bollinger Bands
        bbands = ta.bbands(
            klines_df["close"],
            length=config.get("BB_PERIOD", 20),
            std=config.get("BB_STD", 2.0)
        )
        if bbands is not None and not bbands.empty:
            # Les noms de colonnes peuvent varier
            u_col = next((col for col in bbands.columns if col.startswith('BBU')), None)
            m_col = next((col for col in bbands.columns if col.startswith('BBM')), None)
            l_col = next((col for col in bbands.columns if col.startswith('BBL')), None)
            klines_df["bb_upper"] = bbands[u_col] if u_col and u_col in bbands.columns else np.nan
            klines_df["bb_middle"] = bbands[m_col] if m_col and m_col in bbands.columns else np.nan
            klines_df["bb_lower"] = bbands[l_col] if l_col and l_col in bbands.columns else np.nan
        else:
            klines_df["bb_upper"] = np.nan
            klines_df["bb_middle"] = np.nan
            klines_df["bb_lower"] = np.nan

        # Volume moyen
        volume_sma = ta.sma(klines_df["volume"], length=config.get("VOLUME_MA_PERIOD", 20))
        klines_df["volume_sma"] = volume_sma if volume_sma is not None else np.nan

        return klines_df # Retourner le DF avec potentiellement des NaN au début

    except Exception as e:
        logger.error(f"Erreur dans le calcul des indicateurs SCALPING2: {e}", exc_info=True)
        # En cas d'erreur, retourner le DF avec des colonnes NaN
        cols = ["atr", "upperband", "lowerband", "supertrend", "supertrend_direction",
                "rsi", "stoch_k", "stoch_d", "bb_upper", "bb_middle", "bb_lower", "volume_sma"]
        for col in cols: klines_df[col] = np.nan
        return klines_df


# check_long_conditions et check_short_conditions restent globalement inchangés
# (La logique des filtres est spécifique à la stratégie)
def check_long_conditions(row: pd.Series, prev_row: pd.Series) -> Tuple[bool, str]:
    """Vérifie les conditions d'entrée en position longue pour SCALPING2."""
    try:
        # Vérifier si les données nécessaires existent (suite aux modifs de calculate_indicators)
        required_cols = ["supertrend_direction", "rsi", "stoch_k", "stoch_d", "bb_lower", "volume", "volume_sma", "close"]
        # Utiliser pd.isna pour vérifier les valeurs dans la Series
        if any(pd.isna(row.get(col)) for col in required_cols) or any(pd.isna(prev_row.get(col)) for col in required_cols):
             missing_current = [col for col in required_cols if pd.isna(row.get(col))]
             missing_prev = [col for col in required_cols if pd.isna(prev_row.get(col))]
             # logger.debug(f"SCALPING2 Long Check: Indicateurs manquants ou NaN. Current: {missing_current}, Prev: {missing_prev}") # Verbeux
             return False, "Données indicateurs manquantes"

        # Filtre 1: Supertrend
        if row["supertrend_direction"] != 1: return False, "Supertrend non haussier"
        # Filtre 2: RSI et Stochastic
        if not (50 < row["rsi"] < 70): return False, "RSI hors zone (50-70)"
        if not (row["stoch_k"] > row["stoch_d"] and prev_row["stoch_k"] <= prev_row["stoch_d"]): return False, "Pas de croisement Stoch K>D"
        # Filtre 3: Bollinger Bands
        # Assurer que bb_lower est un Decimal valide avant la comparaison
        bb_lower_val = row["bb_lower"]
        if not isinstance(bb_lower_val, Decimal): return False, "Valeur bb_lower invalide"
        if row["close"] < bb_lower_val or row["close"] > bb_lower_val * Decimal("1.01"): # Doit être proche ou au-dessus de la bande inf
             return False, "Prix non proche de la bande inférieure BB"
        # Volume
        if row["volume"] <= row["volume_sma"]: return False, "Volume insuffisant"

        return True, "Tous les filtres validés pour LONG"
    except KeyError as e:
        logger.error(f"Erreur clé manquante dans check_long_conditions: {e}")
        return False, f"Erreur interne (clé: {e})"
    except Exception as e:
        logger.error(f"Erreur dans check_long_conditions: {e}", exc_info=True)
        return False, f"Erreur technique: {e}"

def check_short_conditions(row: pd.Series, prev_row: pd.Series) -> Tuple[bool, str]:
    """Vérifie les conditions d'entrée en position courte pour SCALPING2."""
    try:
        required_cols = ["supertrend_direction", "rsi", "stoch_k", "stoch_d", "bb_upper", "volume", "volume_sma", "close"]
        # Utiliser pd.isna pour vérifier les valeurs dans la Series
        if any(pd.isna(row.get(col)) for col in required_cols) or any(pd.isna(prev_row.get(col)) for col in required_cols):
             missing_current = [col for col in required_cols if pd.isna(row.get(col))]
             missing_prev = [col for col in required_cols if pd.isna(prev_row.get(col))]
             # logger.debug(f"SCALPING2 Short Check: Indicateurs manquants ou NaN. Current: {missing_current}, Prev: {missing_prev}") # Verbeux
             return False, "Données indicateurs manquantes"

        # Filtre 1: Supertrend
        if row["supertrend_direction"] != -1: return False, "Supertrend non baissier"
        # Filtre 2: RSI et Stochastic
        if not (30 < row["rsi"] < 50): return False, "RSI hors zone (30-50)"
        if not (row["stoch_k"] < row["stoch_d"] and prev_row["stoch_k"] >= prev_row["stoch_d"]): return False, "Pas de croisement Stoch K<D"
        # Filtre 3: Bollinger Bands
        # Assurer que bb_upper est un Decimal valide avant la comparaison
        bb_upper_val = row["bb_upper"]
        if not isinstance(bb_upper_val, Decimal): return False, "Valeur bb_upper invalide"
        if row["close"] > bb_upper_val or row["close"] < bb_upper_val * Decimal("0.99"): # Doit être proche ou en dessous de la bande sup
            return False, "Prix non proche de la bande supérieure BB"
        # Volume
        if row["volume"] <= row["volume_sma"]: return False, "Volume insuffisant"

        return True, "Tous les filtres validés pour SHORT"
    except KeyError as e:
        logger.error(f"Erreur clé manquante dans check_short_conditions: {e}")
        return False, f"Erreur interne (clé: {e})"
    except Exception as e:
        logger.error(f"Erreur dans check_short_conditions: {e}", exc_info=True)
        return False, f"Erreur technique: {e}"


def calculate_dynamic_sl_tp(
    entry_price: Decimal,
    side: str,
    config: Dict[str, Any],
    recent_low: Decimal,
    recent_high: Decimal,
    atr_value: Decimal,
) -> Tuple[Decimal, Decimal, Decimal]:
    """
    Calcule les niveaux de SL et TP dynamiques en utilisant Decimal.
    Retourne (sl_price, tp1_price, tp2_price) en Decimal.
    """
    try:
        # Vérifier si atr_value est valide
        if not isinstance(atr_value, Decimal) or atr_value <= 0:
             logger.warning(f"ATR invalide ({atr_value}) pour calcul SL/TP dynamique. Utilisation SL/TP fixes.")
             raise ValueError("ATR invalide") # Force l'utilisation du fallback

        if entry_price <= 0:
             raise ValueError("Prix d'entrée invalide pour calcul SL/TP")

        # SL de base (fraction depuis config) ou basé sur ATR
        base_sl_frac: Decimal = config.get("STOP_LOSS_PERCENTAGE", Decimal("0.005"))
        atr_sl_frac = (atr_value * Decimal("2")) / entry_price # 2 * ATR comme fraction du prix
        sl_frac = min(base_sl_frac, atr_sl_frac)

        # Ratios TP par rapport au risque (distance SL)
        tp1_ratio = Decimal("1.5")
        tp2_ratio = Decimal("2.0")

        if side == "BUY":
            # SL pour LONG: sous le prix d'entrée
            sl_price = entry_price * (Decimal(1) - sl_frac)
            # Ajuster avec le plus bas récent (si plus conservateur et valide)
            if isinstance(recent_low, Decimal) and recent_low > 0:
                sl_price = min(sl_price, recent_low * (Decimal(1) - Decimal("0.001"))) # Légèrement sous le plus bas

            # TP pour LONG: au-dessus du prix d'entrée
            risk_amount = entry_price - sl_price # Risque en $ par unité
            if risk_amount <= 0: raise ValueError("Risque calculé non positif pour BUY")
            tp1_price = entry_price + (risk_amount * tp1_ratio)
            tp2_price = entry_price + (risk_amount * tp2_ratio)

        else:  # SELL
            # SL pour SHORT: au-dessus du prix d'entrée
            sl_price = entry_price * (Decimal(1) + sl_frac)
            # Ajuster avec le plus haut récent (si plus conservateur et valide)
            if isinstance(recent_high, Decimal) and recent_high > 0:
                sl_price = max(sl_price, recent_high * (Decimal(1) + Decimal("0.001"))) # Légèrement au-dessus du plus haut

            # TP pour SHORT: sous le prix d'entrée
            risk_amount = sl_price - entry_price # Risque en $ par unité
            if risk_amount <= 0: raise ValueError("Risque calculé non positif pour SELL")
            tp1_price = entry_price - (risk_amount * tp1_ratio)
            tp2_price = entry_price - (risk_amount * tp2_ratio)

        # Assurer que les prix TP sont valides (pas négatifs)
        tp1_price = max(tp1_price, Decimal("0.00000001"))
        tp2_price = max(tp2_price, Decimal("0.00000001"))

        return sl_price, tp1_price, tp2_price

    except (ValueError, InvalidOperation, TypeError) as e:
         logger.error(f"Erreur calcul SL/TP dynamique: {e}", exc_info=False) # exc_info=False pour moins de bruit
         # Retourner des valeurs basées sur % fixe si ATR échoue ou autre erreur
         sl_frac_fallback = config.get("STOP_LOSS_PERCENTAGE", Decimal("0.005"))
         tp1_frac_fallback = config.get("TAKE_PROFIT_1_PERCENTAGE", Decimal("0.01"))
         tp2_frac_fallback = config.get("TAKE_PROFIT_2_PERCENTAGE", Decimal("0.015"))
         if entry_price <= 0: # Si même le prix d'entrée est invalide, retourner 0
              logger.error("Prix d'entrée invalide, impossible de calculer SL/TP fallback.")
              return Decimal(0), Decimal(0), Decimal(0)
         if side == "BUY":
              sl = entry_price * (1 - sl_frac_fallback)
              tp1 = entry_price * (1 + tp1_frac_fallback)
              tp2 = entry_price * (1 + tp2_frac_fallback)
         else:
              sl = entry_price * (1 + sl_frac_fallback)
              tp1 = entry_price * (1 - tp1_frac_fallback)
              tp2 = entry_price * (1 - tp2_frac_fallback)
         logger.warning("Utilisation de SL/TP fixes par défaut suite à une erreur.")
         return sl, tp1, tp2


def check_exit_conditions(
    current_price: Decimal,
    position_data: Dict[str, Any],
    config: Dict[str, Any],
    position_duration_seconds: int,
) -> Tuple[bool, str]:
    """
    Vérifie les conditions de sortie (SL, TP, Trailing, TimeStop) pour SCALPING2.
    Utilise Decimal. Nécessite que position_data contienne 'highest_price'/'lowest_price'.
    """
    try:
        # Utiliser .get() avec défaut pour éviter KeyError et convertir en Decimal
        entry_price_str = position_data.get("avg_price")
        sl_price_str = position_data.get("sl_price")
        tp1_price_str = position_data.get("tp1_price")
        highest_price_str = position_data.get("highest_price")
        lowest_price_str = position_data.get("lowest_price")
        side = position_data.get("side", "") # 'BUY' ou 'SELL'

        # Convertir en Decimal, gérer None ou conversion invalide
        try:
            entry_price = Decimal(str(entry_price_str)) if entry_price_str is not None else None
            sl_price = Decimal(str(sl_price_str)) if sl_price_str is not None else None
            tp1_price = Decimal(str(tp1_price_str)) if tp1_price_str is not None else None
            highest_price = Decimal(str(highest_price_str)) if highest_price_str is not None else entry_price # Default to entry
            lowest_price = Decimal(str(lowest_price_str)) if lowest_price_str is not None else entry_price # Default to entry
        except (InvalidOperation, TypeError):
             logger.error(f"SCALPING2 Exit Check: Erreur conversion Decimal données position: {position_data}")
             return True, "Erreur conversion données position" # Forcer sortie

        # Vérifier si les valeurs essentielles sont valides
        if not side or entry_price is None or entry_price <= 0 or sl_price is None or sl_price <= 0 or tp1_price is None or tp1_price <= 0:
            logger.error(f"SCALPING2 Exit Check: Données de position invalides après conversion: Side={side}, Entry={entry_price}, SL={sl_price}, TP1={tp1_price}")
            return True, "Données de position invalides" # Forcer sortie si données corrompues

        # 1. Vérification SL / TP
        if side == "BUY":
            if current_price <= sl_price: return True, f"Stop Loss déclenché @ {sl_price:.8f}"
            if current_price >= tp1_price: return True, f"Take Profit 1 déclenché @ {tp1_price:.8f}"
        else: # SELL
            if current_price >= sl_price: return True, f"Stop Loss déclenché @ {sl_price:.8f}"
            if current_price <= tp1_price: return True, f"Take Profit 1 déclenché @ {tp1_price:.8f}"

        # 2. Time Stop
        time_stop_minutes = config.get("TIME_STOP_MINUTES", 15)
        if position_duration_seconds > time_stop_minutes * 60:
            return True, f"Time Stop ({time_stop_minutes} min)"

        # 3. Trailing Stop
        trailing_stop_frac = config.get("TRAILING_STOP_PERCENTAGE", Decimal("0.003"))
        # Assurer que highest/lowest sont valides pour le calcul
        if highest_price is None or lowest_price is None:
             logger.warning("Highest/Lowest price non disponible pour Trailing Stop.")
             highest_price = entry_price # Fallback
             lowest_price = entry_price  # Fallback

        if trailing_stop_frac > 0:
            if side == "BUY":
                # Calculer le prix de déclenchement du trailing stop
                trailing_trigger_price = highest_price * (Decimal(1) - trailing_stop_frac)
                # Activer le trailing seulement s'il est au-dessus du prix d'entrée (profitable)
                if trailing_trigger_price > entry_price:
                    if current_price < trailing_trigger_price:
                        return True, f"Trailing Stop (LONG) déclenché @ {trailing_trigger_price:.8f}"
            else: # SELL
                trailing_trigger_price = lowest_price * (Decimal(1) + trailing_stop_frac)
                # Activer le trailing seulement s'il est en dessous du prix d'entrée (profitable)
                if trailing_trigger_price < entry_price:
                    if current_price > trailing_trigger_price:
                        return True, f"Trailing Stop (SHORT) déclenché @ {trailing_trigger_price:.8f}"

        # 4. Autres conditions de sortie spécifiques à la stratégie?
        #    (Ex: Inversion Supertrend, croisement Stochastique opposé, etc.)
        #    Ces vérifications nécessiteraient les données indicateurs actuelles (row).

        return False, "Pas de condition de sortie"

    except (InvalidOperation, TypeError, KeyError, ValueError) as e:
        logger.error(f"Erreur dans check_exit_conditions SCALPING2: {e}", exc_info=True)
        return True, f"Erreur technique exit check: {e}" # Forcer sortie en cas d'erreur
