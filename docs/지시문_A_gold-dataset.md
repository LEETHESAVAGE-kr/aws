CLAUDE.md와 .kiro/steering/domain.md, engineering.md를 읽어라. 그다음 .kiro/specs/gold-dataset/의 requirements.md, design.md, tasks.md를 읽어라.

작업: tasks.md의 T-01~T-11을 **한 번에, 압축 구현**하라. CLAUDE.md "압축 구현 원칙"을 적용한다.
- 파일은 `tools/_gold/models.py`(데이터 모델·스키마), `tools/build_gold.py`(로더·파서·검증·분할·쓰기·CLI)와 `tests/test_gold.py` 세 개로 제한한다. design.md의 클래스명(XlsxLoader, ColumnMapper, GuidewordParser, MultiValueParser, NodeParser, FieldValidator, DatasetValidator, NodeSplitter, JsonWriter)은 함수 또는 얇은 클래스 이름으로 유지해 추적성만 보존한다.
- 입력 원본은 `data/raw/D1_HAZOP_워크시트.xlsx`, 시트 `HAZOP워크시트`(12열, 헤더 1행). 시트 `평가기준`도 읽어 `data/gold/rating_scale.json`으로 저장한다.
- 출력: `data/gold/hazop_nh3.json`, 노드 단위 홀드아웃 `data/gold/split_node.json`(tune=N1 계열, holdout=나머지). scikit-learn은 쓰지 않는다. mypy는 돌리지 않는다. 품질 게이트는 `ruff check`와 `pytest`만.
- `schemas/gold_record.schema.json`은 design.md §5 그대로 만들고 출력 레코드를 이 스키마로 검증한다.
- `data/README.md`에 원본 출처(본인의 제12회 위험성평가경진대회 출품작, git-ignored 이유)와 라이선스 한 문단.
- Makefile에 `build-gold` 타겟 추가.

완료 보고 4줄: 변경 파일 / `pytest` 결과 / REQ-01~09 충족 여부(미충족은 사유) / **실제 레코드 수와 노드 목록**(이 수치가 이후 모든 문서의 정본이 된다). tasks.md는 수정하지 마라.
