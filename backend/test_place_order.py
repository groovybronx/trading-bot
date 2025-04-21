# /Users/davidmichels/Desktop/trading-bot/backend/test_place_order.py
import requests
import json
import logging
import os
from dotenv import load_dotenv

# Load environment variables (e.g., for API URL if it were configurable)
load_dotenv()

# Configure logging for the test script
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- Configuration ---
# URL of your running Flask backend
BASE_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:5000") # Use env var or default
PLACE_ORDER_URL = f"{BASE_URL}/api/place_order"
REQUEST_TIMEOUT = 20 # Seconds to wait for a response from the backend

# --- Order Parameters to Test ---
# Choose ONE of the examples below by uncommenting it.

# Example 1: Market BUY - Spend 10 USDT to buy BTC
# (Ensure 10 USDT is >= minNotional for BTCUSDT on the exchange)
order_data = {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "order_type": "MARKET",
    "quantity": "10",  # For MARKET BUY by quote quantity
}

# # Example 2: Market SELL - Sell 0.00011 BTC
# # (Ensure 0.00011 BTC meets minQty and stepSize rules for BTCUSDT)
# order_data = {
#     "symbol": "BTCUSDT",
#     "side": "SELL",
#     "order_type": "MARKET",
#     "quantity": "0.00011" # For MARKET SELL by base quantity
# }

# # Example 3: Limit BUY - Buy 0.00011 BTC if price drops to 80000 USDT
# # (Ensure 0.00011 BTC * 80000 USDT >= minNotional)
# order_data = {
#     "symbol": "BTCUSDT",
#     "side": "BUY",
#     "order_type": "LIMIT",
#     "quantity": "0.00011", # Base quantity for LIMIT orders
#     "price": "80000.00",   # Limit price (ensure correct precision)
#     "time_in_force": "GTC" # Good 'Til Canceled
# }

# # Example 4: Limit SELL - Sell 0.00011 BTC if price rises to 95000 USDT
# order_data = {
#     "symbol": "BTCUSDT",
#     "side": "SELL",
#     "order_type": "LIMIT",
#     "quantity": "0.00011", # Base quantity for LIMIT orders
#     "price": "95000.00",   # Limit price
#     "time_in_force": "GTC"
# }

# --- Execute Request ---
logging.info(f"Sending order placement request to {PLACE_ORDER_URL}")
logging.info(f"Order Data: {json.dumps(order_data, indent=2)}")

try:
    # Send POST request with JSON data and timeout
    response = requests.post(
        PLACE_ORDER_URL, json=order_data, timeout=REQUEST_TIMEOUT
    )

    # Check for HTTP errors (4xx or 5xx)
    response.raise_for_status()

    logging.info(f"Response received from backend (Status Code: {response.status_code})")

    # Attempt to parse and log the JSON response from the backend API
    try:
        response_json = response.json()
        logging.info(
            f"Response JSON Content:\n{json.dumps(response_json, indent=2)}"
        )
        # This JSON should contain {"success": True/False, "message": ..., "order_details": ...}
        # as defined in your api_routes.py
    except json.JSONDecodeError:
        logging.error(
            f"Failed to decode JSON response. Raw Response Text:\n{response.text}"
        )

# --- Error Handling ---
except requests.exceptions.ConnectionError as e:
    logging.error(
        f"Connection Error: Could not connect to {PLACE_ORDER_URL}. Is the backend running? Details: {e}"
    )
except requests.exceptions.Timeout as e:
    logging.error(
        f"Timeout Error: Request to {PLACE_ORDER_URL} timed out after {REQUEST_TIMEOUT} seconds. Details: {e}"
    )
except requests.exceptions.HTTPError as e:
    # Handle errors reported by the Flask server (e.g., 400, 500)
    logging.error(f"HTTP Error: {e.response.status_code} {e.response.reason}")
    try:
        # Try to get more details from the error response body
        error_details = e.response.json()
        logging.error(
            f"Error Details (JSON):\n{json.dumps(error_details, indent=2)}"
        )
    except json.JSONDecodeError:
        logging.error(f"Error Details (Raw Text):\n{e.response.text}")
except requests.exceptions.RequestException as e:
    # Catch other general requests errors
    logging.error(f"Request failed for {PLACE_ORDER_URL}. Details: {e}")
except Exception as e:
    # Catch any other unexpected errors in the script
    logging.error(f"An unexpected error occurred: {e}", exc_info=True)

logging.info("--- Test script finished ---")
