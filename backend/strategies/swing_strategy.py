import logging
import pandas as pd
import pandas_ta as ta
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any, List

# Import the base class
from .base_strategy import BaseStrategy

# Import utilities if needed specifically here (prefer base class helpers if possible)
from utils.order_utils import (
    format_quantity,
    get_min_notional,
    check_min_notional,
)

logger = logging.getLogger(__name__)

class SwingStrategy(BaseStrategy):
    """
    Swing trading strategy based on EMA crossover and RSI confirmation.
    Inherits from BaseStrategy.
    """

    def __init__(self):
        """Initializes the Swing Strategy."""
        super().__init__(strategy_name="SWING")
        # Specific initialization for SwingStrategy if needed
        logger.info("SwingStrategy initialized.")

    def calculate_indicators(self, klines_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates EMA, RSI, and optional Volume MA indicators.
        Overrides the base class abstract method.

        Args:
            klines_df: DataFrame of kline data with 'Open', 'High', 'Low', 'Close', 'Volume'.

        Returns:
            DataFrame with indicators added. Returns original df if calculation fails.
        """
        df = klines_df.copy() # Work on a copy
        if df.empty:
            logger.warning("SWING: Input DataFrame for indicators is empty.")
            return df

        try:
            # Ensure necessary columns are numeric
            numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                else:
                    logger.error(f"SWING: Missing required column '{col}' for indicator calculation.")
                    return klines_df # Return original df if required columns missing

            df.dropna(subset=numeric_cols, inplace=True)
            if df.empty:
                logger.warning("SWING: DataFrame empty after dropping NaNs in numeric columns.")
                return df

            # Get parameters from config (accessed via self.config inherited from BaseStrategy)
            ema_s = self.config.get('EMA_SHORT_PERIOD', 9)
            ema_l = self.config.get('EMA_LONG_PERIOD', 21)
            rsi_p = self.config.get('RSI_PERIOD', 14)
            use_ema_f = self.config.get('USE_EMA_FILTER', False)
            ema_f = self.config.get('EMA_FILTER_PERIOD', 50)
            use_vol = self.config.get('USE_VOLUME_CONFIRMATION', False)
            vol_p = self.config.get('VOLUME_AVG_PERIOD', 20)

            # Calculate indicators using pandas_ta
            # Ensure 'Close' column exists and is numeric before calculations
            if 'Close' not in df.columns or not pd.api.types.is_numeric_dtype(df['Close']):
                 logger.error("SWING: 'Close' column is missing or not numeric.")
                 return klines_df

            df.ta.ema(length=ema_s, append=True, col_names=('EMA_short',))
            df.ta.ema(length=ema_l, append=True, col_names=('EMA_long',))
            df.ta.rsi(length=rsi_p, append=True, col_names=('RSI',))
            if use_ema_f:
                df.ta.ema(length=ema_f, append=True, col_names=('EMA_filter',))
            if use_vol:
                # Ensure 'Volume' column exists and is numeric
                if 'Volume' in df.columns and pd.api.types.is_numeric_dtype(df['Volume']):
                     df.ta.sma(close='Volume', length=vol_p, append=True, col_names=('Volume_MA',))
                else:
                     logger.warning("SWING: Volume confirmation enabled but 'Volume' column missing or not numeric. Skipping Volume MA.")


            # Drop rows with NaN values created by indicator calculations
            # df.dropna(inplace=True) # Keep NaNs for now, handle in signal checks if needed

            logger.debug(f"SWING: Indicators calculated. DataFrame shape: {df.shape}")
            return df

        except Exception as e:
            logger.error(f"SWING: Error calculating indicators: {e}", exc_info=True)
            return klines_df # Return original df on error

    def check_entry_signal(self, latest_data: pd.Series, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Checks for a SWING entry signal (EMA bullish crossover + confirmations).
        Overrides the base class abstract method.

        Args:
            latest_data: A pandas Series containing the most recent indicator data.
                         Expected columns: 'EMA_short', 'EMA_long', 'RSI', 'Close',
                         'EMA_filter' (optional), 'Volume' (optional), 'Volume_MA' (optional).
            **kwargs: Not used in this implementation.

        Returns:
            Order parameters dictionary if entry signal is found, otherwise None.
        """
        try:
            # Check required indicators are present
            required_indicators = ['EMA_short', 'EMA_long', 'RSI', 'Close']
            if any(ind not in latest_data or pd.isna(latest_data[ind]) for ind in required_indicators):
                # logger.debug("SWING Entry Check: Missing or NaN required indicators in latest_data.")
                return None

            # Get config values
            rsi_ob = self.config.get('RSI_OVERBOUGHT', 75)
            use_ema_f = self.config.get('USE_EMA_FILTER', False)
            use_vol = self.config.get('USE_VOLUME_CONFIRMATION', False)

            # --- Entry Conditions ---
            # 1. Bullish EMA Crossover (EMA_short crosses above EMA_long)
            #    We need the previous row's data for crossover check. This should be handled
            #    by the caller (e.g., websocket_handler passing the last 2 rows).
            #    Assuming latest_data is the *current* closed kline, and we need the *previous* one too.
            #    Let's modify the expectation: the caller should pass the DataFrame slice.
            #    For now, let's assume the signal logic is based *only* on the latest_data state.
            #    This is a simplification and might need adjustment based on how it's called.
            #    Let's redefine: Signal is based on the state at the close of the *latest* candle.
            #    Crossover condition needs previous candle state.
            #    Let's assume the caller (websocket_handler) calculates the 'signal' column
            #    based on the crossover logic and passes it in latest_data.
            #    Refining this: Base class shouldn't dictate how signals are generated, only checked.
            #    Let's stick to the original logic: check conditions based on latest_data.

            # Simplified check (adjust if crossover logic is needed here): EMA short > EMA long
            ema_bullish = latest_data['EMA_short'] > latest_data['EMA_long']

            # 2. RSI Confirmation (Not overbought)
            rsi_confirm = latest_data['RSI'] < rsi_ob

            # 3. EMA Filter (Optional)
            ema_filter_confirm = True # Default to true if not used
            if use_ema_f:
                if 'EMA_filter' in latest_data and not pd.isna(latest_data['EMA_filter']):
                    ema_filter_confirm = latest_data['Close'] > latest_data['EMA_filter']
                else:
                    ema_filter_confirm = False # Fail if filter enabled but data missing

            # 4. Volume Confirmation (Optional)
            volume_confirm = True # Default to true if not used
            if use_vol:
                 if 'Volume' in latest_data and 'Volume_MA' in latest_data and \
                    not pd.isna(latest_data['Volume']) and not pd.isna(latest_data['Volume_MA']):
                     volume_confirm = latest_data['Volume'] > latest_data['Volume_MA']
                 else:
                     volume_confirm = False # Fail if volume enabled but data missing

            # --- Final Entry Signal ---
            if ema_bullish and rsi_confirm and ema_filter_confirm and volume_confirm:
                logger.info("SWING Entry Signal: Conditions met.")

                # Prepare order parameters
                symbol = self.get_current_state("symbol")
                if not symbol:
                    logger.error("SWING Entry: Symbol not found in state.")
                    return None

                symbol_info = self.get_symbol_info()
                if not symbol_info:
                    logger.error("SWING Entry: Symbol info not available.")
                    return None

                available_balance = self.get_current_state("available_balance")
                if available_balance is None or available_balance <= 0:
                     logger.error("SWING Entry: Available balance not valid.")
                     return None

                try:
                    entry_price = Decimal(str(latest_data['Close']))
                    if entry_price <= 0: raise ValueError("Invalid entry price")

                    # Sizing logic (same as before, using self.config)
                    risk_per_trade_frac = self.config.get("RISK_PER_TRADE", Decimal("0.01"))
                    capital_allocation_frac = self.config.get("CAPITAL_ALLOCATION", Decimal("1.0"))
                    stop_loss_frac = self.config.get("STOP_LOSS_PERCENTAGE", Decimal("0.02"))

                    stop_loss_price = entry_price * (Decimal(1) - stop_loss_frac)
                    risk_per_unit = entry_price - stop_loss_price
                    if risk_per_unit <= 0:
                        logger.warning(f"SWING Entry: Risk per unit zero or negative (SL={stop_loss_price:.8f}, Entry={entry_price:.8f}).")
                        return None

                    max_risk = available_balance * risk_per_trade_frac
                    max_capital = available_balance * capital_allocation_frac
                    qty_risk = max_risk / risk_per_unit
                    qty_capital = max_capital / entry_price
                    quantity_unformatted = min(qty_risk, qty_capital)

                    formatted_quantity = format_quantity(quantity_unformatted, symbol_info)
                    if formatted_quantity is None or formatted_quantity <= 0:
                        logger.warning(f"SWING Entry: Quantity ({quantity_unformatted:.8f}) invalid after formatting.")
                        return None

                    min_notional = get_min_notional(symbol_info)
                    if not check_min_notional(formatted_quantity, entry_price, min_notional):
                        logger.warning(f"SWING Entry: Notional ({formatted_quantity * entry_price:.4f}) < MIN_NOTIONAL ({min_notional:.4f}).")
                        return None

                    order_notional = formatted_quantity * entry_price
                    if order_notional > max_capital * Decimal("1.01"): # Add tolerance
                        logger.warning(f"SWING Entry: Order notional ({order_notional:.4f}) > allocated capital ({max_capital:.4f}). Adjusting.")
                        quantity_unformatted = max_capital / entry_price
                        formatted_quantity = format_quantity(quantity_unformatted, symbol_info)
                        if formatted_quantity is None or formatted_quantity <= 0 or not check_min_notional(formatted_quantity, entry_price, min_notional):
                            logger.error("SWING Entry: Failed to adjust quantity for capital/min_notional.")
                            return None

                    logger.info(f"SWING Entry: Size calculation OK. Qty={formatted_quantity} {symbol}")

                    order_params = {
                        "symbol": symbol,
                        "side": "BUY",
                        "order_type": "MARKET",
                        "quantity": float(formatted_quantity), # Pass float to order manager/executor
                    }
                    # Add SL/TP info for OrderManager/Execution handler if needed
                    # kwargs['sl_price'] = float(stop_loss_price)
                    # kwargs['tp1_price'] = float(entry_price * (Decimal(1) + self.config.get("TAKE_PROFIT_1_PERCENTAGE", Decimal("0.01"))))

                    return order_params

                except (InvalidOperation, TypeError, ValueError, ZeroDivisionError, KeyError) as e:
                    logger.error(f"SWING Entry: Error calculating/preparing order: {e}", exc_info=True)
                    return None
            else:
                # logger.debug("SWING Entry Signal: Conditions NOT met.")
                return None

        except Exception as e:
            logger.error(f"SWING: Error checking entry signal: {e}", exc_info=True)
            return None

    def check_exit_signal(self, latest_data: pd.Series, position_data: Dict[str, Any], **kwargs) -> Optional[str]:
        """
        Checks for a SWING exit signal (EMA bearish crossover).
        Overrides the base class abstract method.

        Args:
            latest_data: A pandas Series containing the most recent indicator data ('EMA_short', 'EMA_long').
            position_data: Dictionary with current position details (not used by this simple exit).
            **kwargs: Not used in this implementation.

        Returns:
            "Indicator Exit" if an exit signal is found, otherwise None.
        """
        try:
            # Check required indicators are present
            if 'EMA_short' not in latest_data or 'EMA_long' not in latest_data or \
               pd.isna(latest_data['EMA_short']) or pd.isna(latest_data['EMA_long']):
                # logger.debug("SWING Exit Check: Missing or NaN required indicators.")
                return None

            # --- Exit Condition: Bearish EMA Crossover ---
            # Simplified check: EMA short < EMA long
            # Proper crossover needs previous candle state, handled similarly to entry signal.
            # Assuming signal is based on the state at the close of the *latest* candle.
            if latest_data['EMA_short'] < latest_data['EMA_long']:
                logger.info("SWING Exit Signal: EMA_short < EMA_long. Conditions met.")
                return "Indicator Exit" # Return reason string
            else:
                # logger.debug("SWING Exit Signal: Conditions NOT met.")
                return None

        except Exception as e:
            logger.error(f"SWING: Error checking exit signal: {e}", exc_info=True)
            return None

# Note: The original standalone functions are now replaced by the class methods.
# The calling code (e.g., websocket_handlers) will need to be updated to instantiate
# this class and call its methods instead of the old standalone functions.
