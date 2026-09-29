# backlog — "있으면 좋을" 항목 한 줄 기록 (CLAUDE.md 범위 규율)

- (9/29 H) `core/llm/anthropic_client.py` 에 명시 timeout 없음 — H-01 실호출 3번째 호출이 19분 매달린 뒤 DNS 실패로 노드 전체가 죽었다. 호출 timeout + 노드 중간 결과 보존 검토
- (9/29 H) `DeviationRecord.confidence` 기본값 inferred + 스키마가 null 불허 → 골드 재생 레코드가 파일에 inferred 로 저장된다(UI·내보내기는 `apps/web/service.py` 에서 미부여로 덮음). 사람 작성 레코드용 값 필요
- (9/29 H) PRD FR-10 의 "NH3 확산 지도 이미지 1장" 은 지시문 H 범위 밖이라 미구현
- (9/29 J) 본선: `HazopGenerator.generate_quick()` 공개 API 로 승격 — 지금은 `apps/web/service.py::run_quick` 이 비공개 메서드 3곳(`_enumerate_parameters`·`_generate_batch`·`_assemble`)에 의존한다
- (9/29 M, 실무자평가 P-5) 공정 설명 → 노드 분할 제안(예: 탱크 / 펌프·배관 / 로딩암·탱크로리) — 지금은 입력 1개 = 노드 1개
- (9/29 M, 실무자평가 P-3) 사업장 위험성 매트릭스(S·F 정의) 업로드 — 지금은 NH3 선박 벙커링 기준 `data/gold/rating_scale.json` 고정
- (9/29 M, 실무자평가 P-10) 검토자 흐름: 화면에서 행 수정·채택/기각·검토자 서명·수정 이력
