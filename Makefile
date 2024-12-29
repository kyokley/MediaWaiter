.PHONY: build build-dev up up-no-daemon tests attach shell help list static publish push static pytest bandit

UID := 1000
GID := 1000

export UID
export GID

DOCKER_COMPOSE_EXECUTABLE=$$(which docker-compose >/dev/null 2>&1 && echo 'docker-compose' || echo 'docker compose')

help: ## This help
	@grep -F "##" $(MAKEFILE_LIST) | grep -vF '@grep -F "##" $$(MAKEFILE_LIST)' | sed -r 's/(:).*##/\1/' | sort

list: ## List all targets
	@make -qp | awk -F':' '/^[a-zA-Z0-9][^$$#\/\t=]*:([^=]|$$)/ {split($$1,A,/ /);for(i in A)print A[i]}'

build: ## Build prod-like container
	docker build --build-arg UID=${UID} --tag=kyokley/mediawaiter --target=prod .

build-dev: ## Build dev container
	docker build --build-arg UID=${UID} --tag=kyokley/mediawaiter --target=dev .

build-base: ## Build dev container
	docker build --build-arg UID=${UID} --tag=kyokley/mediawaiter --target=base-builder .

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
	docker run --rm -it \
	    -v $$(pwd):/code \
	    kyokley/mediawaiter sh

shell-base: build-base ## Run shell in builder-base container
	docker run --rm -it \
	    -v $$(pwd):/code \
	    kyokley/mediawaiter sh

tests: pytest bandit ## Run tests

pytest: build-dev ## Run pytests
	docker run --rm -t \
	    -v $$(pwd):/code \
	    kyokley/mediawaiter sh -c "/venv/bin/pytest"

bandit: build-dev ## Run bandit
	docker run --rm -t \
	    -v $$(pwd):/code \
	    kyokley/mediawaiter sh -c "/venv/bin/bandit -x '**/tests/test_*.py,./.venv' -r ."

down: ## Bring all containers down
	${DOCKER_COMPOSE_EXECUTABLE} down

push: build ## Push image to docker hub
	docker push kyokley/mediawaiter

publish: push ## Alias for push

autoformat: build-dev
	docker run --rm -t -v $$(pwd):/code kyokley/mediawaiter /venv/bin/black /code
