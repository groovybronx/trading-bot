import logging
import pandas as pd
import numpy as np
import pandas_ta as ta
from typing import Dict, Tuple, Optional, Any
from decimal import Decimal, InvalidOperation

# Import the base class
from .base_strategy import BaseStrategy

# Import utilities
from utils.order_utils import (
    format_quantity,
    get_min_notional,
    check_min_notional,
    format_price,
)

logger = logging.getLogger(__name__)

class ScalpingStrategy2(BaseStrategy):
    """
    Scalping strategy based on technical indicators (Supertrend, RSI, Stoch, BB).
    Inherits from BaseStrategy.
    """

    def __init__(self):
        """Initializes the Scalping Strategy 2."""
        super().__init__(strategy_name="SCALPING2")
        logger.info("ScalpingStrategy2 initialized.")

    def _calculate_supertrend(self, df: pd.DataFrame, atr_period: int, atr_multiplier: float) -> pd.DataFrame:
        """Calculates the Supertrend indicator. (Private method)"""
        try:
            # Ensure input columns are numeric first
            for col in ["High", "Low", "Close"]:
                 if col not in df.columns or not pd.api.types.is_numeric_dtype(df[col]):
                      logger.error(f"Supertrend: Column '{col}' missing or not numeric.")
                      df["atr"], df["upperband"], df["lowerband"], df["supertrend"], df["supertrend_direction"] = np.nan, np.nan, np.nan, np.nan, 0
                      return df

            atr = ta.atr(df["High"], df["Low"], df["Close"], length=atr_period)
            if atr is None or atr.isnull().all():
                raise ValueError("ATR calculation failed or resulted in all NaNs")
            df["atr"] = atr

            # Check ATR column
            if "atr" not in df.columns or not pd.api.types.is_numeric_dtype(df["atr"]):
                 logger.error("Supertrend: 'atr' column missing or not numeric after calculation.")
                 df["supertrend"], df["supertrend_direction"] = np.nan, 0
                 return df

            # Calculations require float, ensure type consistency
            high_f = df["High"].astype(float)
            low_f = df["Low"].astype(float)
            close_f = df["Close"].astype(float)
            atr_f = df["atr"].astype(float)
            atr_multiplier_f = float(atr_multiplier) # Ensure multiplier is float

            hl2 = (high_f + low_f) / 2.0
            df["upperband"] = hl2 + (atr_multiplier_f * atr_f)
            df["lowerband"] = hl2 - (atr_multiplier_f * atr_f)
            df["supertrend"] = np.nan # Initialize with float NaN
            df["supertrend_direction"] = 0 # Initialize with int

            # Convert relevant columns to numpy arrays for potentially faster iteration
            close_np = close_f.to_numpy()
            upperband_np = df["upperband"].to_numpy()
            lowerband_np = df["lowerband"].to_numpy()
            supertrend_np = df["supertrend"].to_numpy() # Get as numpy array
            direction_np = df["supertrend_direction"].to_numpy().astype(int) # Get as numpy array, ensure int

            for i in range(1, len(df)):
                prev_st = supertrend_np[i-1]
                prev_st_dir = direction_np[i-1]
                curr_close = close_np[i]
                curr_upper = upperband_np[i]
                curr_lower = lowerband_np[i]

                # Check for NaNs in current values needed for logic
                if np.isnan(curr_close) or np.isnan(curr_upper) or np.isnan(curr_lower):
                    direction_np[i] = prev_st_dir # Propagate previous state
                    supertrend_np[i] = prev_st
                    continue

                # Handle initial NaN for prev_st
                if np.isnan(prev_st):
                    if curr_close > curr_upper:
                        direction_np[i] = 1
                        supertrend_np[i] = curr_lower
                    else:
                        direction_np[i] = -1
                        supertrend_np[i] = curr_upper
                    continue

                # Main Supertrend Logic (using floats and NaN checks)
                st_dir, st_val = 0, np.nan
                if prev_st_dir == 1:
                    if curr_close > prev_st:
                        st_dir = 1
                        st_val = np.fmax(prev_st, curr_lower) # NaN-safe max
                    else: # curr_close <= prev_st
                        st_dir = -1
                        st_val = curr_upper
                elif prev_st_dir == -1:
                    if curr_close < prev_st:
                        st_dir = -1
                        st_val = np.fmin(prev_st, curr_upper) # NaN-safe min
                    else: # curr_close >= prev_st
                        st_dir = 1
                        st_val = curr_lower
                else: # Should not happen if initial NaN is handled
                    st_dir, st_val = prev_st_dir, prev_st

                direction_np[i] = st_dir
                supertrend_np[i] = st_val

            # Assign the calculated numpy arrays back to the DataFrame
            df["supertrend"] = supertrend_np
            df["supertrend_direction"] = direction_np

            # Forward fill to handle any remaining NaNs at the beginning
            df["supertrend"] = df["supertrend"].ffill()
            df["supertrend_direction"] = df["supertrend_direction"].ffill().fillna(0).astype(int)

        except Exception as e:
            logger.error(f"Error calculating Supertrend: {e}", exc_info=True)
            df["atr"], df["upperband"], df["lowerband"], df["supertrend"], df["supertrend_direction"] = np.nan, np.nan, np.nan, np.nan, 0
        return df


    def calculate_indicators(self, klines_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates Supertrend, RSI, Stoch, BB, Volume SMA indicators.
        Overrides the base class abstract method.
        """
        df = klines_df.copy()
        if df.empty:
            logger.warning("SCALPING2: Input DataFrame for indicators is empty.")
            return df

        required_cols = ["High", "Low", "Close", "Volume"]
        if not all(col in df.columns for col in required_cols):
             logger.error(f"SCALPING2 Indicators: Missing one or more required columns: {required_cols}")
             return klines_df

        # Ensure columns are numeric, attempting conversion if necessary
        for col in required_cols:
            if not pd.api.types.is_numeric_dtype(df[col]):
                original_type = df[col].dtype
                logger.debug(f"SCALPING2 Indicators: Column '{col}' is not numeric (type: {original_type}). Attempting conversion.")
                df[col] = pd.to_numeric(df[col], errors='coerce')
                # Check if conversion failed (column is still not numeric)
                if not pd.api.types.is_numeric_dtype(df[col]):
                    logger.error(f"SCALPING2 Indicators: Failed to convert column '{col}' (original type: {original_type}) to numeric. Check data source.")
                    # Return original df as we can't proceed reliably
                    return klines_df
                else:
                    logger.debug(f"SCALPING2 Indicators: Column '{col}' successfully converted to numeric.")
            # If already numeric, do nothing.

        # Drop rows where essential numeric columns ended up as NaN after conversion
        df.dropna(subset=required_cols, inplace=True)
        if df.empty:
             logger.warning("SCALPING2: DataFrame empty after dropping NaNs in essential columns.")
             return df

        try:
            st_atr_period = self.config.get("SUPERTREND_ATR_PERIOD", 3)
            st_atr_mult = self.config.get("SUPERTREND_ATR_MULTIPLIER", 1.5)
            rsi_period = self.config.get("SCALPING_RSI_PERIOD", 7)
            stoch_k = self.config.get("STOCH_K_PERIOD", 14)
            stoch_d = self.config.get("STOCH_D_PERIOD", 3)
            stoch_smooth = self.config.get("STOCH_SMOOTH", 3)
            bb_period = self.config.get("BB_PERIOD", 20)
            bb_std = self.config.get("BB_STD", 2.0)
            vol_ma_period = self.config.get("VOLUME_MA_PERIOD", 20)

            df = self._calculate_supertrend(df, st_atr_period, st_atr_mult)

            df.ta.rsi(length=rsi_period, append=True, col_names=('rsi',))
            stoch = df.ta.stoch(k=stoch_k, d=stoch_d, smooth_k=stoch_smooth)
            if stoch is not None:
                k_col = next((col for col in stoch.columns if col.startswith("STOCHk")), None)
                d_col = next((col for col in stoch.columns if col.startswith("STOCHd")), None)
                df['stoch_k'] = stoch[k_col] if k_col else np.nan
                df['stoch_d'] = stoch[d_col] if d_col else np.nan
            else: df['stoch_k'], df['stoch_d'] = np.nan, np.nan

            bbands = df.ta.bbands(length=bb_period, std=bb_std)
            if bbands is not None:
                u_col = next((col for col in bbands.columns if col.startswith("BBU")), None)
                m_col = next((col for col in bbands.columns if col.startswith("BBM")), None)
                l_col = next((col for col in bbands.columns if col.startswith("BBL")), None)
                df['bb_upper'] = bbands[u_col] if u_col else np.nan
                df['bb_middle'] = bbands[m_col] if m_col else np.nan
                df['bb_lower'] = bbands[l_col] if l_col else np.nan
            else: df['bb_upper'], df['bb_middle'], df['bb_lower'] = np.nan, np.nan, np.nan

            df.ta.sma(close='Volume', length=vol_ma_period, append=True, col_names=('volume_sma',))

            # Keep indicators as float/NaN. Conversion to Decimal will happen explicitly when needed.
            # Removing the problematic conversion loop:
            # decimal_cols = ['Close', 'Low', 'High', 'atr', 'bb_lower', 'bb_upper', 'volume_sma']
            # ... (loop removed) ...

            logger.debug(f"SCALPING2: Indicators calculated. DataFrame shape: {df.shape}")
            return df

        except Exception as e:
            logger.error(f"SCALPING2: Error calculating indicators: {e}", exc_info=True)
            return klines_df

    def _check_long_conditions(self, row: pd.Series, prev_row: pd.Series) -> Tuple[bool, str]:
        """Checks LONG entry conditions. (Private method)"""
        try:
            required_cols = ["supertrend_direction", "rsi", "stoch_k", "stoch_d", "bb_lower", "Volume", "volume_sma", "Close"]
            if any(pd.isna(row.get(col)) for col in required_cols) or any(pd.isna(prev_row.get(col)) for col in required_cols):
                return False, "Données indicateurs manquantes"

            rsi_val = float(row["rsi"]) if pd.notna(row["rsi"]) else np.nan
            stoch_k_val = float(row["stoch_k"]) if pd.notna(row["stoch_k"]) else np.nan
            stoch_d_val = float(row["stoch_d"]) if pd.notna(row["stoch_d"]) else np.nan
            prev_stoch_k_val = float(prev_row["stoch_k"]) if pd.notna(prev_row["stoch_k"]) else np.nan
            prev_stoch_d_val = float(prev_row["stoch_d"]) if pd.notna(prev_row["stoch_d"]) else np.nan
            volume_val = row["Volume"]
            volume_sma_val = row["volume_sma"]
            close_val = row["Close"]
            bb_lower_val = row["bb_lower"]

            if row["supertrend_direction"] != 1: return False, "Supertrend non haussier"
            if np.isnan(rsi_val) or not (50 < rsi_val < 70): return False, "RSI hors zone (50-70)"
            if np.isnan(stoch_k_val) or np.isnan(stoch_d_val) or np.isnan(prev_stoch_k_val) or np.isnan(prev_stoch_d_val): return False, "Données Stochastique NaN"
            if not (stoch_k_val > stoch_d_val and prev_stoch_k_val <= prev_stoch_d_val): return False, "Pas de croisement Stoch K>D"

            if not isinstance(bb_lower_val, Decimal): return False, "Valeur bb_lower invalide"
            if not isinstance(close_val, Decimal): return False, "Valeur Close invalide"
            if close_val < bb_lower_val or close_val > bb_lower_val * Decimal("1.01"): return False, "Prix non proche de la bande inférieure BB"

            if not isinstance(volume_val, Decimal) or not isinstance(volume_sma_val, Decimal): return False, "Données Volume invalides"
            if volume_val <= volume_sma_val: return False, "Volume insuffisant"

            return True, "Tous les filtres validés pour LONG"
        except Exception as e:
            logger.error(f"Erreur dans _check_long_conditions: {e}", exc_info=True)
            return False, f"Erreur technique: {e}"

    def _check_short_conditions(self, row: pd.Series, prev_row: pd.Series) -> Tuple[bool, str]:
        """Checks SHORT entry conditions. (Private method)"""
        logger.debug("SCALPING2: Short conditions check called, but shorting is not implemented/enabled.")
        return False, "Shorting non implémenté"

    def _calculate_dynamic_sl_tp(self, entry_price: Decimal, side: str, recent_low: Decimal, recent_high: Decimal, atr_value: Optional[Decimal]) -> Tuple[Decimal, Decimal, Decimal]:
        """Calculates dynamic SL/TP levels. Handles potential None for atr_value."""
        try:
            if atr_value is None or not isinstance(atr_value, Decimal) or atr_value <= 0:
                logger.warning(f"ATR invalide ({atr_value}) pour calcul SL/TP dynamique. Utilisation SL/TP fixes.")
                raise ValueError("ATR invalide")
            if entry_price <= 0:
                raise ValueError("Prix d'entrée invalide")

            base_sl_frac = self.config.get("STOP_LOSS_PERCENTAGE", Decimal("0.005"))
            atr_sl_frac = (atr_value * Decimal("2")) / entry_price
            sl_frac = min(base_sl_frac, atr_sl_frac)
            tp1_ratio = Decimal("1.5")
            tp2_ratio = Decimal("2.0")

            if side == "BUY":
                sl_price = entry_price * (Decimal(1) - sl_frac)
                if isinstance(recent_low, Decimal) and recent_low > 0:
                    sl_price = min(sl_price, recent_low * (Decimal(1) - Decimal("0.001")))
                risk_amount = entry_price - sl_price
                if risk_amount <= 0: raise ValueError("Risque calculé non positif pour BUY")
                tp1_price = entry_price + (risk_amount * tp1_ratio)
                tp2_price = entry_price + (risk_amount * tp2_ratio)
            else: # SELL
                sl_price = entry_price * (Decimal(1) + sl_frac)
                if isinstance(recent_high, Decimal) and recent_high > 0:
                    sl_price = max(sl_price, recent_high * (Decimal(1) + Decimal("0.001")))
                risk_amount = sl_price - entry_price
                if risk_amount <= 0: raise ValueError("Risque calculé non positif pour SELL")
                tp1_price = entry_price - (risk_amount * tp1_ratio)
                tp2_price = entry_price - (risk_amount * tp2_ratio)

            tp1_price = max(tp1_price, Decimal("0.00000001"))
            tp2_price = max(tp2_price, Decimal("0.00000001"))
            return sl_price, tp1_price, tp2_price

        except (ValueError, InvalidOperation, TypeError, ZeroDivisionError) as e:
            logger.error(f"Erreur calcul SL/TP dynamique: {e}", exc_info=False)
            sl_frac_fallback = self.config.get("STOP_LOSS_PERCENTAGE", Decimal("0.005"))
            tp1_frac_fallback = self.config.get("TAKE_PROFIT_1_PERCENTAGE", Decimal("0.01"))
            tp2_frac_fallback = self.config.get("TAKE_PROFIT_2_PERCENTAGE", Decimal("0.015"))
            if not isinstance(entry_price, Decimal) or entry_price <= 0:
                 logger.error("Prix d'entrée invalide, impossible de calculer SL/TP fallback.")
                 return Decimal(0), Decimal(0), Decimal(0)
            if side == "BUY":
                sl, tp1, tp2 = entry_price * (1 - sl_frac_fallback), entry_price * (1 + tp1_frac_fallback), entry_price * (1 + tp2_frac_fallback)
            else:
                sl, tp1, tp2 = entry_price * (1 + sl_frac_fallback), entry_price * (1 - tp1_frac_fallback), entry_price * (1 - tp2_frac_fallback)
            logger.warning("Utilisation de SL/TP fixes par défaut suite à une erreur.")
            return sl, tp1, tp2

    def check_entry_signal(self, latest_data: pd.Series, **kwargs) -> Optional[Dict[str, Any]]:
        """Checks for SCALPING2 entry signals (LONG only currently)."""
        prev_row = kwargs.get('prev_row')
        if prev_row is None:
            logger.warning("SCALPING2 Entry Check: 'prev_row' missing in kwargs.")
            return None

        long_signal, long_reason = self._check_long_conditions(latest_data, prev_row)
        side = "BUY" if long_signal else None

        if side:
            try:
                symbol = self.get_current_state("symbol")
                symbol_info = self.get_symbol_info()
                available_balance = self.get_current_state("available_balance")
                if not symbol or not symbol_info or available_balance is None:
                    logger.error("SCALPING2 Entry: Missing state data.")
                    return None

                entry_price = latest_data["Close"] # Should be Decimal now
                if not isinstance(entry_price, Decimal) or entry_price <= 0:
                     logger.error(f"SCALPING2 Entry: Invalid entry price type or value: {entry_price}")
                     return None

                recent_low = latest_data["Low"] if isinstance(latest_data["Low"], Decimal) else None
                recent_high = latest_data["High"] if isinstance(latest_data["High"], Decimal) else None
                atr_value = latest_data["atr"] if isinstance(latest_data["atr"], Decimal) else None

                if recent_low is None or recent_high is None:
                     logger.error("SCALPING2 Entry: Invalid Low/High for SL/TP calc.")
                     return None

                sl_price, tp1_price, tp2_price = self._calculate_dynamic_sl_tp(
                    entry_price=entry_price, side=side,
                    recent_low=recent_low, recent_high=recent_high, atr_value=atr_value
                )

                risk_per_trade_frac = self.config.get("RISK_PER_TRADE", Decimal("0.01"))
                capital_allocation_frac = self.config.get("CAPITAL_ALLOCATION", Decimal("0.5"))
                max_risk = available_balance * risk_per_trade_frac
                max_capital = available_balance * capital_allocation_frac

                if side == "BUY": risk_per_unit = entry_price - sl_price
                else: risk_per_unit = sl_price - entry_price

                if risk_per_unit <= 0:
                    logger.warning(f"SCALPING2 Entry ({side}): Risk per unit zero or negative.")
                    return None

                qty_risk = max_risk / risk_per_unit
                qty_capital = max_capital / entry_price
                quantity_unformatted = min(qty_risk, qty_capital)

                formatted_quantity = format_quantity(quantity_unformatted, symbol_info)
                if formatted_quantity is None or formatted_quantity <= 0:
                    logger.warning(f"SCALPING2 Entry ({side}): Quantity invalid after formatting.")
                    return None

                min_notional = get_min_notional(symbol_info)
                if not check_min_notional(formatted_quantity, entry_price, min_notional):
                    logger.warning(f"SCALPING2 Entry ({side}): Notional < MIN_NOTIONAL.")
                    return None

                order_params = {
                    "symbol": symbol, "side": side, "order_type": "MARKET",
                    "quantity": float(formatted_quantity),
                    "sl_price": float(sl_price), "tp1_price": float(tp1_price), "tp2_price": float(tp2_price),
                }
                logger.info(f"SCALPING2 Entry Signal: Preparing {side} MARKET Qty={formatted_quantity} @ ~{entry_price:.8f} (SL: {sl_price:.8f}, TP1: {tp1_price:.8f})")
                return order_params

            except Exception as e:
                logger.error(f"SCALPING2 Entry: Error preparing order: {e}", exc_info=True)
                return None

        return None

    def _check_exit_conditions(self, current_price: Decimal, position_data: Dict[str, Any], position_duration_seconds: int) -> Tuple[bool, str]:
        """Checks exit conditions (SL, TP, Trailing, TimeStop). (Private method)"""
        try:
            entry_price_str = position_data.get("avg_price")
            sl_price_str = position_data.get("sl_price")
            tp1_price_str = position_data.get("tp1_price")
            highest_price_str = position_data.get("highest_price")
            lowest_price_str = position_data.get("lowest_price")
            side = position_data.get("side", "")

            try:
                entry_price = Decimal(str(entry_price_str)) if entry_price_str is not None else None
                sl_price = Decimal(str(sl_price_str)) if sl_price_str is not None else None
                tp1_price = Decimal(str(tp1_price_str)) if tp1_price_str is not None else None
                highest_price = Decimal(str(highest_price_str)) if highest_price_str is not None else entry_price
                lowest_price = Decimal(str(lowest_price_str)) if lowest_price_str is not None else entry_price
            except (InvalidOperation, TypeError):
                logger.error(f"SCALPING2 Exit Check: Error converting position data Decimals.")
                return True, "Erreur conversion données position"

            if not side or entry_price is None or entry_price <= 0 or sl_price is None or sl_price <= 0 or tp1_price is None or tp1_price <= 0:
                logger.error(f"SCALPING2 Exit Check: Invalid position data.")
                return True, "Données de position invalides"

            # 1. SL / TP
            if side == "BUY":
                if current_price <= sl_price: return True, f"Stop Loss @ {sl_price:.8f}"
                if current_price >= tp1_price: return True, f"Take Profit 1 @ {tp1_price:.8f}"
            else: # SELL
                if current_price >= sl_price: return True, f"Stop Loss @ {sl_price:.8f}"
                if current_price <= tp1_price: return True, f"Take Profit 1 @ {tp1_price:.8f}"

            # 2. Time Stop
            time_stop_minutes = self.config.get("TIME_STOP_MINUTES", 15)
            if position_duration_seconds > time_stop_minutes * 60:
                return True, f"Time Stop ({time_stop_minutes} min)"

            # 3. Trailing Stop
            trailing_stop_frac = self.config.get("TRAILING_STOP_PERCENTAGE", Decimal("0.003"))
            if highest_price is None or lowest_price is None:
                 logger.warning("Highest/Lowest price None for Trailing Stop.")
                 highest_price, lowest_price = entry_price, entry_price

            if trailing_stop_frac > 0:
                if side == "BUY":
                    trailing_trigger_price = highest_price * (Decimal(1) - trailing_stop_frac)
                    if trailing_trigger_price > entry_price and current_price < trailing_trigger_price:
                        return True, f"Trailing Stop (LONG) @ {trailing_trigger_price:.8f}"
                else: # SELL
                    trailing_trigger_price = lowest_price * (Decimal(1) + trailing_stop_frac)
                    if trailing_trigger_price < entry_price and current_price > trailing_trigger_price:
                        return True, f"Trailing Stop (SHORT) @ {trailing_trigger_price:.8f}"

            return False, "Pas de condition de sortie"

        except Exception as e:
            logger.error(f"Erreur dans _check_exit_conditions SCALPING2: {e}", exc_info=True)
            return True, f"Erreur technique exit check: {e}"

    def check_exit_signal(self, latest_data: pd.Series, position_data: Dict[str, Any], **kwargs) -> Optional[str]:
        """Checks for SCALPING2 exit signals (SL, TP, Trailing, TimeStop)."""
        current_price = kwargs.get('current_price')
        position_duration_seconds = kwargs.get('position_duration_seconds')

        if current_price is None or position_duration_seconds is None:
             logger.warning("SCALPING2 Exit Check: Missing 'current_price' or 'position_duration_seconds' in kwargs.")
             return None

        if not isinstance(current_price, Decimal):
             try: current_price = Decimal(str(current_price))
             except: logger.error("SCALPING2 Exit Check: Invalid current_price type."); return "Erreur Prix Actuel"

        should_exit, exit_reason = self._check_exit_conditions(current_price, position_data, position_duration_seconds)

        return exit_reason if should_exit else None

# Remove old standalone functions
