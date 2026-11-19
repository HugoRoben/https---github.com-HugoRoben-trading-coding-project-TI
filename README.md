# Local options research lab

Collect U.S. option quotes from Alpaca or Amsterdam ASML option executions from Euronext, inspect them in SQLite, and value them with a European Black–Scholes–Merton baseline. A separate synthetic dataset exercises the trading rule and cash accounting. All three workflows run locally.

## Where the code lives

Each Python module, class and function has a docstring. In VS Code, hover over a function name to read its inputs, units, return values and relevant timing or storage assumptions. In a notebook, for example, run `from modules.euronext.observations import trade_rows` and then `help(trade_rows)` to see how an option execution is matched to a share trade.

| Folder | Contents |
| --- | --- |
| [options_lab/](options_lab/) | The application entry point for the CLI and notebook, shared settings, contract and quote types, and validation. The old collector, model, and storage import paths forward to their implementations under `modules/`. |
| [modules/alpaca/](modules/alpaca/) | `retrieval.py` runs a collection session. `client.py` handles authentication, endpoints and request errors. `normalization.py` converts provider fields into contracts and quotes. |
| [modules/euronext/](modules/euronext/) | Retrieves delayed Amsterdam executions, identifies ASML options using ESMA reference data and pairs each option print with an earlier share trade. |
| [modules/models/](modules/models/) | `black_scholes.py` prices options, `strategies.py` defines the entry rule and fill costs, and `simulation.py` replays the trades. |
| [modules/storage_reporting/](modules/storage_reporting/) | `raw_captures.py` archives provider JSON. `database.py` stores quote snapshots, and `amsterdam.py` stores and values Dutch trade windows. `status.py` exposes read-only table previews. `reporting.py` builds USD valuations and simulated trade reports. |

To trace a collection, start with `iter_captures()` in [retrieval.py](modules/alpaca/retrieval.py). Each call to `fetch_capture()` gets the latest stock quote. On the first capture, `select_universe()` uses the midpoint to choose nearby strikes from the contract catalog. Each capture then fetches option quotes for that same set of symbols. The underlying, expiry window, strike band and interval are in [default.toml](config/default.toml).

The notebook calls the same [CLI](options_lab/cli.py) as the terminal. Its `save_market()` function normalizes each capture, archives the original response, and writes the snapshot and quality flags to SQLite. Earlier scripts can still import the collector, pricing, simulation, storage and reporting functions from their original `options_lab` modules.

## Run the offline example

From the root of a fresh clone, create a virtual environment with Python 3.11 or newer.

```sh
python3 -m venv .venv
```

In a new terminal session, activate the environment and run the offline example.

```sh
source .venv/bin/activate
python -m options_lab init-db
python -m options_lab demo
```

The CLI and its offline tests use the standard library. `init-db` creates the market database. `demo` creates the synthetic database and replay report. Notebook packages are listed in `notebooks/requirements.txt`.

| Path | What you can inspect |
| --- | --- |
| `data/options.sqlite3` | Market captures. Starts empty and fills when you run the collector. |
| `data/demo.sqlite3` | Five timestamped synthetic captures, two contracts, ten quote rows. |
| `reports/replay-…/valuations.csv` | Bid, ask, spot, model price, timestamps and quality flags for each observation. |
| `reports/replay-…/replay.json` | Entry signal, simulated fills, fees, cash and P&L. |
| `reports/replay-…/manifest.json` | Exact capture IDs, input hashes, feed labels, model version and settings. |
| `config/default.toml` | Universe, collection interval, annual model inputs, quote age limits and transaction costs. |

The demo prints the exact report directory. With the default settings, the signal occurs at 15:00 UTC. At the next capture the ask is $1.60. The simulated purchase costs $161.65 including slippage and the fee. Thirty minutes later the bid is $2.10 and the simulated sale returns $208.35. The difference is **$46.70**. Those prices were chosen to make the arithmetic checkable. Repeating the demo reuses its five captures. Run `python -m options_lab replay` to recompute results from SQLite after editing a model input or fee.

## Run the notebook in VS Code

On a fresh checkout, activate the environment and run `python -m pip install -r notebooks/requirements.txt`. Open [notebooks/project_status.ipynb](notebooks/project_status.ipynb), choose the project's `.venv` under **Select Kernel**, and click **Run All**.

The first cell controls collection and the number of rows to display. With `COLLECT_MARKET = True`, each run reads the Alpaca credentials from the project’s `.env` and requests one snapshot. Use `False` for offline inspection. If the request fails, the notebook shows the collection status and the captures already on disk.

The status table shows capture counts, quote timestamps and flagged observations for each database. Below it are the newest completed trades in the current synthetic replay, previews of all three SQLite tables, and per-share valuations from saved reports. The default fixture has one completed trade. Increasing `ROWS` shows additional trades when the replay contains them. You can explore the displayed data in the `recent_trades`, `snapshots`, `contracts`, `quotes` and `valuations` DataFrames.

To keep a run with its tables visible, save a copy as `notebooks/project_status.local.ipynb`. Git ignores `*.local.ipynb`. Before staging changes to the tracked notebook, use **Clear All Outputs** and save it.

## Test ASML during the Dutch trading day

Open [asml_amsterdam.ipynb](notebooks/asml_amsterdam.ipynb), select the project's `.venv` kernel, and choose **Run All**. This profile uses public market data and requires no API key. On regular trading days the ASL order book trades continuously from **09:01 to 17:30 Amsterdam time**. Euronext publishes its free trade files with about a 15-minute delay. **10:00–12:00 Amsterdam time** is a convenient test window before the U.S. regular session. [ASL contract specifications](https://live.euronext.com/en/product/stock-options/ASL-DAMS/contract-specification) · [Euronext delayed data](https://www.euronext.com/en/data/pricing-specs-agreements/mifid-ii-compliant-data)

The [Amsterdam settings](config/asml_amsterdam.toml) select ASML shares (ISIN `NL0010273215`) and the standard `ASL` option class. The default capture covers the last available hour of today's trades and expiries from 0 to 60 calendar days ahead. The same profile works from the terminal.

```sh
python -m options_lab --config config/asml_amsterdam.toml collect
python -m options_lab --config config/asml_amsterdam.toml value
```

The notebook shows capture counts, recent exchange executions in EUR, and a European Black–Scholes–Merton scenario for each eligible trade. ASL options allow early exercise. Each scenario uses the latest retained ASML share execution already published by the time the option traded. The report leaves the model value blank when that share price is missing or too old. Euronext's public files contain post-trade prices. Spread analysis and the fill simulator require bid/ask data. [Euronext trade files](https://marketdata.euronext.com/data-reporting-service/trades-file) · [ESMA instrument register](https://registers.esma.europa.eu/publication/searchRegister?core=esma_registers_firds)

Each retrieval creates a window in `data/amsterdam.sqlite3`. Its raw inputs are archived under `data/raw/euronext/`, and `value` writes `trades.csv` and `manifest.json` under `reports/amsterdam-…/`. Reports count each execution once within the selected window and exclude known cancellations and amendments. Overlapping windows can contain the same execution. Set `REFRESH = False` in the notebook to inspect the latest saved window offline.

## Inspect SQLite

SQLite stores each database in a local file. The `init-db` command opens the market database, creates its tables and index if needed, and preserves existing observations. Python opens the file directly for each run. For an interactive read-only session, use the SQLite shell already on this Mac.

```sh
sqlite3 -readonly -header -column data/demo.sqlite3
```

Inside the SQLite shell, run the following. The timestamps let you distinguish the age of the market observation from the time the collector could use it. The third put quote deliberately repeats an older observation.

```sql
.tables
.schema quotes
SELECT s.capture_id, c.symbol, s.retrieved_at, q.quote_at, q.bid, q.ask, q.ingest_flags
FROM snapshots AS s
JOIN quotes AS q USING (capture_id)
JOIN contracts AS c USING (terms_id)
ORDER BY s.retrieved_at, c.symbol;
.quit
```

One snapshot represents one completed retrieval. Each quote joins its snapshot to the contract terms observed at the time. A corrected multiplier creates a new version of those terms. Identical market quotes can appear in separate captures. Reimporting the same capture adds zero rows. The collector publishes all rows for one capture in a single transaction.

## Collect your first two market snapshots

1. Use a key ID and secret from the same Alpaca account. A paper account is sufficient. Stock and option quotes use the market-data host for both paper and live credentials. The collector only issues GET requests for quotes and contract metadata. [Alpaca authentication](https://docs.alpaca.markets/us/docs/authentication)
2. The project's `.env` supplies the two API credentials. On a fresh checkout, create it with `(umask 077 && cp -n .env.example .env)`, then fill in the values after the two `export` assignments. Git ignores this file.
3. During a regular US trading session, load the keys into this terminal, collect twice and value the latest completed capture.

```sh
source .env
python -m options_lab collect --count 2
python -m options_lab value
```

The first capture runs immediately. Keep the terminal open and the Mac awake for the second, 15 minutes after the first completes. Each completed capture prints its ID, quote count, flagged count and raw JSON path. A single `collect` takes one snapshot. The app stops with an error on an authentication, feed-access or request failure. Prior completed captures remain in SQLite.

For contract metadata, the collector selects the live catalog for an `AK` key ID and otherwise defaults to the paper catalog. Alpaca treats these prefixes as hints. If your dashboard identifies a different environment, set `APCA_API_BASE_URL` in `.env` to `https://paper-api.alpaca.markets` or `https://api.alpaca.markets` to override the choice. Use `export` if you also source the file from Terminal. [Alpaca key environments](https://alpaca.markets/learn/api-key-security-best-practices-for-alpaca-builders)

On a request failure, the notebook and CLI show the endpoint and cause. A DNS failure means the hostname lookup failed before authentication. HTTP 401 means Alpaca received the request and rejected authentication. For HTTP 403, check access to the specific endpoint and feed named in the request.

The defaults select **AAPL**, the earliest listed expiry 14–28 calendar days out, and the three listed strikes closest to the IEX stock midpoint inside a ±5% band. Available calls and puts at those strikes make up the universe. It stays fixed for both captures. You can pass an exact listed date using `collect --expiry YYYY-MM-DD`. The collector requests Alpaca's **indicative** option feed, whose quotes are modified. Treat these prices as observations for pipeline and model research. [Option feed definitions](https://docs.alpaca.markets/us/docs/historical-option-data) · [Contract lookup](https://docs.alpaca.markets/us/reference/get-options-contracts) · [Option quotes](https://docs.alpaca.markets/us/reference/optionlatestquotes) · [Underlying quotes](https://docs.alpaca.markets/us/reference/stocklatestquotesingle-1)

Check how much new information the two requests returned. This query runs directly from Terminal.

```sh
sqlite3 -readonly -header -column data/options.sqlite3 "
  SELECT c.symbol, COUNT(*) AS captures, COUNT(DISTINCT q.quote_at) AS distinct_quote_times,
         SUM(q.ingest_flags <> '[]') AS flagged
  FROM quotes AS q JOIN contracts AS c USING (terms_id)
  GROUP BY c.symbol ORDER BY c.symbol;"
```

After those two captures, these commands reimport the first capture and reproduce its valuation.

```sh
capture_id=$(sqlite3 -readonly data/options.sqlite3 'SELECT capture_id FROM snapshots ORDER BY retrieved_at, capture_id LIMIT 1;')
raw_ref=$(sqlite3 -readonly data/options.sqlite3 'SELECT raw_ref FROM snapshots ORDER BY retrieved_at, capture_id LIMIT 1;')
python -m options_lab import-capture "data/$raw_ref"
python -m options_lab value --capture "$capture_id"
```

The raw envelope preserves the provider response fields, the contract lookup pages, feed choices and selected symbols. Stored timestamps are UTC with microsecond resolution. The original provider timestamp strings are in the raw JSON. Raw references resolve from the data directory for market captures and the project root for the synthetic fixture.

## Model and simulation conventions

- Premiums and slippage are USD per share. Cash accounting uses the observed contract multiplier, one fee per contract on each side and cent rounding on each cash flow. An absent multiplier stays unknown. The provider's deliverable-size field has a distinct meaning.
- Valuations use ACT/365F from retrieval to expiry. The default annual scenarios are 25% volatility, 4% continuously compounded interest and 0.5% continuous dividend yield. The model omits early exercise and discrete dividends. The live adapter receives an expiry date and assumes 16:00 New York time on that date, including on early-close dates. The CSV flags this time assumption. [OIC pricing overview](https://www.optionseducation.org/advancedconcepts/black-scholes-formula)
- Quote and underlying timestamps must be at or before retrieval. The default maximum age is 300 seconds and maximum timestamp difference is 60 seconds. A timestamp, price or metadata problem is recorded in the flags. A recent valid stock observation can still produce a per-share model value when an option quote is missing. Flagged rows have a blank model-minus-ask comparison.
- The replay processes captures in retrieval order. With sufficient cash, it signals one call when its model price exceeds the ask by more than the buffer. Ties are resolved by symbol after ranking by model-minus-ask. A fill needs a new, valid quote timestamped after the signal. The simulator buys at ask plus slippage and checks cash again. The holding clock starts at that fill. A sale uses the next eligible bid at or after the deadline, less slippage and the fee.
- The synthetic session has a predefined closing time. A valid closing quote can liquidate early. A missing exit leaves the position open with a flagged valuation. New entries require a planned exit before contract expiry. The simulator assumes one contract can fill and ignores queue position and depth. The fixture measures execution mechanics only.

## Verification and version control

```sh
python -m unittest discover -s tests -v
```

Tests cover pricing references and parity, duplicate imports and rollback, stale and missing quotes, new observations after a signal, capital constraints, hand-calculated P&L, and two collector intervals using mocked provider replies.

The GitHub repository uses `main`. A clone already has its `origin` remote. To check the upstream branch and review the staged changes, run the following from the project root.

```sh
git status --short --branch
git diff --cached --stat
```

The next milestone is two successful external captures, a check of their timestamps and flags, and a valuation pinned to one capture. The [roadmap](docs/ROADMAP.md) and [architecture notes](docs/ARCHITECTURE.md) describe later stages.
