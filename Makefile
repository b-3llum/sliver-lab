.DEFAULT_GOAL := help
SHELL := /bin/bash

help: ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[1;36m%-12s\033[0m %s\n",$$1,$$2}'

setup: ## install prerequisites, deps, generate .env + operator config
	./scripts/setup.sh

up: ## start teamserver + backend + frontend
	./scripts/start.sh

down: ## stop backend + frontend (teamserver stays up)
	./scripts/stop.sh

down-all: ## stop everything including the teamserver
	./scripts/stop.sh --all

status: ## show ports, processes, and BFF health
	./scripts/status.sh

listeners: ## start default mTLS listeners (:8443 :9001)
	./scripts/bootstrap-listeners.sh

logs: ## tail all logs
	@tail -n 40 -f /tmp/sliver-server.log /tmp/bff.log /tmp/vite.log

compose-up: ## run the UI via docker compose (teamserver must already run)
	docker compose up --build

.PHONY: help setup up down down-all status listeners logs compose-up
