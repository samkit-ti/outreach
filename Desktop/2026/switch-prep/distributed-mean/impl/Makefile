.PHONY: up down seed demo demo-example chaos straggler test logs clean

W ?= 4
F ?= 1000
C ?= 100000

up:
	docker compose up -d --build --scale worker=$(W)

down:
	docker compose down

seed:
	python3 harness/seed.py --f $(F) --c $(C)

demo:
	python3 harness/seed.py --f $(F) --c $(C) --submit

demo-example:  ## the brief's worked example: [1,2,3]+[4,5,6] -> [2.5,3.5,4.5]
	python3 harness/seed.py --values "1,2,3;4,5,6" --submit
	@echo "expected: 2.5 3.5 4.5"

chaos:  ## kill a busy worker mid-demo; the job must still complete exactly
	python3 harness/seed.py --f 300 --c 50000 --submit & \
	sleep 12 && docker kill $$(docker ps -q --filter label=dm.role=worker | head -1); \
	wait

straggler:  ## one 10x-slow worker; watch the Gantt gaps close around it
	docker compose up -d --build --scale worker=3
	SPEED_FACTOR=10 docker compose run -d worker

test:
	cd tests && python3 -m pytest -x -q

logs:
	docker compose logs -f --tail=50 api worker supervisor

clean: down
	docker compose down -v --remove-orphans
