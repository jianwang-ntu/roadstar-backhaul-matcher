.PHONY: test demo sweep clean

test:
	python3 -m pytest -q

demo:
	python3 -m roadstar.experiment --trucks 40 --loads 50 --instances 30

sweep:
	mkdir -p results
	python3 -m roadstar.experiment --trucks 40 --loads 50 --instances 30 --out results/sweep_40x50.json
	python3 -m roadstar.experiment --trucks 100 --loads 120 --instances 10 --out results/sweep_100x120.json

clean:
	rm -rf .pytest_cache **/__pycache__
