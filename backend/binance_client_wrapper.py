# /Users/davidmichels/Desktop/trading-bot/backend/binance_client_wrapper.py

import logging
import threading
import time
import os
import dotenv
# Ensure List, Dict, Any, Optional, Union are imported from typing
from typing import Optional, List, Dict, Union, Any

from binance.spot import Spot as SpotClient
from binance.error import ClientError, ServerError

# Import config manager to get settings like USE_TESTNET
from config_manager import config_manager

dotenv.load_dotenv()
logger = logging.getLogger(__name__)

# --- Module Globals ---
_client: Optional[SpotClient] = None
_client_lock = threading.Lock() # Lock for thread-safe client initialization

# --- Client Initialization ---

def get_client() -> Optional[SpotClient]:
    """
    Initializes and returns the Binance Spot client (singleton pattern).
    Uses configuration from ConfigManager (API keys from .env, testnet from config).
    Returns None if initialization fails.
    """
    global _client
    # Fast check without lock
    if _client is not None:
        return _client

    # Acquire lock only if client is not initialized
    with _client_lock:
        # Double check inside lock
        if _client is None:
            try:
                # Read keys directly from environment variables
                api_key = os.getenv('ENV_API_KEY')
                api_secret = os.getenv('ENV_API_SECRET')
                # Read testnet setting from config manager
                use_testnet = config_manager.get_value("USE_TESTNET", True) # Default to True if not set

                # Validate API keys
                if not api_key or not api_secret or api_key == "YOUR_API_KEY_PLACEHOLDER" or api_secret == "YOUR_SECRET_KEY_PLACEHOLDER":
                    logger.critical("Binance API keys not configured or are placeholders in .env file.")
                    return None # Cannot proceed without valid keys

                # Determine base URL
                base_url = "https://testnet.binance.vision" if use_testnet else "https://api.binance.com"
                logger.info(f"Initializing Binance Spot client (Base URL: {base_url})...")

                # Create client instance
                client_instance = SpotClient(api_key=api_key, api_secret=api_secret, base_url=base_url)

                # Test connection
                client_instance.ping()
                logger.info("Connection to Binance Spot API successful (ping OK).")
                _client = client_instance # Assign to global variable

            except ClientError as e:
                logger.critical(f"Binance Client Error during initialization: Status={e.status_code}, Code={e.error_code}, Msg={e.error_message}", exc_info=False)
                _client = None # Ensure client remains None on error
            except ServerError as e:
                 logger.critical(f"Binance Server Error during initialization: Status={e.status_code}, Msg={str(e)}", exc_info=False)
                 _client = None
            except Exception as e:
                # Catch any other unexpected exceptions
                logger.critical(f"Unexpected error during Binance Spot client initialization: {e}", exc_info=True)
                _client = None
        # Return the initialized client (or None if failed)
        return _client

# --- API Call Wrappers ---

def get_klines(
    symbol: str,
    interval: str, # Expects '1m', '1h', etc.
    limit: int = 100,
    retries: int = 3,
    delay: int = 5 # Seconds between retries
) -> Optional[List[List[Any]]]:
    """
    Retrieves kline/candlestick data for a symbol and interval.
    Handles API errors and retries.
    """
    client = get_client()
    if not client: return None

    logger.debug(f"Attempting to retrieve {limit} klines for {symbol} ({interval})...")
    for attempt in range(retries):
        try:
            # Make the API call
            klines = client.klines(symbol=symbol.upper(), interval=interval, limit=limit)

            # Validate response structure
            if isinstance(klines, list):
                if not klines: # Empty list received
                     logger.warning(f"get_klines({symbol}, {interval}): Received empty list (Attempt {attempt + 1}/{retries}).")
                     if attempt < retries - 1: time.sleep(delay); continue
                     else: logger.error(f"get_klines({symbol}, {interval}): Failed after {retries} attempts (empty data)."); return None
                # Check if all items in the list are also lists (expected kline format)
                if all(isinstance(item, list) for item in klines):
                    logger.info(f"get_klines({symbol}, {interval}): Successfully retrieved {len(klines)} klines.")
                    return klines
                else:
                    logger.error(f"get_klines({symbol}, {interval}): Unexpected format in response list items."); return None
            else:
                # Response was not a list
                logger.error(f"get_klines({symbol}, {interval}): Unexpected response type: {type(klines)}."); return None

        except ClientError as e:
            logger.error(f"get_klines({symbol}, {interval}): Client Error (Attempt {attempt + 1}/{retries}). Status={e.status_code}, Code={e.error_code}, Msg={e.error_message}")
            if attempt < retries - 1: time.sleep(delay)
            else: logger.error(f"get_klines({symbol}, {interval}): Final attempt failed."); return None
        except ServerError as e:
             logger.error(f"get_klines({symbol}, {interval}): Server Error (Attempt {attempt + 1}/{retries}). Status={e.status_code}, Msg={str(e)}")
             if attempt < retries - 1: time.sleep(delay)
             else: logger.error(f"get_klines({symbol}, {interval}): Final attempt failed."); return None
        except Exception as e:
            logger.exception(f"get_klines({symbol}, {interval}): Unexpected error (Attempt {attempt + 1}/{retries}).")
            if attempt < retries - 1: time.sleep(delay)
            else: logger.error(f"get_klines({symbol}, {interval}): Final attempt failed."); return None
    return None # Should not be reached if retries > 0, but acts as fallback


def get_account_balance(asset: str) -> Optional[float]:
    """
    Retrieves the available ('free') balance for a specific asset.
    Returns None on API error, 0.0 if asset not found in balances.
    """
    client = get_client()
    if not client: return None

    try:
        logger.debug(f"Retrieving balance for {asset}...")
        # Increase recvWindow if needed, default might be too short sometimes
        account_info = client.account(recvWindow=10000)
        balances = account_info.get('balances', [])

        # Find the specific asset in the balances list
        balance_info = next((item for item in balances if item.get("asset") == asset.upper()), None)

        if balance_info and 'free' in balance_info:
            try:
                # Convert the 'free' balance string to float
                available_balance = float(balance_info['free'])
                logger.info(f"Available {asset} balance: {available_balance}")
                return available_balance
            except (ValueError, TypeError):
                 logger.error(f"get_account_balance({asset}): Could not convert balance '{balance_info['free']}' to float.")
                 return None # Indicate conversion error
        else:
            # Asset not found in the account balances
            logger.warning(f"get_account_balance({asset}): Asset not found in account balances. Returning 0.0")
            return 0.0
    except ClientError as e:
        logger.error(f"get_account_balance({asset}): Client Error. Status={e.status_code}, Code={e.error_code}, Msg={e.error_message}")
        return None
    except ServerError as e:
         logger.error(f"get_account_balance({asset}): Server Error. Status={e.status_code}, Msg={str(e)}")
         return None
    except Exception as e:
        logger.exception(f"get_account_balance({asset}): Unexpected error.")
        return None


def get_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves exchange information (filters, precision) for a specific symbol.
    Returns None if error or symbol not found.
    """
    client = get_client()
    if not client: return None

    try:
        logger.debug(f"Retrieving exchange info for {symbol}...")
        # Request info only for the specific symbol
        all_info = client.exchange_info(symbol=symbol.upper())

        # Validate response structure
        if all_info and 'symbols' in all_info and len(all_info['symbols']) == 1:
            info = all_info['symbols'][0]
            logger.debug(f"Exchange info for {symbol} retrieved successfully.")
            return info
        else:
            logger.error(f"get_symbol_info({symbol}): Symbol info not found or invalid format in response: {all_info}")
            return None
    except ClientError as e:
        logger.error(f"get_symbol_info({symbol}): Client Error. Status={e.status_code}, Code={e.error_code}, Msg={e.error_message}")
        return None
    except ServerError as e:
         logger.error(f"get_symbol_info({symbol}): Server Error. Status={e.status_code}, Msg={str(e)}")
         return None
    except Exception as e:
        logger.exception(f"get_symbol_info({symbol}): Unexpected error.")
        return None


def get_symbol_ticker(symbol: str) -> Optional[Dict[str, str]]:
    """
    Retrieves the latest price ticker for a specific symbol.
    Returns None on error.
    """
    client = get_client()
    if not client: return None

    try:
        logger.debug(f"Retrieving ticker for {symbol}...")
        ticker = client.ticker_price(symbol=symbol.upper())

        # Validate response
        if ticker and 'price' in ticker:
            logger.debug(f"Ticker for {symbol}: Price={ticker['price']}")
            return ticker
        else:
            logger.error(f"get_symbol_ticker({symbol}): Invalid response format: {ticker}")
            return None
    except ClientError as e:
        logger.error(f"get_symbol_ticker({symbol}): Client Error. Status={e.status_code}, Code={e.error_code}, Msg={e.error_message}")
        return None
    except ServerError as e:
         logger.error(f"get_symbol_ticker({symbol}): Server Error. Status={e.status_code}, Msg={str(e)}")
         return None
    except Exception as e:
        logger.exception(f"get_symbol_ticker({symbol}): Unexpected error.")
        return None


def place_order(
    symbol: str, side: str, quantity: Union[float, str], order_type: str = 'MARKET',
    price: Optional[Union[float, str]] = None, time_in_force: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Places an order on Binance. Handles MARKET vs LIMIT logic for quantity/price.
    Returns the order details dict from Binance API, or None on failure.
    """
    client = get_client()
    if not client: return None

    try:
        # Prepare base parameters
        params = {'symbol': symbol.upper(), 'side': side.upper(), 'type': order_type.upper()}
        log_price_info = ""
        log_qty_info = "" # Initialize qty info

        # Handle quantity parameter based on order type/side
        if params['type'] == 'MARKET' and params['side'] == 'BUY':
            # For MARKET BUY, quantity is the amount of QUOTE asset to spend
            params['quoteOrderQty'] = str(quantity)
            log_qty_info = f"{quantity} QUOTE" # Simplified log
        else:
            # For LIMIT orders (BUY/SELL) and MARKET SELL, quantity is the amount of BASE asset
            params['quantity'] = str(quantity)
            log_qty_info = f"{quantity} BASE" # Simplified log


        # Handle price and timeInForce for LIMIT orders
        if params['type'] == 'LIMIT':
            if price is None or float(price) <= 0:
                raise ValueError(f"Invalid or missing price for LIMIT order: {price}")
            params['price'] = str(price)
            params['timeInForce'] = (time_in_force or 'GTC').upper() # Default to GTC if not provided
            log_price_info = f" @ {params['price']} ({params['timeInForce']})"
        elif params['type'] == 'MARKET':
             log_price_info = " @ market"
        # Add other order types (STOP_LOSS_LIMIT etc.) here if needed
        else:
            # Raise error for unsupported types passed to this function
            raise ValueError(f"Unsupported order_type for place_order: {order_type}")

        # Log the attempt
        logger.info(f"Placing Order: {params['side']} {params['type']} {log_qty_info} {symbol}{log_price_info}...")

        # Make the API call
        order_response = client.new_order(**params)

        # Log the result
        order_id = order_response.get('orderId', 'N/A')
        status = order_response.get('status', 'N/A')
        log_level = logging.INFO # Default log level for success/pending
        if status in ['REJECTED', 'EXPIRED']:
            log_level = logging.WARNING
        elif status not in ['NEW', 'FILLED', 'PARTIALLY_FILLED']:
             log_level = logging.ERROR # Unexpected status

        logger.log(log_level, f"Order Placement Result {order_id}: Status={status}, Type={order_response.get('type')}, Side={order_response.get('side')}, Qty={order_response.get('origQty')}, ExecQty={order_response.get('executedQty', 'N/A')}")

        return order_response # Return the full response dictionary

    except (ClientError, ValueError) as e:
        # Handle API client errors and validation errors (like invalid price)
        error_code = getattr(e, 'error_code', None) if isinstance(e, ClientError) else None
        error_msg = getattr(e, 'error_message', str(e)) if isinstance(e, ClientError) else str(e)
        logger.error(f"place_order({symbol}, {side}, {order_type}): Client/Validation Error. Status={getattr(e, 'status_code', 'N/A')}, Code={error_code}, Msg={error_msg}")
        # Provide hints for common errors
        if error_code == -1013: logger.error(" -> Hint: Check order filters (minNotional, lotSize, priceFilter) or quantity/price precision.")
        if error_code == -2010: logger.error(" -> Hint: Insufficient balance.")
        return None # Indicate failure
    except ServerError as e:
         logger.error(f"place_order({symbol}, {side}, {order_type}): Server Error. Status={e.status_code}, Msg={str(e)}")
         return None
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception(f"place_order({symbol}, {side}, {order_type}): Unexpected error.")
        return None


def cancel_order(symbol: str, orderId: int) -> Optional[Dict[str, Any]]:
    """
    Cancels an open order.
    Returns order details on success, special status if already done/unknown, None on API error.
    """
    client = get_client()
    if not client: return None

    try:
        logger.info(f"Attempting to cancel order {orderId} for {symbol}...")
        result = client.cancel_order(symbol=symbol.upper(), orderId=orderId)
        status = result.get('status')
        logger.info(f"Cancel Order Result {orderId}: Status={status}")
        return result
    except ClientError as e:
        # Handle specific error code for "Unknown order sent."
        if e.error_code == -2011:
            logger.warning(f"cancel_order({symbol}, {orderId}): Failed (Code: {e.error_code}). Order unknown or already filled/cancelled.")
            # Return a synthetic response indicating the order is no longer open
            return {"symbol": symbol, "orderId": orderId, "status": "UNKNOWN_OR_ALREADY_COMPLETED"}
        else:
            # Log other client errors
            logger.error(f"cancel_order({symbol}, {orderId}): Client Error. Status={e.status_code}, Code={e.error_code}, Msg={e.error_message}")
            return None
    except ServerError as e:
         logger.error(f"cancel_order({symbol}, {orderId}): Server Error. Status={e.status_code}, Msg={str(e)}")
         return None
    except Exception as e:
        logger.exception(f"cancel_order({symbol}, {orderId}): Unexpected error.")
        return None

# --- ADDED: Function to get all orders via REST ---
def get_all_orders(symbol: str, limit: int = 50, retries: int = 3, delay: int = 2) -> Optional[List[Dict[str, Any]]]:
    """
    Retrieves recent order history for a symbol via REST API (GET /api/v3/allOrders).
    Uses the client's all_orders method.
    """
    client = get_client()
    if not client: return None

    logger.debug(f"Attempting to retrieve last {limit} orders for {symbol} via REST...")
    # Parameters for the API call
    params = {"symbol": symbol.upper(), "limit": limit}

    for attempt in range(retries):
        try:
            # Use the correct method name from binance-connector's Spot client
            orders = client.get_orders(**params)
            # Validate the response
            if isinstance(orders, list):
                logger.info(f"get_all_orders({symbol}): Successfully retrieved {len(orders)} orders via REST.")
                return orders
            else:
                # Should not happen with a valid client call, but handle defensively
                logger.error(f"get_all_orders({symbol}): Unexpected response type from client.all_orders: {type(orders)}.")
                return None # Fail if response is not a list
        except ClientError as e:
            logger.error(f"get_all_orders({symbol}): Client Error (Attempt {attempt + 1}/{retries}). Status={e.status_code}, Code={e.error_code}, Msg={e.error_message}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                logger.error(f"get_all_orders({symbol}): Final attempt failed after {retries} retries.")
                return None
        except ServerError as e:
             logger.error(f"get_all_orders({symbol}): Server Error (Attempt {attempt + 1}/{retries}). Status={e.status_code}, Msg={str(e)}")
             if attempt < retries - 1:
                 time.sleep(delay)
             else:
                 logger.error(f"get_all_orders({symbol}): Final attempt failed after {retries} retries.")
                 return None
        except Exception as e:
            # Catch any other unexpected errors during the API call
            logger.exception(f"get_all_orders({symbol}): Unexpected error (Attempt {attempt + 1}/{retries}).")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                logger.error(f"get_all_orders({symbol}): Final attempt failed after {retries} retries.")
                return None
    return None # Fallback if all retries fail
# --- END ADDED ---


# --- User Data Stream Listen Key Management ---

def create_listen_key() -> Optional[str]:
    """Creates a new listenKey for the User Data Stream via REST API."""
    client = get_client()
    if not client: return None

    try:
        logger.info("Creating new ListenKey via REST API...")
        response = client.new_listen_key() # Use the correct method from binance-connector
        key = response.get('listenKey')
        if key:
            logger.info(f"New ListenKey created successfully: {key[:5]}...")
            return key
        else:
            logger.error(f"Failed to create ListenKey, invalid API response: {response}")
            return None
    except (ClientError, ServerError) as e:
        logger.error(f"API error creating ListenKey: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.exception("Unexpected error creating ListenKey.")
        return None


def renew_listen_key(listen_key: str) -> bool:
    """Renews (keepalive) an existing ListenKey via REST API."""
    client = get_client()
    if not client or not listen_key:
        logger.error("Cannot renew listen key: client not available or key missing.")
        return False

    try:
        logger.debug(f"Renewing ListenKey {listen_key[:5]}... via REST API...")
        client.renew_listen_key(listenKey=listen_key) # Use the correct method
        logger.info(f"ListenKey {listen_key[:5]}... renewed successfully.")
        return True
    except ClientError as e:
        # Handle invalid/expired key error specifically
        if e.error_code == -1125:
             logger.warning(f"Failed to renew ListenKey {listen_key[:5]} (Code {e.error_code}): Key likely expired or invalid.")
             return False # Indicate failure so caller can handle (e.g., get new key)
        else:
             logger.error(f"API Client Error renewing ListenKey {listen_key[:5]}: {e}")
             return False
    except ServerError as e:
        logger.error(f"API Server Error renewing ListenKey {listen_key[:5]}: {str(e)}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error renewing ListenKey {listen_key[:5]}.")
        return False


def close_listen_key(listen_key: str) -> bool:
    """Closes an existing ListenKey via REST API."""
    client = get_client()
    # Don't fail if client/key missing, just log and return True (nothing to close)
    if not client or not listen_key:
        logger.debug("No client or listen key provided for closing.")
        return True

    try:
        logger.info(f"Closing ListenKey {listen_key[:5]}... via REST API...")
        client.close_listen_key(listenKey=listen_key) # Use the correct method
        logger.info(f"ListenKey {listen_key[:5]}... closed successfully.")
        return True
    except ClientError as e:
         # If key is already invalid/expired, consider it successfully closed
        if e.error_code == -1125:
             logger.warning(f"Attempted to close ListenKey {listen_key[:5]} but it was already invalid/expired (Code {e.error_code}).")
             return True # Effectively closed
        else:
             logger.error(f"API Client Error closing ListenKey {listen_key[:5]}: {e}")
             return False # Indicate potential issue
    except ServerError as e:
        logger.error(f"API Server Error closing ListenKey {listen_key[:5]}: {str(e)}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error closing ListenKey {listen_key[:5]}.")
        return False


# --- Example Usage / Test Block ---
if __name__ == '__main__':
    # Setup basic logging for the test
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')
    logger.info("--- Testing Binance Client Wrapper ---")

    test_client = get_client()
    if test_client:
        logger.info("Test 1: Client Initialization -> OK")

        # Test getting symbol info
        symbol = config_manager.get_value("SYMBOL", "BTCUSDT")
        logger.info(f"\nTest 2: Get Symbol Info ({symbol})")
        info = get_symbol_info(symbol)
        if info:
            logger.info(f"-> OK: Base={info.get('baseAsset')}, Quote={info.get('quoteAsset')}")
        else:
            logger.error("-> FAILED")

        # Test getting balance
        quote_asset = info.get('quoteAsset', 'USDT') if info else 'USDT'
        logger.info(f"\nTest 3: Get Account Balance ({quote_asset})")
        balance = get_account_balance(quote_asset)
        if balance is not None:
            logger.info(f"-> OK: Balance = {balance}")
        else:
            logger.error("-> FAILED")

        # Test getting klines
        tf = config_manager.get_value("TIMEFRAME_STR", "1m")
        logger.info(f"\nTest 4: Get Klines ({symbol}, {tf}, limit=5)")
        klines = get_klines(symbol, tf, limit=5)
        if klines:
            logger.info(f"-> OK: Retrieved {len(klines)} klines.")
        else:
            logger.error("-> FAILED")

        # Test Listen Key cycle
        logger.info("\nTest 5: Listen Key Cycle (Create, Renew, Close)")
        lk = create_listen_key()
        if lk:
            logger.info(f"-> Create OK: {lk[:5]}...")
            logger.info("   Waiting 5s...")
            time.sleep(5)
            logger.info("   Testing Renew...")
            renew_ok = renew_listen_key(lk)
            logger.info(f"-> Renew {'OK' if renew_ok else 'FAILED'}")
            logger.info("   Testing Close...")
            close_ok = close_listen_key(lk)
            logger.info(f"-> Close {'OK' if close_ok else 'FAILED'}")
        else:
            logger.error("-> Create FAILED.")

        # Add test for get_all_orders
        logger.info(f"\nTest 6: Get All Orders ({symbol}, limit=5)")
        recent_orders = get_all_orders(symbol, limit=5)
        if recent_orders is not None:
            logger.info(f"-> OK: Retrieved {len(recent_orders)} orders.")
            # Optionally print some details
            for order in recent_orders[:2]:
                 logger.info(f"  - ID: {order.get('orderId')}, Status: {order.get('status')}, Time: {order.get('updateTime')}")
        else:
            logger.error("-> FAILED")

    else:
        logger.error("Test 1: Client Initialization -> FAILED")

    logger.info("\n--- Wrapper Tests Finished ---")
