CLAUDE.md와 .kiro/steering/aws.md, engineering.md를 읽어라. 그다음 .kiro/specs/bedrock-client/의 requirements.md, design.md, tasks.md를 읽어라.

작업: tasks.md의 T-01~T-12를 **한 번에, 압축 구현**하라. CLAUDE.md "압축 구현 원칙"을 적용한다.
- 파일은 `core/llm/types.py`, `core/llm/config.py`, `core/llm/client.py`(BedrockClient + 재시도 + 캐싱 + 스키마 검증 + 비용 로깅을 한 파일에), `core/llm/mock.py`, `core/llm/__init__.py`(팩토리 get_bedrock_client), `tests/test_llm.py`, `tests/test_llm_live.py`로 제한한다. design.md의 클래스명은 유지하되 별도 파일로 쪼개지 않는다.
- `config/models.yaml`을 생성한다. 모델 ID는 아래 값으로 채운다 (docs/G0_bedrock_access_20260904.md에서 확인한 실제 값):
  - region: ______
  - generation.model_id: ______
  - verifier.model_id: ______
  - embedding.model_id: ______
  - guardrails.id: null
- CostCalculator: 가격표에 없는 모델 ID는 예외를 던지지 말고 비용 0으로 기록하고 WARNING 1회. 가격표는 `config/prices.yaml`로 분리한다.
- 프롬프트 캐싱은 `models.yaml`의 플래그로 켜고 끈다. 지원하지 않는 모델에서 캐싱 관련 오류가 나면 캐싱을 끄고 재시도한다.
- `HAZOP_USE_MOCK=true`면 MockBedrockClient. 기본 `pytest`는 mock으로 오프라인 통과, 실호출은 `@pytest.mark.live`(`pyproject.toml`에 마커 등록).
- mypy는 돌리지 않는다. 품질 게이트는 `ruff check`와 `pytest`만. Makefile에 `test`, `test-live` 타겟 추가.

완료 보고 4줄: 변경 파일 / `pytest`와 `pytest -m live` 결과 / REQ-01~11 충족 여부 / 노드 1건 스모크 호출의 토큰·지연·비용 실측값. tasks.md는 수정하지 마라.
