# TradingView Fractal Replay Journal

This local Chrome extension captures a TradingView Bar Replay decision, obtains
decision-time OHLCV evidence from KIS, calculates SMA 50, SMA 200, and VWMA 100,
then asks the isolated Hermes `trading` profile to review the decision note. The
review describes sufficient, missing, excessive, and contradictory evidence; it
does not issue a trade instruction.

## Prerequisites

- Python 3.13 and `uv`
- Bun and Chrome/Chromium
- A KIS Open API app key and secret for a real review
- A working Hermes Agent checkout and configured `trading` profile

The backend reads `KIS_APP_KEY` and `KIS_APP_SECRET` from its environment first.
If they are absent, `load_credentials` checks
`/home/lee/trading-ta-knowledge/.env` by default and accepts either those uppercase
names or `appkey`/`appsecret`. Without credentials, the server starts with the
fixture provider, but Submit cannot produce KIS evidence and the review fails
closed as `evidence_unavailable`.

## Start the backend

```bash
cd /home/lee/tradingview-fractal-replay-journal
uv sync
TRFJ_SHARED_API_TOKEN='<local-token>' \
  uv run uvicorn fractal_journal.main:app --host 127.0.0.1 --port 8766
```

Keep the server on loopback. Write routes require a non-empty
`TRFJ_SHARED_API_TOKEN`; the extension must use the same bearer token. Check the
process with:

```bash
curl --fail http://127.0.0.1:8766/health
```

Relevant optional settings are:

| Setting | Default |
| --- | --- |
| `TRFJ_DATA_DIR` | `/home/lee/var/tradingview-fractal-replay-journal` |
| `TRFJ_SCREENSHOT_DIR` | `/home/lee/var/tradingview-fractal-replay-journal/storage/screenshots` |
| `TRFJ_KIS_TOKEN_CACHE_PATH` | `/home/lee/.cache/tradingview-fractal-replay-journal/kis-token-cache.json` |
| `TRFJ_HERMES_PYTHON_PATH` | `/home/lee/hermes-agent/venv/bin/python3` |
| `TRFJ_HERMES_WORKER_PATH` | this repository's `src/fractal_journal/hermes_worker.py` |
| `TRFJ_HERMES_HOME` | `/home/lee/.hermes/profiles/trading` |
| `TRFJ_HERMES_TIMEOUT_SECONDS` | `180` |
| `TRFJ_HERMES_OUTPUT_MAX_BYTES` | `64000` |

`TRFJ_STORAGE_DIR` is retained as a setting, but the current file store uses
`TRFJ_DATA_DIR` and `TRFJ_SCREENSHOT_DIR` directly.

## Build and load the extension

```bash
cd /home/lee/tradingview-fractal-replay-journal/extension
bun install
bun run build
```

In `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and
select `extension/dist`. Open the extension options and set:

- API base URL: `http://127.0.0.1:8766`
- API token: the same value as `TRFJ_SHARED_API_TOKEN`

Open a `https://*.tradingview.com/chart/...` page and click the extension action
icon. The dock and sheet can be dragged by their header areas; the last position
is kept in extension-local storage and clamped back into the viewport.

## Submit workflow

There is one primary action: **Submit for review**.

1. Start TradingView Bar Replay and move to the decision candle.
2. Open the journal. Confirm Symbol, KIS provider symbol, Time frame, and Decision
   time. Select Golden cross, Dead cross, or Uncertain and write the Decision note.
3. Press **Submit for review** or `Ctrl/Cmd+Enter` while the sheet is open.
4. The extension refreshes TradingView metadata, captures the visible tab, and
   persists the capture first.
5. The backend pages backward through KIS data, calculates SMA 50, SMA 200,
   VWMA 100, slopes, price distances, and the SMA gap trend.
6. Hermes reviews the structured evidence and note. The sheet remains open and
   renders the assessment, evidence lists, revised note, risk note, and evidence
   summary.

Edits are automatically saved as a local draft. Closing the sheet saves the
draft but does not submit it. There are no Long, Short, Watch, or Skip submission
buttons.

Only positive ASCII numeric minute timeframes are supported by KIS history, for
example `1`, `3`, `5`, `15`, `60`, or `240`. TradingView hour resolutions are
normalized to minutes. Seconds, daily, weekly, and monthly values such as `30S`,
`1D`, `1W`, and `1M` are rejected for evidence as `unsupported_timeframe`.

## Evidence boundary and price basis

Decision time is the only date/time boundary. There is no separate trade-date
field. KIS history is requested backward from the timezone-aware Decision time,
and every bar later than that instant is filtered before aggregation and indicator
calculation. Hermes receives the calculated decision-time evidence and the
untrusted Decision note; it does not receive future bars, the screenshot path, or
raw KIS responses.

KIS returns one-minute source rows, currently up to 120 rows per page. The
collector pages backward until it has the requested 201 aggregated bars or meets
the page cap (default `256`), sleeping `0.05` seconds between page calls. A KIS
`EGW00201` response stops collection as `rate_limited`; page-cap, empty-page, and
no-progress stops return partial or empty evidence rather than inventing values.
Higher numeric minute timeframes need proportionally more one-minute rows and may
therefore require many pages.

If KIS rejects a cached access token with `EGW00123`, the provider deletes that
cache entry, forces one fresh token issue, and retries once. For paged history it
restarts the complete backward request so pages are collected under one token.
This recovery is deliberately bounded: a repeated `EGW00123` response is surfaced
as `api_error`, and non-authentication API failures are surfaced immediately
without a token refresh.

The stored price basis defaults to `unknown_unadjusted_assumed`. It is provenance,
not an adjustment switch: the backend does not convert or verify KIS prices.
TradingView and KIS indicators can differ because of adjusted-price policy,
session coverage, source-feed details, or bar aggregation. KIS aggregation uses
regular-session rows from 09:00 through 15:30 Asia/Seoul, bucketed from 09:00.
Treat `price_basis_unverified` as an active comparison warning.

## Hermes isolation

The backend launches the configured Hermes Python and worker as a subprocess with
`HERMES_HOME` set to the `trading` profile. That profile supplies the active
provider/model configuration and credentials. Each journal review uses:

- `enabled_toolsets=[]`
- `skip_memory=True`
- `persist_session=False`
- `save_trajectories=False`
- `max_iterations=1`

The worker treats Decision note content as quoted, untrusted data. The model may
return only the bounded code-selection fields; it cannot author review provenance
or prose. The worker wraps that selection in the strict
`hermes_worker_envelope.v1` and owns the active model identifier, current UTC
timestamp, `trading` profile, and trusted prompt-input SHA-256. Worker logs remain
suppressed, and the process is bounded by its timeout and output cap.

The backend accepts the envelope only when its input hash matches, then checks the
selected codes against the trusted indicator evidence, hypothesis, and Decision
note presence. Unknown or extra fields, free-form model prose, internally
inconsistent selections, and codes contradicted by the supplied evidence are
rejected.

After validation, the server maps the codes to fixed Korean summaries and
evidence findings. It deterministically rebuilds the revised Decision note from
the trusted hypothesis and numeric SMA/VWMA/gap/bar-count evidence, and adds the
fixed risk note. Only this server-generated `decision_review.v1` is exposed to the
extension; the raw worker envelope, selection codes, and bound input hash do not
enter the user-visible review.

## Failure and retry behavior

Capture and review are separate stages:

- If capture fails, no capture ID is available to review. The draft remains and a
  new Submit retries the capture flow. The current sheet does not expose the
  lower-level full-screenshot retry payload.
- Once capture succeeds, it remains stored even if KIS or Hermes fails. A
  retryable review shows **Retry review**, which calls the review route with the
  same capture ID and does not recapture or duplicate the journal entry.
- Missing KIS evidence fails closed before Hermes is invoked. Provider/network
  failures are retryable.
- Hermes unavailable/timeout failures are retryable. Strict-schema, oversized,
  or prohibited-content responses fail as non-retryable `invalid_response`.
- Each review attempt atomically replaces the stored decision-review result for
  that capture, including a failed retry replacing an older ready result.

## Local storage

With default settings, backend artifacts are:

- Captures: `/home/lee/var/tradingview-fractal-replay-journal/captures.jsonl`
- Screenshots: `/home/lee/var/tradingview-fractal-replay-journal/storage/screenshots/<capture-id>.png`
- Decision reviews: `/home/lee/var/tradingview-fractal-replay-journal/decision_reviews/<capture-id>.json`
- Scores: `/home/lee/var/tradingview-fractal-replay-journal/scores/<capture-id>.json`
- Legacy local AI reviews: `/home/lee/var/tradingview-fractal-replay-journal/ai_reviews/<capture-id>.json`
- KIS token cache: `/home/lee/.cache/tradingview-fractal-replay-journal/kis-token-cache.json` (mode `0600`)

The API token, draft, draggable position, and any retry payload use
`chrome.storage.local`. Only the API base URL uses `chrome.storage.sync`. Do not
put credentials or other secrets in Decision note: the journal UI runs inside the
TradingView page, which can observe browser input events.

## Quality gates

```bash
cd /home/lee/tradingview-fractal-replay-journal
uv run ruff check .
uv run basedpyright
uv run pytest

cd extension
bun run typecheck
bun test
bun run build
```
