import pandas as pd
import numpy as np
import pandas_ta as ta  # Pour les indicateurs techniques
from typing import Dict, Tuple, Optional, Any
import logging

logger = logging.getLogger(__name__)


def calculate_supertrend(
    df: pd.DataFrame, atr_period: int = 3, atr_multiplier: float = 1.5
) -> pd.DataFrame:
    """Calcule le Supertrend."""
    # Calculer l'ATR
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=atr_period)

    # Calculer les bandes
    df["upperband"] = ((df["high"] + df["low"]) / 2) + (atr_multiplier * df["atr"])
    df["lowerband"] = ((df["high"] + df["low"]) / 2) - (atr_multiplier * df["atr"])

    # Initialiser le Supertrend
    df["supertrend"] = df["close"].copy()
    df["supertrend_direction"] = 0  # 1 pour haussier, -1 pour baissier

    # Vérifier qu'il y a assez de données
    if len(df) <= 1:
        return df

    for i in range(1, len(df)):
        # S'assurer que les valeurs précédentes existent
        prev_close = df["close"].iloc[i - 1]
        prev_upperband = df["upperband"].iloc[i - 1]
        prev_lowerband = df["lowerband"].iloc[i - 1]
        prev_direction = df["supertrend_direction"].iloc[i - 1]

        current_close = df["close"].iloc[i]

        if (
            pd.isna(prev_close)
            or pd.isna(prev_upperband)
            or pd.isna(prev_lowerband)
            or pd.isna(current_close)
        ):
            # En cas de valeur manquante, conserver la direction précédente
            df.loc[df.index[i], "supertrend_direction"] = prev_direction
            continue

        if current_close > prev_upperband:
            df.loc[df.index[i], "supertrend_direction"] = 1
        elif current_close < prev_lowerband:
            df.loc[df.index[i], "supertrend_direction"] = -1
        else:
            df.loc[df.index[i], "supertrend_direction"] = prev_direction

    return df


def calculate_indicators(
    klines_df: pd.DataFrame, config: Dict[str, Any]
) -> pd.DataFrame:
    """Calcule tous les indicateurs techniques nécessaires."""
    try:
        # Vérifier si assez de données
        if len(klines_df) < 20:  # Minimum requis pour les indicateurs
            logger.warning("Not enough data for indicators calculation")
            return klines_df

        # Supertrend
        klines_df = calculate_supertrend(klines_df, atr_period=3, atr_multiplier=1.5)

        # RSI
        rsi_series = ta.rsi(klines_df["close"], length=7)
        klines_df["rsi"] = (
            rsi_series if rsi_series is not None else pd.Series(index=klines_df.index)
        )

        # Stochastic
        stoch = ta.stoch(
            klines_df["high"],
            klines_df["low"],
            klines_df["close"],
            k=14,
            d=3,
            smooth_k=3,
        )
        if stoch is not None:
            klines_df["stoch_k"] = stoch["STOCHk_14_3_3"]
            klines_df["stoch_d"] = stoch["STOCHd_14_3_3"]
        else:
            klines_df["stoch_k"] = pd.Series(index=klines_df.index)
            klines_df["stoch_d"] = pd.Series(index=klines_df.index)

        # Bollinger Bands
        bbands = ta.bbands(klines_df["close"], length=20, std=2)
        if bbands is not None:
            klines_df["bb_upper"] = bbands["BBU_20_2.0"]
            klines_df["bb_middle"] = bbands["BBM_20_2.0"]
            klines_df["bb_lower"] = bbands["BBL_20_2.0"]
        else:
            klines_df["bb_upper"] = pd.Series(index=klines_df.index)
            klines_df["bb_middle"] = pd.Series(index=klines_df.index)
            klines_df["bb_lower"] = pd.Series(index=klines_df.index)

        # Volume moyen
        volume_sma = ta.sma(klines_df["volume"], length=20)
        klines_df["volume_sma"] = (
            volume_sma if volume_sma is not None else pd.Series(index=klines_df.index)
        )

        return klines_df

    except Exception as e:
        logger.error(f"Erreur dans le calcul des indicateurs: {str(e)}")
        raise


def check_long_conditions(row: pd.Series, prev_row: pd.Series) -> Tuple[bool, str]:
    """Vérifie les conditions d'entrée en position longue."""
    try:
        reasons = []

        # Filtre 1: Supertrend
        if row["supertrend_direction"] != 1:
            return False, "Supertrend non haussier"

        # Filtre 2: RSI et Stochastic
        if not (50 < row["rsi"] < 70):
            return False, "RSI hors zone (50-70)"

        # Vérifier le croisement stochastique
        if not (
            row["stoch_k"] > row["stoch_d"]
            and prev_row["stoch_k"] <= prev_row["stoch_d"]
        ):
            return False, "Pas de croisement Stoch K>D"

        # Filtre 3: Bollinger Bands
        if row["close"] > row["bb_lower"] * 1.01:  # 1% au-dessus de la bande inf
            return False, "Prix trop éloigné de la bande inférieure"

        # Volume
        if row["volume"] <= row["volume_sma"]:
            return False, "Volume insuffisant"

        return True, "Tous les filtres validés pour LONG"

    except Exception as e:
        logger.error(f"Erreur dans check_long_conditions: {str(e)}")
        return False, f"Erreur technique: {str(e)}"


def check_short_conditions(row: pd.Series, prev_row: pd.Series) -> Tuple[bool, str]:
    """Vérifie les conditions d'entrée en position courte."""
    try:
        reasons = []

        # Filtre 1: Supertrend
        if row["supertrend_direction"] != -1:
            return False, "Supertrend non baissier"

        # Filtre 2: RSI et Stochastic
        if not (30 < row["rsi"] < 50):
            return False, "RSI hors zone (30-50)"

        # Vérifier le croisement stochastique
        if not (
            row["stoch_k"] < row["stoch_d"]
            and prev_row["stoch_k"] >= prev_row["stoch_d"]
        ):
            return False, "Pas de croisement Stoch K<D"

        # Filtre 3: Bollinger Bands
        if row["close"] < row["bb_upper"] * 0.99:  # 1% sous la bande sup
            return False, "Prix trop éloigné de la bande supérieure"

        # Volume
        if row["volume"] <= row["volume_sma"]:
            return False, "Volume insuffisant"

        return True, "Tous les filtres validés pour SHORT"

    except Exception as e:
        logger.error(f"Erreur dans check_short_conditions: {str(e)}")
        return False, f"Erreur technique: {str(e)}"


def calculate_dynamic_sl_tp(
    entry_price: float,
    side: str,
    config: Dict[str, Any],
    recent_low: float,
    recent_high: float,
    atr_value: float,
) -> Tuple[float, float, float]:
    """Calcule les niveaux de SL et TP dynamiques."""

    # SL de base (0.5% ou 2×ATR, le plus petit des deux)
    base_sl_pct = config.get("STOP_LOSS_PERCENTAGE", 0.005)
    atr_sl = (atr_value * 2) / entry_price
    sl_pct = min(base_sl_pct, atr_sl)

    if side == "BUY":
        # Pour un LONG
        sl_price = entry_price * (1 - sl_pct)
        # Utiliser le plus bas récent si plus proche
        if recent_low > 0:
            sl_price = max(sl_price, recent_low * 0.995)  # 0.5% sous le plus bas

        # TP1 à 1.5× la distance du SL
        tp1_price = entry_price * (1 + (sl_pct * 1.5))
        # TP2 à 2× la distance du SL
        tp2_price = entry_price * (1 + (sl_pct * 2))

    else:  # SELL
        # Pour un SHORT
        sl_price = entry_price * (1 + sl_pct)
        # Utiliser le plus haut récent si plus proche
        if recent_high > 0:
            sl_price = min(sl_price, recent_high * 1.005)  # 0.5% au-dessus du plus haut

        # TP1 à 1.5× la distance du SL
        tp1_price = entry_price * (1 - (sl_pct * 1.5))
        # TP2 à 2× la distance du SL
        tp2_price = entry_price * (1 - (sl_pct * 2))

    return sl_price, tp1_price, tp2_price


def check_exit_conditions(
    current_price: float,
    position_data: Dict[str, Any],
    config: Dict[str, Any],
    position_duration: int,
) -> Tuple[bool, str]:
    """
    Vérifie les conditions de sortie, incluant le trailing stop et le time stop.

    Args:
        current_price: Prix actuel
        position_data: Données de la position (prix d'entrée, côté, etc.)
        config: Configuration du bot
        position_duration: Durée de la position en secondes

    Returns:
        (bool, str): (Sortir ou non, Raison de la sortie)
    """
    try:
        entry_price = float(position_data.get("entry_price", 0))
        side = position_data.get("side", "")

        if not entry_price or not side:
            return True, "Données de position invalides"

        # Time Stop (15 minutes = 900 secondes)
        if position_duration > 900:
            return True, "Time Stop (15 minutes)"

        # Trailing Stop (0.3%)
        trailing_stop_pct = 0.003
        if side == "BUY":
            trailing_stop_price = current_price * (1 - trailing_stop_pct)
            if (
                position_data.get("highest_price", entry_price)
                * (1 - trailing_stop_pct)
                > entry_price
            ):
                if current_price < trailing_stop_price:
                    return True, f"Trailing Stop déclenché @ {trailing_stop_price:.8f}"
        else:  # SELL
            trailing_stop_price = current_price * (1 + trailing_stop_pct)
            if (
                position_data.get("lowest_price", entry_price) * (1 + trailing_stop_pct)
                < entry_price
            ):
                if current_price > trailing_stop_price:
                    return True, f"Trailing Stop déclenché @ {trailing_stop_price:.8f}"

        return False, "Pas de condition de sortie"

    except Exception as e:
        logger.error(f"Erreur dans check_exit_conditions: {str(e)}")
        return True, f"Erreur technique: {str(e)}"
