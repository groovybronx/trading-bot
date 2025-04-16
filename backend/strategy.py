import pandas as pd
import pandas_ta as ta
import logging
from decimal import Decimal, ROUND_DOWN, InvalidOperation # Pour le formatage précis et la gestion d'erreur
import binance_client_wrapper # Import the wrapper

# Importer la configuration (pour les périodes, niveaux RSI, etc.)
try:
    import config
    # Définir les paramètres à partir de config.py ou utiliser des valeurs par défaut
    EMA_SHORT_PERIOD = getattr(config, 'EMA_SHORT_PERIOD', 9)
    EMA_LONG_PERIOD = getattr(config, 'EMA_LONG_PERIOD', 21)
    EMA_FILTER_PERIOD = getattr(config, 'EMA_FILTER_PERIOD', 50) # Optionnel
    RSI_PERIOD = getattr(config, 'RSI_PERIOD', 14)
    RSI_OVERBOUGHT = getattr(config, 'RSI_OVERBOUGHT', 75)
    RSI_OVERSOLD = getattr(config, 'RSI_OVERSOLD', 25)
    VOLUME_AVG_PERIOD = getattr(config, 'VOLUME_AVG_PERIOD', 20) # Pour la confirmation de volume
    USE_EMA_FILTER = getattr(config, 'USE_EMA_FILTER', True) # Activer/désactiver le filtre EMA long
    USE_VOLUME_CONFIRMATION = getattr(config, 'USE_VOLUME_CONFIRMATION', False) # Activer/désactiver confirmation volume

except ImportError:
    logging.warning("Fichier config.py non trouvé. Utilisation des paramètres par défaut pour la stratégie.")
    # Valeurs par défaut si config.py n'est pas là
    EMA_SHORT_PERIOD = 9
    EMA_LONG_PERIOD = 21
    EMA_FILTER_PERIOD = 50
    RSI_PERIOD = 14
    RSI_OVERBOUGHT = 75
    RSI_OVERSOLD = 25
    VOLUME_AVG_PERIOD = 20
    USE_EMA_FILTER = True
    USE_VOLUME_CONFIRMATION = False


def format_quantity(quantity, symbol_info):
    """
    Formate la quantité selon les règles LOT_SIZE du symbole en utilisant Decimal.

    Args:
        quantity (float): La quantité théorique.
        symbol_info (dict): Informations du symbole de Binance.

    Returns:
        float: Quantité formatée, ou 0.0 si erreur ou formatage impossible.
    """
    try:
        lot_size_filter = next((f for f in symbol_info.get('filters', []) if f.get('filterType') == 'LOT_SIZE'), None)
        if lot_size_filter:
            step_size_str = lot_size_filter.get('stepSize')
            min_qty_str = lot_size_filter.get('minQty')
            if step_size_str and min_qty_str:
                step_size = Decimal(step_size_str)
                min_qty = Decimal(min_qty_str)
                # Convertir float en Decimal via str pour précision
                quantity_decimal = Decimal(str(quantity))

                # Arrondir vers le bas (floor) au multiple de step_size
                formatted_quantity_decimal = (quantity_decimal // step_size) * step_size
                # Alternativement, pour arrondir au nombre de décimales de step_size:
                # formatted_quantity_decimal = quantity_decimal.quantize(step_size, rounding=ROUND_DOWN)

                formatted_quantity = float(formatted_quantity_decimal)

                # Vérifier si la quantité formatée est >= minQty
                if formatted_quantity_decimal < min_qty:
                     logging.warning(f"Quantité formatée {formatted_quantity} < minQty ({min_qty_str}). Retourne 0.")
                     return 0.0

                logging.debug(f"Quantité {quantity} formatée à {formatted_quantity} (stepSize: {step_size_str}, minQty: {min_qty_str})")
                return formatted_quantity
        # Si pas de filtre ou stepSize/minQty, retourner 0 car on ne peut pas garantir la validité
        logging.error(f"Impossible de formater la quantité pour {symbol_info.get('symbol')}: filtre LOT_SIZE ou stepSize/minQty manquant.")
        return 0.0
    except (InvalidOperation, TypeError, ValueError, KeyError, AttributeError) as e:
        logging.error(f"Erreur lors du formatage de la quantité: {e}")
        return 0.0 # Retourner 0 en cas d'erreur


def calculate_position_size(balance, risk_per_trade, entry_price, stop_loss_price, symbol_info):
    """
    Calcule la taille de la position en fonction du risque, en tenant compte des règles LOT_SIZE et MIN_NOTIONAL.

    Args:
        balance (float): Solde disponible (ou alloué) de l'asset de cotation (ex: USDT).
        risk_per_trade (float): Pourcentage du capital à risquer (ex: 0.01 pour 1%).
        entry_price (float): Prix d'entrée prévu.
        stop_loss_price (float): Prix du stop-loss prévu.
        symbol_info (dict): Informations du symbole de Binance.

    Returns:
        float: Quantité formatée à trader, ou 0.0 si invalide ou erreur.
    """
    try:
        if entry_price <= 0 or stop_loss_price <= 0:
             logging.error("Prix d'entrée ou de stop loss invalide (<= 0).")
             return 0.0

        risk_amount = balance * risk_per_trade
        risk_per_unit = abs(entry_price - stop_loss_price)

        if risk_per_unit == 0:
            logging.warning("Calcul taille position: Risque par unité est zéro (entry=stop_loss?).")
            return 0.0

        theoretical_quantity = risk_amount / risk_per_unit
        formatted_quantity = format_quantity(theoretical_quantity, symbol_info) # Utilise la fonction de formatage

        if formatted_quantity <= 0:
             # Le formatage a échoué ou la quantité est trop petite (inférieure à minQty)
             # Les logs sont déjà dans format_quantity
             return 0.0

        # Vérifier MIN_NOTIONAL
        min_notional_filter = next((f for f in symbol_info.get('filters', []) if f.get('filterType') == 'MIN_NOTIONAL'), None)
        if min_notional_filter:
            min_notional_str = min_notional_filter.get('minNotional')
            if min_notional_str:
                min_notional = float(min_notional_str)
                current_notional = formatted_quantity * entry_price
                if current_notional < min_notional:
                    logging.warning(f"Taille calculée ({formatted_quantity}) trop petite pour MIN_NOTIONAL ({min_notional_str}). Notionnel: {current_notional:.2f}")
                    return 0.0 # Ne pas trader si trop petit

        logging.info(f"Taille de position calculée et formatée: {formatted_quantity} (Risque: {risk_amount:.2f}, Risque/unité: {risk_per_unit:.4f})")
        return formatted_quantity

    except (TypeError, ValueError, KeyError, AttributeError, ZeroDivisionError) as e:
        logging.error(f"Erreur lors du calcul de la taille de position: {e}")
        return 0.0


def calculate_indicators_and_signals(klines_list):
    """
    Calcule les indicateurs et génère des signaux sur les données klines fournies.
    Combine calculate_indicators et generate_signals.
    """
    if not klines_list:
        logging.error("Aucune donnée kline fournie pour calculate_indicators_and_signals.")
        return None
    try:
        # 1. Créer le DataFrame
        columns = ['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close time',
                   'Quote asset volume', 'Number of trades', 'Taker buy base asset volume',
                   'Taker buy quote asset volume', 'Ignore']
        df = pd.DataFrame(klines_list, columns=columns)

        # 2. Convertir les types et nettoyer
        for col in ['Open', 'High', 'Low', 'Close', 'Volume', 'Quote asset volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(subset=['Open', 'High', 'Low', 'Close', 'Volume'], inplace=True)
        if df.empty:
             logging.error("DataFrame vide après nettoyage initial.")
             return None
        df['Close time'] = pd.to_datetime(df['Close time'], unit='ms') # Optionnel

        # 3. Calculer les indicateurs avec pandas_ta
        df.ta.ema(length=EMA_SHORT_PERIOD, append=True)
        df.ta.ema(length=EMA_LONG_PERIOD, append=True)
        df.ta.rsi(length=RSI_PERIOD, append=True)
        if USE_EMA_FILTER:
            df.ta.ema(length=EMA_FILTER_PERIOD, append=True)
        if USE_VOLUME_CONFIRMATION:
             df.ta.sma(close='Volume', length=VOLUME_AVG_PERIOD, prefix='VOL', append=True) # Ajoute VOL_SMA_...

        # Supprimer les lignes avec NaN générés par les indicateurs
        df.dropna(inplace=True)
        if df.empty:
             logging.error("DataFrame vide après calcul des indicateurs et dropna.")
             return None

        # 4. Générer les signaux
        # Renommer les colonnes pour la clarté (ajuster selon les noms générés par ta)
        ema_short_col = df.columns[df.columns.str.startswith(f'EMA_{EMA_SHORT_PERIOD}')][0]
        ema_long_col = df.columns[df.columns.str.startswith(f'EMA_{EMA_LONG_PERIOD}')][0]
        rsi_col = df.columns[df.columns.str.startswith(f'RSI_{RSI_PERIOD}')][0]
        ema_filter_col = f'EMA_{EMA_FILTER_PERIOD}' if USE_EMA_FILTER else None
        vol_sma_col = df.columns[df.columns.str.startswith(f'VOL_SMA_{VOLUME_AVG_PERIOD}')][0] if USE_VOLUME_CONFIRMATION else None

        # Conditions d'achat (Long)
        buy_condition = (df[ema_short_col] > df[ema_long_col]) & \
                        (df[ema_short_col].shift(1) <= df[ema_long_col].shift(1)) & \
                        (df[rsi_col] < RSI_OVERBOUGHT)

        if USE_EMA_FILTER and ema_filter_col in df.columns:
            buy_condition = buy_condition & (df['Close'] > df[ema_filter_col])

        if USE_VOLUME_CONFIRMATION and vol_sma_col in df.columns:
             buy_condition = buy_condition & (df['Volume'] > df[vol_sma_col])

        # Conditions de vente (Short/Exit)
        sell_condition = (df[ema_short_col] < df[ema_long_col]) & \
                         (df[ema_short_col].shift(1) >= df[ema_long_col].shift(1)) & \
                         (df[rsi_col] > RSI_OVERSOLD)

        # Appliquer les conditions pour créer la colonne 'signal'
        df['signal'] = 'HOLD' # Par défaut
        df.loc[buy_condition, 'signal'] = 'BUY'
        df.loc[sell_condition, 'signal'] = 'SELL' # Pour la sortie de position

        logging.debug(f"Calcul indicateurs/signaux terminé. Dernière ligne: {df.iloc[-1].to_dict()}")
        return df

    except KeyError as e:
        logging.error(f"Erreur de clé lors du calcul indicateurs/signaux (colonne manquante?): {e}")
        return None
    except Exception as e:
        logging.exception("Erreur inattendue lors du calcul des indicateurs/signaux.")
        return None


def check_entry_conditions(current_data, symbol, risk_per_trade, capital_allocation, available_balance, symbol_info):
    """
    Vérifie les conditions d'entrée et place un ordre si nécessaire.
    Retourne les détails de l'ordre (dict) si placé, None sinon.
    """
    signal = current_data.get('signal')
    order_details = None # Initialiser

    if signal == 'BUY':
        logging.info(f"Signal d'ACHAT détecté pour {symbol}!")

        entry_price = current_data['Close'] # Utiliser le prix de clôture comme prix d'entrée approx.

        # Définir un stop-loss (exemple simple: sous le dernier Low ou basé sur ATR)
        # Pour cet exemple, utilisons un % sous le prix d'entrée
        stop_loss_percentage = 0.02 # Exemple: 2%
        stop_loss_price = entry_price * (1 - stop_loss_percentage)

        # Calculer la taille de la position
        # Utiliser seulement une partie du capital disponible si capital_allocation < 1
        effective_balance = available_balance * capital_allocation
        quantity = calculate_position_size(effective_balance, risk_per_trade, entry_price, stop_loss_price, symbol_info)

        if quantity > 0:
            # La quantité est déjà formatée et validée par calculate_position_size
            logging.info(f"Conditions d'entrée remplies. Tentative d'achat de {quantity} {symbol}...")

            # Placer l'ordre MARKET via le wrapper
            order_details = binance_client_wrapper.place_order(
                symbol=symbol,
                side='BUY',
                quantity=quantity, # Utiliser la quantité formatée
                order_type='MARKET'
            )
            if order_details:
                # Le wrapper logue déjà le succès/échec
                # !! IMPORTANT: Retourner les détails de l'ordre !!
                return order_details
            else:
                # Le wrapper logue déjà l'échec
                return None # Échec du placement
        else:
            # calculate_position_size a déjà loggué pourquoi quantity est 0
            logging.warning("Taille de position calculée est 0 ou invalide, pas d'ordre d'achat placé.")
            return None # Taille de position nulle ou invalide

    # Si pas de signal BUY
    return None


def check_exit_conditions(current_data, symbol, current_quantity, symbol_info):
    """
    Vérifie les conditions de sortie (signal SELL) et place un ordre si nécessaire.
    Retourne les détails de l'ordre (dict) si placé, None sinon.
    """
    signal = current_data.get('signal')
    order_details = None

    if signal == 'SELL':
        logging.info(f"Signal de VENTE (sortie) détecté pour {symbol}!")

        # Formater la quantité actuelle possédée pour s'assurer qu'elle respecte stepSize
        # Important si la quantité a été acquise via plusieurs ordres partiels par ex.
        # Utiliser la quantité de bot_state['symbol_quantity'] passée en argument
        quantity_to_sell = format_quantity(current_quantity, symbol_info)

        if quantity_to_sell > 0:
             logging.info(f"Conditions de sortie remplies. Tentative de vente de {quantity_to_sell} {symbol}...")
             # Placer l'ordre MARKET SELL via le wrapper
             order_details = binance_client_wrapper.place_order(
                 symbol=symbol,
                 side='SELL',
                 quantity=quantity_to_sell, # Utiliser la quantité formatée
                 order_type='MARKET'
             )
             if order_details:
                 # Le wrapper logue déjà le succès/échec
                 # !! IMPORTANT: Retourner les détails de l'ordre !!
                 return order_details
             else:
                 # Le wrapper logue déjà l'échec
                 return None
        else:
             logging.warning(f"Quantité à vendre ({current_quantity}) formatée à 0 ou invalide, pas d'ordre de vente placé.")
             return None

    # Si pas de signal SELL
    return None


# Exemple d'utilisation (pourrait être dans bot.py)
if __name__ == '__main__':
    # Ceci est un exemple, nécessite de vraies données klines
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Simuler des données klines (remplacer par un appel API réel)
    # Générer plus de données pour les indicateurs
    base_price = 27000
    dummy_klines = []
    for i in range(200): # Générer 200 bougies
        open_p = base_price + (i % 10) * 10
        high_p = open_p + 50
        low_p = open_p - 50
        close_p = low_p + 70 + (i%5)*5 # Simuler une variation
        volume = 100 + (i%20)*5
        timestamp = 1678886400000 + i * 60000 # Chaque minute
        dummy_klines.append([
            timestamp, str(open_p), str(high_p), str(low_p), str(close_p), str(volume),
            timestamp + 59999, str(close_p * volume / 10), 100 + i, str(volume/2), str(close_p*volume/20), '0'
        ])

    required_length = max(EMA_SHORT_PERIOD, EMA_LONG_PERIOD, EMA_FILTER_PERIOD if USE_EMA_FILTER else 0, RSI_PERIOD, VOLUME_AVG_PERIOD if USE_VOLUME_CONFIRMATION else 0) + 5

    if len(dummy_klines) >= required_length: # Utiliser >=
        results = calculate_indicators_and_signals(dummy_klines)
        if results is not None and not results.empty:
            print("Calculs terminés. Dernières lignes avec signaux :")
            print(results.tail())
            print("\nSignaux générés (BUY=1, SELL=-1):")
            print(results[results['signal'] != 'HOLD']['signal']) # Afficher seulement BUY/SELL
        else:
            print("Erreur lors du calcul ou DataFrame vide après calcul.")
    else:
        print(f"Pas assez de données simulées ({len(dummy_klines)}) pour calculer les indicateurs (besoin >= {required_length}).")

    # Exemple de calcul de taille de position (nécessite symbol_info réel)
    dummy_symbol_info = {
        'symbol': 'BTCUSDT',
        'filters': [
            {'filterType': 'PRICE_FILTER', 'minPrice': '0.01', 'maxPrice': '1000000.00', 'tickSize': '0.01'},
            {'filterType': 'LOT_SIZE', 'minQty': '0.00001000', 'maxQty': '9000.00000000', 'stepSize': '0.00001000'},
            {'filterType': 'ICEBERG_PARTS', 'limit': 10},
            {'filterType': 'MARKET_LOT_SIZE', 'minQty': '0.00000000', 'maxQty': '130.55801384', 'stepSize': '0.00000000'},
            {'filterType': 'TRAILING_DELTA', 'minTrailingAboveDelta': 10, 'maxTrailingAboveDelta': 2000, 'minTrailingBelowDelta': 10, 'maxTrailingBelowDelta': 2000},
            {'filterType': 'PERCENT_PRICE_BY_SIDE', 'bidMultiplierUp': '5', 'bidMultiplierDown': '0.2', 'askMultiplierUp': '5', 'askMultiplierDown': '0.2', 'avgPriceMins': 5},
            {'filterType': 'NOTIONAL', 'minNotional': '10.00000000', 'applyMinToMarket': True, 'maxNotional': '9000000.00000000', 'avgPriceMins': 5}, # Changed from MIN_NOTIONAL
            {'filterType': 'MAX_NUM_ORDERS', 'maxNumOrders': 200},
            {'filterType': 'MAX_NUM_ALGO_ORDERS', 'maxNumAlgoOrders': 5}
        ]
    }
    print("\nExemple calcul taille position:")
    qty = calculate_position_size(1000, 0.01, 27000, 26900, dummy_symbol_info)
    print(f"Quantité calculée: {qty}")

    # Simuler une donnée de signal pour tester check_entry_conditions
    if results is not None and not results.empty:
         print("\nTest check_entry_conditions (simulation):")
         last_data = results.iloc[-1].copy()
         last_data['signal'] = 'BUY' # Forcer un signal d'achat pour le test
         # Simuler un appel (ne place pas d'ordre réel car le wrapper n'est pas initialisé ici)
         # Pour un test réel, il faudrait initialiser le wrapper avec des clés (testnet de préférence)
         print("Simulating check_entry_conditions with BUY signal...")
         # result = check_entry_conditions(last_data, 'BTCUSDT', 0.01, 1.0, 1000, dummy_symbol_info)
         # print(f"Résultat simulation check_entry_conditions: {result}") # Devrait être None car place_order échoue
    else:
         print("\nImpossible de tester check_entry_conditions car les calculs précédents ont échoué.")
