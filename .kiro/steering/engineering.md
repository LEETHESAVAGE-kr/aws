---
inclusion: always
---

# 엔지니어링 규칙 — HAZOP 위험성평가 코파일럿

이 파일은 코드 작성·테스트·커밋 전반에 걸쳐 항상 적용되는 기술 표준이다.
Claude Code와 Kiro 모두 이 규칙을 준수한다.

---

## 1. 언어 및 런타임

- **Python 3.12** 이상 사용. f-string, `match`, `tomllib` 등 3.12 기능 활용 가능.
- `pyproject.toml`에 `requires-python = ">=3.12"` 명시.
- 한글 출력이 포함된 모든 실행 환경에서 `PYTHONIOENCODING=utf-8` 설정 필수.
  - `Makefile`, `Dockerfile`, `.env.example` 모두에 포함.
  - 코드 내에서 인코딩 가정 없이 `str` 타입으로만 다루고, 파일 I/O는 `encoding="utf-8"` 명시.

---

## 2. 타입 힌트

- 모든 함수·메서드의 인자와 반환값에 타입 힌트 **필수**.
- `Any` 사용은 외부 라이브러리 경계에서만 허용하며, 내부 코드에서는 금지.
- `from __future__ import annotations`는 파일 상단에 일관되게 추가.
- 복잡한 타입은 `TypeAlias` 또는 `type` 문(3.12+)으로 이름을 부여한다.

```python
# 올바른 예
from __future__ import annotations
from typing import TypeAlias

NodeId: TypeAlias = str

def generate_deviations(node_meta: NodeMeta) -> list[DeviationRecord]:
    ...
```

---

## 3. Pydantic v2

- 데이터 모델은 **pydantic v2** `BaseModel` 사용. v1 호환 API(`from pydantic.v1`) 금지.
- 스키마 유효성 검사 실패 시 `ValidationError`를 잡아 사용자에게 의미 있는 메시지로 전환.
- JSON 직렬화는 `.model_dump_json()`, 역직렬화는 `.model_validate_json()` 사용.
- `schemas/deviation.schema.json`은 `DeviationRecord.model_json_schema()`로 자동 생성 후 파일로 고정.

```python
from pydantic import BaseModel, Field

class DeviationRecord(BaseModel):
    id: int
    node: str
    guideword: str
    parameter: str
    deviation: str
    causes: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    safeguards_before: list[str] = Field(default_factory=list)
    severity: int = Field(ge=1, le=5)
    frequency: int = Field(ge=1, le=5)
    recommendations: list[str] = Field(default_factory=list)
    scenario: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: Confidence = Confidence.inferred
```

---

## 4. 파일 경로

- 경로 조작은 반드시 **`pathlib.Path`** 사용. `os.path` 함수 및 문자열 연결(`"/path/" + name`) 금지.
- 프로젝트 루트 기준 상대 경로는 `Path(__file__).parent` 체인으로 해결.

```python
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
GOLD_FILE = DATA_DIR / "gold" / "hazop_nh3.json"
```

---

## 5. 테스트 (pytest)

### 5.1 기본 원칙
- 테스트 프레임워크: **pytest**. `tests/` 디렉토리에 위치.
- **오프라인 기본**: 기본 실행(`pytest`)은 외부 API 호출 없이 완전히 통과해야 한다.
- 실제 Bedrock·AWS 호출이 필요한 테스트는 `@pytest.mark.live` 마커를 붙인다.
- CI 및 기본 `make test`에서는 `pytest -m "not live"` 실행.

```python
import pytest

@pytest.mark.live
def test_bedrock_real_call():
    """실제 Bedrock Converse API 호출 — CI에서 제외"""
    ...
```

### 5.2 마커 등록
`pyproject.toml`에 마커 등록 필수:
```toml
[tool.pytest.ini_options]
markers = [
    "live: requires real AWS credentials and network access",
]
```

### 5.3 커버리지 목표
- 핵심 모듈(`core/llm/`, `core/agent/`, `core/export/`) 커버리지 ≥ 70%.
- `pytest-cov`로 측정: `pytest --cov=core --cov-report=term-missing -m "not live"`.

### 5.4 모의 클라이언트
- `core/llm/` 내에 `MockBedrockClient`를 제공하여 오프라인 테스트 가능하게 한다.
- 환경변수 `HAZOP_USE_MOCK=true` 시 자동으로 모의 클라이언트 사용.

---

## 6. 린팅 및 포매팅 (ruff)

- **ruff** 사용. black·isort·flake8 별도 설치 금지.
- `pyproject.toml` 설정:

```toml
[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "C4", "SIM", "TCH"]
ignore = ["E501"]  # line-length는 formatter가 처리

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101"]  # assert 허용
```

- 저장 훅 또는 커밋 전에 `ruff check . --fix && ruff format .` 실행.
- ruff 경고가 0건이어야 커밋 가능.

---

## 7. 로깅

- 표준 라이브러리 `logging` 사용. `print()` 디버그 출력 금지(최종 코드 기준).
- 로거 이름: 모듈 경로 그대로 `logging.getLogger(__name__)`.
- 로그 형식 (구조화 JSON 권장, 최소 텍스트 형식):

```
%(asctime)s | %(levelname)-8s | %(name)s | %(message)s
```

- 레벨 기준:
  - `DEBUG`: 프롬프트 전문, 토큰 수 등 상세 정보
  - `INFO`: 노드 처리 시작/완료, 비용, 지연
  - `WARNING`: 스키마 검증 실패 후 재시도, 신뢰도 격하
  - `ERROR`: API 오류, 파일 I/O 실패
- 비용·지연 로그는 `INFO` 레벨, 구조:
  ```
  INFO | core.llm.client | node=N1 tokens_in=1234 tokens_out=567 cost_usd=0.042 latency_s=18.3
  ```

---

## 8. 시크릿 관리

- **소스 코드와 `.kiro/` 디렉토리에 시크릿 하드코딩 절대 금지.**
- 허용 파일: `.env`(gitignore됨), 환경변수.
- 커밋 대상: `.env.example` (값은 플레이스홀더만):

```bash
# .env.example
AWS_ACCESS_KEY_ID=<your-access-key>
AWS_SECRET_ACCESS_KEY=<your-secret-key>
AWS_DEFAULT_REGION=us-east-1
HAZOP_USE_MOCK=false
```

- `.gitignore`에 `.env`, `*.key`, `*.pem`, `credentials` 등록 필수.
- 커밋 전 시크릿 스캔 훅(`detect-secrets` 또는 `gitleaks`)을 `.kiro/hooks/`에 등록.

---

## 9. 커밋 메시지 규칙

형식: `spec:<spec-name> T-xx — 한글 요약`

| 부분 | 설명 | 예시 |
|------|------|------|
| `spec:<spec-name>` | 대응하는 Kiro spec 이름 | `spec:bedrock-client` |
| `T-xx` | tasks.md의 태스크 ID | `T-03` |
| `— 한글 요약` | 변경 내용 한글 50자 이내 | `— Converse API 래퍼 및 재시도 로직 구현` |

예시:
```
spec:bedrock-client T-03 — Converse API 래퍼 및 재시도 로직 구현
spec:hazop-generation T-07 — 가이드워드×파라미터 매트릭스 열거 로직 추가
spec:gold-dataset T-01 — xlsx → JSON 변환 스크립트 초안
```

- spec에 대응하지 않는 잡일(환경 설정, 문서 수정)은 `chore:` 또는 `docs:` 접두어 사용.
- `--amend`는 아직 push되지 않은 본인 커밋에만 허용. push 후 수정 불가.

---

## 10. 프로젝트 구조 규칙

- 새 모듈 추가 시 `__init__.py`에 공개 인터페이스만 re-export.
- 순환 임포트 금지. 의존 방향: `apps` → `services` → `core` → 외부 라이브러리.
- 설정값은 `config/models.yaml` 또는 환경변수에서만 읽는다. 코드 내 상수 하드코딩 금지(모델 ID, 리전, 임계값 포함).
