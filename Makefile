PYTHON ?= python3
PORT ?= 8080
NODE_TOOLS ?= $(firstword $(wildcard node_modules/.bin $(HOME)/.hermes/hermes-agent/node_modules/.bin))
WEB_FORMAT = "web/src/**/*.{ts,tsx}" web/build.mjs web/style.css "tests/browser/**/*.mjs" package.json tsconfig.json .prettierrc.json

.PHONY: build web run test test-browser validate validate-full check format

build:
	$(PYTHON) native/build_reader.py

web:
	node web/build.mjs

run:
	$(PYTHON) server.py --port $(PORT)

test:
	$(PYTHON) -m unittest discover -s tests -t . -p 'test_*.py' -v

test-browser: web
	PYTHON="$(PYTHON)" node tests/browser/run.mjs

validate:
	$(PYTHON) tests/validation/validate_samples.py

validate-full:
	$(PYTHON) tests/validation/validate_samples.py --source-count

format:
	$(PYTHON) -m black server.py viewer native tools tests
	$(NODE_TOOLS)/prettier --write $(WEB_FORMAT)

check:
	$(PYTHON) -m compileall -q server.py viewer native/build_reader.py tests
	$(PYTHON) -m black --check server.py viewer native tools tests
	$(NODE_TOOLS)/prettier --check $(WEB_FORMAT)
	$(NODE_TOOLS)/tsc --noEmit
	node web/build.mjs --check
