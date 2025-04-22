# /Users/davidmichels/Desktop/trading-bot/backend/utils/order_utils.py
import logging
from decimal import Decimal, ROUND_DOWN, InvalidOperation, Context, setcontext, getcontext, ROUND_HALF_UP
from typing import Dict, Any, Optional, Union # Ajout Union

logger = logging.getLogger(__name__)

# Configurer le contexte Decimal pour une précision suffisante (optionnel, peut être géré localement)
# setcontext(Context(prec=18))

def get_symbol_filter(symbol_info: Dict[str, Any], filter_type: str) -> Optional[Dict[str, Any]]:
    """Récupère un filtre spécifique depuis symbol_info."""
    if not symbol_info or "filters" not in symbol_info:
        # logger.warning(f"get_symbol_filter: Données symbol_info invalides ou manquantes.") # Verbeux
        return None
    return next((f for f in symbol_info["filters"] if f.get("filterType") == filter_type), None)

def format_quantity(quantity: Union[float, Decimal, str], symbol_info: Dict[str, Any]) -> Optional[Decimal]:
    """
    Formate la quantité (BASE asset) pour respecter les filtres LOT_SIZE (stepSize, minQty).
    Retourne la quantité formatée en Decimal, ou None si invalide ou < minQty.
    Ne gère PAS le filtre NOTIONAL ici.
    """
    try:
        qty_decimal = Decimal(str(quantity))
        if qty_decimal <= 0:
             logger.error(f"format_quantity: Quantité initiale invalide ({qty_decimal}).")
             return None

        lot_size_filter = get_symbol_filter(symbol_info, "LOT_SIZE")
        if not lot_size_filter:
            logger.warning(f"format_quantity: Filtre LOT_SIZE non trouvé pour {symbol_info.get('symbol')}. Formatage basique.")
            # Retourner avec une précision raisonnable par défaut si pas de filtre
            return qty_decimal.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        min_qty = Decimal(lot_size_filter.get("minQty", "0"))
        max_qty = Decimal(lot_size_filter.get("maxQty", "inf")) # Utiliser 'inf' pour gérer l'absence
        step_size = Decimal(lot_size_filter.get("stepSize", "0"))

        # Vérifier minQty AVANT arrondi pour éviter calculs inutiles
        if qty_decimal < min_qty:
            logger.error(f"format_quantity: Quantité initiale {qty_decimal} < minQty {min_qty}. Impossible.")
            return None

        if qty_decimal > max_qty:
             logger.warning(f"format_quantity: Quantité {qty_decimal} > maxQty {max_qty}. Tronquée à maxQty.")
             qty_decimal = max_qty

        if step_size > 0:
            # Calculer le nombre de décimales basé sur step_size
            exponent = step_size.normalize().as_tuple().exponent
            decimal_places = exponent * -1 if isinstance(exponent, int) and exponent < 0 else 0
            quantizer = Decimal('1e-' + str(decimal_places))

            # Appliquer le step_size en arrondissant vers le bas (ROUND_DOWN)
            # C'est la méthode la plus sûre pour ne pas dépasser le solde disponible
            formatted_qty = (qty_decimal // step_size) * step_size
            formatted_qty = formatted_qty.quantize(quantizer, rounding=ROUND_DOWN)

            # Vérification finale minQty APRES arrondi
            if formatted_qty < min_qty:
                 logger.error(f"format_quantity: Quantité formatée {formatted_qty} < minQty {min_qty} après arrondi stepSize. Impossible.")
                 return None

            # logger.debug(f"format_quantity: {quantity} -> {formatted_qty} (step: {step_size}, min: {min_qty})") # Verbeux
            return formatted_qty
        else:
            # Si step_size est 0 (ne devrait pas arriver), retourner la quantité validée min/max
            logger.warning(f"format_quantity: stepSize est 0 pour {symbol_info.get('symbol')}")
            # Assurer que la quantité respecte minQty même si step_size est 0
            if qty_decimal < min_qty: return None
            return qty_decimal.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN) # Précision par défaut

    except (InvalidOperation, TypeError, ValueError, KeyError) as e:
        logger.error(f"format_quantity: Erreur lors du formatage de la quantité {quantity}: {e}", exc_info=True)
        return None

def get_min_notional(symbol_info: Dict[str, Any]) -> Decimal:
    """
    Récupère la valeur MIN_NOTIONAL (filtre NOTIONAL ou MIN_NOTIONAL) pour le symbole.
    Retourne une valeur par défaut (ex: 10.0) si non trouvé ou erreur.
    Retourne un Decimal.
    """
    default_min_notional = Decimal("10.0") # Valeur USDT par défaut
    # Binance utilise 'MIN_NOTIONAL' pour les ordres MARKET et 'NOTIONAL' pour les ordres LIMIT
    # Essayons de récupérer MIN_NOTIONAL d'abord, puis NOTIONAL.minNotional
    min_notional_filter = get_symbol_filter(symbol_info, "MIN_NOTIONAL")
    notional_filter = get_symbol_filter(symbol_info, "NOTIONAL")

    notional_str = None
    if min_notional_filter:
        notional_str = min_notional_filter.get("minNotional")
        # logger.debug(f"get_min_notional: Filtre MIN_NOTIONAL trouvé: {notional_str}")
    elif notional_filter:
        notional_str = notional_filter.get("minNotional")
        # logger.debug(f"get_min_notional: Filtre NOTIONAL trouvé: {notional_str}")

    if notional_str:
        try:
            min_notional_val = Decimal(notional_str)
            # logger.debug(f"get_min_notional: Valeur minNotional extraite: {min_notional_val}") # Verbeux
            return min_notional_val
        except (InvalidOperation, TypeError):
            logger.error(
                f"get_min_notional: Impossible de convertir minNotional '{notional_str}'. Utilisation défaut {default_min_notional}."
            )
            return default_min_notional

    logger.warning(
        f"get_min_notional: Filtres MIN_NOTIONAL/NOTIONAL non trouvés ou invalides pour {symbol_info.get('symbol')}. Utilisation défaut {default_min_notional}."
    )
    return default_min_notional

def check_min_notional(
        quantity: Optional[Decimal],
        price: Optional[Decimal],
        min_notional_value: Decimal
    ) -> bool:
    """
    Vérifie si la valeur notionnelle (quantité * prix) atteint le minimum requis.
    Retourne True si valide ou si les entrées sont invalides (pour ne pas bloquer inutilement), False sinon.
    """
    if quantity is None or price is None or quantity <= 0 or price <= 0:
        # logger.warning("check_min_notional: Quantité ou prix invalide pour la vérification.") # Verbeux
        return True # Ne pas bloquer si les données sont mauvaises en amont

    notional = quantity * price
    is_valid = notional >= min_notional_value
    # if not is_valid: logger.debug(f"check_min_notional: Échec ({notional:.4f} < {min_notional_value:.4f})") # Verbeux
    return is_valid

def get_price_filter(symbol_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Récupère le filtre PRICE_FILTER."""
    return get_symbol_filter(symbol_info, "PRICE_FILTER")

def format_price(price: Union[float, Decimal, str], symbol_info: Dict[str, Any]) -> Optional[Decimal]:
    """
    Formate le prix pour respecter le filtre PRICE_FILTER (tickSize).
    Arrondit au tick valide le plus proche (ROUND_HALF_UP).
    Retourne le prix formaté en Decimal, ou None si invalide.
    """
    try:
        price_decimal = Decimal(str(price))
        if price_decimal <= 0:
             logger.error(f"format_price: Prix initial invalide ({price_decimal}).")
             return None

        price_filter = get_price_filter(symbol_info)
        if not price_filter:
            logger.warning(f"format_price: Filtre PRICE_FILTER non trouvé pour {symbol_info.get('symbol')}. Formatage basique.")
            # Retourner avec une précision raisonnable par défaut
            return price_decimal.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP) # Arrondi au plus proche

        min_price = Decimal(price_filter.get("minPrice", "0"))
        max_price = Decimal(price_filter.get("maxPrice", "inf"))
        tick_size = Decimal(price_filter.get("tickSize", "0"))

        if price_decimal < min_price:
            logger.error(f"format_price: Prix {price_decimal} < minPrice {min_price}. Impossible.")
            return None
        if price_decimal > max_price:
            logger.warning(f"format_price: Prix {price_decimal} > maxPrice {max_price}. Tronqué à maxPrice.")
            price_decimal = max_price

        if tick_size > 0:
            # Calculer le nombre de décimales basé sur tick_size
            exponent = tick_size.normalize().as_tuple().exponent
            decimal_places = exponent * -1 if isinstance(exponent, int) and exponent < 0 else 0
            quantizer = Decimal('1e-' + str(decimal_places))

            # Appliquer tick_size en arrondissant au tick valide le plus proche
            # (price / tick_size).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * tick_size
            # Note: L'implémentation de Binance peut varier légèrement. ROUND_HALF_UP est un choix courant.
            # L'ancienne méthode avec modulo arrondissait vers le bas, ce qui n'est pas toujours souhaité pour les prix.
            formatted_price = (price_decimal / tick_size).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick_size
            formatted_price = formatted_price.quantize(quantizer) # Assurer le bon nombre de décimales

            # Vérification finale minPrice après arrondi
            if formatted_price < min_price:
                 # Si l'arrondi fait passer sous minPrice, utiliser minPrice
                 logger.warning(f"format_price: Prix formaté {formatted_price} < minPrice {min_price}. Utilisation de minPrice.")
                 formatted_price = min_price.quantize(quantizer)

            # logger.debug(f"format_price: {price} -> {formatted_price} (tick: {tick_size})") # Verbeux
            return formatted_price
        else:
            logger.warning(f"format_price: tickSize est 0 pour {symbol_info.get('symbol')}")
            # Assurer que le prix respecte min/max même si tick_size est 0
            if price_decimal < min_price: return None
            price_decimal = min(price_decimal, max_price)
            return price_decimal.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP) # Précision par défaut

    except (InvalidOperation, TypeError, ValueError, KeyError) as e:
        logger.error(f"format_price: Erreur lors du formatage du prix {price}: {e}", exc_info=True)
        return None
