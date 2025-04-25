import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

from manager.config_manager import config_manager

logger = logging.getLogger(__name__)

class BaseExitStrategy(ABC):
    """
    Classe de base abstraite pour les stratégies de sortie.
    """

    def __init__(self, strategy_name: str):
        """
        Initialise la stratégie de sortie de base.
        Args:
            strategy_name: Le nom de la stratégie de sortie.
        """
        self.strategy_name = strategy_name
        self.config = config_manager.get_config() # Load config
        logger.info(f"BaseExitStrategy initialized: {self.strategy_name}")

    @abstractmethod
    def check_exit_signal(self, latest_data: Any, position_data: Dict[str, Any], **kwargs) -> Optional[str]:
        """
        Vérifie si un signal de sortie est présent.

        Args:
            latest_data: Les données les plus récentes disponibles (par exemple, book ticker, klines).
            position_data: Les détails de la position actuelle (prix d'entrée, quantité, etc.).
            **kwargs: Arguments supplémentaires spécifiques à la stratégie de sortie.

        Returns:
            Une chaîne indiquant la raison de la sortie (par exemple, "SL", "TP", "Imbalance Exit"), ou None si aucune sortie n'est requise.
        """
        raise NotImplementedError
