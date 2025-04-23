import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
import pandas as pd
from decimal import Decimal

# Import necessary components used by strategies or handlers calling them
from manager.state_manager import state_manager
from manager.config_manager import config_manager
# Import the singleton order_manager instance from its central location
from manager.order_manager import order_manager

logger = logging.getLogger(__name__)

class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    Defines the common interface and potentially shared utility methods.
    """

    def __init__(self, strategy_name: str):
        """
        Initializes the base strategy.
        Args:
            strategy_name: The name of the strategy.
        """
        self.strategy_name = strategy_name
        self.config = config_manager.get_config()
        self.state = state_manager # Direct access to the singleton state manager
        self.order_manager = order_manager # Direct access to the singleton order manager
        logger.info(f"BaseStrategy initialized for: {self.strategy_name}")

    # --- Methods related to Klines/Indicators (Potentially shared or abstract) ---

    @abstractmethod
    def calculate_indicators(self, klines_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates necessary technical indicators based on kline data.
        Must be implemented by subclasses.

        Args:
            klines_df: DataFrame of kline data.

        Returns:
            DataFrame with indicators added.
        """
        pass

    # --- Methods related to Entry/Exit Signals (Abstract) ---

    @abstractmethod
    def check_entry_signal(self, latest_data: pd.Series, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Checks for an entry signal based on the latest indicator data.
        Must be implemented by subclasses.

        Args:
            latest_data: A pandas Series containing the most recent indicator data.
            **kwargs: Additional context if needed (e.g., book ticker, depth).

        Returns:
            A dictionary with order parameters if an entry signal is found, otherwise None.
            Example: {'symbol': 'BTCUSDT', 'side': 'BUY', 'order_type': 'MARKET', 'quantity': 0.001}
        """
        pass

    @abstractmethod
    def check_exit_signal(self, latest_data: pd.Series, position_data: Dict[str, Any], **kwargs) -> Optional[str]:
        """
        Checks for an exit signal based on the latest indicator data and current position.
        Must be implemented by subclasses.

        Args:
            latest_data: A pandas Series containing the most recent indicator data.
            position_data: A dictionary containing details of the current open position.
            **kwargs: Additional context if needed (e.g., book ticker, depth).

        Returns:
            A string indicating the reason for exit (e.g., "Indicator Exit", "SL", "TP") if an exit signal is found, otherwise None.
        """
        pass

    # --- Helper/Utility methods (Optional, can be added here if shared) ---

    def get_current_state(self, key: Optional[str] = None) -> Any:
        """Helper to get current bot state."""
        return self.state.get_state(key)

    def get_symbol_info(self) -> Optional[Dict[str, Any]]:
        """Helper to get cached symbol info."""
        return self.state.get_symbol_info()

    # Add more shared utilities as needed, e.g., formatting, risk calculation helpers
