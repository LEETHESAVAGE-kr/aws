.PHONY: setup test test-live build-gold

PY ?= python
VENV := .venv
VENV_PY := $(VENV)/Scripts/python.exe
export PYTHONIOENCODING := utf-8

# venv 생성 + 의존성 설치 (NFR-02 단일 명령 설치)
setup:
	$(PY) -m venv $(VENV)
	$(VENV_PY) -m pip install --upgrade pip
	$(VENV_PY) -m pip install -e ".[dev]"

# 오프라인 테스트 — 외부 API 호출 없이 통과해야 한다 (CLAUDE.md 불변규칙 7)
test:
	$(VENV_PY) -m ruff check .
	$(VENV_PY) -m pytest -m "not live"

# 실 AWS 호출 테스트 — 비용 발생. 자격증명 필요.
test-live:
	$(VENV_PY) -m pytest -m live

# 골드셋 빌드: data/raw/*.xlsx -> data/gold/*.json (spec:gold-dataset)
build-gold:
	$(VENV_PY) tools/build_gold.py
