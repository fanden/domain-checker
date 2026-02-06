# domain-checker

A CLI tool that checks domain name availability across all IANA top-level domains. Give it one or more words and it checks every TLD combination (e.g. `milk.com`, `milk.net`, `milk.org`, ...) using a three-tier lookup strategy: DNS, RDAP, and WHOIS.

Checking ~1,500 TLDs is a long-running task, so the tool saves progress automatically and supports resuming interrupted runs.

## How it works

For each `word.tld` combination, the checker runs a pipeline:

1. **DNS lookup** — Queries for NS records. If nameservers exist, the domain is registered. If the response is NXDOMAIN, the domain is likely available. This handles ~90% of checks in milliseconds with no rate limits.

2. **RDAP query** — For domains that DNS says might be available, the tool queries the TLD's own registry RDAP server (using [IANA's bootstrap data](https://data.iana.org/rdap/dns.json) to map each TLD to its server). An HTTP 404 confirms the domain is available; 200 means registered. Since each registry runs its own server, requests are distributed across hundreds of different hosts.

3. **WHOIS fallback** — For TLDs without RDAP support, a raw TCP query to the TLD's WHOIS server on port 43. The response text is pattern-matched against known "not found" / "registered" strings.

The TLD list is pulled from [IANA's authoritative source](https://data.iana.org/TLD/tlds-alpha-by-domain.txt) and cached locally.

## Setup

Requires Python 3.11+.

```
pip install -e .
```

This installs three dependencies: `dnspython`, `httpx`, and `rich`.

## Usage

### Basic check

```
domain-checker milk cookies
```

Checks `milk` and `cookies` against all ~1,500 TLDs (~3,000 combinations total).

### Resume an interrupted run

Progress is saved automatically every 50 checks and on Ctrl+C. To continue:

```
domain-checker milk cookies --resume
```

If a state file exists and you don't pass `--resume` or `--no-resume`, you'll be prompted.

### Check specific TLDs

```
domain-checker milk --tlds com net org io dev xyz
```

### Show only available domains

```
domain-checker milk --filter available
```

### Export results

```
domain-checker milk --format csv -o results.csv
domain-checker milk --format json -o results.json
```

### Fast DNS-only mode

Skips RDAP and WHOIS confirmation. Faster but may have false positives for available domains (a domain could be registered but have no DNS records).

```
domain-checker milk --dns-only
```

### Verbose mode

Prints each available domain as it's found:

```
domain-checker milk -v
```

### All options

```
domain-checker [OPTIONS] WORD [WORD ...]

Positional:
  WORD                     Words to check

Options:
  -o, --output FILE        Write results to file
  -f, --format FMT         Output format: table, csv, json (default: table)
  --filter STATUS          Filter: all, available, registered (default: all)
  --resume                 Resume a previous run
  --no-resume              Start fresh, ignore existing state
  --tlds TLD [TLD ...]     Only check these TLDs
  --exclude-tlds TLD ...   Skip these TLDs
  --include-idn            Include internationalized (xn--) TLDs
  --dns-only               DNS check only, skip RDAP/WHOIS
  --no-whois               Skip WHOIS, use DNS + RDAP only
  --nameservers NS ...     Custom DNS resolvers (e.g. 8.8.8.8)
  --concurrency N          Max concurrent checks (default: 100)
  --checkpoint-every N     Save interval (default: 50)
  --data-dir DIR           Cache/state directory (default: ./data)
  --timeout SECONDS        Per-check timeout (default: 10)
  -v, --verbose            Print each result as it completes
  -q, --quiet              Suppress progress bar
```

## State files

State is stored in `./data/` (or wherever `--data-dir` points):

- `tlds.txt` — Cached IANA TLD list (refreshed every 24h)
- `rdap_bootstrap.json` — Cached RDAP server mapping (refreshed every 24h)
- `state_<hash>.json` — Checkpoint for each unique set of words

The state hash is derived from your sorted word list, so `domain-checker milk cookies` and `domain-checker cookies milk` share the same state file. Different word lists get separate files, so multiple jobs can coexist.

## Concurrency and rate limits

The tool uses per-host concurrency control to avoid overwhelming any single server:

| Layer | Concurrent limit | Notes |
|-------|------------------|-------|
| DNS   | 50               | Queries go to public resolvers, high capacity |
| RDAP  | 10 per host      | Hundreds of distinct registry servers |
| WHOIS | 3 per host       | Most sensitive to load |
| Global| 100              | Overall cap across all layers |

RDAP queries that get rate-limited (HTTP 429) are retried with exponential backoff up to 3 times.

## Project structure

```
src/domain_checker/
├── __init__.py          # Package version
├── __main__.py          # python -m domain_checker entry point
├── cli.py               # Argument parsing, progress display, main loop
├── models.py            # CheckResult, TaskState, CheckerConfig dataclasses
├── checker.py           # Orchestrator: runs DNS → RDAP → WHOIS pipeline
├── dns_check.py         # Async DNS NS record lookup
├── rdap_check.py        # Async HTTP RDAP queries
├── whois_check.py       # Async raw TCP WHOIS queries
├── rdap_bootstrap.py    # IANA RDAP bootstrap data (TLD → server URL)
├── tld_list.py          # IANA TLD list download and caching
├── rate_limiter.py      # Per-host semaphore concurrency control
├── state.py             # JSON checkpoint save/load with atomic writes
└── output.py            # Table, CSV, JSON output formatting
```
