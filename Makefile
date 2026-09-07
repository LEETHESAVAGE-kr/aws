.PHONY: setup test test-live build-gold test-gold test-llm smoke

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
	HAZOP_USE_MOCK=true $(VENV_PY) -m pytest -m "not live"

# 실 AWS 호출 테스트 — 비용 발생. 자격증명 필요.
test-live:
	$(VENV_PY) -m pytest -m live

# Bedrock 래퍼 단위 테스트만 실행 (전체는 make test)
test-llm:
	HAZOP_USE_MOCK=true $(VENV_PY) -m pytest tests/test_llm.py -v

# G0 킬체크 스모크 — 자격증명 + config/models.yaml 모델 ID 필요. 로그를 results/g0/ 에 남긴다.
smoke:
	@mkdir -p results/g0
	$(VENV_PY) -m pytest tests/test_llm_live.py -m live -v 2>&1 | tee results/g0/smoke_$(shell date +%Y%m%d_%H%M%S).log

# 골드셋 빌드: data/raw/*.xlsx -> data/gold/*.json (spec:gold-dataset T-13)
build-gold:
	$(VENV_PY) tools/build_gold.py \
		--input data/raw/D1_HAZOP_워크시트.xlsx \
		--sheet HAZOP워크시트 \
		--split node --tune-nodes N1

# 골드셋 단위 테스트만 실행 (전체는 make test)
test-gold:
	$(VENV_PY) -m pytest tests/test_gold.py -v
