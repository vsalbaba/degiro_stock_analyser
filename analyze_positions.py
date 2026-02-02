#!/usr/bin/env python3
"""
DeGiro Transactions Parser with FIFO Position Tracking

Parses Transactions.csv and calculates current positions using FIFO (First In First Out) logic.
- Positive quantity = BUY
- Negative quantity = SELL
"""

# ============================================================================
# IMPORTS
# ============================================================================
import csv
import argparse
import logging
import json
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Tuple, Optional, Any
from pathlib import Path

# ============================================================================
# CONSTANTS
# ============================================================================
DEFAULT_INPUT_FILE = 'Transactions.csv'
TICKER_MAPPINGS_FILE = 'ticker_mappings.csv'
TAX_FREE_YEARS_THRESHOLD = 3
DAYS_PER_YEAR = 365.25
DISPLAY_WIDTH = 80
DATE_FORMAT_INPUT = '%d-%m-%Y'
DATE_FORMAT_OUTPUT = '%Y-%m-%d'
CACHE_VALIDITY_HOURS = 24
CACHE_FALLBACK_DAYS = 7
DEFAULT_CACHE_DIR = Path.home() / '.cache' / 'degiro_positions'
DEFAULT_CACHE_FILE = 'price_cache.json'
DEFAULT_TICKER_MAPPINGS_FILE = 'ticker_mappings.csv'

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# DATA PARSING
# ============================================================================


def parse_csv(filename: str) -> List[Dict[str, Any]]:
    """Parse DeGiro transactions from CSV file.

    Reads a CSV export from DeGiro and extracts transaction data.
    Transactions with positive quantities are purchases (BUY),
    negative quantities are sales (SELL).

    Args:
        filename: Path to the CSV file containing transaction data.
                  Expected format: Date, Product, ISIN, Quantity columns.

    Returns:
        List of transaction dictionaries, each containing:
            - date (datetime): Transaction date
            - product (str): Stock/ETF name
            - isin (str): ISIN identifier
            - quantity (int or float): Number of shares (positive=buy, negative=sell)

    Raises:
        FileNotFoundError: If the CSV file doesn't exist.

    Example:
        >>> transactions = parse_csv('Transactions.csv')
        >>> logger.info(f"Loaded {len(transactions)} transactions")
    """
    file_path = Path(filename)
    if not file_path.exists():
        raise FileNotFoundError(f"Transaction file not found: {filename}")

    transactions: List[Dict[str, Any]] = []
    skipped_rows = 0

    with open(filename, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is 1)
            # Validate required fields
            if not row.get('Date') or not row.get('Quantity'):
                logger.warning(f"Row {row_num}: Missing Date or Quantity, skipping")
                skipped_rows += 1
                continue

            if not row.get('Product') or not row.get('ISIN'):
                logger.warning(f"Row {row_num}: Missing Product or ISIN, skipping")
                skipped_rows += 1
                continue

            # Parse date with better error handling
            try:
                date = datetime.strptime(row['Date'], DATE_FORMAT_INPUT)
            except ValueError:
                logger.warning(f"Row {row_num}: Invalid date format '{row['Date']}', skipping")
                skipped_rows += 1
                continue

            # Parse quantity (support both int and float)
            try:
                quantity_str = row['Quantity'].replace(',', '.')
                quantity = float(quantity_str)
                # Check if it's effectively an integer
                if quantity.is_integer():
                    quantity = int(quantity)
            except ValueError:
                logger.warning(f"Row {row_num}: Invalid quantity '{row['Quantity']}', skipping")
                skipped_rows += 1
                continue

            transactions.append({
                'date': date,
                'product': row['Product'],
                'isin': row['ISIN'],
                'quantity': quantity
            })

    if skipped_rows > 0:
        logger.info(f"Skipped {skipped_rows} invalid rows")

    return transactions


# ============================================================================
# TICKER MAPPINGS
# ============================================================================


def load_ticker_mappings(mappings_file: Optional[Path] = None) -> Dict[str, str]:
    """Load ISIN to ticker mappings from CSV file.

    Args:
        mappings_file: Path to ticker mappings CSV file. If None, uses default location.

    Returns:
        Dictionary mapping ISIN to ticker symbol.
    """
    if mappings_file is None:
        mappings_file = Path(DEFAULT_TICKER_MAPPINGS_FILE)

    mappings_file = Path(mappings_file)

    # Create default mappings file if it doesn't exist
    if not mappings_file.exists():
        logger.info(f"Creating ticker mappings file: {mappings_file}")
        _create_default_ticker_mappings(mappings_file)

    mappings = {}

    try:
        with open(mappings_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                isin = row.get('ISIN', '').strip()
                ticker = row.get('TICKER', '').strip()

                # Only add mappings where ticker is not empty
                if isin and ticker:
                    mappings[isin] = ticker

        logger.debug(f"Loaded {len(mappings)} ticker mappings from {mappings_file}")
        return mappings

    except (IOError, csv.Error) as e:
        logger.warning(f"Failed to load ticker mappings from {mappings_file}: {e}")
        return {}


def save_ticker_mappings(mappings: Dict[str, str], mappings_file: Optional[Path] = None) -> None:
    """Save ISIN to ticker mappings to CSV file.

    Args:
        mappings: Dictionary mapping ISIN to ticker symbol
        mappings_file: Path to ticker mappings CSV file. If None, uses default location.
    """
    if mappings_file is None:
        mappings_file = Path(DEFAULT_TICKER_MAPPINGS_FILE)

    mappings_file = Path(mappings_file)

    try:
        # Read existing file to preserve all entries (including empty ones)
        existing_entries = {}
        if mappings_file.exists():
            with open(mappings_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    isin = row.get('ISIN', '').strip()
                    if isin:
                        existing_entries[isin] = {
                            'NAME': row.get('NAME', '').strip(),
                            'TICKER': row.get('TICKER', '').strip()
                        }

        # Update with new mappings
        for isin, ticker in mappings.items():
            if isin not in existing_entries:
                existing_entries[isin] = {'NAME': '', 'TICKER': ticker}
            elif ticker:  # Only update if we have a non-empty ticker
                existing_entries[isin]['TICKER'] = ticker

        # Write back to file
        with open(mappings_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['ISIN', 'NAME', 'TICKER']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            # Sort by ISIN for consistent ordering
            for isin in sorted(existing_entries.keys()):
                writer.writerow({
                    'ISIN': isin,
                    'NAME': existing_entries[isin]['NAME'],
                    'TICKER': existing_entries[isin]['TICKER']
                })

        logger.debug(f"Saved {len(existing_entries)} ticker mappings to {mappings_file}")

    except IOError as e:
        logger.warning(f"Failed to save ticker mappings to {mappings_file}: {e}")


def _create_default_ticker_mappings(mappings_file: Path) -> None:
    """Create empty ticker mappings CSV file with headers only.

    Args:
        mappings_file: Path to ticker mappings CSV file
    """
    try:
        with open(mappings_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['ISIN', 'NAME', 'TICKER']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

        logger.info(f"Created empty ticker mappings file: {mappings_file}")

    except IOError as e:
        logger.error(f"Failed to create ticker mappings file: {e}")


def add_missing_isin_to_mappings(
    isin: str,
    product_name: str,
    mappings: Dict[str, str],
    mappings_file: Optional[Path] = None
) -> None:
    """Add an ISIN with empty ticker to the mappings file for user to fill in later.

    Args:
        isin: ISIN identifier
        product_name: Product name
        mappings: Current mappings dictionary
        mappings_file: Path to ticker mappings CSV file
    """
    if mappings_file is None:
        mappings_file = Path(DEFAULT_TICKER_MAPPINGS_FILE)

    mappings_file = Path(mappings_file)

    try:
        # Read existing file
        existing_entries = {}
        if mappings_file.exists():
            with open(mappings_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    isin_key = row.get('ISIN', '').strip()
                    if isin_key:
                        existing_entries[isin_key] = {
                            'NAME': row.get('NAME', '').strip(),
                            'TICKER': row.get('TICKER', '').strip()
                        }

        # Add new ISIN if not present
        if isin not in existing_entries:
            existing_entries[isin] = {
                'NAME': product_name,
                'TICKER': ''  # Empty for user to fill in
            }
            logger.warning(f"Ticker not found for {product_name} (ISIN: {isin}) - added to {mappings_file} for manual completion")

            # Write back to file
            with open(mappings_file, 'w', newline='', encoding='utf-8') as f:
                fieldnames = ['ISIN', 'NAME', 'TICKER']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

                # Sort by ISIN for consistent ordering
                for isin_key in sorted(existing_entries.keys()):
                    writer.writerow({
                        'ISIN': isin_key,
                        'NAME': existing_entries[isin_key]['NAME'],
                        'TICKER': existing_entries[isin_key]['TICKER']
                    })

    except IOError as e:
        logger.warning(f"Failed to add missing ISIN to mappings file: {e}")


def validate_all_ticker_mappings(
    transactions: List[Dict[str, Any]],
    mappings_file: Optional[Path] = None
) -> None:
    """Validate that all stocks from transactions exist in ticker mappings file.

    Adds any missing stocks with empty TICKER field for user to fill in manually.

    Args:
        transactions: List of transaction dictionaries
        mappings_file: Path to ticker mappings CSV file
    """
    if mappings_file is None:
        mappings_file = Path(DEFAULT_TICKER_MAPPINGS_FILE)

    mappings_file = Path(mappings_file)

    # Read existing mappings
    existing_entries = {}
    if mappings_file.exists():
        with open(mappings_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                isin_key = row.get('ISIN', '').strip()
                if isin_key:
                    existing_entries[isin_key] = {
                        'NAME': row.get('NAME', '').strip(),
                        'TICKER': row.get('TICKER', '').strip()
                    }

    # Extract unique stocks from transactions
    transaction_stocks = {}
    for transaction in transactions:
        isin = transaction['isin']
        name = transaction['product']
        if isin not in transaction_stocks:
            transaction_stocks[isin] = name

    # Find missing stocks
    missing_stocks = []
    for isin, name in transaction_stocks.items():
        if isin not in existing_entries:
            missing_stocks.append((isin, name))
            existing_entries[isin] = {
                'NAME': name,
                'TICKER': ''  # Empty for user to fill in
            }

    # Write updated mappings if there are new entries
    if missing_stocks:
        logger.warning(f"Found {len(missing_stocks)} stocks missing from {mappings_file}:")
        for isin, name in sorted(missing_stocks, key=lambda x: x[1]):  # Sort by name
            logger.warning(f"  - {name} ({isin})")

        try:
            with open(mappings_file, 'w', newline='', encoding='utf-8') as f:
                fieldnames = ['ISIN', 'NAME', 'TICKER']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

                # Sort by NAME for easier manual editing
                for isin_key in sorted(existing_entries.keys(), key=lambda k: existing_entries[k]['NAME']):
                    writer.writerow({
                        'ISIN': isin_key,
                        'NAME': existing_entries[isin_key]['NAME'],
                        'TICKER': existing_entries[isin_key]['TICKER']
                    })

            logger.warning(f"Updated {mappings_file} - please add missing TICKER symbols manually")
        except IOError as e:
            logger.error(f"Failed to update ticker mappings file: {e}")
    else:
        logger.info(f"All {len(transaction_stocks)} stocks found in {mappings_file}")


# ============================================================================
# PRICE FETCHING AND CURRENCY CONVERSION
# ============================================================================


def load_price_cache(cache_location: Optional[Path] = None) -> Dict[str, Any]:
    """Load price cache from disk.

    Args:
        cache_location: Path to cache file. If None, uses default location.

    Returns:
        Dictionary containing cached prices and exchange rates.
        Returns empty cache structure if file doesn't exist or is invalid.
    """
    if cache_location is None:
        cache_location = DEFAULT_CACHE_DIR / DEFAULT_CACHE_FILE

    cache_location = Path(cache_location)

    if not cache_location.exists():
        return {
            'version': '1.0',
            'last_updated': datetime.now().isoformat(),
            'prices': {},
            'exchange_rates': {}
        }

    try:
        with open(cache_location, 'r', encoding='utf-8') as f:
            cache = json.load(f)
            # Ensure all required keys exist
            if 'prices' not in cache:
                cache['prices'] = {}
            if 'exchange_rates' not in cache:
                cache['exchange_rates'] = {}
            return cache
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load cache from {cache_location}: {e}")
        return {
            'version': '1.0',
            'last_updated': datetime.now().isoformat(),
            'prices': {},
            'exchange_rates': {}
        }


def save_price_cache(cache: Dict[str, Any], cache_location: Optional[Path] = None) -> None:
    """Save price cache to disk.

    Args:
        cache: Dictionary containing prices and exchange rates to cache
        cache_location: Path to cache file. If None, uses default location.
    """
    if cache_location is None:
        cache_location = DEFAULT_CACHE_DIR / DEFAULT_CACHE_FILE

    cache_location = Path(cache_location)

    # Create directory if it doesn't exist
    cache_location.parent.mkdir(parents=True, exist_ok=True)

    try:
        cache['last_updated'] = datetime.now().isoformat()
        with open(cache_location, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.warning(f"Failed to save cache to {cache_location}: {e}")


def clean_ticker_not_found_from_cache(cache: Dict[str, Any]) -> int:
    """Remove all 'ticker_not_found' entries from cache.

    These should not be cached as users might add ticker symbols later.

    Args:
        cache: Price cache dictionary

    Returns:
        Number of entries removed
    """
    if 'prices' not in cache:
        return 0

    to_remove = []
    for isin, entry in cache['prices'].items():
        if entry.get('fetch_status') == 'ticker_not_found':
            to_remove.append(isin)

    for isin in to_remove:
        del cache['prices'][isin]

    if to_remove:
        logger.info(f"Cleaned {len(to_remove)} ticker_not_found entries from cache")

    return len(to_remove)


def isin_to_ticker(
    isin: str,
    product_name: str,
    ticker_mappings: Dict[str, str],
    mappings_file: Optional[Path] = None
) -> Optional[str]:
    """Map ISIN to ticker symbol.

    Args:
        isin: ISIN identifier
        product_name: Product name from transactions
        ticker_mappings: Dictionary of ISIN to ticker mappings
        mappings_file: Path to mappings file (for adding missing ISINs)

    Returns:
        Ticker symbol or None if not found
    """
    # Priority 1: Check loaded mappings
    if isin in ticker_mappings:
        return ticker_mappings[isin]

    # Priority 2: Heuristics for US stocks
    if isin.startswith('US'):
        # Try to extract ticker from product name
        # Common patterns: "TESLA INC", "AT&T INC", "MICROSOFT CORP"
        name_upper = product_name.upper()

        # Remove common suffixes
        for suffix in [' INC', ' CORP', ' CORPORATION', ' LTD', ' LIMITED', ' PLC', ' NV']:
            if name_upper.endswith(suffix):
                name_upper = name_upper[:-len(suffix)].strip()

        # Check if it's a known ticker pattern
        # This is a basic heuristic - we mainly rely on the static mapping
        words = name_upper.split()
        if len(words) == 1 and len(words[0]) <= 5:
            # Might be a ticker already
            return words[0]

    # Not found - add to mappings file for user to complete
    add_missing_isin_to_mappings(isin, product_name, ticker_mappings, mappings_file)

    return None


def fetch_exchange_rate(from_currency: str, to_currency: str = 'EUR') -> Optional[float]:
    """Fetch exchange rate from one currency to another.

    Args:
        from_currency: Source currency code (e.g., 'USD')
        to_currency: Target currency code (default: 'EUR')

    Returns:
        Exchange rate or None if fetch failed
    """
    if from_currency == to_currency:
        return 1.0

    try:
        import yfinance as yf

        # Construct forex pair symbol for yfinance
        # yfinance uses format like "EURUSD=X" for EUR to USD
        pair_symbol = f"{from_currency}{to_currency}=X"

        ticker = yf.Ticker(pair_symbol)
        data = ticker.history(period='1d')

        if data.empty:
            logger.warning(f"No exchange rate data for {pair_symbol}")
            return None

        # Get the most recent closing price
        rate = data['Close'].iloc[-1]
        return float(rate)

    except Exception as e:
        logger.warning(f"Failed to fetch exchange rate {from_currency} to {to_currency}: {e}")
        return None


def fetch_current_price(
    isin: str,
    product_name: str,
    cache: Dict[str, Any],
    ticker_mappings: Dict[str, str],
    use_cache: bool = True,
    mappings_file: Optional[Path] = None
) -> Dict[str, Any]:
    """Fetch current price for a stock.

    Args:
        isin: ISIN identifier
        product_name: Product name
        cache: Price cache dictionary
        ticker_mappings: Dictionary of ISIN to ticker mappings
        use_cache: Whether to use cached prices (if valid)
        mappings_file: Path to ticker mappings file

    Returns:
        Dictionary with price information:
        - ticker: Ticker symbol or None
        - price: Price in original currency or None
        - currency: Original currency or None
        - price_eur: Price in EUR or None
        - fetch_status: 'success', 'ticker_not_found', 'api_error', 'currency_error'
        - timestamp: ISO format timestamp
    """
    now = datetime.now()

    # Map ISIN to ticker first (before cache check)
    ticker_symbol = isin_to_ticker(isin, product_name, ticker_mappings, mappings_file)

    # Check cache
    if use_cache and isin in cache['prices']:
        cached_entry = cache['prices'][isin]
        cached_ticker = cached_entry.get('ticker')

        # Invalidate cache if:
        # 1. Status is 'ticker_not_found' (user might have added ticker symbol)
        # 2. Ticker symbol has changed (user updated the mapping)
        should_skip_cache = False

        if cached_entry.get('fetch_status') == 'ticker_not_found':
            logger.debug(f"Ignoring cached ticker_not_found for {product_name} - retrying")
            should_skip_cache = True
        elif ticker_symbol != cached_ticker:
            logger.debug(f"Ticker changed for {product_name} ({cached_ticker} -> {ticker_symbol}) - refetching")
            should_skip_cache = True

        if not should_skip_cache:
            cached_time = datetime.fromisoformat(cached_entry['timestamp'])

            # Check if cache is still valid (within 24 hours)
            if (now - cached_time).total_seconds() < CACHE_VALIDITY_HOURS * 3600:
                logger.debug(f"Using cached price for {product_name} ({isin})")
                return cached_entry

    if ticker_symbol is None:
        result = {
            'ticker': None,
            'price': None,
            'currency': None,
            'price_eur': None,
            'fetch_status': 'ticker_not_found',
            'timestamp': now.isoformat()
        }
        # DO NOT cache ticker_not_found - user might add the ticker symbol later
        return result

    # Fetch price from yfinance
    try:
        import yfinance as yf

        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info

        # Try to get current price from various fields
        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')

        if price is None:
            # Fallback: try getting from history
            hist = ticker.history(period='1d')
            if not hist.empty:
                price = hist['Close'].iloc[-1]

        if price is None:
            logger.warning(f"No price data available for {ticker_symbol} ({product_name})")
            result = {
                'ticker': ticker_symbol,
                'price': None,
                'currency': None,
                'price_eur': None,
                'fetch_status': 'api_error',
                'timestamp': now.isoformat()
            }
            cache['prices'][isin] = result
            return result

        # Get currency
        currency = info.get('currency', 'EUR')

        # Convert to EUR if needed
        if currency == 'EUR':
            price_eur = price
            exchange_rate = 1.0
        else:
            # Check cache for exchange rate
            rate_key = f"{currency}EUR"
            exchange_rate = None

            if use_cache and rate_key in cache['exchange_rates']:
                rate_entry = cache['exchange_rates'][rate_key]
                rate_time = datetime.fromisoformat(rate_entry['timestamp'])
                if (now - rate_time).total_seconds() < CACHE_VALIDITY_HOURS * 3600:
                    exchange_rate = rate_entry['rate']

            # Fetch fresh exchange rate if not cached
            if exchange_rate is None:
                exchange_rate = fetch_exchange_rate(currency, 'EUR')
                if exchange_rate is not None:
                    cache['exchange_rates'][rate_key] = {
                        'rate': exchange_rate,
                        'timestamp': now.isoformat()
                    }

            if exchange_rate is None:
                logger.warning(f"Failed to get exchange rate for {currency} to EUR")
                result = {
                    'ticker': ticker_symbol,
                    'price': float(price),
                    'currency': currency,
                    'price_eur': None,
                    'fetch_status': 'currency_error',
                    'timestamp': now.isoformat()
                }
                cache['prices'][isin] = result
                return result

            price_eur = float(price) * exchange_rate

        result = {
            'ticker': ticker_symbol,
            'price': float(price),
            'currency': currency,
            'price_eur': float(price_eur),
            'fetch_status': 'success',
            'timestamp': now.isoformat()
        }
        cache['prices'][isin] = result
        return result

    except Exception as e:
        logger.warning(f"Failed to fetch price for {ticker_symbol} ({product_name}): {e}")
        result = {
            'ticker': ticker_symbol,
            'price': None,
            'currency': None,
            'price_eur': None,
            'fetch_status': 'api_error',
            'timestamp': now.isoformat()
        }
        cache['prices'][isin] = result
        return result


# ============================================================================
# POSITION PROCESSING (FIFO LOGIC)
# ============================================================================


def _apply_fifo_logic(
    transactions: List[Dict[str, Any]],
    track_sold: bool
) -> Tuple[defaultdict, defaultdict]:
    """Apply FIFO logic to transactions.

    Args:
        transactions: List of transaction dictionaries
        track_sold: If True, also track sold positions

    Returns:
        Tuple of (positions, sold_positions) as defaultdicts
    """
    # Dictionary to store positions by stock
    # Key: (product, isin), Value: list of position entries
    positions = defaultdict(list)

    # Dictionary to store sold positions
    sold_positions = defaultdict(list)

    # Sort transactions by date
    transactions_by_date = sorted(transactions, key=lambda x: x['date'])

    for transaction in transactions_by_date:
        stock_key = (transaction['product'], transaction['isin'])
        quantity = transaction['quantity']
        date = transaction['date']

        if quantity > 0:  # Buy (positive quantity)
            # Add new position
            positions[stock_key].append({
                'date': date,
                'quantity': quantity
            })
        else:  # Sell (negative quantity)
            # Remove from oldest positions first (FIFO)
            remaining_to_sell = abs(quantity)

            while remaining_to_sell > 0 and positions[stock_key]:
                oldest_lot = positions[stock_key][0]

                if oldest_lot['quantity'] <= remaining_to_sell:
                    # Sell entire oldest position
                    sold_qty = oldest_lot['quantity']
                    remaining_to_sell -= sold_qty

                    if track_sold:
                        sold_positions[stock_key].append({
                            'buy_date': oldest_lot['date'],
                            'sell_date': date,
                            'quantity': sold_qty
                        })

                    positions[stock_key].pop(0)
                else:
                    # Partially sell oldest position
                    if track_sold:
                        sold_positions[stock_key].append({
                            'buy_date': oldest_lot['date'],
                            'sell_date': date,
                            'quantity': remaining_to_sell
                        })

                    oldest_lot['quantity'] -= remaining_to_sell
                    remaining_to_sell = 0

            # If we still have remaining_to_sell > 0, it means we oversold
            # This could happen with stock splits or data issues
            if remaining_to_sell > 0:
                logger.error(
                    f"FIFO violation: Oversold {transaction['product']} by {remaining_to_sell} "
                    f"shares on {_format_date_for_display(date)}. "
                    f"This may indicate stock splits, data issues, or missing buy transactions."
                )

    return positions, sold_positions


def _format_current_positions(positions: defaultdict) -> Dict[str, Any]:
    """Format current positions for output.

    Args:
        positions: defaultdict of positions by stock key

    Returns:
        Dictionary of formatted current positions
    """
    result = {}
    for (product, isin), lot_list in positions.items():
        if lot_list:  # Only include stocks with current positions
            total = sum(lot['quantity'] for lot in lot_list)
            result[product] = {
                'isin': isin,
                'positions': [
                    {
                        'date': lot['date'],
                        'change': lot['quantity']
                    } for lot in lot_list
                ],
                'total': total
            }

    return result


def _format_sold_positions(sold_positions: defaultdict) -> Dict[str, Any]:
    """Format sold positions for output.

    Args:
        sold_positions: defaultdict of sold positions by stock key

    Returns:
        Dictionary of formatted sold positions
    """
    result = {}
    for (product, isin), sold_list in sold_positions.items():
        if sold_list:
            total_sold = sum(lot['quantity'] for lot in sold_list)
            result[product] = {
                'isin': isin,
                'positions': [
                    {
                        'buy_date': lot['buy_date'],
                        'sell_date': lot['sell_date'],
                        'quantity': lot['quantity']
                    } for lot in sold_list
                ],
                'total_sold': total_sold
            }

    return result


def process_positions(
    transactions: List[Dict[str, Any]],
    track_sold: bool = False,
    fetch_prices: bool = False,
    use_cache: bool = True,
    cache_location: Optional[Path] = None,
    mappings_file: Optional[Path] = None
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Process transactions with FIFO logic to get current positions.

    Args:
        transactions: List of transaction dictionaries
        track_sold: If True, also track sold positions
        fetch_prices: If True, fetch current prices for positions
        use_cache: If True, use cached prices (if valid)
        cache_location: Path to cache file (None = default location)
        mappings_file: Path to ticker mappings file (None = default location)

    Returns:
        Tuple of (current_positions, sold_positions).
        If track_sold=False, sold_positions will be None.
    """
    positions, sold_positions = _apply_fifo_logic(transactions, track_sold)
    current_result = _format_current_positions(positions)

    # Fetch current prices if requested
    if fetch_prices and current_result:
        logger.info("Fetching current prices...")

        # Load ticker mappings
        ticker_mappings = load_ticker_mappings(mappings_file)

        cache = load_price_cache(cache_location)

        # Clean up any old ticker_not_found entries (shouldn't be cached)
        clean_ticker_not_found_from_cache(cache)

        # Get unique ISINs to fetch
        unique_stocks = list(current_result.items())
        successful = 0
        failed = 0

        for stock_name, data in unique_stocks:
            isin = data['isin']
            price_info = fetch_current_price(
                isin,
                stock_name,
                cache,
                ticker_mappings,
                use_cache,
                mappings_file
            )

            # Add price information to position data
            data['price_info'] = price_info

            # Calculate position value if we have EUR price
            if price_info['price_eur'] is not None:
                data['position_value_eur'] = price_info['price_eur'] * data['total']
                successful += 1
            else:
                data['position_value_eur'] = None
                failed += 1

        # Save updated cache
        save_price_cache(cache, cache_location)

        total = successful + failed
        logger.info(f"Price fetch complete: {successful}/{total} successful")

    if track_sold:
        sold_result = _format_sold_positions(sold_positions)
        return current_result, sold_result

    return current_result, None


# ============================================================================
# FILTERING AND ANALYSIS
# ============================================================================


def filter_tax_free_positions(
    positions: Dict[str, Any],
    years: int = TAX_FREE_YEARS_THRESHOLD
) -> Dict[str, Any]:
    """Filter positions that can be sold tax-free (older than specified years).

    Args:
        positions: Dictionary of current positions
        years: Number of years for tax-free threshold (default: 3)

    Returns:
        Dictionary of positions that can be sold tax-free
    """
    today = datetime.now()
    threshold_date = today - timedelta(days=years * DAYS_PER_YEAR)

    tax_free_positions = {}

    for stock_name, data in positions.items():
        tax_free_lots = []

        for position in data['positions']:
            # Date is already a datetime object
            pos_date = position['date']

            if pos_date <= threshold_date:
                # Calculate holding period
                holding_days = (today - pos_date).days
                holding_years = holding_days / DAYS_PER_YEAR

                tax_free_lots.append({
                    'date': pos_date,
                    'change': position['change'],
                    'holding_days': holding_days,
                    'holding_years': holding_years
                })

        if tax_free_lots:
            total_tax_free = sum(lot['change'] for lot in tax_free_lots)
            tax_free_positions[stock_name] = {
                'isin': data['isin'],
                'positions': tax_free_lots,
                'total': total_tax_free,
                'total_held': data['total']
            }

            # Preserve price information if it exists
            if 'price_info' in data:
                tax_free_positions[stock_name]['price_info'] = data['price_info']
                # Calculate tax-free position value
                if data.get('position_value_eur') is not None and data['price_info']['price_eur'] is not None:
                    tax_free_positions[stock_name]['tax_free_value_eur'] = data['price_info']['price_eur'] * total_tax_free
                else:
                    tax_free_positions[stock_name]['tax_free_value_eur'] = None

    return tax_free_positions


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def _format_date_for_display(date: datetime) -> str:
    """Convert datetime to display string format.

    Args:
        date: datetime object to format

    Returns:
        Formatted date string in YYYY-MM-DD format
    """
    return date.strftime(DATE_FORMAT_OUTPUT)


# ============================================================================
# OUTPUT FUNCTIONS
# ============================================================================


def export_to_csv(
    positions: Dict[str, Any],
    filename: str,
    sold_positions: Optional[Dict[str, Any]] = None
) -> None:
    """Export regular positions to CSV file.

    Args:
        positions: Dictionary of current positions
        filename: Output CSV filename
        sold_positions: Optional dictionary of sold positions
    """
    rows = []

    sorted_stocks = sorted(positions.items())

    # Check if we have price information
    has_prices = any('price_info' in data for _, data in sorted_stocks)

    if sold_positions:
        # Export format with sold positions (includes Status and Sell Date columns)
        # Add current positions
        for stock_name, data in sorted_stocks:
            for position in data['positions']:
                row = {
                    'Stock': stock_name,
                    'ISIN': data['isin'],
                    'Status': 'CURRENT',
                    'Buy Date': _format_date_for_display(position['date']),
                    'Sell Date': '',
                    'Quantity': position['change'],
                    'Total Stock Quantity': data['total']
                }

                # Add price columns if available
                if has_prices and 'price_info' in data:
                    price_info = data['price_info']
                    row['Ticker'] = price_info.get('ticker', '')
                    row['Current Price'] = price_info.get('price', '')
                    row['Currency'] = price_info.get('currency', '')
                    row['Price EUR'] = price_info.get('price_eur', '')
                    row['Position Value EUR'] = data.get('position_value_eur', '')
                    row['Price Fetch Status'] = price_info.get('fetch_status', '')

                rows.append(row)

        # Add sold positions
        sorted_sold = sorted(sold_positions.items())
        for stock_name, data in sorted_sold:
            for position in data['positions']:
                row = {
                    'Stock': stock_name,
                    'ISIN': data['isin'],
                    'Status': 'SOLD',
                    'Buy Date': _format_date_for_display(position['buy_date']),
                    'Sell Date': _format_date_for_display(position['sell_date']),
                    'Quantity': position['quantity'],
                    'Total Stock Quantity': ''
                }

                # Add empty price columns for sold positions if we have prices
                if has_prices:
                    row['Ticker'] = ''
                    row['Current Price'] = ''
                    row['Currency'] = ''
                    row['Price EUR'] = ''
                    row['Position Value EUR'] = ''
                    row['Price Fetch Status'] = ''

                rows.append(row)

        with open(filename, 'w', newline='', encoding='utf-8') as f:
            if has_prices:
                fieldnames = ['Stock', 'ISIN', 'Status', 'Buy Date', 'Sell Date', 'Quantity',
                             'Total Stock Quantity', 'Ticker', 'Current Price', 'Currency',
                             'Price EUR', 'Position Value EUR', 'Price Fetch Status']
            else:
                fieldnames = ['Stock', 'ISIN', 'Status', 'Buy Date', 'Sell Date', 'Quantity', 'Total Stock Quantity']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        current_count = sum(len(data['positions']) for data in positions.values())
        sold_count = sum(len(data['positions']) for data in sold_positions.values())
        total_count = current_count + sold_count

        logger.info(f"Exported {total_count} position entries to {filename}")
        logger.info(f"  - Current positions: {current_count}")
        logger.info(f"  - Sold positions: {sold_count}")
    else:
        # Simpler export format for current positions only (no Status or Sell Date columns)
        for stock_name, data in sorted_stocks:
            for position in data['positions']:
                row = {
                    'Stock': stock_name,
                    'ISIN': data['isin'],
                    'Buy Date': _format_date_for_display(position['date']),
                    'Quantity': position['change'],
                    'Total Stock Quantity': data['total']
                }

                # Add price columns if available
                if has_prices and 'price_info' in data:
                    price_info = data['price_info']
                    row['Ticker'] = price_info.get('ticker', '')
                    row['Current Price'] = price_info.get('price', '')
                    row['Currency'] = price_info.get('currency', '')
                    row['Price EUR'] = price_info.get('price_eur', '')
                    row['Position Value EUR'] = data.get('position_value_eur', '')
                    row['Price Fetch Status'] = price_info.get('fetch_status', '')

                rows.append(row)

        with open(filename, 'w', newline='', encoding='utf-8') as f:
            if has_prices:
                fieldnames = ['Stock', 'ISIN', 'Buy Date', 'Quantity', 'Total Stock Quantity',
                             'Ticker', 'Current Price', 'Currency', 'Price EUR',
                             'Position Value EUR', 'Price Fetch Status']
            else:
                fieldnames = ['Stock', 'ISIN', 'Buy Date', 'Quantity', 'Total Stock Quantity']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        current_count = len(rows)
        logger.info(f"Exported {current_count} position entries to {filename}")


def export_tax_free_to_csv(
    positions: Dict[str, Any],
    filename: str
) -> None:
    """Export tax-free positions to CSV file.

    Args:
        positions: Dictionary of tax-free positions
        filename: Output CSV filename
    """
    rows = []

    sorted_stocks = sorted(positions.items())

    # Check if we have price information
    has_prices = any('price_info' in data for _, data in sorted_stocks)

    for stock_name, data in sorted_stocks:
        for position in data['positions']:
            row = {
                'Stock': stock_name,
                'ISIN': data['isin'],
                'Buy Date': _format_date_for_display(position['date']),
                'Quantity': position['change'],
                'Holding Days': position['holding_days'],
                'Holding Years': f"{position['holding_years']:.2f}",
                'Tax-Free Quantity': data['total'],
                'Total Stock Quantity': data['total_held']
            }

            # Add price columns if available
            if has_prices and 'price_info' in data:
                price_info = data['price_info']
                row['Ticker'] = price_info.get('ticker', '')
                row['Current Price'] = price_info.get('price', '')
                row['Currency'] = price_info.get('currency', '')
                row['Price EUR'] = price_info.get('price_eur', '')
                row['Tax-Free Position Value EUR'] = data.get('tax_free_value_eur', '')
                row['Price Fetch Status'] = price_info.get('fetch_status', '')

            rows.append(row)

    with open(filename, 'w', newline='', encoding='utf-8') as f:
        if has_prices:
            fieldnames = ['Stock', 'ISIN', 'Buy Date', 'Quantity', 'Holding Days', 'Holding Years',
                         'Tax-Free Quantity', 'Total Stock Quantity', 'Ticker', 'Current Price',
                         'Currency', 'Price EUR', 'Tax-Free Position Value EUR', 'Price Fetch Status']
        else:
            fieldnames = ['Stock', 'ISIN', 'Buy Date', 'Quantity', 'Holding Days', 'Holding Years',
                         'Tax-Free Quantity', 'Total Stock Quantity']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Exported {len(rows)} tax-free position entries to {filename}")


def _print_stock_list(
    stocks: Dict[str, Any],
    title: str,
    is_sold: bool = False
) -> None:
    """Helper to print a list of stocks.

    Args:
        stocks: Dictionary of stock positions
        title: Title to display for this section
        is_sold: True if printing sold positions, False for current positions
    """
    print("\n" + "=" * DISPLAY_WIDTH)
    print(f"{title} (sorted by stock name)")
    print("=" * DISPLAY_WIDTH)

    if not stocks:
        status = "sold" if is_sold else "current"
        print(f"\nNo {status} positions found.")
    else:
        sorted_stocks = sorted(stocks.items())
        total_portfolio_value = 0.0
        priced_stocks = 0

        for stock_name, data in sorted_stocks:
            print(f"\n{stock_name}")
            print(f"  ISIN: {data['isin']}")

            # Display price information if available
            if 'price_info' in data and not is_sold:
                price_info = data['price_info']
                if price_info['ticker']:
                    print(f"  Ticker: {price_info['ticker']}")

                if price_info['fetch_status'] == 'success':
                    if price_info['currency'] == 'EUR':
                        print(f"  Current Price: €{price_info['price']:.2f}")
                    else:
                        print(f"  Current Price: €{price_info['price_eur']:.2f} (from {price_info['currency']} {price_info['price']:.2f})")

                    if data['position_value_eur'] is not None:
                        print(f"  Position Value: €{data['position_value_eur']:.2f}")
                        total_portfolio_value += data['position_value_eur']
                        priced_stocks += 1
                elif price_info['fetch_status'] == 'ticker_not_found':
                    print(f"  Current Price: N/A (ticker not found)")
                elif price_info['fetch_status'] == 'api_error':
                    print(f"  Current Price: API Error")
                elif price_info['fetch_status'] == 'currency_error':
                    print(f"  Current Price: {price_info['currency']} {price_info['price']:.2f} (EUR conversion failed)")

            if is_sold:
                print(f"  Total Sold: {data['total_sold']} shares")
                print(f"  Sold Positions (chronological):")
                for i, position in enumerate(data['positions'], 1):
                    buy_date = _format_date_for_display(position['buy_date'])
                    sell_date = _format_date_for_display(position['sell_date'])
                    print(f"    {i}. Bought: {buy_date}, Sold: {sell_date}, Quantity: {position['quantity']}")
            else:
                print(f"  Total Shares: {data['total']}")
                print(f"  Positions (FIFO order):")
                for i, position in enumerate(data['positions'], 1):
                    date_str = _format_date_for_display(position['date'])
                    print(f"    {i}. Date: {date_str}, Quantity: {position['change']}")

        print("\n" + "=" * DISPLAY_WIDTH)
        status = "sold" if is_sold else "held"
        print(f"Total different stocks {status}: {len(stocks)}")
        total_positions = sum(len(data['positions']) for data in stocks.values())
        print(f"Total position entries: {total_positions}")

        # Print portfolio summary if prices were fetched
        if not is_sold and priced_stocks > 0:
            print(f"\nPORTFOLIO SUMMARY")
            print(f"Total portfolio value: €{total_portfolio_value:.2f}")
            print(f"Successfully priced: {priced_stocks}/{len(stocks)} stocks")
            print(f"Price data fetched: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        print("=" * DISPLAY_WIDTH)


def _print_missing_tickers_footer(positions: Dict[str, Any]) -> None:
    """Print footer with stocks that could not be priced.

    Args:
        positions: Dictionary of positions (current or tax-free)
    """
    # Check if we have price information at all
    has_prices = any('price_info' in data for _, data in positions.items())
    if not has_prices:
        return

    # Collect stocks by failure reason
    ticker_not_found = []
    api_error = []
    currency_error = []

    for stock_name, data in sorted(positions.items()):
        if 'price_info' not in data:
            continue

        price_info = data['price_info']
        status = price_info.get('fetch_status')

        if status == 'ticker_not_found':
            ticker_not_found.append({
                'name': stock_name,
                'isin': data['isin']
            })
        elif status == 'api_error':
            ticker = price_info.get('ticker', 'N/A')
            api_error.append({
                'name': stock_name,
                'isin': data['isin'],
                'ticker': ticker
            })
        elif status == 'currency_error':
            ticker = price_info.get('ticker', 'N/A')
            currency = price_info.get('currency', 'N/A')
            currency_error.append({
                'name': stock_name,
                'isin': data['isin'],
                'ticker': ticker,
                'currency': currency
            })

    # Print footer if there are any issues
    if ticker_not_found or api_error or currency_error:
        print("\n" + "=" * DISPLAY_WIDTH)
        print("STOCKS NOT PRICED")
        print("=" * DISPLAY_WIDTH)

        if ticker_not_found:
            print(f"\nTicker not found ({len(ticker_not_found)} stocks):")
            print("These stocks need ticker symbols added to ticker_mappings.csv\n")
            for item in ticker_not_found:
                print(f"  • {item['name']}")
                print(f"    ISIN: {item['isin']}")

        if api_error:
            print(f"\nAPI/Data error ({len(api_error)} stocks):")
            print("Ticker symbols may be incorrect or stock may be delisted\n")
            for item in api_error:
                print(f"  • {item['name']}")
                print(f"    ISIN: {item['isin']}, Ticker: {item['ticker']}")

        if currency_error:
            print(f"\nCurrency conversion error ({len(currency_error)} stocks):")
            print("Price fetched but could not convert to EUR\n")
            for item in currency_error:
                print(f"  • {item['name']}")
                print(f"    ISIN: {item['isin']}, Ticker: {item['ticker']}, Currency: {item['currency']}")

        print("\n" + "=" * DISPLAY_WIDTH)


def print_positions(
    positions: Dict[str, Any],
    sold_positions: Optional[Dict[str, Any]] = None
) -> None:
    """Print current positions and optionally sold positions.

    Args:
        positions: Dictionary of current positions
        sold_positions: Optional dictionary of sold positions
    """
    _print_stock_list(positions, "CURRENT POSITIONS", is_sold=False)

    if sold_positions:
        _print_stock_list(sold_positions, "SOLD POSITIONS", is_sold=True)

    # Print footer with missing tickers if price info is available
    _print_missing_tickers_footer(positions)

    print()


def print_tax_free_positions(positions: Dict[str, Any]) -> None:
    """Print tax-free positions with holding period information.

    Args:
        positions: Dictionary of tax-free positions
    """
    print("\n" + "=" * DISPLAY_WIDTH)
    print("TAX-FREE POSITIONS (held > 3 years, sorted by stock name)")
    print("=" * DISPLAY_WIDTH)

    if not positions:
        print("\nNo positions eligible for tax-free sale found.")
        print("(No positions have been held for more than 3 years)")
    else:
        sorted_stocks = sorted(positions.items())
        total_tax_free_value = 0.0
        priced_stocks = 0

        for stock_name, data in sorted_stocks:
            print(f"\n{stock_name}")
            print(f"  ISIN: {data['isin']}")

            # Display price information if available
            if 'price_info' in data:
                price_info = data['price_info']
                if price_info['ticker']:
                    print(f"  Ticker: {price_info['ticker']}")

                if price_info['fetch_status'] == 'success':
                    if price_info['currency'] == 'EUR':
                        print(f"  Current Price: €{price_info['price']:.2f}")
                    else:
                        print(f"  Current Price: €{price_info['price_eur']:.2f} (from {price_info['currency']} {price_info['price']:.2f})")

                    if data.get('tax_free_value_eur') is not None:
                        print(f"  Tax-Free Position Value: €{data['tax_free_value_eur']:.2f}")
                        total_tax_free_value += data['tax_free_value_eur']
                        priced_stocks += 1
                elif price_info['fetch_status'] == 'ticker_not_found':
                    print(f"  Current Price: N/A (ticker not found)")
                elif price_info['fetch_status'] == 'api_error':
                    print(f"  Current Price: API Error")
                elif price_info['fetch_status'] == 'currency_error':
                    print(f"  Current Price: {price_info['currency']} {price_info['price']:.2f} (EUR conversion failed)")

            print(f"  Tax-Free Shares: {data['total']} (out of {data['total_held']} total)")
            print(f"  Positions eligible for tax-free sale (FIFO order):")
            for i, position in enumerate(data['positions'], 1):
                date_str = _format_date_for_display(position['date'])
                print(f"    {i}. Bought: {date_str}, Quantity: {position['change']}, "
                      f"Held: {position['holding_years']:.2f} years ({position['holding_days']} days)")

        print("\n" + "=" * DISPLAY_WIDTH)
        print(f"Total different stocks with tax-free positions: {len(positions)}")
        total_tax_free = sum(data['total'] for data in positions.values())
        print(f"Total tax-free shares across all stocks: {total_tax_free}")
        total_positions = sum(len(data['positions']) for data in positions.values())
        print(f"Total tax-free position entries: {total_positions}")

        # Print portfolio summary if prices were fetched
        if priced_stocks > 0:
            print(f"\nTAX-FREE PORTFOLIO SUMMARY")
            print(f"Total tax-free position value: €{total_tax_free_value:.2f}")
            print(f"Successfully priced: {priced_stocks}/{len(positions)} stocks")
            print(f"Price data fetched: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        print("=" * DISPLAY_WIDTH)

    # Print footer with missing tickers if price info is available
    _print_missing_tickers_footer(positions)

    print()


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================


def main() -> None:
    """Main entry point for the DeGiro position analyzer."""
    parser = argparse.ArgumentParser(
        description='DeGiro Position Analyzer with FIFO tracking',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s                                      # Display current positions
  %(prog)s --with-sold                          # Display current and sold positions
  %(prog)s --can-be-sold                        # Display only positions held > 3 years (tax-free)
  %(prog)s --with-prices                        # Display current positions with live prices
  %(prog)s --can-be-sold --with-prices          # Display tax-free positions with current values
  %(prog)s --with-prices --no-cache             # Fetch fresh prices (ignore cache)
  %(prog)s --ticker-mappings my_tickers.csv     # Use custom ticker mappings file
  %(prog)s --export positions.csv               # Export current positions to CSV
  %(prog)s --export positions.csv --with-sold   # Export current and sold positions
  %(prog)s --export positions.csv --with-prices # Export with current prices
  %(prog)s --export tax_free.csv --can-be-sold --with-prices # Export tax-free positions with values
  %(prog)s --input custom.csv                   # Use custom input file
        '''
    )
    parser.add_argument(
        '--input',
        metavar='FILENAME',
        default=DEFAULT_INPUT_FILE,
        help=f'Input CSV file with transactions (default: {DEFAULT_INPUT_FILE})'
    )
    parser.add_argument(
        '--export',
        metavar='FILENAME',
        help='Export positions to CSV file'
    )
    parser.add_argument(
        '--with-sold',
        action='store_true',
        help='Include historical sold positions in output'
    )
    parser.add_argument(
        '--can-be-sold',
        action='store_true',
        help='Show only positions held > 3 years (tax-free selling)'
    )
    parser.add_argument(
        '--with-prices',
        action='store_true',
        help='Fetch and display current stock prices in EUR'
    )
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Force fresh price fetch, ignoring cache'
    )
    parser.add_argument(
        '--cache-location',
        metavar='PATH',
        type=Path,
        help='Custom cache file location (default: ~/.cache/degiro_positions/price_cache.json)'
    )
    parser.add_argument(
        '--ticker-mappings',
        metavar='PATH',
        type=Path,
        help='Custom ticker mappings CSV file (default: ticker_mappings.csv)'
    )

    args = parser.parse_args()

    # Check for conflicting options
    if args.with_sold and args.can_be_sold:
        logger.error("--with-sold and --can-be-sold cannot be used together")
        return

    # Check for price-related option conflicts
    if args.no_cache and not args.with_prices:
        logger.warning("--no-cache has no effect without --with-prices")

    if args.cache_location and not args.with_prices:
        logger.warning("--cache-location has no effect without --with-prices")

    input_filename = args.input

    print("DeGiro Position Analyzer (FIFO)")
    print("=" * DISPLAY_WIDTH)

    # Parse transactions
    logger.info(f"Parsing transactions from {input_filename}...")
    try:
        transactions = parse_csv(input_filename)
    except FileNotFoundError as e:
        logger.error(str(e))
        return

    logger.info(f"Found {len(transactions)} valid transactions")

    # Validate ticker mappings for all stocks
    validate_all_ticker_mappings(transactions, args.ticker_mappings)

    # Process with FIFO logic
    logger.info("Processing positions with FIFO logic...")

    if args.can_be_sold:
        # Get current positions with optional price fetching
        current_positions, _ = process_positions(
            transactions,
            track_sold=False,
            fetch_prices=args.with_prices,
            use_cache=not args.no_cache,
            cache_location=args.cache_location,
            mappings_file=args.ticker_mappings
        )

        # Filter for tax-free positions
        tax_free_positions = filter_tax_free_positions(current_positions, years=TAX_FREE_YEARS_THRESHOLD)

        # Export to CSV if requested
        if args.export:
            export_tax_free_to_csv(tax_free_positions, args.export)
        else:
            # Print results to terminal
            print_tax_free_positions(tax_free_positions)
    else:
        # Regular mode with optional sold positions
        current_positions, sold_positions = process_positions(
            transactions,
            track_sold=args.with_sold,
            fetch_prices=args.with_prices,
            use_cache=not args.no_cache,
            cache_location=args.cache_location,
            mappings_file=args.ticker_mappings
        )

        # Export to CSV if requested
        if args.export:
            export_to_csv(current_positions, args.export, sold_positions)
        else:
            # Print results to terminal
            print_positions(current_positions, sold_positions)


if __name__ == '__main__':
    main()
