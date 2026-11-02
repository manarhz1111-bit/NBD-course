SHELL := /bin/bash
COMPOSE := docker compose
RATE ?= 100
DURATION ?= 2m
-include .env
REDIS_ADMIN := $(COMPOSE) exec redis redis-cli --no-auth-warning --user admin --pass $(REDIS_ADMIN_PASSWORD)

.PHONY: help env up down clean ps logs smoke stampede chaos load redis-cli redis-info keys flush urls

help:
	@printf '%s\n' '  make help        show this help' '  make env         create .env with random passwords (once)' '  make up          build and start everything, wait until healthy' '  make down        stop containers (data is kept)' '  make clean       stop and delete all data volumes' '  make ps          container status' '  make logs        follow API and Redis logs' '  make smoke       functional checks: hit/miss, invalidation, negative cache, bypass' '  make stampede    200 concurrent requests on one missing key -> 1 SQL query' '  make chaos       stop Redis for 30 s, the API keeps working from PostgreSQL' '  make load        k6: same traffic with cache, then without (RATE=100 DURATION=2m)' '  make redis-cli   interactive redis-cli as admin' '  make redis-info  memory, hit/miss and eviction counters' '  make keys        biggest keys and memory per key type' '  make flush       drop the whole cache (cold start experiment)' '  make urls        where to look'

env:
	@if [ -f .env ]; then echo ".env already exists"; else \
	  while IFS= read -r l; do case "$$l" in *change-me*) echo "$${l%%=*}=$$(openssl rand -hex 16)";; *) echo "$$l";; esac; \
	  done < .env.example > .env && echo ".env created with random passwords"; fi

up: env
	$(COMPOSE) up -d --build --wait
	@$(MAKE) --no-print-directory urls

down:
	$(COMPOSE) down

clean:
	$(COMPOSE) --profile load down -v

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f api redis

smoke:
	./scripts/smoke.sh

stampede:
	./scripts/stampede.sh

chaos:
	./scripts/chaos-redis.sh

load:
	$(COMPOSE) --profile load run --rm -e RATE=$(RATE) -e DURATION=$(DURATION) \
	  k6 run -o experimental-prometheus-rw /scripts/cache-test.js

redis-cli:
	$(REDIS_ADMIN)

redis-info:
	@$(REDIS_ADMIN) INFO memory | grep -E '^(used_memory_human|maxmemory_human|maxmemory_policy|mem_fragmentation_ratio)'
	@$(REDIS_ADMIN) INFO stats  | grep -E '^(keyspace_hits|keyspace_misses|evicted_keys|expired_keys|total_commands_processed)'
	@$(REDIS_ADMIN) INFO keyspace | grep db0 || true

keys:
	$(COMPOSE) exec redis redis-cli --no-auth-warning --user admin --pass $(REDIS_ADMIN_PASSWORD) --memkeys

flush:
	$(REDIS_ADMIN) FLUSHDB ASYNC

urls:
	@echo "API         http://127.0.0.1:8000/docs"
	@echo "Grafana     http://127.0.0.1:3001  (admin / GRAFANA_ADMIN_PASSWORD from .env)"
	@echo "Prometheus  http://127.0.0.1:9091/alerts"
