.PHONY: setup test preflight sim-eval smoke docker-build docker-smoke

setup:
	python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[anthropic,dev]"

test:
	python -m pytest -q

preflight:
	bash scripts/preflight.sh

# No API key needed. Simulated worst-case model, all guardrail presets.
sim-eval:
	python -m evals.run_eval --suite attacks --client gullible --config all

# Cheap real-model smoke test: 3 normal tasks, no guardrails.
smoke:
	python -m evals.run_eval --suite normal --config none --limit 3

docker-build:
	docker build -t secure-agents-tools:latest -f docker/Dockerfile .

# Same attack eval, but the tool servers run in locked-down containers.
docker-smoke: docker-build
	python -m evals.run_eval --suite attacks --client gullible --config none,full --sandbox docker
