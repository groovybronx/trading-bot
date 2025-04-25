import logging
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any

from .base_exit_strategy import BaseExitStrategy

logger = logging.getLogger(__name__)

class ImbalanceExit(BaseExitStrategy):
    """
    Stratégie de sortie basée sur l'inversion du déséquilibre du carnet d'ordres.
    """

    def __init__(self):
        """Initialise la stratégie de sortie basée sur l'inversion du déséquilibre."""
        super().__init__(strategy_name="ImbalanceExit")
        logger.info("ImbalanceExit initialized.")

    def check_exit_signal(self, latest_data: Any, position_data: Dict[str, Any], **kwargs) -> Optional[str]:
        """
        Vérifie si le déséquilibre du carnet d'ordres s'est inversé et signale une sortie.

        Args:
            latest_data: Les données les plus récentes disponibles (par exemple, book ticker, klines).
            position_data: Les détails de la position actuelle (prix d'entrée, quantité, etc.).
            **kwargs: Doit contenir 'depth' (le snapshot du carnet d'ordres).

        Returns:
            "Imbalance Exit" si le déséquilibre s'est inversé, sinon None.
        """
        depth = kwargs.get('depth')

        if not depth or not depth.get("bids") or not depth.get("asks"):
            # logger.debug("ImbalanceExit: Missing depth data in kwargs.")
            return None

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
                logger.info(f"ImbalanceExit: Imbalance Exit Condition Met: Ratio={imbalance_ratio:.2f} (<{exit_imbalance_threshold:.2f})")
                return "Imbalance Exit"

        except (IndexError, TypeError, KeyError, ZeroDivisionError, InvalidOperation) as e:
            logger.error(f"ImbalanceExit: Error calculating imbalance exit: {e}", exc_info=True)

        return None
