import pandas as pd
import pandas_ta as ta
import logging
import math # Pour les ajustements de quantité (floor, log10)
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


def calculate_indicators(df):
    """
    Calcule les indicateurs techniques nécessaires sur le DataFrame de klines.

    Args:
        df (pd.DataFrame): DataFrame contenant les données OHLCV avec colonnes
                           ['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close time',
                            'Quote asset volume', 'Number of trades', 'Taker buy base asset volume',
                            'Taker buy quote asset volume', 'Ignore'] - typique de python-binance.
                           Assurez-vous que 'Close' et 'Volume' sont de type float.

    Returns:
        pd.DataFrame: DataFrame original avec les indicateurs ajoutés.
                      Retourne None si une erreur se produit.
    """
    if df is None or df.empty:
        logging.error("DataFrame vide fourni pour le calcul des indicateurs.")
        return None

    try:
        # Assurer les types de données corrects
        df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
        df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce')
        df.dropna(subset=['Close', 'Volume'], inplace=True) # Supprimer les lignes avec NaN après conversion

        if df.empty:
             logging.error("DataFrame vide après nettoyage des NaN.")
             return None

        # Calcul des EMAs
        df[f'EMA_{EMA_SHORT_PERIOD}'] = ta.ema(df['Close'], length=EMA_SHORT_PERIOD)
        df[f'EMA_{EMA_LONG_PERIOD}'] = ta.ema(df['Close'], length=EMA_LONG_PERIOD)
        if USE_EMA_FILTER:
            df[f'EMA_{EMA_FILTER_PERIOD}'] = ta.ema(df['Close'], length=EMA_FILTER_PERIOD)

        # Calcul du RSI
        df[f'RSI_{RSI_PERIOD}'] = ta.rsi(df['Close'], length=RSI_PERIOD)

        # Calcul de la moyenne mobile du volume
        if USE_VOLUME_CONFIRMATION:
            df[f'Volume_MA_{VOLUME_AVG_PERIOD}'] = ta.sma(df['Volume'], length=VOLUME_AVG_PERIOD)

        # Supprimer les lignes initiales avec NaN dues aux calculs d'indicateurs
        df.dropna(inplace=True)

        return df

    except Exception as e:
        logging.error(f"Erreur lors du calcul des indicateurs : {e}")
        return None


def generate_signals(df):
    """
    Génère les signaux d'achat (1), de vente (-1) ou neutre (0) basés sur la stratégie.

    Args:
        df (pd.DataFrame): DataFrame avec les indicateurs calculés.

    Returns:
        pd.DataFrame: DataFrame avec une colonne 'signal' ajoutée.
                      Retourne None si une erreur se produit.
    """
    if df is None or df.empty:
        logging.error("DataFrame vide fourni pour la génération de signaux.")
        return None

    try:
        # Conditions initiales (pas de signal)
        df['signal'] = 0

        # --- Conditions de base pour le croisement EMA ---
        # Croisement haussier : EMA courte passe au-dessus de l'EMA longue
        condition_crossover_bull = (df[f'EMA_{EMA_SHORT_PERIOD}'] > df[f'EMA_{EMA_LONG_PERIOD}']) & \
                                   (df[f'EMA_{EMA_SHORT_PERIOD}'].shift(1) <= df[f'EMA_{EMA_LONG_PERIOD}'].shift(1))

        # Croisement baissier : EMA courte passe en dessous de l'EMA longue
        condition_crossover_bear = (df[f'EMA_{EMA_SHORT_PERIOD}'] < df[f'EMA_{EMA_LONG_PERIOD}']) & \
                                   (df[f'EMA_{EMA_SHORT_PERIOD}'].shift(1) >= df[f'EMA_{EMA_LONG_PERIOD}'].shift(1))

        # --- Filtres Optionnels ---
        # Filtre EMA longue
        condition_ema_filter_long = True # Par défaut, n'applique pas le filtre
        if USE_EMA_FILTER:
            condition_ema_filter_long = (df['Close'] > df[f'EMA_{EMA_FILTER_PERIOD}'])

        condition_ema_filter_short = True # Par défaut, n'applique pas le filtre
        if USE_EMA_FILTER:
            condition_ema_filter_short = (df['Close'] < df[f'EMA_{EMA_FILTER_PERIOD}'])

        # Filtre RSI (éviter achat/vente extrêmes)
        condition_rsi_ok_long = (df[f'RSI_{RSI_PERIOD}'] < RSI_OVERBOUGHT)
        condition_rsi_ok_short = (df[f'RSI_{RSI_PERIOD}'] > RSI_OVERSOLD)

        # Filtre Volume (confirmation)
        condition_volume_ok = True # Par défaut, n'applique pas le filtre
        if USE_VOLUME_CONFIRMATION:
            condition_volume_ok = (df['Volume'] > df[f'Volume_MA_{VOLUME_AVG_PERIOD}'])

        # --- Application des Conditions ---
        # Signal d'Achat (Long)
        df.loc[condition_crossover_bull & condition_ema_filter_long & condition_rsi_ok_long & condition_volume_ok, 'signal'] = 1

        # Signal de Vente (Short)
        df.loc[condition_crossover_bear & condition_ema_filter_short & condition_rsi_ok_short & condition_volume_ok, 'signal'] = -1

        return df

    except KeyError as e:
        logging.error(f"Erreur de clé lors de la génération des signaux (colonne manquante ?) : {e}")
        return None
    except Exception as e:
        logging.error(f"Erreur lors de la génération des signaux : {e}")
        return None


def calculate_indicators_and_signals(klines_data):
    """
    Fonction principale pour traiter les données klines, calculer les indicateurs et générer les signaux.

    Args:
        klines_data (list): Liste de listes, format retourné par client.get_klines().

    Returns:
        pd.DataFrame: DataFrame final avec OHLCV, indicateurs et signaux.
                      Retourne None si une erreur se produit.
    """
    if not klines_data:
        logging.error("Aucune donnée kline fournie.")
        return None

    # Noms de colonnes typiques de python-binance
    columns = ['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close time',
               'Quote asset volume', 'Number of trades', 'Taker buy base asset volume',
               'Taker buy quote asset volume', 'Ignore']

    # Créer le DataFrame
    df = pd.DataFrame(klines_data, columns=columns)

    # Convertir les timestamps en datetime (optionnel mais utile)
    df['Open time'] = pd.to_datetime(df['Open time'], unit='ms')
    df['Close time'] = pd.to_datetime(df['Close time'], unit='ms')

    # Calculer les indicateurs
    df_with_indicators = calculate_indicators(df.copy()) # Utiliser une copie pour éviter SettingWithCopyWarning

    if df_with_indicators is None:
        logging.error("Échec du calcul des indicateurs.")
        return None

    # Générer les signaux
    df_with_signals = generate_signals(df_with_indicators.copy()) # Utiliser une copie

    if df_with_signals is None:
        logging.error("Échec de la génération des signaux.")
        return None

    logging.info("Indicateurs et signaux calculés avec succès.")
    return df_with_signals

# --- Fonctions pour la gestion des ordres (à développer) ---

def calculate_position_size(account_balance, risk_per_trade, entry_price, stop_loss_price, symbol_info):
    """
    Calcule la taille de la position en fonction du risque, en tenant compte des règles de Binance.

    Args:
        account_balance (float): Solde disponible du compte (en USDT).
        risk_per_trade (float): Pourcentage du capital à risquer par trade (ex: 0.01 pour 1%).
        entry_price (float): Prix d'entrée de la position.
        stop_loss_price (float): Prix du stop-loss.
        symbol_info (dict): Informations du symbole récupérées via l'API Binance (get_symbol_info).

    Returns:
        float: La quantité à acheter/vendre, formatée selon les règles de Binance (stepSize).
               Retourne 0 en cas d'erreur ou si la taille de la position est invalide.
    """
    try:
        # 1. Calculer le risque en USDT
        risk_amount = account_balance * risk_per_trade

        # 2. Calculer la distance du stop-loss (en prix)
        stop_loss_distance = abs(entry_price - stop_loss_price)

        # 3. Calculer la quantité théorique à trader
        if stop_loss_distance == 0:
            logging.error("Distance du stop-loss est zéro. Impossible de calculer la taille de la position.")
            return 0

        theoretical_quantity = risk_amount / stop_loss_distance

        # 4. Ajuster la quantité en fonction des règles de Binance (LOT_SIZE)
        lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
        if not lot_size_filter:
            logging.error("Filtre LOT_SIZE non trouvé dans les informations du symbole.")
            return 0

        min_qty = float(lot_size_filter.get('minQty'))
        max_qty = float(lot_size_filter.get('maxQty'))
        step_size = float(lot_size_filter.get('stepSize'))

        # Formater la quantité selon le stepSize
        # Exemple : si stepSize est 0.001, on veut arrondir à 3 décimales
        decimal_places = int(-math.log10(step_size)) if step_size > 0 else 0 # Gérer le cas stepSize == 0

        # Arrondir à la baisse (floor) pour respecter le stepSize
        # Utiliser une chaîne de formatage pour contrôler le nombre de décimales
        # Correction: On doit arrondir *vers le bas* au multiple de step_size
        # quantity = math.floor(theoretical_quantity / step_size) * step_size
        # Utiliser le formatage est plus simple pour les décimales standard
        quantity = math.floor(theoretical_quantity * (10**decimal_places)) / (10**decimal_places)


        # 5. Vérifier les contraintes minQty et maxQty
        if quantity < min_qty:
            logging.warning(f"Quantité calculée ({quantity}) après arrondi est inférieure à la quantité minimale autorisée ({min_qty}).")
            return 0
        if quantity > max_qty:
            logging.warning(f"Quantité calculée ({quantity}) est supérieure à la quantité maximale autorisée ({max_qty}). Ajustement à maxQty.")
            quantity = max_qty # Ou retourner 0 si on ne veut pas ajuster ?

        # Re-vérifier après ajustement potentiel à maxQty (si maxQty < minQty, ce qui ne devrait pas arriver)
        if quantity < min_qty:
             logging.error(f"Quantité ({quantity}) toujours inférieure à minQty ({min_qty}) même après ajustement maxQty. Problème de configuration?")
             return 0


        logging.info(f"Taille de position calculée : {quantity} (risque : {risk_amount:.2f} USDT, distance SL : {stop_loss_distance:.4f})")
        return quantity

    except Exception as e:
        logging.error(f"Erreur lors du calcul de la taille de la position : {e}")
        return 0

# CORRECTION: Removed 'client' parameter
def check_entry_conditions(current_signal_data, symbol, risk_per_trade, capital_allocation, available_balance, symbol_info):
    """
    Vérifie s'il faut entrer en position et place l'ordre si toutes les conditions sont remplies.
    Utilise le client géré par binance_client_wrapper.

    Args:
        current_signal_data (pd.Series): Les données de la bougie actuelle et les signaux.
        symbol (str): Le symbole à trader.
        risk_per_trade (float): Le risque par trade (ex: 0.01 pour 1%).
        capital_allocation (float): Le pourcentage du capital à allouer (pourrait être utilisé).
        available_balance (float): Le solde disponible.
        symbol_info (dict): Les informations du symbole (pour LOT_SIZE).

    Returns:
        bool: True si l'ordre a été placé avec succès, False sinon.
    """
    try:
        # 1. Vérifier s'il y a déjà une position ouverte (à implémenter plus tard si nécessaire)
        # open_positions = binance_client_wrapper.get_open_orders(symbol=symbol) # No client passed
        # if open_positions:
        #     logging.warning(f"Position déjà ouverte pour {symbol}. Pas de nouvelle entrée.")
        #     return False

        # 2. Vérifier le signal (1 pour long, -1 pour short)
        signal = current_signal_data['signal']
        if signal == 0:
            # logging.info("Pas de signal d'entrée.") # Peut être trop verbeux
            return False

        side = 'BUY' if signal == 1 else 'SELL' # BUY pour long, SELL pour short
        logging.info(f"Signal d'entrée {side} détecté pour {symbol}.")

        # 3. Définir le prix d'entrée et le prix du stop-loss
        entry_price = current_signal_data['Close'] # Utiliser le prix de clôture comme prix d'entrée
        # Exemple simple : stop-loss à 0.3% en dessous/au-dessus du prix d'entrée
        stop_loss_percent = 0.003 # 0.3%
        stop_loss_price = entry_price * (1 - stop_loss_percent) if side == 'BUY' else entry_price * (1 + stop_loss_percent)

        # 4. Calculer la taille de la position
        quantity = calculate_position_size(available_balance, risk_per_trade, entry_price, stop_loss_price, symbol_info)
        if quantity == 0:
            logging.error("Impossible de calculer une taille de position valide. Pas d'ordre placé.")
            return False

        # 5. Placer l'ordre via le wrapper (qui gère le client)
        logging.info(f"Tentative de placement d'ordre {side} {quantity} {symbol} au marché...")
        # CORRECTION: Assume place_order in wrapper doesn't need client passed
        order = binance_client_wrapper.place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type='MARKET'
            # price=None,
            # stop_loss_price=None,
            # take_profit_price=None
        )

        if order:
            # La fonction place_order dans le wrapper devrait déjà logger le succès/échec
            # logging.info(f"Ordre {side} placé avec succès pour {symbol} (quantité: {quantity}). Détails: {order}")
            return True
        else:
            # La fonction place_order dans le wrapper devrait déjà logger l'échec
            # logging.error(f"Échec du placement de l'ordre {side} pour {symbol}.")
            return False

    except Exception as e:
        # Log l'exception complète avec traceback
        logging.exception(f"Erreur lors de la vérification des conditions d'entrée")
        return False

# CORRECTION: Removed 'client' parameter
def check_exit_conditions(symbol):
    """Vérifie s'il faut sortir d'une position existante (TP/SL/Signal inverse)."""
    # ... logique à implémenter ...
    # Utiliser binance_client_wrapper pour récupérer les positions, ordres, etc.
    # Exemple:
    # position = binance_client_wrapper.get_position(symbol)
    # if position:
    #    current_price = binance_client_wrapper.get_current_price(symbol)
    #    # Vérifier SL/TP/Signal inverse
    #    if should_exit:
    #        binance_client_wrapper.close_position(symbol, position_qty)
    pass

# Exemple d'utilisation (pourrait être dans bot.py)
if __name__ == '__main__':
    # Ceci est un exemple, nécessite de vraies données klines
    logging.basicConfig(level=logging.INFO)
    # Simuler des données klines (remplacer par un appel API réel)
    dummy_klines = [
        [1678886400000, '27000', '27100', '26900', '27050', '100', 1678886699999, '2705000', 1000, '50', '1352500', '0'],
        [1678886700000, '27050', '27200', '27000', '27150', '120', 1678886999999, '3258000', 1200, '60', '1629000', '0'],
        # ... ajouter plus de données pour que les indicateurs soient valides
    ] * 100 # Multiplier pour avoir assez de données pour les indicateurs

    # Ajuster la condition pour vérifier la longueur des données
    required_length = max(EMA_SHORT_PERIOD, EMA_LONG_PERIOD, EMA_FILTER_PERIOD if USE_EMA_FILTER else 0, RSI_PERIOD, VOLUME_AVG_PERIOD if USE_VOLUME_CONFIRMATION else 0) + 5

    if len(dummy_klines) > required_length: # Assurer assez de données
        results = calculate_indicators_and_signals(dummy_klines)
        if results is not None:
            print("Calculs terminés. Dernières lignes avec signaux :")
            print(results.tail())
            # Afficher les signaux générés
            print("\nSignaux générés (1=Achat, -1=Vente):")
            print(results[results['signal'] != 0]['signal'])
        else:
            print("Erreur lors du calcul.")
    else:
        print(f"Pas assez de données simulées ({len(dummy_klines)}) pour calculer les indicateurs (besoin > {required_length}).")

    # Exemple de calcul de taille de position (nécessite symbol_info réel)
    dummy_symbol_info = {
        'symbol': 'BTCUSDT',
        'filters': [
            {'filterType': 'PRICE_FILTER', 'minPrice': '0.01', 'maxPrice': '1000000.00', 'tickSize': '0.01'},
            {'filterType': 'LOT_SIZE', 'minQty': '0.00001', 'maxQty': '9000.0', 'stepSize': '0.00001'},
            {'filterType': 'ICEBERG_PARTS', 'limit': 10},
            {'filterType': 'MARKET_LOT_SIZE', 'minQty': '0.0', 'maxQty': '100.0', 'stepSize': '0.0'},
            {'filterType': 'TRAILING_DELTA', 'minTrailingAboveDelta': 10, 'maxTrailingAboveDelta': 2000, 'minTrailingBelowDelta': 10, 'maxTrailingBelowDelta': 2000},
            {'filterType': 'PERCENT_PRICE_BY_SIDE', 'bidMultiplierUp': '5', 'bidMultiplierDown': '0.2', 'askMultiplierUp': '5', 'askMultiplierDown': '0.2', 'avgPriceMins': 5},
            {'filterType': 'NOTIONAL', 'minNotional': '10.0', 'applyMinToMarket': True, 'maxNotional': '9000000.0', 'avgPriceMins': 5},
            {'filterType': 'MAX_NUM_ORDERS', 'maxNumOrders': 200},
            {'filterType': 'MAX_NUM_ALGO_ORDERS', 'maxNumAlgoOrders': 5}
        ]
    }
    print("\nExemple calcul taille position:")
    qty = calculate_position_size(1000, 0.01, 27000, 26900, dummy_symbol_info)
    print(f"Quantité calculée: {qty}")

