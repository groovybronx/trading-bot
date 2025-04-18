# /Users/davidmichels/Desktop/trading-bot/backend/config_manager.py
import logging
from binance.client import Client as BinanceClient
import config # Importer le fichier config.py

logger = logging.getLogger()

# --- Constantes et Configuration Globale ---
SYMBOL = getattr(config, 'SYMBOL', 'BTCUSDT')
VALID_TIMEFRAMES = ['1s', '1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']
TIMEFRAME_CONSTANT_MAP = {
    '1s': BinanceClient.KLINE_INTERVAL_1SECOND, '1m': BinanceClient.KLINE_INTERVAL_1MINUTE,
    '3m': BinanceClient.KLINE_INTERVAL_3MINUTE, '5m': BinanceClient.KLINE_INTERVAL_5MINUTE,
    '15m': BinanceClient.KLINE_INTERVAL_15MINUTE, '30m': BinanceClient.KLINE_INTERVAL_30MINUTE,
    '1h': BinanceClient.KLINE_INTERVAL_1HOUR, '2h': BinanceClient.KLINE_INTERVAL_2HOUR,
    '4h': BinanceClient.KLINE_INTERVAL_4HOUR, '6h': BinanceClient.KLINE_INTERVAL_6HOUR,
    '8h': BinanceClient.KLINE_INTERVAL_8HOUR, '12h': BinanceClient.KLINE_INTERVAL_12HOUR,
    '1d': BinanceClient.KLINE_INTERVAL_1DAY, '3d': BinanceClient.KLINE_INTERVAL_3DAY,
    '1w': BinanceClient.KLINE_INTERVAL_1WEEK, '1M': BinanceClient.KLINE_INTERVAL_1MONTH,
}

# Configuration modifiable du bot (initialisée depuis config.py)
bot_config = {
    "TIMEFRAME_STR": getattr(config, 'TIMEFRAME', '1m'),
    "RISK_PER_TRADE": getattr(config, 'RISK_PER_TRADE', 0.01),
    "CAPITAL_ALLOCATION": getattr(config, 'CAPITAL_ALLOCATION', 1.0),
    "STOP_LOSS_PERCENTAGE": getattr(config, 'STOP_LOSS_PERCENTAGE', 0.02),
    "TAKE_PROFIT_PERCENTAGE": getattr(config, 'TAKE_PROFIT_PERCENTAGE', 0.05),
    "EMA_SHORT_PERIOD": getattr(config, 'EMA_SHORT_PERIOD', 9),
    "EMA_LONG_PERIOD": getattr(config, 'EMA_LONG_PERIOD', 21),
    "EMA_FILTER_PERIOD": getattr(config, 'EMA_FILTER_PERIOD', 50),
    "RSI_PERIOD": getattr(config, 'RSI_PERIOD', 14),
    "RSI_OVERBOUGHT": getattr(config, 'RSI_OVERBOUGHT', 75),
    "RSI_OVERSOLD": getattr(config, 'RSI_OVERSOLD', 25),
    "VOLUME_AVG_PERIOD": getattr(config, 'VOLUME_AVG_PERIOD', 20),
    "USE_EMA_FILTER": getattr(config, 'USE_EMA_FILTER', True),
    "USE_VOLUME_CONFIRMATION": getattr(config, 'USE_VOLUME_CONFIRMATION', False),
}

# Vérifier si le timeframe initial est valide
if bot_config["TIMEFRAME_STR"] not in VALID_TIMEFRAMES:
    logger.error(f"Timeframe initial '{bot_config['TIMEFRAME_STR']}' dans config.py est invalide. Utilisation de '1m'.")
    bot_config["TIMEFRAME_STR"] = '1m'

# Exporter les variables nécessaires
__all__ = [
    'SYMBOL', 'VALID_TIMEFRAMES', 'TIMEFRAME_CONSTANT_MAP', 'bot_config',
    'config' # Exporter aussi le module config original si besoin d'accéder à BINANCE_API_KEY etc. ailleurs
]
