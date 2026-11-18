# Proposed Mac mini / MacBook architecture

Design date: 5 November 2026. This records the proposed deployment; no application, network service, database, or scheduled job has been installed by creating this document.

## One repository, two roles

Keep the project as one Python package with independent collection and research entry points. Both roles first run on the MacBook using local SQLite. Deployment to two machines is a later milestone within the same project, not a requirement for the 5–8-hour first week.

| Mac mini: collection and storage | MacBook: research and computation |
| --- | --- |
| Scheduled provider requests | Initiates access to the mini |
| Validation, metadata and raw captures | Downloads a selected, bounded dataset |
| Database writes and collection logs | Keeps fixed local copies for offline work |
| Later PostgreSQL administration and backups | Pricing, simulations, reports and local LLM inference |

The mini continues collecting with the MacBook asleep, disconnected, or powered off. The mini needs its own internet connection to collect external data. Record collection failures and actual data gaps; do not invent observations for missed intervals. MacBook results stay local initially; central result storage can be added as a separate feature without modifying raw observations.

## Data flow

```text
Market-data provider
    |
    v
Mac mini: collector -> validation -> database / raw captures
                                       |
                     MacBook initiates authenticated data pull
                                       |
                                       v
MacBook: fixed local dataset -> pricing / simulation / LLM -> reports
```

The mini performs ingestion work and serves requested data. Model calculations and simulations run on the MacBook against a fixed local dataset, rather than repeatedly transferring individual records during a compute loop. This preserves reproducibility and lets a running computation survive loss of the network connection.

## Connection and availability logic

Use a configured mini address, preferably a router-reserved LAN IP or a working local hostname. A Bonjour/mDNS .local name is an option if configured for the chosen OS. Wired Ethernet on the mini and Wi-Fi on the MacBook can communicate through the same router if the network permits it; a shared Wi-Fi name is neither the access test nor the authentication mechanism.

The MacBook initiates the connection. A proposed client flow is:

1. On command startup, attempt authenticated access to the known mini with short, separately bounded SSH/connection/query timeouts.
2. Query data availability, including which collection batches are complete, last successful collection, and quote-time coverage.
3. Download the requested missing completed batches to temporary local storage. Validate identifiers and completeness before publishing a new local dataset.
4. Record the completed batch identifiers, coverage and dataset version, then update local sync state only after the data is saved successfully.
5. If a background sync command is enabled later, retry transient connection failures periodically while the MacBook is awake, for example every 60 seconds initially with a bounded backoff. Check again after the process resumes or restarts. An asleep or powered-off MacBook cannot poll; catch up at its next opportunity.

Treat temporary unreachability as an offline state. Invalid credentials, failed host verification, incompatible schemas and invalid transfers should produce distinct actionable errors. Keep connection status, last successful transfer, last successful collection and latest market quote time separate. A reachable database can contain stale data; a successful transfer does not prove that the market observations are current.

Previously downloaded datasets remain available offline, with coverage and age visible. If no suitable local data exists, wait for a connection or fail the research command clearly. Do not silently substitute fixtures for real data. Make automatic computation an explicit later option; being connected need not trigger an expensive backtest or LLM job.

## Database and transfer choice

Use SQLite locally during the first milestone. When deploying the split for database-management practice, PostgreSQL on the mini is the recommended next step. Access it from the MacBook through an SSH tunnel with verified host identity and normal database authentication, using a read-only research role. The collector uses a separate writer role. PostgreSQL can remain bound to loopback on the mini, with the tunnel carrying database traffic; no public database exposure or separate web application is needed for this design.

An earlier SQLite-based mini deployment is also possible: run an export query or supported backup on the mini and transfer the completed export over SSH. Do not open a live SQLite file from a MacBook-mounted network share, or copy only the live database file while collection is writing. Reads and writes to that SQLite database should occur on the mini. The MacBook consumes a consistent export, not a second writable copy of the source database.

For small datasets, a simple CSV/JSON export with a manifest is adequate. Columnar formats can follow when dataset size makes them useful. Export only the requested universe/time range. The local cache is a research input, not multi-master database replication and not a replacement for server backups.

## Sync and experiment correctness

- Publish each collection batch only when it is complete, using transactions and stable collection/contract identifiers. Define completion relative to the requested universe, including any expected pagination.
- Track completed batch IDs and deduplicate repeated transfers. Do not use market quote timestamps as the sole sync cursor: newly ingested records can have older quote timestamps. A future sequence-based cursor needs explicit commit-order guarantees if multiple writers are introduced.
- Publish local datasets atomically. Interrupted transfers must leave the previous usable dataset and checkpoint intact, and retries must not duplicate observations.
- Pin every research run to a saved dataset version, configuration and model version. Ongoing collection and later syncs must not mutate that run's inputs.
- Keep chronological replay and information-availability rules separate from ingestion/transfer ordering.

## Deployment acceptance checks

1. The mini collects and persists data while the MacBook is off the network.
2. The MacBook can authenticate and retrieve a bounded dataset when access is available.
3. A disconnected MacBook can finish a computation against its saved dataset.
4. An interrupted download preserves the old dataset, then succeeds on retry without missing or duplicated completed batches.
5. Connection status and data freshness can differ and are reported separately.
6. Stopping or failing the MacBook LLM does not interrupt collection or deterministic research calculations.

## References

- [SQLite: network access caveats](https://sqlite.org/useovernet.html)
- [PostgreSQL: SSH tunnels](https://www.postgresql.org/docs/current/ssh-tunnels.html)
- [PostgreSQL: connection settings and timeouts](https://www.postgresql.org/docs/current/libpq-connect.html)
