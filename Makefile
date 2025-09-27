.PHONY: build build-dev up up-no-daemon tests attach shell help list static publish push static pytest bandit all clean test

UID := 1000

export UID

NO_CACHE ?= 0
USE_HOST_NET ?= 0

DOCKER_COMPOSE_EXECUTABLE=$$(command -v docker-compose >/dev/null 2>&1 && echo 'docker-compose' || echo 'docker compose')
DOCKER_COMPOSE_TEST_ARGS=-f docker-compose.yml -f docker-compose.test.yml

help: ## This help
	@grep -F "##" $(MAKEFILE_LIST) | grep -vF '@grep -F "##" $$(MAKEFILE_LIST)' | sed -r 's/(:).*##/\1/' | sort

list: ## List all targets
	@make -qp | awk -F':' '/^[a-zA-Z0-9][^$$#\/\t=]*:([^=]|$$)/ {split($$1,A,/ /);for(i in A)print A[i]}'

_build: touch-history
	docker build \
		$$(test ${USE_HOST_NET} -ne 0 && echo "--network=host" || echo "") \
		$$(test ${NO_CACHE} -ne 0 && echo "--no-cache" || echo "") \
		--build-arg UID=${UID} \
		--tag=kyokley/mediawaiter \
		--target=prod \
		.

build: _build ## Build prod-like container

build-dev: touch-history ## Build dev container
	docker build \
		$$(test ${USE_HOST_NET} -ne 0 && echo "--network=host" || echo "") \
		$$(test ${NO_CACHE} -ne 0 && echo "--no-cache" || echo "") \
		--build-arg UID=${UID} \
		--tag=kyokley/mediawaiter \
		--target=dev \
		.

build-base: touch-history ## Build dev container
	docker build \
		$$(test ${USE_HOST_NET} -ne 0 && echo "--network=host" || echo "") \
		$$(test ${NO_CACHE} -ne 0 && echo "--no-cache" || echo "") \
		--build-arg UID=${UID} \
		--tag=kyokley/mediawaiter \
		--target=base \
		.

logs: ## Tail container logs
	${DOCKER_COMPOSE_EXECUTABLE} logs -f mediawaiter

up: ## Bring up containers and daemonize
	${DOCKER_COMPOSE_EXECUTABLE} up -d
	${DOCKER_COMPOSE_EXECUTABLE} logs -f mediawaiter

up-d: ## Bring up containers, daemonize, and return immediately
	${DOCKER_COMPOSE_EXECUTABLE} up -d

up-no-daemon: ## Bring up all containers
	${DOCKER_COMPOSE_EXECUTABLE} up

attach: ## Attach to a running mediawaiter container
	docker attach $$(docker ps -qf name=mediawaiter_mediawaiter)

shell: build-dev up-d ## Open a shell in a mediawaiter container
	${DOCKER_COMPOSE_EXECUTABLE} ${DOCKER_COMPOSE_TEST_ARGS} run --rm \
	    mediawaiter sh

shell-base: build-base ## Run shell in builder-base container
	docker run --rm -it \
	    -v $$(pwd):/code \
	    kyokley/mediawaiter sh

tests: pytest bandit ## Run tests

pytest: build-dev ## Run pytests
	${DOCKER_COMPOSE_EXECUTABLE} ${DOCKER_COMPOSE_TEST_ARGS} run --rm mediawaiter pytest

bandit: build-dev ## Run bandit
	${DOCKER_COMPOSE_EXECUTABLE} ${DOCKER_COMPOSE_TEST_ARGS} run --rm mediawaiter sh -c "bandit -x '**/tests/test_*.py,./.venv' -r ."

down: ## Bring all containers down
	${DOCKER_COMPOSE_EXECUTABLE} down --remove-orphans

push: build ## Push image to docker hub
	docker push kyokley/mediawaiter

publish: push ## Alias for push

autoformat: build-dev
	docker run --rm -t -v $$(pwd):/code kyokley/mediawaiter black /code

touch-history:
	@mkdir -p logs
	@chmod -R 777 logs
