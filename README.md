# OTF Observatory

Offline, browser-based viewer for OTF2 / Score-P and OTF 1 performance traces.

## Run

Requires Python 3.10+, GCC, and OTF2 3.x.

```sh
python3 -m pip install numpy
OTF2_PREFIX=/path/to/otf2 make build
python3 server.py --trace /path/to/traces.otf2
```

Open http://127.0.0.1:8080.

## Development

Requires Node.js.

```sh
python3 -m pip install black
npm ci
make web check test
npx playwright install chromium
make test-browser
```
