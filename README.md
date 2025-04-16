# Trading Bot

## Description

This is a trading bot that uses the Binance API to trade cryptocurrencies. The bot uses the EMA Crossover RSI strategy to generate trading signals. The bot is controlled via a web interface.

## Installation

1. Clone the repository:

```bash
git clone https://github.com/your-username/trading-bot.git
cd trading-bot
```

2. Install the dependencies:

```bash
pip install -r backend/requirements.txt
```

3. Configure the bot:

- Copy `.env.example` to `.env` in the `backend` directory and fill in your Binance API keys.
- Modify `backend/config.py` to configure the bot's parameters.

## Usage

1. Start the backend:

```bash
cd backend
python bot.py
```

2. Open the frontend in your browser:

```
open frontend/index.html
```

3. Use the web interface to control the bot.

## Configuration

The following parameters can be configured in `backend/config.py`:

- `SYMBOL`: The trading symbol (e.g. BTCUSDT).
- `TIMEFRAME`: The trading timeframe (e.g. 5m).
- `RISK_PER_TRADE`: The percentage of capital to risk per trade.
- `CAPITAL_ALLOCATION`: The percentage of capital to allocate to the bot.
- `EMA_SHORT_PERIOD`: The period for the short EMA.
- `EMA_LONG_PERIOD`: The period for the long EMA.
- `EMA_FILTER_PERIOD`: The period for the EMA filter.
- `RSI_PERIOD`: The period for the RSI.
- `RSI_OVERBOUGHT`: The overbought level for the RSI.
- `RSI_OVERSOLD`: The oversold level for the RSI.
- `USE_TESTNET`: Whether to use the Binance testnet.

The following parameters can be configured in the web interface:

- `Strategy`: The trading strategy.
- `Leverage`: The leverage to use.
- `Amount`: The amount to trade.
- `Portfolio Percentage`: The percentage of the portfolio to allocate to the bot.

## Dependencies

The following dependencies are required:

- Flask
- Flask-CORS
- python-binance
- pandas
- pandas_ta
