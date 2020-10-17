.PHONY: build build-dev up up-no-daemon tests attach shell help list static publish push

help: ## This help
	@grep -F "##" $(MAKEFILE_LIST) | grep -vF '@grep -F "##" $$(MAKEFILE_LIST)' | sed -r 's/(:).*##/\1/' | sort

list: ## List all targets
	@make -qp | awk -F':' '/^[a-zA-Z0-9][^$$#\/\t=]*:([^=]|$$)/ {split($$1,A,/ /);for(i in A)print A[i]}'

build: ## Build prod-like container
	docker build --tag=kyokley/mediawaiter --target=prod .

build-dev: ## Build dev container
	docker build --tag=kyokley/mediawaiter --target=dev .

up: ## Bring up containers and daemonize
	docker-compose up -d

up-no-daemon: ## Bring up all containers
	docker-compose up

attach: ## Attach to a running mediawaiter container
	docker attach $$(docker ps -qf name=mediawaiter_mediawaiter)

shell: build-dev up ## Open a shell in a mediawaiter container
	docker-compose exec mediawaiter /bin/bash

tests: build-dev ## Run tests
	./run-tests.sh

down: ## Bring all containers down
	docker-compose down

static: ## Install static files
	rm -rf node_modules
	yarn install
	rm -rf static/bower_components
	mv node_modules static/bower_components

push: build ## Push image to docker hub
	docker push kyokley/mediawaiter

publish: push ## Alias for push
