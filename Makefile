.PHONY=build
build:
	docker build -t retrowrite \
	--build-arg USER_ID=$(shell id -u) \
	--build-arg GROUP_ID=$(shell id -g) .

.PHONY=build-cftool
build-cftool:
	docker run --rm \
	-v "${PWD}/cftool:/usr/local/go/src/cftool" \
	golang:1.16.0-alpine \
	go build -o /usr/local/go/src/cftool/ cftool

.PHONY=shell
shell: build
	docker run --rm -v "${PWD}:/home/retrowrite/retrowrite" -it retrowrite bash

.PHONY=demo
demo: build
	docker run --rm -v "${PWD}:/home/retrowrite/retrowrite" -it retrowrite bash -c "\
	cd demos/user_demo && \
	make && \
	make test && \
	make clean"

.PHONY=test
test: build
	docker run --rm -v "${PWD}:/home/retrowrite/retrowrite" -it retrowrite bash scripts/integrationtests.sh
	docker run --rm -v "${PWD}:/home/retrowrite/retrowrite" -it retrowrite bash scripts/unittests.sh
