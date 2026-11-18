# Project instructions

## Purpose and sequence

Build an educational options research and trading-simulation system in Python. It should periodically collect options and underlying data, persist observations, price contracts with Black–Scholes as the initial baseline, and evaluate explicit trading rules through reproducible simulations.

The owner has multiple years of intensive Python experience. Focus explanations on quantitative assumptions, market-data limitations, database design, and engineering trade-offs. Explain unfamiliar finance or infrastructure concepts when relevant; skip introductory Python teaching.

Deliver a working local pipeline first. The intended later deployment splits responsibilities: an inexpensive Mac mini collects and stores data independently, while the more powerful MacBook pulls datasets and runs pricing, simulations, reports, and the local LLM. Use the mini to learn database administration and local-server operations. Expand models and optimize measured bottlenecks using one of C, C++, or Rust after the baseline works. Keep hardware and infrastructure costs low. Do not build later stages before they serve a working milestone.

## Working approach

- Obtain the owner's explicit approval for each publication of project code or artifacts. This includes pushing branches or tags, opening pull requests, and publishing releases.
- Work in small, runnable increments. Keep implementation within the requested milestone; future ideas belong in the roadmap.
- Make routine implementation decisions autonomously, explain material trade-offs, and ask only when missing information changes scope or correctness.
- Challenge flawed financial or statistical reasoning directly. State assumptions and uncertainty rather than presenting model output as fact.
- Prefer a small, understandable design. Avoid speculative abstractions, infrastructure, and dependencies.
- Keep the README current with actual setup and run commands. For implementation changes, report the resulting behavior, relevant verification, and remaining limitations.
- The first-week budget is 5–8 hours; use docs/ROADMAP.md for scope and acceptance criteria.

## Research and simulation correctness

- Keep real observations, synthetic fixtures, assumptions, model values, signals, simulated fills, and realized outcomes distinguishable.
- Record the provider/feed, retrieval time, quote time, underlying observation time, currency, expiry, option type, strike, and contract multiplier. Preserve exercise style when known and flag unknown metadata. Use UTC internally and explicit units for rates, volatility, and time to expiry.
- Treat Black–Scholes as a European-exercise baseline; disclose American-exercise and dividend approximations. Record the interest-rate, dividend, and volatility assumptions used for each run.
- Do not infer volatility from a quote and then call the same quote mispriced merely because it is compared with that fitted model value. Keep volatility-estimation inputs and windows explicit.
- Use only information available at the simulated decision time. Process replay data chronologically and make order/fill timing explicit.
- Include bid/ask spreads, contract multipliers, transaction costs, capital constraints, and an explicit exit rule. Flag stale, missing, crossed, or unsynchronized observations.
- A synthetic replay demonstrates software behavior; a snapshot comparison does not establish historical performance or a profitable trading edge.
- The initial simulator uses long options, one open position at a time, and closes before expiry. Exercise, assignment, uncovered selling, and live execution are outside this milestone.

## Architecture and verification

- Keep provider access, validation, persistence, pricing, strategy rules, simulation, and reporting separate. Pricing functions should have no network or database side effects.
- Start with SQLite and straightforward SQL. Keep database access localized so a later PostgreSQL migration is manageable; do not build a general database framework in advance.
- Keep one repository with independently runnable collection and research roles. For the two-machine phase, follow docs/ARCHITECTURE.md: MacBook-initiated authenticated data access, bounded retries, completed snapshot batches, and fixed local datasets for offline computation. Collection must continue when the MacBook is unavailable. Keep SQLite files local to their host; use PostgreSQL or a consistent server-side export for network access.
- Store configuration outside business logic, secrets in environment variables, and local captures/databases/generated reports outside version control. Commit small synthetic fixtures and a dependency lockfile.
- Use deterministic fixtures and focused tests for pricing references and identities, storage round trips and duplicate imports, and simulation accounting/timing. Routine tests should run offline.
- Keep commands and paths portable between the current Mac and a future Mac mini. Add unattended scheduling, backups, restore exercises, and database administration when that phase begins.
- Use a future local LLM first to explain saved results or answer questions through constrained read-only data access. Pricing, risk calculations, fills, and P&L remain deterministic, with a working path when the LLM is unavailable.
- Add compiled code only after profiling a correct, reproducible workload. Preserve a Python reference implementation and verify numerical agreement across the boundary.
