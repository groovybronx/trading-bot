import logging
import threading
import time
from typing import Optional, List, Dict, Any

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# Importer la configuration pour les clés API et le mode testnet
try:
    import config
    API_KEY = config.BINANCE_API_KEY
    API_SECRET = config.BINANCE_API_SECRET
    USE_TESTNET = getattr(config, 'USE_TESTNET', False)
except ImportError:
    logging.error("Fichier config.py non trouvé ou clés API non définies dans binance_client_wrapper.")
    API_KEY = "YOUR_API_KEY_PLACEHOLDER"
    API_SECRET = "YOUR_SECRET_KEY_PLACEHOLDER"
    USE_TESTNET = False

# Variable globale pour le client et lock pour la gestion thread-safe
_client: Optional[Client] = None
_client_lock = threading.Lock()

# Configuration du logging (partagé avec bot.py)
logger = logging.getLogger()

def get_client() -> Optional[Client]:
    """
    Initialise et retourne le client Binance (API réelle ou testnet) de manière thread-safe.
    Retourne None si l'initialisation échoue.
    """
    global _client
    with _client_lock:
        if _client is None:
            try:
                # Vérification plus robuste des clés placeholders
                if not API_KEY or not API_SECRET or API_KEY == "YOUR_API_KEY_PLACEHOLDER" or API_SECRET == "YOUR_SECRET_KEY_PLACEHOLDER":
                    logger.error("Clés API Binance non configurées ou invalides dans config.py ou .env.")
                    return None

                if USE_TESTNET:
                    _client = Client(API_KEY, API_SECRET, testnet=True)
                    logger.info("Client Binance initialisé en mode TESTNET.")
                else:
                    _client = Client(API_KEY, API_SECRET)
                    logger.info("Client Binance initialisé en mode API réelle.")

                _client.ping()
                logger.info("Connexion à l'API Binance réussie (ping OK).")

            except (BinanceAPIException, BinanceRequestException) as e:
                logger.error(f"Erreur API Binance lors de l'initialisation : {e}")
                _client = None
            except Exception as e:
                logger.exception(f"Erreur inattendue lors de l'initialisation du client Binance : {e}")
                _client = None
        return _client

def get_klines(
    symbol: str,
    interval: str,
    limit: int = 100,
    retries: int = 3,
    delay: int = 5
) -> Optional[List[List[Any]]]:
    """
    Récupère les données klines pour un symbole et un intervalle donnés.
    Gère les erreurs API et les tentatives multiples.
    (Correction Pylance appliquée)
    """
    client = get_client()
    if not client:
        logger.error("Client Binance non initialisé pour get_klines.")
        return None

    for attempt in range(retries):
        try:
            klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
            logger.debug(f"Klines récupérées pour {symbol} ({interval}), limit={limit}.")

            # --- FIX: Add explicit type check before returning ---
            if isinstance(klines, list) and all(isinstance(item, list) for item in klines):
                return klines # Succès - Confirmed it's a list of lists
            elif not klines and isinstance(klines, list): # Handle empty list case
                 logger.warning(f"Aucune kline retournée (liste vide) pour {symbol} ({interval}). Tentative {attempt + 1}/{retries}")
                 if attempt < retries - 1: time.sleep(delay); continue
                 else: logger.error(f"Échec récupération klines pour {symbol} après {retries} tentatives (données vides)."); return None
            else:
                # This case *shouldn't* happen based on API behavior, but handles Pylance's concern
                logger.error(f"Type inattendu reçu de client.get_klines pour {symbol}: {type(klines)}. Attendu: List[List[Any]]")
                return None # Return None as per the function's type hint on failure/unexpected type
            # --- END FIX ---

        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"Erreur API Binance lors récupération klines {symbol} ({interval}). Tentative {attempt + 1}/{retries}. Erreur : {e}")
            if attempt < retries - 1: time.sleep(delay)
            else: logger.error(f"Échec final récupération klines {symbol} après {retries} tentatives."); return None
        except Exception as e:
            logger.exception(f"Erreur inattendue lors récupération klines {symbol} ({interval}). Tentative {attempt + 1}/{retries}.")
            if attempt < retries - 1: time.sleep(delay)
            else: logger.error(f"Échec final récupération klines {symbol} après {retries} tentatives (erreur inattendue)."); return None
    return None

def get_account_balance(asset: str = 'USDT') -> Optional[float]:
    """
    Récupère le solde disponible ('free') pour un actif spécifique.
    (Code inchangé par rapport à la version précédente)
    """
    client = get_client()
    if not client: logger.error("Client Binance non initialisé pour get_account_balance."); return None
    try:
        account_info = client.get_account()
        balances = account_info.get('balances', [])
        balance_info = next((item for item in balances if item.get("asset") == asset), None)
        if balance_info and 'free' in balance_info:
            try:
                available_balance = float(balance_info['free'])
                logger.info(f"Solde {asset} disponible récupéré : {available_balance}")
                return available_balance
            except (ValueError, TypeError):
                 logger.error(f"Impossible de convertir le solde 'free' ({balance_info['free']}) en float pour {asset}.")
                 return None
        else:
            logger.warning(f"Aucune information de solde trouvée pour l'asset {asset} dans le compte.")
            return 0.0
    except (BinanceAPIException, BinanceRequestException) as e:
        logger.error(f"Erreur API Binance lors de la récupération du solde {asset} : {e}")
        return None
    except Exception as e:
        logger.exception(f"Erreur inattendue lors de la récupération du solde {asset}.")
        return None

def get_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Récupère les informations et règles de trading pour un symbole.
    (Code inchangé par rapport à la version précédente)
    """
    client = get_client()
    if not client: logger.error("Client Binance non initialisé pour get_symbol_info."); return None
    try:
        info = client.get_symbol_info(symbol)
        if info: logger.debug(f"Informations récupérées pour le symbole {symbol}."); return info
        else: logger.warning(f"Aucune information trouvée pour le symbole {symbol} (symbole inexistant?)."); return None
    except (BinanceAPIException, BinanceRequestException) as e:
        logger.error(f"Erreur API Binance lors de la récupération des infos pour {symbol} : {e}")
        return None
    except Exception as e:
        logger.exception(f"Erreur inattendue lors de la récupération des infos pour {symbol}.")
        return None

def get_symbol_ticker(symbol: str) -> Optional[Dict[str, str]]:
    """
    Récupère les informations du ticker (prix actuel) pour un symbole spécifique.
    (Code inchangé par rapport à la version précédente)
    """
    client = get_client()
    if not client: logger.error("Client Binance non initialisé pour get_symbol_ticker."); return None
    try:
        logger.debug(f"Récupération du ticker pour {symbol}...")
        ticker = client.get_symbol_ticker(symbol=symbol)
        logger.debug(f"Ticker pour {symbol} reçu: {ticker}")
        return ticker
    except (BinanceAPIException, BinanceRequestException) as e:
        logger.error(f"Erreur API/Request Binance lors de la récupération du ticker pour {symbol}: {e}")
        return None
    except Exception as e:
        logger.exception(f"Erreur inattendue lors de la récupération du ticker pour {symbol}")
        return None

def place_order(
    symbol: str,
    side: str,
    quantity: float,
    order_type: str = 'MARKET',
    price: Optional[str] = None,
    time_in_force: str = 'GTC'
) -> Optional[Dict[str, Any]]:
    """
    Place un ordre sur Binance avec gestion d'erreur.
    (Code inchangé par rapport à la version précédente)
    """
    client = get_client()
    if not client: logger.error("Client Binance non initialisé pour place_order."); return None
    try:
        params = {'symbol': symbol, 'side': side, 'type': order_type, 'quantity': quantity}
        if order_type == 'LIMIT':
            if price is None: logger.error("Le prix est requis pour un ordre LIMIT."); return None
            params['price'] = price; params['timeInForce'] = time_in_force
        elif order_type != 'MARKET':
            logger.error(f"Type d'ordre '{order_type}' non supporté."); return None
        log_price_info = f"au prix {price}" if order_type == 'LIMIT' else "au marché"
        logger.info(f"Tentative de placement d'un ordre {order_type} {side} de {quantity} {symbol} {log_price_info}...")
        order = client.create_order(**params)
        order_id = order.get('orderId', 'N/A'); status = order.get('status', 'N/A')
        logger.info(f"Ordre {order_type} {side} placé avec succès pour {quantity} {symbol}. OrderId: {order_id}, Statut: {status}")
        return order
    except (BinanceAPIException, BinanceRequestException) as e:
        logger.error(f"Erreur API Binance lors placement ordre {order_type} {side} {symbol}: Code={getattr(e, 'code', 'N/A')}, Message={e}")
        return None
    except Exception as e:
        logger.exception(f"Erreur inattendue lors placement ordre {order_type} {side} {symbol}.")
        return None

# --- Fonctions pour User Data Stream ---

def start_user_data_stream() -> Optional[str]:
    """
    Démarre un User Data Stream et retourne le listenKey.
    Retourne None en cas d'échec.
    """
    client = get_client()
    if not client:
        logger.error("Client Binance non initialisé pour start_user_data_stream.")
        return None
    try:
        response = client.stream_get_listen_key()
        listen_key = response.get('listenKey')
        if listen_key:
            logger.info(f"ListenKey User Data Stream obtenu: {listen_key[:5]}...")
            return listen_key
        else:
            logger.error(f"Échec obtention ListenKey User Data Stream. Réponse: {response}")
            return None
    except (BinanceAPIException, BinanceRequestException) as e:
        logger.error(f"Erreur API Binance lors de l'obtention du ListenKey: {e}")
        return None
    except Exception as e:
        logger.exception("Erreur inattendue lors de l'obtention du ListenKey.")
        return None

def keepalive_user_data_stream(listen_key: str) -> bool:
    """
    Envoie une requête keepalive pour un listenKey donné.
    Retourne True si succès, False sinon.
    """
    client = get_client()
    if not client:
        logger.error("Client Binance non initialisé pour keepalive_user_data_stream.")
        return False
    if not listen_key:
        logger.error("Tentative de keepalive avec un listenKey vide.")
        return False
    try:
        client.stream_keepalive(listenKey=listen_key)
        logger.info(f"Keepalive envoyé pour ListenKey: {listen_key[:5]}...")
        return True
    except (BinanceAPIException, BinanceRequestException) as e:
        # Une erreur ici peut signifier que la clé a expiré
        logger.error(f"Erreur API Binance lors du keepalive pour ListenKey {listen_key[:5]}...: {e}")
        return False
    except Exception as e:
        logger.exception(f"Erreur inattendue lors du keepalive pour ListenKey {listen_key[:5]}...")
        return False

def close_user_data_stream(listen_key: str) -> bool:
    """
    Ferme un User Data Stream associé à un listenKey.
    Retourne True si succès, False sinon.
    """
    client = get_client()
    if not client:
        logger.error("Client Binance non initialisé pour close_user_data_stream.")
        return False
    if not listen_key:
        logger.warning("Tentative de fermeture avec un listenKey vide.")
        return True # Considérer comme succès si pas de clé à fermer
    try:
        client.stream_close(listenKey=listen_key)
        logger.info(f"Requête de fermeture envoyée pour ListenKey: {listen_key[:5]}...")
        return True
    except (BinanceAPIException, BinanceRequestException) as e:
        logger.error(f"Erreur API Binance lors de la fermeture du ListenKey {listen_key[:5]}...: {e}")
        return False
    except Exception as e:
        logger.exception(f"Erreur inattendue lors de la fermeture du ListenKey {listen_key[:5]}...")
        return False

# --- Bloc d'Exemple/Test (inchangé) ---
if __name__ == '__main__':
    # ... (code de test inchangé) ...
    pass
