UV ?= uv

.PHONY: help sync test lint check build clean

help:  ## show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

sync:  ## install the dev environment (extras included)
	$(UV) sync --all-groups --all-extras

test:  ## run the suite
	$(UV) run pytest

lint:  ## ruff (src/ is vendored and excluded; lint upstream)
	$(UV) run ruff check tooling tests

check: lint test  ## every local gate

build:  ## build the wheel + sdist
	$(UV) build

clean:
	rm -rf dist build .pytest_cache .ruff_cache htmlcov .coverage
