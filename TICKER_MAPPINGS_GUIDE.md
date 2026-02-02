# Ticker Mappings Guide

The `ticker_mappings.csv` file maps ISIN identifiers to stock ticker symbols for price fetching.

## File Location

- **Default**: `ticker_mappings.csv` (in the project directory)
- **Custom**: Use `--ticker-mappings PATH` to specify a different location

## File Format

The file is a simple CSV with three columns:

```csv
ISIN,Ticker,Description
US00206R1023,T,AT&T
IE00B4L5Y983,IWDA.AS,iShares MSCI World
US9344231041,,WARNER BROS DISCOVERY INC
```

### Columns

1. **ISIN**: The ISIN identifier (required)
2. **Ticker**: The ticker symbol for yfinance (optional - leave empty if unknown)
3. **Description**: Human-readable description of the security (helpful for identification)

## How It Works

### 1. First Run

On first run with `--with-prices`, the script:
- Creates `ticker_mappings.csv` with default mappings for common stocks
- Adds any unknown ISINs with **empty ticker fields**
- Logs warnings for each unknown ticker

Example log output:
```
WARNING: Ticker not found for 908 DEVICES INC (ISIN: US65443P1021) - added to ticker_mappings.csv for manual completion
```

### 2. Manual Completion

Open `ticker_mappings.csv` in any text editor or spreadsheet application and fill in the missing tickers:

**Before:**
```csv
US9344231041,,WARNER BROS DISCOVERY INC
US01609W1027,,ADR ON ALIBABA GROUP HOLDING LTD
```

**After:**
```csv
US9344231041,WBD,WARNER BROS DISCOVERY INC
US01609W1027,BABA,ADR ON ALIBABA GROUP HOLDING LTD
```

### 3. Next Run

On the next run, the script will:
- Load your updated mappings
- Fetch prices for the newly mapped tickers
- Continue adding any new unknown ISINs with empty fields

## Finding Ticker Symbols

### For US Stocks
- Search on [Yahoo Finance](https://finance.yahoo.com/)
- Example: "Warner Bros Discovery" → ticker is `WBD`

### For European Stocks/ETFs
You need to include the exchange suffix:

| Exchange | Suffix | Example |
|----------|--------|---------|
| Amsterdam | .AS | IWDA.AS |
| London | .L | BA.L |
| Frankfurt/Xetra | .DE | DBK.DE |
| Paris | .PA | AIR.PA |
| Vienna | .VI | EBS.VI |
| Prague | .PR | CEZ.PR |
| Stockholm | .ST | SAAB-B.ST |

**Example:**
- iShares MSCI World on Amsterdam: `IWDA.AS`
- BAE Systems on London: `BA.L`

### Tips for Finding Tickers

1. **Search by ISIN**: Google "ISIN [your-ISIN]" to find the stock name
2. **Check Yahoo Finance**: Search for the stock name on finance.yahoo.com
3. **Verify the exchange**: Make sure you use the correct exchange suffix
4. **Test it**: Run with `--with-prices --no-cache` to verify the ticker works

## Common Issues

### Ticker Works But Shows "API Error"

The ticker might be correct but the stock could be:
- Delisted
- Has no recent trading data
- Uses a different exchange than expected

Try different exchange suffixes or check if the stock is still actively traded.

### Multiple Tickers for Same Stock

Some stocks trade on multiple exchanges. Choose the one with:
- Most liquidity (usually the primary listing)
- Currency you prefer (affects conversion accuracy)

Example: A European stock might trade on both Amsterdam (.AS) and Frankfurt (.DE)

## File Maintenance

### Keep It Clean

The file is automatically sorted by ISIN. Feel free to:
- Add comments in the Description column
- Remove ISINs you no longer hold (optional)
- Update tickers if they change

### Version Control

Consider version controlling this file if you:
- Manage multiple portfolios
- Want to track ticker changes over time
- Share configurations across machines

## Examples

### Complete Mapping Example

```csv
ISIN,Ticker,Description
AT0000652011,EBS.VI,Erste Group (Vienna)
CH0454664001,21XB.PA,21Shares Bitcoin ETP
GB0002634946,BA.L,BAE Systems (London)
IE00B4L5Y983,IWDA.AS,iShares MSCI World
US00206R1023,T,AT&T
US01609W1027,BABA,Alibaba ADR
US88160R1014,TSLA,Tesla
US9344231041,WBD,Warner Bros Discovery
```

### Empty Mappings Waiting for User Input

```csv
ISIN,Ticker,Description
BMG0171K1018,,ALIBABA HEALTH INFORMATION TECHNOLOGY LTD
US65443P1021,,908 DEVICES INC
NL0010391108,,PHOTON ENERGY NV
```

## Advanced Usage

### Custom Mappings File

```bash
# Use a different mappings file
python analyze_positions.py --with-prices --ticker-mappings /path/to/my_tickers.csv
```

### Per-Portfolio Mappings

```bash
# Portfolio 1
python analyze_positions.py --input portfolio1.csv --ticker-mappings tickers1.csv --with-prices

# Portfolio 2
python analyze_positions.py --input portfolio2.csv --ticker-mappings tickers2.csv --with-prices
```

## Need Help?

If you can't find a ticker:
1. Search the stock name + "yahoo finance ticker"
2. Try the ISIN on financial websites
3. Check if the stock is still actively traded
4. Leave it empty - the script will continue to work with other stocks

The price fetching is designed to be resilient - unknown tickers won't break the analysis!
