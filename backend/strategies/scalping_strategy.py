# /Users/davidmichels/Desktop/trading-bot/backend/strategies/scalping_strategy.py
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any, List

# Importer les utilitaires partagés
from utils.order_utils import format_quantity, get_min_notional

logger = logging.getLogger(__name__)


def check_entry_conditions(
    current_symbol: str,
    book_ticker: Dict[str, Any],
    depth: Dict[str, Any],
    current_config: Dict[str, Any],
    available_balance: float,
    symbol_info: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Vérifie les conditions d'entrée pour la stratégie de scalping.
    Retourne les détails de l'ordre à placer si les conditions sont remplies, sinon None.
    """
    if not book_ticker or not depth or not depth.get("bids") or not depth.get("asks"):
        return None

    try:
        best_bid_price_str = book_ticker.get("b")
        best_ask_price_str = book_ticker.get("a")
        best_bid_qty_str = book_ticker.get("B")
        best_ask_qty_str = book_ticker.get("A")

        if not all(
            [best_bid_price_str, best_ask_price_str, best_bid_qty_str, best_ask_qty_str]
        ):
            logger.warning("SCALPING Entry Check: Données book ticker incomplètes.")
            return None

        best_bid_price = Decimal(best_bid_price_str or "0")
        best_ask_price = Decimal(best_ask_price_str or "0")

        if best_bid_price <= 0 or best_ask_price <= 0:
            logger.warning(
                f"SCALPING Entry Check: Prix invalides dans book ticker (bid={best_bid_price}, ask={best_ask_price})."
            )
            return None

    except (InvalidOperation, TypeError) as e:
        logger.error(
            f"SCALPING Entry Check: Erreur conversion données book ticker: {e}"
        )
        return None

    # --- Logique de Scalping (Exemple Basique) ---
    should_buy = False
    try:
        relative_spread = (
            (best_ask_price - best_bid_price) / best_ask_price
            if best_ask_price > 0
            else Decimal("0")
        )
        spread_threshold = Decimal(
            str(current_config.get("SCALPING_SPREAD_THRESHOLD", 0.0001))
        )

        levels = current_config.get("SCALPING_DEPTH_LEVELS", 5)
        valid_bids = [
            Decimal(level[1]) for level in depth["bids"][:levels] if len(level) > 1
        ]
        valid_asks = [
            Decimal(level[1]) for level in depth["asks"][:levels] if len(level) > 1
        ]

        if not valid_bids or not valid_asks:
            logger.warning(
                "SCALPING Entry Check: Données de profondeur invalides ou insuffisantes."
            )
            return None

        total_bid_qty = sum(valid_bids)
        total_ask_qty = sum(valid_asks)

        imbalance_ratio = (
            total_bid_qty / total_ask_qty if total_ask_qty > 0 else Decimal("Infinity")
        )
        imbalance_threshold = Decimal(
            str(current_config.get("SCALPING_IMBALANCE_THRESHOLD", 1.5))
        )

        if relative_spread < spread_threshold and imbalance_ratio > imbalance_threshold:
            logger.info(
                f"SCALPING BUY Condition Met: Spread={relative_spread:.5f} (<{spread_threshold}), Imbalance={imbalance_ratio:.2f} (>{imbalance_threshold})"
            )
            should_buy = True

    except (IndexError, TypeError, KeyError, ZeroDivisionError, InvalidOperation) as e:
        logger.error(
            f"SCALPING Entry Check: Erreur calcul indicateurs (spread/imbalance): {e}",
            exc_info=True,
        )
        return None

    if should_buy:
        try:
            # Calculer le capital maximum utilisable avec allocation
            capital_allocation = Decimal(
                str(current_config.get("CAPITAL_ALLOCATION", 50.0))
            ) / Decimal("100.0")
            capital_to_use = Decimal(str(available_balance)) * capital_allocation
            capital_to_use = capital_to_use * Decimal("0.95")  # Marge de sécurité 5%

            entry_price_decimal = best_ask_price
            min_notional = Decimal(str(get_min_notional(symbol_info)))

            # Assurer un notionnel minimum de 11 USDT (ou min_notional + 10%)
            min_order_value = max(Decimal("11.0"), min_notional * Decimal("1.1"))

            # Calculer la quantité basée sur le notionnel minimum
            min_quantity = min_order_value / entry_price_decimal

            # Calculer la quantité maximale basée sur le capital disponible
            max_quantity = capital_to_use / entry_price_decimal

            # Utiliser la plus petite des deux quantités
            quantity_to_use = min(max_quantity, min_quantity)

            # Formater la quantité selon les règles du symbole
            formatted_quantity = format_quantity(float(quantity_to_use), symbol_info)

            if formatted_quantity <= 0:
                logger.warning(
                    f"SCALPING Entry: Quantité calculée ({quantity_to_use:.8f}) invalide après formatage."
                )
                return None

            # Vérifier le notionnel final
            final_notional = Decimal(str(formatted_quantity)) * entry_price_decimal
            if final_notional < min_notional:
                logger.warning(
                    f"SCALPING Entry: Notionnel final ({final_notional:.4f}) < MIN_NOTIONAL ({min_notional:.4f})"
                )
                return None

            # Préparer les paramètres de l'ordre
            order_params = {
                "symbol": current_symbol,
                "side": "BUY",
                "quantity": formatted_quantity,
                "order_type": current_config.get("SCALPING_ORDER_TYPE", "MARKET"),
            }

            return order_params

        except (InvalidOperation, TypeError, ValueError, ZeroDivisionError) as e:
            logger.error(
                f"SCALPING Entry: Erreur calcul taille position: {e}", exc_info=True
            )
            return None

    return None


def check_strategy_exit_conditions(
    current_symbol: str,
    entry_details: Dict[str, Any],
    book_ticker: Dict[str, Any],
    depth: Dict[str, Any],
    current_config: Dict[str, Any],
) -> bool:
    """
    Vérifie les conditions de sortie spécifiques à la stratégie de scalping
    (autres que SL/TP).
    """
    if not book_ticker or not depth or not depth.get("bids") or not depth.get("asks"):
        # logger.debug("SCALPING Exit Check: Données temps réel manquantes.") # Commenté
        return False

    try:
        best_bid_price_str = book_ticker.get("b")
        if not best_bid_price_str:
            return False
        best_bid_price = Decimal(best_bid_price_str)
        if best_bid_price <= 0:
            return False

        entry_price = Decimal(str(entry_details.get("avg_price", "0")))
        if entry_price <= 0:
            logger.warning("SCALPING Exit Check: Prix d'entrée invalide.")
            return False

    except (InvalidOperation, TypeError) as e:
        logger.error(f"SCALPING Exit Check: Erreur conversion données: {e}")
        return False

    # --- Logique de sortie Scalping (Exemple Basique) ---
    should_exit = False
    try:
        levels = current_config.get("SCALPING_DEPTH_LEVELS", 5)
        valid_bids = [
            Decimal(level[1]) for level in depth["bids"][:levels] if len(level) > 1
        ]
        valid_asks = [
            Decimal(level[1]) for level in depth["asks"][:levels] if len(level) > 1
        ]

        if not valid_bids or not valid_asks:
            return False

        total_bid_qty = sum(valid_bids)
        total_ask_qty = sum(valid_asks)
        imbalance_ratio = (
            total_bid_qty / total_ask_qty if total_ask_qty > 0 else Decimal("Infinity")
        )

        imbalance_entry_threshold = Decimal(
            str(current_config.get("SCALPING_IMBALANCE_THRESHOLD", 1.5))
        )
        exit_imbalance_threshold = (
            Decimal("1") / imbalance_entry_threshold
            if imbalance_entry_threshold > 0
            else Decimal("0")
        )

        # Condition de sortie si LONG
        if imbalance_ratio < exit_imbalance_threshold:
            logger.info(
                f"SCALPING EXIT Condition Met: Imbalance={imbalance_ratio:.2f} (<{exit_imbalance_threshold:.2f})"
            )
            should_exit = True

    except (IndexError, TypeError, KeyError, ZeroDivisionError, InvalidOperation) as e:
        logger.error(
            f"SCALPING Exit Check: Erreur calcul indicateur sortie (imbalance): {e}"
        )
        should_exit = False
    # --- Fin Logique Scalping ---

    return should_exit


def check_sl_tp(
    current_symbol: str,
    entry_details: Dict[str, Any],
    book_ticker: Dict[str, Any],
    current_config: Dict[str, Any],
) -> Optional[str]:
    """
    Vérifie si le Stop Loss ou le Take Profit est atteint pour SCALPING.
    Retourne 'SL' ou 'TP' si atteint, sinon None.
    """
    if not book_ticker or not entry_details:
        return None

    try:
        entry_price = Decimal(str(entry_details.get("avg_price", "0")))
        if entry_price <= 0:
            return None

        # Pour une position LONG:
        # SL est déclenché par le prix BID (prix auquel on peut vendre)
        # TP est déclenché par le prix BID (prix auquel on peut vendre)
        current_price_str = book_ticker.get("b")  # Best Bid
        if not current_price_str:
            return None
        current_price = Decimal(current_price_str)
        if current_price <= 0:
            return None

        sl_pct = Decimal(str(current_config.get("STOP_LOSS_PERCENTAGE", 0.005)))
        tp_pct = Decimal(str(current_config.get("TAKE_PROFIT_PERCENTAGE", 0.01)))

        stop_loss_price = entry_price * (Decimal(1) - sl_pct)
        take_profit_price = entry_price * (Decimal(1) + tp_pct)

        # Vérifier SL
        if current_price <= stop_loss_price:
            logger.info(
                f"SCALPING SL Hit: Current Price (Bid) {current_price:.4f} <= SL Price {stop_loss_price:.4f} (Entry: {entry_price:.4f})"
            )
            return "SL"

        # Vérifier TP
        if current_price >= take_profit_price:
            logger.info(
                f"SCALPING TP Hit: Current Price (Bid) {current_price:.4f} >= TP Price {take_profit_price:.4f} (Entry: {entry_price:.4f})"
            )
            return "TP"

    except (InvalidOperation, TypeError, KeyError) as e:
        logger.error(f"SCALPING Check SL/TP Error: {e}", exc_info=True)

    return None
