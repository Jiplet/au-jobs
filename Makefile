# Makefile - the whole au-jobs pipeline as one command per stage.
#
# Run `make all` for the full pipeline end to end (uses the claude-cli scoring backend
# by default so it works without an API key - see README for the anthropic backend).
# Run `make serve` then open http://localhost:8000 to view the map locally.

.PHONY: fetch parse score site prompt serve test all

fetch:
	uv run python fetch.py

parse:
	uv run python parse.py

score:
	uv run python score.py --backend claude-cli --max-minutes 20

site:
	uv run python build_site.py

prompt:
	uv run python make_prompt.py

serve:
	cd docs && python3 -m http.server 8000

test:
	uv run pytest -q

all: fetch parse score site prompt
	@echo "Done. Run 'make serve' and open http://localhost:8000 to view the map."
