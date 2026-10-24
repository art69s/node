# Gold & Dollar Market Check

`market_check.py` fetches the current price of gold and shows how the US dollar is doing against world currencies.

It uses only the Python standard library (Python 3.9+) and free data sources that need no API key:

| Data | Source |
| --- | --- |
| Gold price | Yahoo Finance COMEX gold futures (`GC=F`), falls back to gold-api.com spot |
| US Dollar Index (DXY) | Yahoo Finance (`DX-Y.NYB`) |
| Exchange rates and history | Frankfurter (European Central Bank rates), falls back to open.er-api.com |

## Usage

```bash
python3 market_check.py                                  # full report, 30-day trend
python3 market_check.py --days 7                         # 7-day trend
python3 market_check.py --currencies EUR,JPY,GBP,CNY     # choose currencies
python3 market_check.py --json                           # machine-readable output
```

The report shows:

- **Gold**: price per troy ounce and per gram in USD, with 1-day and period change
- **DXY**: the dollar against a basket of six major currencies
- **USD vs. each currency**: rate, 1-day and period change (▲ means the dollar got stronger), and the gold price in that currency
- **Verdict**: how many currencies the dollar gained against over the period
