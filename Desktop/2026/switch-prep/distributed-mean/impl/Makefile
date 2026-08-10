.PHONY: setup up down seed demo demo-example chaos straggler test logs clean

W ?= 4
F ?= 1000
C ?= 100000
PY := tests/.venv/bin/python

setup:  ## one-time: python venv for the harness + tests (docker handles the rest)
	python3 -m venv tests/.venv
	tests/.venv/bin/pip install -q -r tests/requirements.txt

up:
	docker compose up -d --build --scale worker=$(W)

down:
	docker compose down

seed:
	$(PY) harness/seed.py --f $(F) --c $(C)

demo:
	$(PY) harness/seed.py --f $(F) --c $(C) --submit

demo-example:  ## the brief's worked example: [1,2,3]+[4,5,6] -> [2.5,3.5,4.5]
	$(PY) harness/seed.py --values "1,2,3;4,5,6" --submit
	@echo "expected: 2.5 3.5 4.5"

chaos:  ## kill a busy worker mid-demo; the job must still complete exactly
	$(PY) harness/seed.py --f 300 --c 50000 --submit & \
	sleep 12 && docker kill $$(docker ps -q --filter label=dm.role=worker | head -1); \
	wait

straggler:  ## one 10x-slow worker; watch the Gantt gaps close around it
	docker compose up -d --build --scale worker=3
	SPEED_FACTOR=10 docker compose run -d worker

test:
	cd tests && .venv/bin/python -m pytest -q

logs:
	docker compose logs -f --tail=50 api worker supervisor

clean: down
	docker compose down -v --remove-orphans
