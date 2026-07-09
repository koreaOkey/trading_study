# TradingView Fractal Replay Journal

TradingView chart replay screens are captured into a local journal with explicit
metadata, warning states, and replay decisions.

## Run the backend

```bash
cd /home/lee/tradingview-fractal-replay-journal
uv sync
TRFJ_SHARED_API_TOKEN=<local-token> uv run uvicorn fractal_journal.main:app --host 127.0.0.1 --port 8766
```

The API stores captures under `TRFJ_DATA_DIR` or the local private default.
Write endpoints require `TRFJ_SHARED_API_TOKEN` and a matching bearer token.

## Build the extension

```bash
cd /home/lee/tradingview-fractal-replay-journal/extension
bun install
bun run build
```

Load `extension/dist` as an unpacked Chrome extension. Open the extension
options screen, set `http://127.0.0.1:8766`, and set the same API token as the
backend.

On TradingView, click the extension action icon once to grant `activeTab` and
open the capture sheet. The overlay can then capture the visible tab without
requesting broad `<all_urls>` permission.
