import logging
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Optional, Dict, Any, List
import pandas as pd  # Still needed for type hints in base class

# Import the base class
from .base_strategy import BaseStrategy

# Import exit strategies
from exit_strategies import *

# Import utilities
from utils.order_utils import (
    format_quantity,
    get_min_notional,
    check_min_notional,
    format_price,
)

logger = logging.getLogger(__name__)


class ScalpingStrategy(BaseStrategy):
    """
    Scalping strategy based on order book imbalance and spread.
    Inherits from BaseStrategy.
    """

    def __init__(self):
        """Initializes the Scalping Strategy."""
        super().__init__(strategy_name="SCALPING")
        self.exit_strategies = self._load_exit_strategies()
        logger.info(f"ScalpingStrategy initialized with exit strategies: {[s.strategy_name for s in self.exit_strategies]}")

    def _load_exit_strategies(self) -> List[BaseExitStrategy]:
        """Loads and initializes the exit strategies based on configuration."""
        exit_strategy_names = [s.strip() for s in str(self.config.get("SCALPING_EXIT_STRATEGIES", "")).split(",") if s.strip()]
        exit_strategies = []
        for name in exit_strategy_names:
            if name == "ImbalanceExit":
                exit_strategies.append(ImbalanceExit())
            else:
                logger.warning(f"ScalpingStrategy: Unknown exit strategy '{name}'. Ignoring.")
        return exit_strategies

    def calculate_indicators(self, klines_df: pd.DataFrame) -> pd.DataFrame:
        """
        This strategy does not rely on kline-based indicators.
        Overrides the base class abstract method.

        Args:
            klines_df: DataFrame of kline data (unused).

        Returns:
            The original DataFrame.
        """
        logger.debug("SCALPING: calculate_indicators called, but not used by this strategy.")
        return klines_df  # No indicators calculated from klines

    def check_entry_signal(self, latest_data: pd.Series, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Checks for a SCALPING entry signal based on book ticker and depth imbalance.
        Overrides the base class abstract method.

        Args:
            latest_data: Unused in this strategy.
            **kwargs: Must contain 'book_ticker' and 'depth' dictionaries.

        Returns:
            Order parameters dictionary if entry signal is found, otherwise None.
        """
        book_ticker = kwargs.get('book_ticker')
        depth = kwargs.get('depth')

        if not book_ticker or not depth or not depth.get("bids") or not depth.get("asks"):
            # logger.debug("SCALPING Entry Check: Missing book_ticker or depth data in kwargs.")
            return None

        try:
            best_bid_price = Decimal(book_ticker.get("b", "0"))
            best_ask_price = Decimal(book_ticker.get("a", "0"))
            if best_bid_price <= 0 or best_ask_price <= 0:
                logger.warning(f"SCALPING Entry Check: Invalid prices (bid={best_bid_price}, ask={best_ask_price}).")
                return None
        except (InvalidOperation, TypeError) as e:
            logger.error(f"SCALPING Entry Check: Error converting book ticker data: {e}")
            return None

        # --- Scalping Logic (Imbalance & Spread) ---
        should_buy = False
        try:
            relative_spread = (best_ask_price - best_bid_price) / best_ask_price if best_ask_price > 0 else Decimal("Infinity")
            spread_threshold = self.config.get("SCALPING_SPREAD_THRESHOLD", Decimal("0.0001"))
            levels = self.config.get("SCALPING_DEPTH_LEVELS", 5)

            valid_bids = [Decimal(level[1]) for level in depth["bids"][:levels] if len(level) > 1 and Decimal(level[1]) > 0]
            valid_asks = [Decimal(level[1]) for level in depth["asks"][:levels] if len(level) > 1 and Decimal(level[1]) > 0]
            if not valid_bids or not valid_asks: return None # Need valid levels

            total_bid_qty = sum(valid_bids)
            total_ask_qty = sum(valid_asks)
            imbalance_ratio = total_bid_qty / total_ask_qty if total_ask_qty > 0 else Decimal("Infinity")
            imbalance_threshold = Decimal(str(self.config.get("SCALPING_IMBALANCE_THRESHOLD", 1.5)))

            # --- Check Capital Before Logging Signal ---
            available_balance = self.get_current_state("available_balance")
            if available_balance is None: logger.error("SCALPING Entry: Available balance is None."); return None

            capital_allocation_fraction = self.config.get("CAPITAL_ALLOCATION", Decimal("0.5"))
            capital_to_use = available_balance * capital_allocation_fraction
            capital_to_use *= Decimal("0.95") # Apply safety margin

            symbol_info = self.get_symbol_info()
            if not symbol_info: logger.error("SCALPING Entry: Symbol info not available."); return None
            min_notional = get_min_notional(symbol_info)
            min_order_value = max(Decimal("5.1"), min_notional * Decimal("1.05")) # Use slightly above minNotional or 5.1 USDT

            if relative_spread < spread_threshold and imbalance_ratio > imbalance_threshold:
                if capital_to_use < min_order_value:
                    # logger.debug(f"SCALPING Entry: Insufficient capital ({capital_to_use:.4f}) for min order value ({min_order_value:.4f}).")
                    return None
                logger.info(f"SCALPING BUY Condition Met: Spread={relative_spread:.5f} (<{spread_threshold}), Imbalance={imbalance_ratio:.2f} (>{imbalance_threshold})")
                should_buy = True

        except (IndexError, TypeError, KeyError, ZeroDivisionError, InvalidOperation) as e:
            logger.error(f"SCALPING Entry Check: Error calculating indicators: {e}", exc_info=True)
            return None

        # --- Prepare Order if Signal ---
        if should_buy:
            try:
                symbol = self.get_current_state("symbol")
                if not symbol: logger.error("SCALPING Entry: Symbol missing in state."); return None

                entry_price_decimal = best_ask_price # Use Ask for BUY
                order_type = str(self.config.get("SCALPING_ORDER_TYPE", "MARKET")).upper()
                order_params = {"symbol": symbol, "side": "BUY", "order_type": order_type}

                if order_type == "LIMIT":
                    risk_per_trade_frac = self.config.get("RISK_PER_TRADE", Decimal("0.01"))
                    stop_loss_frac = self.config.get("STOP_LOSS_PERCENTAGE", Decimal("0.005"))
                    max_risk = available_balance * risk_per_trade_frac
                    max_capital = capital_to_use # Already calculated with safety margin

                    stop_loss_price = entry_price_decimal * (Decimal(1) - stop_loss_frac)
                    risk_per_unit = entry_price_decimal - stop_loss_price
                    if risk_per_unit <= 0:
                        logger.warning(f"SCALPING Entry (LIMIT): Risk per unit zero or negative.")
                        return None

                    qty_risk = max_risk / risk_per_unit
                    qty_capital = max_capital / entry_price_decimal
                    base_quantity_unformatted = min(qty_risk, qty_capital)

                    formatted_base_quantity = format_quantity(base_quantity_unformatted, symbol_info)
                    if formatted_base_quantity is None or formatted_base_quantity <= 0:
                        logger.warning(f"SCALPING Entry (LIMIT): Base quantity invalid after formatting.")
                        return None

                    limit_price = format_price(entry_price_decimal, symbol_info)
                    if limit_price is None:
                        logger.error(f"SCALPING Entry (LIMIT): Limit price invalid after formatting.")
                        return None

                    if not check_min_notional(formatted_base_quantity, limit_price, min_notional):
                        logger.warning(f"SCALPING Entry (LIMIT): Final notional < MIN_NOTIONAL.")
                        return None

                    order_params["quantity"] = float(formatted_base_quantity) # Executor expects float
                    order_params["price"] = float(limit_price) # Executor expects float
                    order_params["time_in_force"] = self.config.get("SCALPING_LIMIT_TIF", "GTC")
                    logger.info(f"SCALPING Entry: Preparing LIMIT BUY Qty={order_params['quantity']} @ Price={order_params['price']}")

                elif order_type == "MARKET":
                    # Use quoteOrderQty based on calculated capital_to_use
                    quote_amount_to_spend_raw = capital_to_use # Use the pre-calculated capital
                    quote_precision = symbol_info.get("quotePrecision", 8)
                    quantizer = Decimal("1e-" + str(quote_precision))
                    quote_amount_to_spend = quote_amount_to_spend_raw.quantize(quantizer, rounding=ROUND_DOWN)

                    if quote_amount_to_spend < min_notional:
                        logger.error(f"SCALPING Entry (MARKET): Final quote amount ({quote_amount_to_spend}) < MIN_NOTIONAL ({min_notional}).")
                        return None

                    order_params["quoteOrderQty"] = float(quote_amount_to_spend) # Executor expects float
                    log_format_str = "{:." + str(quote_precision) + "f}"
                    logger.info(f"SCALPING Entry: Preparing MARKET BUY with quoteOrderQty={log_format_str.format(quote_amount_to_spend)}")

                else:
                    logger.error(f"SCALPING Entry: Unsupported order type '{order_type}'.")
                    return None

                return order_params

            except (InvalidOperation, TypeError, ValueError, ZeroDivisionError, KeyError) as e:
                logger.error(f"SCALPING Entry: Error calculating/preparing order: {e}", exc_info=True)
                return None

        return None  # No signal

    def check_exit_signal(self, latest_data: pd.Series, position_data: Dict[str, Any], **kwargs) -> Optional[str]:
        """
        Checks for a SCALPING exit signal (SL, TP, or imbalance reversal).
        Overrides the base class abstract method.

        Args:
            latest_data: Unused in this strategy.
            position_data: Dictionary with current position details ('avg_price', etc.).
            **kwargs: Must contain 'book_ticker' and 'depth' dictionaries.

        Returns:
            A string indicating the reason for exit ("SL", "TP", "Imbalance Exit") or None.
        """
        book_ticker = kwargs.get('book_ticker')
        depth = kwargs.get('depth')

        if not book_ticker or not position_data:
            # logger.debug("SCALPING Exit Check: Missing book_ticker or position_data.")
            return None

        # --- 1. Check SL/TP ---
        try:
            entry_price = Decimal(str(position_data.get("avg_price", "0")))
            if entry_price <= 0: return None  # Invalid entry price

            current_price = Decimal(book_ticker.get("b", "0"))  # Use BID for selling (closing LONG)
            if current_price <= 0: return None  # Invalid current price

            # SL Check
            sl_pct = self.config.get("STOP_LOSS_PERCENTAGE", Decimal("0.005"))
            stop_loss_price = entry_price * (Decimal(1) - sl_pct)
            if current_price <= stop_loss_price:
                logger.info(f"SCALPING SL Hit: Bid {current_price:.4f} <= SL {stop_loss_price:.4f}")
                return "SL"

            # TP Check (using TP1)
            tp_pct = self.config.get("TAKE_PROFIT_1_PERCENTAGE", Decimal("0.01"))
            take_profit_price = entry_price * (Decimal(1) + tp_pct)
            if current_price >= take_profit_price:
                logger.info(f"SCALPING TP Hit: Bid {current_price:.4f} >= TP {take_profit_price:.4f}")
                return "TP"

        except (InvalidOperation, TypeError, KeyError) as e:
            logger.error(f"SCALPING Check SL/TP Error: {e}", exc_info=True)
            # Continue to check imbalance even if SL/TP fails

        # --- 2. Check Imbalance Reversal ---
        if not depth or not depth.get("bids") or not depth.get("asks"):
             # logger.debug("SCALPING Exit Check: Missing depth data for imbalance check.")
             return None  # Cannot check imbalance without depth

        try:
            levels = self.config.get("SCALPING_DEPTH_LEVELS", 5)
            valid_bids = [Decimal(level[1]) for level in depth["bids"][:levels] if len(level) > 1 and Decimal(level[1]) > 0]
            valid_asks = [Decimal(level[1]) for level in depth["asks"][:levels] if len(level) > 1 and Decimal(level[1]) > 0]
            if not valid_bids or not valid_asks: return None

            total_bid_qty = sum(valid_bids)
            total_ask_qty = sum(valid_asks)
            imbalance_ratio = total_bid_qty / total_ask_qty if total_ask_qty > 0 else Decimal("Infinity")

            imbalance_entry_threshold = Decimal(str(self.config.get("SCALPING_IMBALANCE_THRESHOLD", 1.5)))
            exit_imbalance_threshold = Decimal("1.0") / imbalance_entry_threshold if imbalance_entry_threshold > Decimal("1.0") else Decimal("0.9")

            if imbalance_ratio < exit_imbalance_threshold:
                logger.info(f"SCALPING Imbalance Exit Condition Met: Ratio={imbalance_ratio:.2f} (<{exit_imbalance_threshold:.2f})")
                return "Imbalance Exit"

        except (IndexError, TypeError, KeyError, ZeroDivisionError, InvalidOperation) as e:
            logger.error(f"SCALPING Exit Check: Error calculating imbalance exit: {e}", exc_info=True)

        # --- 3. Check Exit Strategies ---
        for strategy in self.exit_strategies:
            try:
                exit_reason = strategy.check_exit_signal(latest_data, position_data, book_ticker=book_ticker, depth=depth)
                if exit_reason:
                    logger.info(f"Scalping Exit triggered by {strategy.strategy_name}: {exit_reason}")
                    return exit_reason
            except Exception as e:
                logger.error(f"Error during exit strategy {strategy.strategy_name}: {e}", exc_info=True)

        # --- 3. Check Exit Strategies ---
        for strategy in self.exit_strategies:
            try:
                exit_reason = strategy.check_exit_signal(latest_data, position_data, book_ticker=book_ticker, depth=depth)
                if exit_reason:
                    logger.info(f"Scalping Exit triggered by {strategy.strategy_name}: {exit_reason}")
                    return exit_reason
            except Exception as e:
                logger.error(f"Error during exit strategy {strategy.strategy_name}: {e}", exc_info=True)

        return None  # No exit signal


# Remove old standalone functions if they existed
# (The provided file content already didn't have them as top-level functions,
# but had check_entry_conditions, check_strategy_exit_conditions, check_sl_tp)
