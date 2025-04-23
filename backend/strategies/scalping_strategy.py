# /Users/davidmichels/Desktop/trading-bot/backend/strategies/scalping_strategy.py
import logging
from decimal import Decimal, InvalidOperation, ROUND_DOWN  # Importer ROUND_DOWN
from typing import Optional, Dict, Any, List, Union

# Importer les utilitaires partagés mis à jour
from utils.order_utils import (
    format_quantity,
    get_min_notional,
    check_min_notional,
    format_price,
)

logger = logging.getLogger(__name__)


def check_entry_conditions(
    current_symbol: str,
    book_ticker: Dict[str, Any],
    depth: Dict[str, Any],
    current_config: Dict[str, Any],
    available_balance: Decimal,  # Utiliser Decimal ici
    symbol_info: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Vérifie les conditions d'entrée pour la stratégie de scalping.
    Retourne les détails de l'ordre à placer si les conditions sont remplies, sinon None.
    Utilise les fonctions d'ordre_utils pour la validation et le formatage.
    """
    if not book_ticker or not depth or not depth.get("bids") or not depth.get("asks"):
        # logger.debug("SCALPING Entry Check: Données temps réel manquantes.") # Verbeux
        return None

    try:
        # Utiliser Decimal pour les prix et quantités dès le début
        best_bid_price = Decimal(book_ticker.get("b", "0"))
        best_ask_price = Decimal(book_ticker.get("a", "0"))
        best_bid_qty = Decimal(book_ticker.get("B", "0"))
        best_ask_qty = Decimal(book_ticker.get("A", "0"))

        if best_bid_price <= 0 or best_ask_price <= 0:
            logger.warning(
                f"SCALPING Entry Check: Prix invalides (bid={best_bid_price}, ask={best_ask_price})."
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
            else Decimal("Infinity")
        )
        spread_threshold = current_config.get(
            "SCALPING_SPREAD_THRESHOLD", Decimal("0.0001")
        )
        levels = current_config.get("SCALPING_DEPTH_LEVELS", 5)
        valid_bids = [
            Decimal(level[1])
            for level in depth["bids"][:levels]
            if len(level) > 1 and Decimal(level[1]) > 0
        ]
        valid_asks = [
            Decimal(level[1])
            for level in depth["asks"][:levels]
            if len(level) > 1 and Decimal(level[1]) > 0
        ]
        if not valid_bids or not valid_asks:
            return None
        total_bid_qty = sum(valid_bids)
        total_ask_qty = sum(valid_asks)
        imbalance_ratio = (
            total_bid_qty / total_ask_qty if total_ask_qty > 0 else Decimal("Infinity")
        )
        imbalance_threshold = Decimal(
            str(current_config.get("SCALPING_IMBALANCE_THRESHOLD", 1.5))
        )
        # --- Vérification du capital minimum AVANT le log du signal ---
        capital_allocation_fraction = current_config.get(
            "CAPITAL_ALLOCATION", Decimal("0.5")
        )
        capital_to_use = available_balance * capital_allocation_fraction
        capital_to_use *= Decimal("0.95")
        min_notional = get_min_notional(symbol_info)
        min_order_value = max(Decimal("5.1"), min_notional * Decimal("1.05"))
        if relative_spread < spread_threshold and imbalance_ratio > imbalance_threshold:
            if capital_to_use < min_order_value:
                logger.warning(
                    f"SCALPING Entry: Capital insuffisant ({capital_to_use:.4f}) pour atteindre la valeur min ({min_order_value:.4f})."
                )
                return None
            logger.info(
                f"SCALPING BUY Condition Met: Spread={relative_spread:.5f} (<{spread_threshold}), Imbalance={imbalance_ratio:.2f} (>{imbalance_threshold})"
            )
            should_buy = True
        # --- Fin Condition d'achat ---
    except (IndexError, TypeError, KeyError, ZeroDivisionError, InvalidOperation) as e:
        logger.error(
            f"SCALPING Entry Check: Erreur calcul indicateurs: {e}", exc_info=True
        )
        return None

    if should_buy:
        try:
            # --- Calcul Taille Position / Montant ---
            # available_balance est déjà un Decimal
            risk_per_trade_frac = current_config.get("RISK_PER_TRADE", Decimal("0.01"))
            capital_allocation_fraction = current_config.get("CAPITAL_ALLOCATION", Decimal("0.5"))
            stop_loss_frac = current_config.get("STOP_LOSS_PERCENTAGE", Decimal("0.005"))
            max_risk = available_balance * risk_per_trade_frac
            max_capital = available_balance * capital_allocation_fraction
            entry_price_decimal = best_ask_price  # Utiliser Ask pour acheter
            min_notional = get_min_notional(symbol_info)  # Récupère en Decimal
            order_type = str(current_config.get("SCALPING_ORDER_TYPE", "MARKET")).upper()
            order_params = {"symbol": current_symbol, "side": "BUY", "order_type": order_type}
            # Pour LIMIT: sizing classique
            if order_type == "LIMIT":
                # Calcul du prix de stop (SL)
                stop_loss_price = entry_price_decimal * (Decimal(1) - stop_loss_frac)
                risk_per_unit = entry_price_decimal - stop_loss_price
                if risk_per_unit <= 0:
                    logger.warning(f"SCALPING Entry: Risque par unité nul ou négatif (SL={stop_loss_price:.8f}, Entry={entry_price_decimal:.8f}).")
                    return None
                qty_risk = max_risk / risk_per_unit
                qty_capital = max_capital / entry_price_decimal
                base_quantity_unformatted = min(qty_risk, qty_capital)
                # Formater la quantité BASE selon LOT_SIZE
                formatted_base_quantity = format_quantity(
                    base_quantity_unformatted, symbol_info
                )
                if formatted_base_quantity is None or formatted_base_quantity <= 0:
                    logger.warning(
                        f"SCALPING Entry (LIMIT): Quantité base ({base_quantity_unformatted:.8f}) invalide après formatage."
                    )
                    return None
                # Vérifier le notionnel final pour l'ordre LIMIT avec la quantité formatée
                limit_price = format_price(
                    entry_price_decimal, symbol_info
                )  # Formater aussi le prix
                if limit_price is None:
                    logger.error(
                        f"SCALPING Entry (LIMIT): Prix limite invalide après formatage."
                    )
                    return None
                if not check_min_notional(
                    formatted_base_quantity, limit_price, min_notional
                ):
                    logger.warning(
                        f"SCALPING Entry (LIMIT): Notionnel final ({formatted_base_quantity * limit_price:.4f}) < MIN_NOTIONAL ({min_notional:.4f}) après formatage Qty/Prix. Ordre annulé."
                    )
                    return None  # Annuler si on veut être strict
                order_params["quantity"] = str(formatted_base_quantity)
                order_params["price"] = str(limit_price)
                order_params["time_in_force"] = current_config.get(
                    "SCALPING_LIMIT_TIF", "GTC"
                )
                logger.info(
                    f"SCALPING Entry: Préparation LIMIT BUY Qty={order_params['quantity']} @ Price={order_params['price']} ({order_params['time_in_force']})"
                )
            elif order_type == "MARKET":
                # Pour MARKET BUY: Utiliser quoteOrderQty avec le capital à utiliser ET le risque max
                # Approximation: montant max risqué = max_risk / stop_loss_frac
                # (si SL touché, perte = quoteOrderQty * stop_loss_frac)
                if stop_loss_frac > 0:
                    max_quote_risk = max_risk / stop_loss_frac
                else:
                    max_quote_risk = max_capital  # fallback
                quote_amount_to_spend_raw = min(max_capital, max_quote_risk, available_balance)
                # Récupérer la précision de l'asset de cotation (ex: USDT)
                quote_precision = symbol_info.get(
                    "quotePrecision", 8
                )  # Défaut 8 si non trouvé
                quantizer = Decimal("1e-" + str(quote_precision))
                quote_amount_to_spend = quote_amount_to_spend_raw.quantize(
                    quantizer, rounding=ROUND_DOWN
                )
                # Vérification finale: le montant arrondi atteint-il le min_notional?
                if quote_amount_to_spend < min_notional:
                    logger.error(
                        f"SCALPING Entry (MARKET): Montant final arrondi ({quote_amount_to_spend}) < MIN_NOTIONAL ({min_notional}). Raw: {quote_amount_to_spend_raw}"
                    )
                    return None
                order_params["quoteOrderQty"] = str(quote_amount_to_spend)
                log_format_str = "{:." + str(quote_precision) + "f}"
                logger.info(
                    f"SCALPING Entry: Préparation MARKET BUY avec quoteOrderQty={log_format_str.format(Decimal(order_params['quoteOrderQty']))}"
                )
            else:
                logger.error(
                    f"SCALPING Entry: Type d'ordre non supporté '{order_type}'."
                )
                return None
            return order_params

        except (
            InvalidOperation,
            TypeError,
            ValueError,
            ZeroDivisionError,
            KeyError,
        ) as e:
            logger.error(
                f"SCALPING Entry: Erreur calcul/préparation ordre: {e}", exc_info=True
            )
            return None

    return None  # Si should_buy est False


# Le reste du fichier (check_strategy_exit_conditions, check_sl_tp) reste inchangé
def check_strategy_exit_conditions(
    current_symbol: str,
    entry_details: Dict[str, Any],
    book_ticker: Dict[str, Any],
    depth: Dict[str, Any],
    current_config: Dict[str, Any],
) -> bool:
    """
    Vérifie les conditions de sortie spécifiques à la stratégie de scalping (déséquilibre).
    """
    if not book_ticker or not depth or not depth.get("bids") or not depth.get("asks"):
        return False

    try:
        # Pas besoin de prix ici, juste la profondeur
        levels = current_config.get("SCALPING_DEPTH_LEVELS", 5)
        valid_bids = [
            Decimal(level[1])
            for level in depth["bids"][:levels]
            if len(level) > 1 and Decimal(level[1]) > 0
        ]
        valid_asks = [
            Decimal(level[1])
            for level in depth["asks"][:levels]
            if len(level) > 1 and Decimal(level[1]) > 0
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
        # Seuil de sortie: inverse du seuil d'entrée (ou proche de 1)
        exit_imbalance_threshold = (
            Decimal("1.0") / imbalance_entry_threshold
            if imbalance_entry_threshold > Decimal("1.0")
            else Decimal("0.9")
        )

        # Condition de sortie si LONG (le déséquilibre s'inverse)
        if imbalance_ratio < exit_imbalance_threshold:
            logger.info(
                f"SCALPING EXIT Condition Met: Imbalance={imbalance_ratio:.2f} (<{exit_imbalance_threshold:.2f})"
            )
            return True

    except (IndexError, TypeError, KeyError, ZeroDivisionError, InvalidOperation) as e:
        logger.error(f"SCALPING Exit Check: Erreur calcul indicateur sortie: {e}")
        return False

    return False


# check_sl_tp reste globalement inchangé mais utilise Decimal
def check_sl_tp(
    current_symbol: str,
    entry_details: Dict[str, Any],
    book_ticker: Dict[str, Any],
    current_config: Dict[str, Any],
) -> Optional[str]:
    """
    Vérifie si le Stop Loss ou le Take Profit est atteint pour SCALPING.
    Retourne 'SL' ou 'TP' si atteint, sinon None. Utilise Decimal.
    """
    if not book_ticker or not entry_details:
        return None

    try:
        entry_price = Decimal(str(entry_details.get("avg_price", "0")))
        if entry_price <= 0:
            return None

        # Pour une position LONG: SL/TP déclenchés par le prix BID (prix de vente)
        current_price = Decimal(book_ticker.get("b", "0"))  # Best Bid
        if current_price <= 0:
            return None

        # --- Stop Loss ---
        sl_pct = current_config.get(
            "STOP_LOSS_PERCENTAGE", Decimal("0.005")
        )  # Déjà Decimal
        stop_loss_price = entry_price * (Decimal(1) - sl_pct)
        if current_price <= stop_loss_price:
            logger.info(
                f"SCALPING SL Hit: Bid {current_price:.4f} <= SL {stop_loss_price:.4f} (Entry: {entry_price:.4f})"
            )
            return "SL"

        # --- Take Profit ---
        # Utiliser TP1 comme seuil principal si défini, sinon TP générique (qui est TP1 par défaut)
        tp_pct = current_config.get(
            "TAKE_PROFIT_1_PERCENTAGE", Decimal("0.01")
        )  # Déjà Decimal

        take_profit_price = entry_price * (Decimal(1) + tp_pct)

        if current_price >= take_profit_price:
            logger.info(
                f"SCALPING TP Hit: Bid {current_price:.4f} >= TP {take_profit_price:.4f} (Entry: {entry_price:.4f})"
            )
            # Note: Gestion TP1/TP2 partielle nécessiterait plus de logique. Ici, sortie totale au TP1.
            return "TP"

    except (InvalidOperation, TypeError, KeyError) as e:
        logger.error(f"SCALPING Check SL/TP Error: {e}", exc_info=True)

    return None
