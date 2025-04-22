# /Users/davidmichels/Desktop/trading-bot/backend/utils/order_utils.py
import logging
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import Dict, Any

logger = logging.getLogger(__name__)


def format_quantity(quantity: float, symbol_info: dict) -> float:
    """Format quantity to meet exchange requirements.

    Args:
        quantity: The quantity to format
        symbol_info: Symbol info dictionary containing filters

    Returns:
        float: Formatted quantity respecting filters
    """
    try:
        filters = symbol_info.get("filters", [])

        # Get LOT_SIZE filter
        lot_size = next((f for f in filters if f["filterType"] == "LOT_SIZE"), None)
        if lot_size:
            min_qty = float(lot_size["minQty"])
            step_size = float(lot_size["stepSize"])

            # Validate minimum quantity
            if quantity < min_qty:
                raise ValueError(f"Quantity {quantity} below minimum {min_qty}")

            # Round to step size precision
            decimal_places = len(str(step_size).split(".")[-1].rstrip("0"))
            quantity = round(quantity - (quantity % step_size), decimal_places)

        # Check MIN_NOTIONAL filter
        min_notional = next(
            (f for f in filters if f["filterType"] == "MIN_NOTIONAL"), None
        )
        if min_notional:
            min_value = float(min_notional["minNotional"])
            return max(quantity, min_value)

        return float(f"{quantity:.8f}")

    except (TypeError, ValueError) as e:
        raise ValueError(f"Error formatting quantity: {str(e)}")


def get_min_notional(symbol_info: Dict[str, Any]) -> float:
    """
    Récupère la valeur MIN_NOTIONAL pour le symbole.
    Retourne une valeur par défaut élevée (ex: 10.0) si non trouvé ou erreur.
    """
    default_min_notional = 10.0  # Valeur USDT par défaut
    if not symbol_info or "filters" not in symbol_info:
        logger.error(f"get_min_notional: Données symbol_info invalides ou manquantes.")
        return default_min_notional

    min_notional_filter = next(
        (f for f in symbol_info["filters"] if f.get("filterType") == "NOTIONAL"), None
    )
    notional_str = None

    if min_notional_filter and "minNotional" in min_notional_filter:
        notional_str = min_notional_filter["minNotional"]

    if notional_str:
        try:
            min_notional_val = float(notional_str)
            # logger.debug(f"get_min_notional: Filtre MIN_NOTIONAL trouvé pour {symbol_info.get('symbol')}: {min_notional_val}") # Commenté
            return min_notional_val
        except (ValueError, TypeError):
            logger.error(
                f"get_min_notional: Impossible de convertir MIN_NOTIONAL '{notional_str}' en float pour {symbol_info.get('symbol')}. Utilisation défaut {default_min_notional}."
            )
            return default_min_notional
    else:
        logger.warning(
            f"get_min_notional: Filtre MIN_NOTIONAL non trouvé pour {symbol_info.get('symbol')}. Utilisation défaut {default_min_notional}."
        )
        return default_min_notional


def validate_order_params(symbol, side, quantity, price=None, order_type="MARKET"):
    """Validate order parameters before sending to exchange."""
    if not symbol or not isinstance(symbol, str):
        raise ValueError("Symbol invalide")

    if side not in ["BUY", "SELL"]:
        raise ValueError("Side doit être 'BUY' ou 'SELL'")

    if not quantity or quantity <= 0:
        raise ValueError("Quantité invalide")

    if order_type == "LIMIT" and (not price or price <= 0):
        raise ValueError("Prix invalide pour ordre LIMIT")

    return True


def validate_notional(quantity: float, price: float, symbol_info: dict) -> bool:
    """Validate if order meets minimum notional value requirement.

    Args:
        quantity: Order quantity
        price: Current price or order price
        symbol_info: Symbol info dictionary containing filters

    Returns:
        bool: True if valid, False otherwise
    """
    try:
        filters = symbol_info.get("filters", [])
        min_notional = next(
            (f for f in filters if f["filterType"] == "MIN_NOTIONAL"), None
        )

        if min_notional:
            min_value = float(min_notional["minNotional"])
            notional = quantity * price

            if notional < min_value:
                return False

        return True

    except (TypeError, ValueError) as e:
        raise ValueError(f"Error validating notional: {str(e)}")


def calculate_valid_quantity(
    quote_amount: float, price: float, symbol_info: dict
) -> float:
    """Calculate valid order quantity from quote amount respecting all filters.

    Args:
        quote_amount: Amount in quote currency to spend/receive
        price: Current price
        symbol_info: Symbol info dictionary containing filters

    Returns:
        float: Valid order quantity
    """
    try:
        # Calculate raw quantity
        quantity = quote_amount / price

        # Format according to LOT_SIZE
        quantity = format_quantity(quantity, symbol_info)

        # Validate MIN_NOTIONAL
        if not validate_notional(quantity, price, symbol_info):
            filters = symbol_info.get("filters", [])
            min_notional = next(
                (f for f in filters if f["filterType"] == "MIN_NOTIONAL"), None
            )
            if min_notional:
                min_value = float(min_notional["minNotional"])
                quantity = min_value / price
                quantity = format_quantity(quantity, symbol_info)

        return quantity

    except (TypeError, ValueError) as e:
        raise ValueError(f"Error calculating valid quantity: {str(e)}")
