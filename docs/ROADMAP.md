# Options research project: structure and roadmap

Original plan dated 5 November 2026. The [README](../README.md) has the current MacBook setup, commands and schema walkthrough.

The local SQLite pipeline, European pricing model, synthetic replay and reports are implemented. The supervised Alpaca collector has been tested against mocked replies, including two intervals and pagination. The first authenticated capture and a second capture during the same session are still pending. The starter package lives at the repository root so it can run directly with Python 3.11+. Its scalar normal CDF and offline tests use the standard library.

The owner is an experienced Python programmer. The first week should concentrate on options modelling, data provenance, persistence, and simulation semantics rather than language fundamentals.

The intended deployment now separates an inexpensive Mac mini for collection/storage from the more powerful MacBook for computation and local LLM inference. See [ARCHITECTURE.md](ARCHITECTURE.md). Develop the first milestone on the MacBook with local SQLite; adding network access and deploying to the mini is a subsequent milestone. Preserve the 5–8-hour first-week scope.

## First working milestone

One underlying, one expiry, a small strike range, one pricing model, and one long-option strategy:

```text
provider snapshot -> validate -> SQLite -> Black–Scholes -> valuation report
                                |
timestamped replay fixtures -----+-> strategy -> simulated fills -> P&L report
```

Begin with one liquid underlying that the selected provider supports. US equity/ETF options are a working assumption, not a settled market choice. If those contracts have American exercise, disclose the European-model approximation. Prefer a usable data source over spending the first week finding an ideal instrument.

Collect snapshots at a configurable modest interval, such as 15 minutes, during a short supervised run. Respect the provider's feed delays and limits; a new request does not guarantee a new quote. Unattended market-calendar scheduling belongs to the operational phase. This plan does not create a Codex automation.

Use deterministic, explicitly synthetic multi-timestamp fixtures to validate the simulator immediately. Separately accumulate real snapshots for future evaluation. A current options chain is not a historical backtest, and a few days of observations will not establish a reliable trading edge.

## Original folder proposal

The sketch below records the original proposal. For the implemented folders and the path through the Alpaca collector, see [Where the code lives](../README.md#where-the-code-lives).

```text
trading project/
├── AGENTS.md                      # Persistent project instructions; created
├── README.md                      # Setup, commands, limitations
├── pyproject.toml                 # Package, dependencies, tool settings
├── uv.lock                        # Reproducible dependency resolution
├── .gitignore
├── .env.example                   # Variable names only; never credentials
├── config/
│   └── default.toml               # Universe, interval, assumptions, costs
├── src/
│   └── options_lab/
│       ├── __init__.py
│       ├── cli.py                 # collect, value, replay, demo
│       ├── config.py
│       ├── domain.py              # Contract, quote, model-input records
│       ├── ingestion.py           # First provider adapter + normalization
│       ├── validation.py          # Quote and metadata checks
│       ├── storage.py             # SQLite queries and transactions
│       ├── schema.sql
│       ├── pricing/
│       │   ├── __init__.py
│       │   └── black_scholes.py   # Pure call/put valuation functions
│       ├── strategies.py          # First long-call rule
│       ├── simulation.py          # Fill timing, cash, positions, costs
│       └── reporting.py           # Valuation table, trades, P&L
├── tests/
│   ├── fixtures/                  # Small synthetic data, committed
│   ├── test_pricing.py
│   ├── test_storage.py
│   └── test_simulation.py
├── notebooks/                     # Optional exploration
├── data/                          # Ignored local files
│   ├── raw/                       # Original provider responses
│   └── options.sqlite3
├── reports/                       # Ignored generated run outputs
└── docs/
    ├── ARCHITECTURE.md            # Mini/MacBook deployment proposal; created
    └── ROADMAP.md                 # This document; created
```

Server, LLM, native code, deployment files and database migrations are planned for later phases.

## Initial tooling

- Python with uv and pyproject.toml for environment and dependency management.
- SciPy for the normal distribution used by the pricing model; use array operations when useful without introducing a separate performance project.
- Standard-library sqlite3 and explicit SQL to expose the database concepts directly.
- A single provider client or HTTP library chosen with the source; avoid multiple overlapping access libraries.
- pytest for focused offline verification, Ruff for formatting and linting. Add notebook/plotting dependencies only when needed.
- A CLI and CSV/JSON reports for the first milestone.

SQLite is a disk-based database without a separate database server process, so it lets the first milestone teach tables, keys, joins, transactions, and indexes with little operational setup. PostgreSQL later adds the server-administration learning objective.

Sources: [uv](https://docs.astral.sh/uv/), [SciPy statistics](https://docs.scipy.org/doc/scipy/reference/stats.html), [Python sqlite3](https://docs.python.org/3/library/sqlite3.html), [pytest](https://docs.pytest.org/en/stable/), and [Ruff](https://docs.astral.sh/ruff/).

## Data source decision

Spend at most 45 minutes of the integration session validating one provider: account access, a successful request, required metadata, bid/ask and timestamps, rate limits, and permitted storage/use. Keep the adapter replaceable.

Alpaca is a candidate to check, not an assumed available account or a commitment to purchase data. Its documented free indicative feed contains modified indicative quotes; OPRA access requires a subscription. Label that feed correctly in every report. It is useful for building plumbing, but do not treat indicative quotes as executable market prices or use them to claim an edge. Its documentation currently describes historical options data beginning in February 2024; endpoint coverage and account entitlements still need validation.

Source: [Alpaca historical option data and feed descriptions](https://docs.alpaca.markets/us/docs/historical-option-data).

If source access blocks progress, complete the pipeline against synthetic fixtures and record live collection as unfinished. Do not fabricate a source, quote timestamps, or missing metadata. The full milestone still requires a successful external-data collection run.

## Week one: 6.5-hour target, 8-hour ceiling

Use five sessions over the next seven days; they do not need to be consecutive calendar days. These are time budgets, not guaranteed completion estimates.

| Session | Budget | Deliverable and verification |
| --- | ---: | --- |
| 1. Scope and foundation | 0.5 h | Choose one universe; establish package/config/CLI shape and dependency management. Specify units, identifiers, quote timestamps, and model inputs before collecting data. |
| 2. First ingestion and SQLite | 2 h | Integrate one source, retain a raw capture, normalize a snapshot, and persist contracts, snapshots, and quotes. Verify a database round trip and that reimporting the same capture does not duplicate it. Timebox provider-access investigation to 45 minutes within this session. |
| 3. Pricing and valuation report | 1.25 h | Implement call/put Black–Scholes with a continuous dividend-yield input, explicit annualized volatility/rate/time conventions, and expiry/zero-volatility handling. Verify an independent reference value and put–call parity. Report bid/ask, model value, input assumptions, and quality flags. |
| 4. One strategy and replay | 1.5 h | Use chronological synthetic fixtures to simulate one long call at a time. Record signals, next-observation fills, cash, position size, costs, and realized/unrealized P&L. Verify a hand-calculated trade and capital/timing constraints. |
| 5. Integration and periodic collection | 1.25 h | Connect documented collect/value/replay commands; provide a one-command offline demo. Run two supervised collection intervals, query both captures, and confirm a reproducible report with its input/config record. Finish concise README instructions. |
| Contingency | Up to 1.5 h | Resolve provider, timestamp, or accounting issues; close gaps in the pipeline before adding features. |

The target is 6.5 hours plus up to 1.5 hours of contingency, for 8 hours maximum. At 5 hours, stop after sessions 1–3 and about 1.25 hours of session 4: aim for stored observations, a valuation report, and a basic verified replay. Finish integration and periodic operation next; do not call that smaller result the complete scheduled system.

### Initial strategy specification

Use an explicit research rule rather than a discretionary trade: with no open position, consider a call only if its model value exceeds its ask by a configurable cost buffer and its data passes validation. Take at most one contract if cash covers premium times the actual multiplier plus fees. Fixed volatility is an explicit first-run scenario assumption, not an estimated fair value or validated source of alpha.

A signal at time t can first fill at the next eligible observation's ask, subject to valid data and available cash. Use a fixed holding period and sell at a subsequent eligible bid, with fees and an explicit slippage convention. Close before expiry. At the end of a fixture, liquidate only when a valid eligible quote exists; otherwise report the open position and a flagged valuation. No same-observation look-ahead fills and no invented exit quotes.

The first replay exercises mechanics. Add an actual trailing volatility estimate, a baseline strategy, sensitivity checks, and out-of-sample evaluation only after those mechanics are reliable. Fitting implied volatility to a quote and then repricing that same quote is not independent evidence of mispricing.

### Minimal persistence design

- contracts: stable identifier, underlying, expiry, strike, option type, currency, multiplier, exercise style or an explicit unknown flag.
- snapshots: collection identifier, provider/feed, retrieval time, raw-capture reference, and collection status.
- quotes: contract/snapshot relation, source quote time, bid/ask, underlying price and its observation time, and quality flags. Add a uniqueness constraint for a contract within one capture.

Preserve event time and retrieval time separately. A later capture can legitimately contain the same source quote; that is different from importing the identical capture twice. Use transactions so a snapshot is either stored consistently or marked unsuccessful. Record model assumptions, configuration, and data identifiers with each generated report; persistent run/trade tables can follow when querying experiments warrants them.

### Full milestone acceptance criteria

1. An offline command runs synthetic input through persistence, pricing, and simulation to a report.
2. One external provider capture is saved with its source/feed and timestamps, with missing metadata identified explicitly.
3. Reimporting a capture is idempotent; independent collection attempts remain distinguishable.
4. A short collector run saves observations from two intervals without manual edits.
5. Focused tests cover pricing reference/parity, persistence, and a hand-checked trade including costs and contract multiplier.
6. Reports distinguish synthetic mechanics, indicative data if used, real observations, modelling assumptions, and simulated outcomes.

## Later phases and entry conditions

1. Reliable research baseline: collect and inspect more real observations, improve stale/invalid quote checks, estimate volatility using past information, and add a second strategy plus a meaningful benchmark. Obtain suitable historical quote data before claiming historical strategy performance.
2. Mac mini and database operations: deploy collection/storage to the mini and keep pricing, simulation, and LLM work on the MacBook. Use a scheduler appropriate to the mini's operating system, such as systemd on Linux or launchd on macOS. Introduce PostgreSQL on the mini with MacBook-initiated access through SSH, a read-only research role, and local dataset exports for offline work. Practise schema migrations, roles, indexes, query plans, and tested backup/restore. Verify that collection continues when the MacBook disconnects and that interrupted transfers resume without duplicated or missing completed batches. See ARCHITECTURE.md. A separate HTTP API is optional; PostgreSQL already provides a database service.
3. Expanded models: add Greeks and implied-volatility inversion, then a binomial model to address American exercise. Add volatility surfaces, Monte Carlo, or stochastic-volatility models when a specific research question warrants them. Compare new models with known references and the original baseline. The options education reference below describes early exercise as a reason to use binomial modelling for American-style equity options.
4. Local LLM: run a model locally on the more powerful MacBook through a service such as Ollama. First feature: give it a saved run's computed metrics, assumptions, and data-quality flags and ask for an explanation grounded in those inputs. A later feature can answer database questions via constrained read-only tools. Keep pricing, risk, fills, and P&L outside generated model text. Select the model after the MacBook's memory and required latency are known; the LLM remains optional to core operation, and the mini's collector never depends on it.
5. Compiled extension: profile a stable workload. Select one actual bottleneck, then one language. Implement one narrow extension behind the Python interface, benchmark the full workload including conversion overhead, and compare numerical outputs with the Python reference. Data retrieval or database latency may dominate before numerical code does.

Sources: [OIC on Black–Scholes and American exercise](https://www.optionseducation.org/advancedconcepts/black-scholes-formula), [Ollama local API](https://docs.ollama.com/api/introduction).
