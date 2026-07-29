PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
PY := $(BIN)/python
PIP := $(BIN)/pip
INPUT ?= samples
MEDIA ?= videos
ORIENTATION ?= vertical
IMAGE_DURATION ?= 3
MAX_DURATION ?=
OUTPUT ?=

.PHONY: help venv install check run gui build-gui slideshow mixed clean

help:
	@echo "Clipweave targets:"
	@echo "  make install                         Create venv and install dependencies"
	@echo "  make check                           Compile Python sources"
	@echo "  make run INPUT=/path/to/clips         Build video montage"
	@echo "  make gui                              Launch desktop UI"
	@echo "  make build-gui                        Build GUI binary with PyInstaller"
	@echo "  make slideshow INPUT=/path/to/photos  Build image slideshow"
	@echo "  make mixed INPUT=/path/to/media       Build mixed media montage"
	@echo "  make clean                           Remove local venv and caches"

venv:
	$(PYTHON) -m venv $(VENV)

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

check:
	$(PYTHON) -m compileall .

run:
	$(PY) clipweave.py "$(INPUT)" --media $(MEDIA) --orientation $(ORIENTATION) $(if $(MAX_DURATION),--max-duration $(MAX_DURATION),) $(if $(OUTPUT),--output "$(OUTPUT)",)

gui:
	$(PY) clipweave-gui.py

build-gui:
	$(PIP) install pyinstaller
	$(PY) -m PyInstaller --onefile --windowed clipweave-gui.py

slideshow:
	$(PY) clipweave.py "$(INPUT)" --media images --orientation $(ORIENTATION) --image-duration $(IMAGE_DURATION) $(if $(MAX_DURATION),--max-duration $(MAX_DURATION),) $(if $(OUTPUT),--output "$(OUTPUT)",)

mixed:
	$(PY) clipweave.py "$(INPUT)" --media mixed --orientation $(ORIENTATION) --image-duration $(IMAGE_DURATION) $(if $(MAX_DURATION),--max-duration $(MAX_DURATION),) $(if $(OUTPUT),--output "$(OUTPUT)",)

clean:
	rm -rf $(VENV) __pycache__ clipweave/__pycache__
