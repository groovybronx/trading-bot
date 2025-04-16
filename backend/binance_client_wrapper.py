import logging
import threading # Import threading for the lock
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
import time

# Importer la configuration pour les clés API et le mode testnet
try:
    import config
    API_KEY = config.BINANCE_API_KEY
    API_SECRET = config.BINANCE_API_SECRET
    USE_TESTNET = getattr(config, 'USE_TESTNET', False) # Par défaut, utiliser l'API réelle
except ImportError:
    logging.error("Fichier config.py non trouvé ou clés API non définies dans binance_client_wrapper.")
    # Utiliser des placeholders ou lever une erreur plus explicite
    API_KEY = "YOUR_API_KEY" # Changed placeholder
    API_SECRET = "YOUR_SECRET_KEY" # Changed placeholder
    USE_TESTNET = False

# Variable globale pour le client et lock pour la gestion thread-safe
_client = None
_client_lock = threading.Lock() # Added lock

def get_client():
    """Initialise et retourne le client Binance (API réelle ou testnet) de manière thread-safe."""
    global _client
    # Utiliser un lock pour éviter les race conditions lors de l'initialisation
    with _client_lock:
        if _client is None:
            try:
                if not API_KEY or not API_SECRET or API_KEY == "YOUR_API_KEY" or API_SECRET == "YOUR_SECRET_KEY":
                     logging.error("Clés API Binance non configurées ou invalides dans config.py.")
                     # Ne pas initialiser le client si les clés sont invalides
                     return None # Retourner None directement

                if USE_TESTNET:
                    _client = Client(API_KEY, API_SECRET, testnet=True)
                    logging.info("Client Binance initialisé en mode TESTNET.")
                else:
                    _client = Client(API_KEY, API_SECRET)
                    logging.info("Client Binance initialisé en mode API réelle.")

                _client.ping() # Teste la connexion
                logging.info("Connexion à l'API Binance réussie.")

            except (BinanceAPIException, BinanceRequestException) as e:
                logging.error(f"Erreur API Binance lors de l'initialisation : {e}")
                _client = None # Assurer que _client reste None en cas d'erreur
            except Exception as e:
                logging.error(f"Erreur inattendue lors de l'initialisation du client Binance : {e}")
                _client = None # Assurer que _client reste None en cas d'erreur
        # Retourner l'instance (qui peut être None si l'initialisation a échoué)
        return _client

def get_klines(symbol, interval, limit=100, retries=3, delay=5):
    """
    Récupère les données klines pour un symbole et un intervalle donnés.
    Gère les erreurs API et les tentatives multiples.
    """
    client = get_client()
    if not client:
        logging.error("Client Binance non initialisé pour get_klines.")
        return None

    for attempt in range(retries):
        try:
            klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
            logging.debug(f"Klines récupérées pour {symbol} ({interval}), limit={limit}.")
            if not klines:
                logging.warning(f"Aucune kline retournée pour {symbol} ({interval}). Tentative {attempt + 1}/{retries}")
                # CORRECTION: Utiliser < au lieu de &lt;
                if attempt < retries - 1:
                    time.sleep(delay)
                    continue
                else:
                    logging.error(f"Échec de récupération des klines pour {symbol} après {retries} tentatives (données vides).")
                    return None
            return klines
        except (BinanceAPIException, BinanceRequestException) as e:
            logging.error(f"Erreur API Binance lors de la récupération des klines pour {symbol} ({interval}). Tentative {attempt + 1}/{retries}. Erreur : {e}")
            # CORRECTION: Utiliser < au lieu de &lt;
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                logging.error(f"Échec final de récupération des klines pour {symbol} après {retries} tentatives.")
                return None
        except Exception as e:
            logging.exception(f"Erreur inattendue lors de la récupération des klines pour {symbol} ({interval}). Tentative {attempt + 1}/{retries}.") # Utiliser logging.exception
            # CORRECTION: Utiliser < au lieu de &lt;
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                logging.error(f"Échec final de récupération des klines pour {symbol} après {retries} tentatives (erreur inattendue).")
                return None
    return None

def get_account_balance(asset='USDT'):
    """Récupère le solde disponible pour un actif spécifique."""
    client = get_client()
    if not client:
        logging.error("Client Binance non initialisé pour get_account_balance.")
        return None # Retourner None pour indiquer une erreur plutôt que 0.0

    try:
        account_info = client.get_account()
        # Utiliser .get('balances', []) pour éviter KeyError si 'balances' manque
        balances = account_info.get('balances', [])
        balance_info = next((item for item in balances if item.get("asset") == asset), None)

        if balance_info and 'free' in balance_info:
            available_balance = float(balance_info['free'])
            logging.info(f"Solde {asset} disponible récupéré : {available_balance}")
            return available_balance
        else:
            logging.warning(f"Aucune information de solde trouvée pour l'asset {asset}.")
            return 0.0 # Retourner 0.0 si l'asset n'est pas trouvé
    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"Erreur API Binance lors de la récupération du solde {asset} : {e}")
        return None # Indiquer une erreur
    except Exception as e:
        logging.exception(f"Erreur inattendue lors de la récupération du solde {asset}.") # Utiliser logging.exception
        return None # Indiquer une erreur

def get_symbol_info(symbol):
    """Récupère les informations et règles de trading pour un symbole."""
    client = get_client()
    if not client:
        logging.error("Client Binance non initialisé pour get_symbol_info.")
        return None
    try:
        info = client.get_symbol_info(symbol)
        if info:
            logging.debug(f"Informations récupérées pour le symbole {symbol}.")
            return info
        else:
            # L'API retourne None si le symbole n'existe pas, ce n'est pas forcément une erreur grave
            logging.warning(f"Aucune information trouvée pour le symbole {symbol} (symbole inexistant?).")
            return None
    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"Erreur API Binance lors de la récupération des infos pour {symbol} : {e}")
        return None
    except Exception as e:
        logging.exception(f"Erreur inattendue lors de la récupération des infos pour {symbol}.") # Utiliser logging.exception
        return None

# --- AJOUT DE LA FONCTION MANQUANTE ---
def get_symbol_ticker(symbol):
    """
    Récupère les informations du ticker (prix actuel) pour un symbole spécifique.
    Wrapper pour client.get_symbol_ticker avec gestion d'erreur.
    """
    client = get_client()
    if not client:
        logging.error("Client Binance non initialisé pour get_symbol_ticker.")
        return None

    try:
        logging.debug(f"Récupération du ticker pour {symbol}...")
        ticker = client.get_symbol_ticker(symbol=symbol)
        logging.debug(f"Ticker pour {symbol} reçu: {ticker}")
        return ticker # Retourne le dictionnaire {'symbol': '...', 'price': '...'}
    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"Erreur API/Request Binance lors de la récupération du ticker pour {symbol}: {e}")
        return None
    except Exception as e:
        logging.exception(f"Erreur inattendue lors de la récupération du ticker pour {symbol}") # Utiliser logging.exception
        return None
# --- FIN AJOUT ---


def place_order(symbol, side, quantity, order_type='MARKET', price=None, time_in_force='GTC'):
    """
    Place un ordre sur Binance avec gestion d'erreur.
    Simplifié pour MARKET et LIMIT GTC.

    Args:
        symbol (str): Le symbole (ex: 'BTCUSDT').
        side (str): 'BUY' ou 'SELL'.
        quantity (float): La quantité à acheter/vendre (doit être formatée correctement avant l'appel).
        order_type (str): 'MARKET' ou 'LIMIT'.
        price (str, optional): Le prix formaté en string pour les ordres LIMIT.
        time_in_force (str): Time in force pour LIMIT (par défaut 'GTC').

    Returns:
        dict: Les informations de l'ordre si succès, None sinon.
    """
    client = get_client()
    if not client:
        logging.error("Client Binance non initialisé pour place_order.")
        return None

    try:
        # Construire les paramètres de l'ordre
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': quantity,
        }

        if order_type == 'LIMIT':
            if price is None:
                logging.error("Le prix est requis pour un ordre LIMIT.")
                return None
            params['price'] = price
            params['timeInForce'] = time_in_force
        elif order_type != 'MARKET':
            logging.error(f"Type d'ordre '{order_type}' non supporté par cette fonction simplifiée.")
            return None

        logging.info(f"Tentative de placement d'un ordre {order_type} {side} de {quantity} {symbol}...")
        order = client.create_order(**params)
        logging.info(f"Ordre {order_type} {side} placé avec succès pour {quantity} {symbol}. OrderId: {order.get('orderId')}")
        return order

    except (BinanceAPIException, BinanceRequestException) as e:
        # Log plus détaillé de l'erreur API
        logging.error(f"Erreur API Binance lors du placement de l'ordre {order_type} {side} pour {symbol}: Code={getattr(e, 'code', 'N/A')}, Message={e}")
        return None
    except Exception as e:
        logging.exception(f"Erreur inattendue lors du placement de l'ordre {order_type} {side} pour {symbol}.") # Utiliser logging.exception
        return None

# Fonction simplifiée, place_order est plus générale
# def place_market_order(symbol, side, quantity):
#     """Place un ordre au marché simple."""
#     return place_order(symbol, side, quantity, order_type='MARKET')


# --- Autres fonctions utiles (get_open_orders, cancel_order, etc.) ---
# ... à implémenter selon les besoins ...


# Exemple d'utilisation (pour tests directs du wrapper)
if __name__ == '__main__':
    # Configurer le logging pour voir les messages INFO et DEBUG lors des tests
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    client_instance = get_client()
    if client_instance:
        print("\n--- Test get_klines ---")
        klines = get_klines('BTCUSDT', Client.KLINE_INTERVAL_1MINUTE, limit=5)
        if klines:
            print(f"Récupéré {len(klines)} klines pour BTCUSDT 1m.")
        else:
            print("Échec de la récupération des klines.")

        print("\n--- Test get_account_balance (USDT) ---")
        balance_usdt = get_account_balance('USDT')
        if balance_usdt is not None:
            print(f"Solde USDT disponible : {balance_usdt}")
        else:
            print("Échec de la récupération du solde USDT.")

        print("\n--- Test get_account_balance (BTC) ---")
        balance_btc = get_account_balance('BTC')
        if balance_btc is not None:
            print(f"Solde BTC disponible : {balance_btc}")
        else:
            print("Échec de la récupération du solde BTC.")


        print("\n--- Test get_symbol_info ---")
        info = get_symbol_info('BTCUSDT')
        if info:
            print(f"Filtres pour BTCUSDT récupérés (exemple: LOT_SIZE):")
            lot_size_filter = next((f for f in info.get('filters', []) if f.get('filterType') == 'LOT_SIZE'), None)
            if lot_size_filter:
                print(f"  minQty: {lot_size_filter.get('minQty')}, maxQty: {lot_size_filter.get('maxQty')}, stepSize: {lot_size_filter.get('stepSize')}")
            else:
                print("  Filtre LOT_SIZE non trouvé.")
        else:
            print("Échec de la récupération des infos symbole.")

        print("\n--- Test get_symbol_ticker ---")
        ticker = get_symbol_ticker('BTCUSDT')
        if ticker:
            print(f"Ticker pour BTCUSDT: {ticker}")
        else:
            print("Échec de la récupération du ticker.")


        # --- ATTENTION : Le test suivant place un ordre réel si les clés sont valides ! ---
        print("\n--- Test place_order (MARKET BUY - ATTENTION : ORDRE RÉEL SI CLÉS VALIDES) ---")
        # Décommentez avec prudence et une petite quantité valide pour tester
        test_symbol = 'BTCUSDT'
        test_side = 'BUY'
        # !! Ajuster cette quantité selon les filtres LOT_SIZE et MIN_NOTIONAL !!
        # 1. Obtenir minQty et stepSize de LOT_SIZE
        # 2. Obtenir minNotional de MIN_NOTIONAL
        # 3. Calculer une quantité q >= minQty et q * prix_actuel >= minNotional
        # 4. Formater q selon stepSize
        test_quantity_str = "0.0001" # Exemple, à adapter absolument !
        print(f"Vérification des conditions pour placer un ordre {test_side} de {test_quantity_str} {test_symbol}...")

        symbol_info_test = get_symbol_info(test_symbol)
        current_ticker = get_symbol_ticker(test_symbol)
        can_place_order = False
        if symbol_info_test and current_ticker and 'price' in current_ticker:
            try:
                current_price = float(current_ticker['price'])
                lot_size = next((f for f in symbol_info_test.get('filters', []) if f.get('filterType') == 'LOT_SIZE'), None)
                min_notional_filter = next((f for f in symbol_info_test.get('filters', []) if f.get('filterType') == 'MIN_NOTIONAL'), None)

                if lot_size and min_notional_filter:
                    min_qty = float(lot_size.get('minQty', 0))
                    step_size = float(lot_size.get('stepSize', 0))
                    min_notional = float(min_notional_filter.get('minNotional', 0))
                    test_quantity_float = float(test_quantity_str)

                    # Vérifier minQty
                    if test_quantity_float < min_qty:
                        print(f"ERREUR: Quantité {test_quantity_float} < minQty ({min_qty})")
                    # Vérifier minNotional
                    elif test_quantity_float * current_price < min_notional:
                         print(f"ERREUR: Notionnel {test_quantity_float * current_price:.2f} < minNotional ({min_notional})")
                    # Vérifier stepSize (si nécessaire, mais create_order le gère souvent)
                    # On pourrait ajouter une fonction pour formater la quantité ici
                    else:
                        print("Conditions de quantité et notionnel minimum respectées.")
                        can_place_order = True
                else:
                    print("ERREUR: Filtres LOT_SIZE ou MIN_NOTIONAL non trouvés.")
            except (ValueError, TypeError) as e:
                print(f"ERREUR lors de la vérification des filtres: {e}")
        else:
             print(f"Impossible de récupérer les infos symbole ou le ticker pour {test_symbol}, ordre non vérifié.")

        if can_place_order:
            # Décommenter la ligne suivante pour réellement placer l'ordre
            # order_result = place_order(test_symbol, test_side, test_quantity_str, order_type='MARKET')
            # if order_result:
            #     print("Ordre de test MARKET BUY placé (simulé ou réel) :", order_result)
            # else:
            #     print("Échec du placement de l'ordre de test MARKET BUY.")
            print(f"Placement d'ordre MARKET BUY pour {test_quantity_str} {test_symbol} NON EXÉCUTÉ dans cet exemple.")
        else:
            print("Placement d'ordre non tenté car les conditions ne sont pas remplies ou n'ont pas pu être vérifiées.")

    else:
        print("Impossible d'initialiser le client Binance.")
