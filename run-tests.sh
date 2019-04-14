#!/bin/bash

docker-compose run --rm mediawaiter sh -c "/venv/bin/pytest && /venv/bin/bandit -x mediawaiter/tests -r ."
exitcode=$?
docker-compose down
exit $exitcode
