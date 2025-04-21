# test_aiohttp_listen_key.py
import asyncio
import aiohttp
import logging

# Try importing your config or define keys here
try:
    import config

    API_KEY = config.BINANCE_API_KEY
    API_SECRET = config.BINANCE_API_SECRET  # Not needed for this endpoint
    USE_TESTNET = config.USE_TESTNET
except ImportError:
    print("config.py not found. Define keys manually.")
    API_KEY = "YOUR_TESTNET_API_KEY"  # Make sure this is correct
    # API_SECRET = "YOUR_TESTNET_SECRET_KEY"
    USE_TESTNET = True  # Set manually

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger()

if USE_TESTNET:
    base_url = "https://testnet.binance.vision"
    logger.info("Using Testnet URL")
else:
    base_url = "https://api.binance.com"
    logger.info("Using Production URL")

path = "/api/v3/userDataStream"
url = base_url + path
headers = {"X-MBX-APIKEY": API_KEY}


async def main():
    # Recommended: Create a single session
    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            logger.info(f"Attempting POST to {url} using aiohttp...")
            # Make the POST request
            timeout = aiohttp.ClientTimeout(total=10)
            async with session.post(url, timeout=timeout) as response:
                logger.info(f"Response Status Code: {response.status}")
                response_text = await response.text()  # Read text first for debugging

                if response.status >= 400:
                    logger.error(f"Request failed with status {response.status}")
                    logger.error(f"Response text: {response_text}")
                    response.raise_for_status()  # Raise exception for bad status

                data = await response.json(
                    content_type=None
                )  # Use content_type=None if Binance doesn't send correct type
                logger.info(f"Success! Listen Key: {data.get('listenKey')}")

        except asyncio.TimeoutError:
            logger.error("Request timed out.")
        except aiohttp.ClientConnectorError as e:
            logger.exception(f"Connection Error occurred: {e}")
        except aiohttp.ClientOSError as e:
            # This is the error we saw before
            logger.exception(f"Client OS Error (likely SSL related) occurred: {e}")
        except aiohttp.ClientError as e:
            # Catch other aiohttp specific errors
            logger.exception(f"aiohttp ClientError occurred: {e}")
        except Exception as e:
            logger.exception(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    # On Windows, you might need this policy if running Python 3.8+
    # asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
