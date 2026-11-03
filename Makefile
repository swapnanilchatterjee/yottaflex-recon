.PHONY: setup test sample demo large bench clean

PYTHON ?= python

setup:
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m pytest -q

sample:
	$(PYTHON) -m recon generate --out data/sample --customers 50 --orders 200 --seed 42

demo: sample
	$(PYTHON) -m recon run --source-dir data/sample/source --target-dir output/target --out-dir output/mode_a
	$(PYTHON) -m recon reconcile --source-dir data/sample/source --target-dir output/target --out-dir output/mode_a
	$(PYTHON) -m recon reconcile --source-dir data/sample/source --target-dir data/sample/target_drifted --out-dir output/mode_b

large:
	$(PYTHON) -m recon generate --out data/large --customers 20000 --orders 100000 --seed 42

bench:
	$(PYTHON) scripts/benchmark.py

clean:
	$(PYTHON) -c "import shutil, os, glob; [shutil.rmtree(p, ignore_errors=True) for p in ['output', 'data/large', '.pytest_cache', '__pycache__', 'build', 'dist', '.venv']] + [os.remove(f) for f in glob.glob('**/*.pyc', recursive=True)]"
