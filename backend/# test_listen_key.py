# test_listen_key.py
import requests
import time
import logging

# Try importing your config or define keys here
try:
    import config

    API_KEY = config.BINANCE_API_KEY
    API_SECRET = config.BINANCE_API_SECRET
    USE_TESTNET = config.USE_TESTNET
except ImportError:
    print("config.py not found. Define keys manually.")
    API_KEY = "YOUR_TESTNET_API_KEY"
    API_SECRET = "YOUR_TESTNET_SECRET_KEY"
    USE_TESTNET = True  # Set manually

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger()

if USE_TESTNET:
    base_url = "https://testnet.binance.vision"
    logger.info("Using Testnet URL")
else:
    base_url = "https://api.binance.com"  # Adjust if needed (e.g., .us)
    logger.info("Using Production URL")

path = "/api/v3/userDataStream"
url = base_url + path
headers = {"X-MBX-APIKEY": API_KEY}

try:
    logger.info(f"Attempting POST to {url}")
    response = requests.post(url, headers=headers, timeout=10)  # Add timeout
    logger.info(f"Response Status Code: {response.status_code}")
    response.raise_for_status()  # Raise exception for bad status codes (4xx or 5xx)
    data = response.json()
    logger.info(f"Success! Listen Key: {data.get('listenKey')}")
except requests.exceptions.Timeout:
    logger.error("Request timed out.")
except requests.exceptions.SSLError as e:
    logger.exception(f"SSL Error occurred: {e}")
except requests.exceptions.RequestException as e:
    logger.error(f"Request failed: {e}")
    if e.response is not None:
        logger.error(f"Response status: {e.response.status_code}")
        logger.error(f"Response text: {e.response.text}")
except Exception as e:
    logger.exception(f"An unexpected error occurred: {e}")
