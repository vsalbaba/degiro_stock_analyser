<!-- Vibe-coded with ✨ Claude -->

# DeGiro Position Analyzer

A Python tool to analyze DeGiro transactions and track current positions using FIFO (First In First Out) logic with support for live stock price fetching.

## Features

- **FIFO Position Tracking**: Accurately tracks current stock positions using First In First Out logic
- **Sold Position Tracking**: Optional tracking of historical sold positions
- **Tax-Free Position Analysis**: Identifies positions held > 3 years (eligible for tax-free sale)
- **Live Price Fetching**: Fetch current stock prices with automatic EUR conversion
- **Smart Caching**: 24-hour price cache for fast repeated queries
- **CSV Export**: Export positions with or without price data

## Installation

Install required dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

```bash
# Display current positions
python analyze_positions.py

# Display current positions with live prices
python analyze_positions.py --with-prices

# Display current and sold positions
python analyze_positions.py --with-sold

# Show only tax-free positions (held > 3 years)
python analyze_positions.py --can-be-sold

# Show tax-free positions with current values
python analyze_positions.py --can-be-sold --with-prices
```

### Price Fetching

```bash
# Fetch current prices (uses cache if < 24h old)
python analyze_positions.py --with-prices

# Force fresh price fetch (ignore cache)
python analyze_positions.py --with-prices --no-cache

# Use custom cache location
python analyze_positions.py --with-prices --cache-location /path/to/cache.json
```

### CSV Export

```bash
# Export current positions
python analyze_positions.py --export positions.csv

# Export with current prices
python analyze_positions.py --with-prices --export positions_with_prices.csv

# Export current and sold positions
python analyze_positions.py --with-sold --export all_positions.csv

# Export tax-free positions
python analyze_positions.py --can-be-sold --export tax_free.csv
```

### Custom Input File

```bash
# Use a different transaction file
python analyze_positions.py --input my_transactions.csv
```

## Price Fetching Details

### Supported Securities

The tool uses **yfinance** to fetch live prices and supports:

- **US Stocks**: Most US stocks are supported (TSLA, AAPL, MSFT, etc.)
- **European Stocks**: Major European stocks with static ticker mappings
- **ETFs**: Common ETFs with exchange-specific tickers
- **Currency Conversion**: Automatic conversion to EUR from USD, GBP, SEK, CZK, and more

### Ticker Mapping

The tool uses a CSV file (`ticker_mappings.csv`) to map ISINs to ticker symbols:

1. **First Run**: Creates default mappings file with common stocks
2. **Auto-Discovery**: Automatically adds unknown ISINs with empty ticker fields
3. **Manual Completion**: Edit the CSV file to add missing ticker symbols
4. **Reload**: Next run will use your updated mappings

**Example workflow:**

```bash
# First run - creates ticker_mappings.csv and identifies unknowns
python analyze_positions.py --with-prices

# Check warnings in output:
# WARNING: Ticker not found for XYZ (ISIN: ABC123) - added to ticker_mappings.csv

# Edit ticker_mappings.csv to fill in missing tickers
nano ticker_mappings.csv  # or use any editor

# Run again - now uses your updated mappings
python analyze_positions.py --with-prices
```

**File format:**
```csv
ISIN,Ticker,Description
US00206R1023,T,AT&T
US9344231041,WBD,Warner Bros Discovery
US65443P1021,,908 DEVICES INC  ← Empty ticker (fill this in!)
```

See [TICKER_MAPPINGS_GUIDE.md](TICKER_MAPPINGS_GUIDE.md) for detailed instructions on finding and adding ticker symbols.

### Caching

Price data is cached at `~/.cache/degiro_positions/price_cache.json` with:

- **Cache Validity**: 24 hours
- **Exchange Rates**: Also cached for 24 hours
- **Graceful Degradation**: Falls back to older cache if API fails

### Error Handling

The tool handles errors gracefully:

- **Ticker Not Found**: Displays "N/A" and continues
- **API Error**: Shows "API Error" and tries to use stale cache
- **Currency Error**: Shows original currency with warning
- **Partial Success**: Portfolio summary shows successfully priced stocks

## Output Format

### Terminal Output (with prices)

```
21SHARES BITCOIN ETP
  ISIN: CH0454664001
  Ticker: 21XB.PA
  Current Price: €324.75 (from $342.50)
  Position Value: €1,949.50
  Total Shares: 6
  Positions (FIFO order):
    1. Date: 2025-06-13, Quantity: 3
    2. Date: 2025-11-11, Quantity: 3

PORTFOLIO SUMMARY
Total portfolio value: €146,061.13
Successfully priced: 8/20 stocks
Price data fetched: 2026-01-27 11:39
```

### Tax-Free Positions Output (with prices)

```
AT&T INC
  ISIN: US00206R1023
  Ticker: T
  Current Price: €19.74 (from USD 23.45)
  Tax-Free Position Value: €434.18
  Tax-Free Shares: 22 (out of 22 total)
  Positions eligible for tax-free sale (FIFO order):
    1. Bought: 2021-02-24, Quantity: 10, Held: 4.92 years (1798 days)
    2. Bought: 2021-03-08, Quantity: 5, Held: 4.89 years (1786 days)
    ...

TAX-FREE PORTFOLIO SUMMARY
Total tax-free position value: €109,897.80
Successfully priced: 5/15 stocks
Price data fetched: 2026-01-27 11:45
```

### CSV Export (with prices)

**Regular positions** columns:
- Stock, ISIN, Buy Date, Quantity, Total Stock Quantity
- **With prices**: Ticker, Current Price, Currency, Price EUR, Position Value EUR, Price Fetch Status

**Tax-free positions** columns:
- Stock, ISIN, Buy Date, Quantity, Holding Days, Holding Years, Tax-Free Quantity, Total Stock Quantity
- **With prices**: Ticker, Current Price, Currency, Price EUR, Tax-Free Position Value EUR, Price Fetch Status

## Requirements

- Python 3.8+
- yfinance >= 0.2.36
- Internet connection (for price fetching)

## Input File Format

The tool expects a CSV file with the following columns:

- **Date**: Transaction date (format: DD-MM-YYYY)
- **Product**: Stock/ETF name
- **ISIN**: ISIN identifier
- **Quantity**: Number of shares (positive for buy, negative for sell)

## License

This is a personal tool. Use at your own discretion.
