---
inclusion: always
---

# 도메인 지식 — HAZOP 위험성평가 코파일럿

이 파일은 프로젝트 전반에서 사용하는 HAZOP·PSM·LOPA·KOSHA 관련 용어와 구조의 정본이다.
코드·프롬프트·문서 어디서나 이 정의를 우선 적용하라.

---

## 1. HAZOP 가이드워드 7종 (Guidewords)

| 번호 | 한글 | 영문 | 의미 |
|------|------|------|------|
| GW-1 | 없음 / 불발생 | No / None | 설계 의도가 전혀 달성되지 않음 |
| GW-2 | 증가 | More | 정량적 증가 (유량·압력·온도·농도 등) |
| GW-3 | 감소 | Less | 정량적 감소 |
| GW-4 | 역방향 | Reverse | 방향 또는 흐름이 반대 |
| GW-5 | 이외 / 이상물질 | Other than | 설계 의도와 다른 물질·상태 |
| GW-6 | 일부 | Part of | 설계 의도 중 일부만 달성 |
| GW-7 | 추가 | As well as | 설계 의도에 더해 추가 사항 발생 |

가이드워드 문자열 파싱 규칙: `"More (압력)"` → `guideword="More"`, `parameter="압력"`.
반드시 가이드워드와 파라미터를 분리 저장한다.

---

## 2. HAZOP 파라미터 목록 (Parameters)

화공 공정에서 적용되는 주요 파라미터. 노드 특성에 따라 적용 가능 항목을 선택한다.

| 파라미터 (한글) | 파라미터 (영문) | 비고 |
|----------------|----------------|------|
| 유량 | Flow | 질량·부피·몰 유량 포함 |
| 압력 | Pressure | 게이지·절대압 포함 |
| 온도 | Temperature | 입·출구 구분 가능 |
| 조성 / 농도 | Composition / Concentration | 혼합물 비율 포함 |
| 준위 / 액위 | Level | 탱크·용기 내 액면 |
| 점도 | Viscosity | |
| 반응 | Reaction | 반응 속도·발열 포함 |
| 상(Phase) | Phase | 기·액·고 전환 |
| 시간 | Time | 배치 공정·인터락 타이밍 |
| 기동·정지 | Start-up / Shut-down | 과도(transient) 조건 |
| 유틸리티 | Utility | 스팀·냉각수·전원·계장공기 |
| 유지보수 | Maintenance | 격리·청소·시험 조건 |

---

## 3. HAZOP 워크시트 12열 정의

골드셋(`data/gold/hazop_nh3.json`) 및 xlsx 출력 양식의 컬럼 순서와 의미.

| 열 번호 | 컬럼명 (한글) | 컬럼명 (영문) | 타입 | 설명 |
|---------|--------------|--------------|------|------|
| 1 | No | No | int | 이탈 고유 번호 |
| 2 | 노드 | Node | str | 공정 노드 식별자 (예: N1) |
| 3 | 가이드워드 | Guideword | str | GW-1~GW-7 중 해당 영문 표현 |
| 4 | 이탈 | Deviation | str | 가이드워드 + 파라미터의 구체적 상태 기술 |
| 5 | 원인 | Causes | list[str] | 이탈을 야기하는 원인 목록 |
| 6 | 결과 | Consequences | list[str] | 이탈로 인한 영향·사고 결과 |
| 7 | 기존 안전장치(Before) | Safeguards (Before) | list[str] | 현재 설치된 안전장치 목록 |
| 8 | S | Severity | int(1-5) | 심각도 등급 (§4 정의 참조) |
| 9 | F | Frequency | int(1-5) | 빈도 등급 (§4 정의 참조) |
| 10 | 위험도 | Risk | int | S × F (xlsx에서 수식 `=H*I` 유지) |
| 11 | 권고 | Recommendations | list[str] | 추가 안전 조치 권고 사항 |
| 12 | 시나리오 연계 | Scenario Link | str | QRA·LOPA 시나리오 ID (예: S1, S2) |

추가 시트 (생성 xlsx 전용):
- **근거** 시트: 이탈 No ↔ `{source_id, doc_title, locator, quote}` 매핑
- **신뢰도** 시트: 이탈 No ↔ `confidence ∈ {grounded, inferred, review}` + 사유

---

## 4. S/F 등급 정의 (평가기준 시트 기준)

### 4.1 심각도(Severity, S) 등급

| 등급 | 한글 | 영문 | 기준 |
|------|------|------|------|
| 1 | 미미 | Negligible | 경미한 부상·재산 피해 없음, 환경 영향 없음 |
| 2 | 경미 | Minor | 경상 또는 소규모 재산 피해, 단기 환경 영향 |
| 3 | 보통 | Moderate | 중상 또는 중규모 재산 피해, 지역적 환경 영향 |
| 4 | 중대 | Major | 1인 사망 또는 다수 중상, 대규모 재산 피해 |
| 5 | 치명 | Catastrophic | 다수 사망, 광역 환경 피해, 사업 존립 위협 |

### 4.2 빈도(Frequency, F) 등급

| 등급 | 한글 | 영문 | 기준 (연간 발생 가능성) |
|------|------|------|----------------------|
| 1 | 극히 낮음 | Rare | < 10⁻⁵/년, 사실상 불가능한 수준 |
| 2 | 낮음 | Unlikely | 10⁻⁵ ~ 10⁻³/년, 수십 년에 1회 |
| 3 | 보통 | Possible | 10⁻³ ~ 10⁻¹/년, 수 년에 1회 |
| 4 | 높음 | Likely | 10⁻¹ ~ 1/년, 연 1회 수준 |
| 5 | 매우 높음 | Almost Certain | > 1/년, 빈번하게 발생 |

위험도 = S × F. 위험도 셀은 xlsx 수식 `=H*I`로 유지하고 하드코딩하지 않는다.

---

## 5. PSM 12요소와 위험성평가 위치

공정안전관리(PSM, Process Safety Management) 12요소 중 HAZOP은 **위험성평가(4번)** 에 해당한다.

| 번호 | 요소 (한글) | 요소 (영문) | 비고 |
|------|------------|------------|------|
| 1 | 공정안전정보 | Process Safety Information | P&ID, 물질 MSDS 포함 |
| 2 | 공정위험성평가 절차 | Process Hazard Analysis Procedure | |
| 3 | 운전절차 | Operating Procedures | |
| **4** | **위험성평가** | **Hazard Identification & Risk Assessment** | **HAZOP 해당 위치** |
| 5 | 도급업체 안전관리 | Contractor Safety Management | |
| 6 | 근로자 훈련 | Training | |
| 7 | 가동 전 안전점검 | Pre-Startup Safety Review | |
| 8 | 기계적 무결성 | Mechanical Integrity | |
| 9 | 변경관리 | Management of Change | |
| 10 | 사고조사 | Incident Investigation | |
| 11 | 비상조치계획 | Emergency Planning & Response | |
| 12 | 공정안전감사 | Compliance Audits | |

이 서비스가 생성하는 HAZOP 워크시트와 LOPA 초안은 PSM 요소 4의 공식 산출물로 활용된다.

---

## 6. LOPA 용어 (Layer of Protection Analysis)

| 약어 | 한글 | 영문 | 정의 |
|------|------|------|------|
| LOPA | 보호계층분석 | Layer of Protection Analysis | 개별 보호계층의 독립성과 PFD를 평가하여 시나리오 위험도를 정량화하는 방법 |
| IE | 기동사건 | Initiating Event | 비정상 시나리오를 촉발하는 초기 사건; 발생 빈도(f_IE, /년)로 표현 |
| IPL | 독립보호계층 | Independent Protection Layer | IE 또는 다른 IPL과 독립적으로 작동하여 결과를 방지·완화하는 장치 또는 시스템 |
| PFD | 요구 시 고장 확률 | Probability of Failure on Demand | IPL이 작동 요구를 받을 때 실패할 확률 (0 < PFD ≤ 1) |
| SIL | 안전 무결성 수준 | Safety Integrity Level | SIS(안전계장시스템)의 성능 등급 (SIL 1~4); SIL 1 → PFD 0.1~0.01 |
| SIS | 안전계장시스템 | Safety Instrumented System | 공정을 안전 상태로 유도하기 위한 계장·로직·최종 요소 시스템 |
| TMEL | 허용 가능 최대 위험도 | Tolerable Maximum Event Likelihood | 사업장에서 허용하는 시나리오 최대 발생 빈도 (/년) |
| f_mitigated | 완화 후 빈도 | Mitigated Event Frequency | f_IE × Π(PFD_IPL). 이 값이 TMEL 이하여야 함 |

LOPA 초안 md 파일에는 위험도 상위 N개 이탈에 대해 IE 식별·IPL 후보·필요 PFD를 서술한다.
형식 기준: `data/` 내 `LOPA_S1_C1.md` (NH3 QRA 기존 파일) 준용.

---

## 7. KOSHA Guide P-시리즈 문서 체계

지식 베이스(`data/kb/kosha/`)에 수록하는 KOSHA Guide 공개 문서 분류.

| 시리즈 | 분야 | 관련 FR |
|--------|------|---------|
| KOSHA Guide P-시리즈 | 공정안전 (Process Safety) | FR-04 KB 구축 |
| KOSHA Guide H-시리즈 | 위험성평가 (Hazard Assessment) | FR-04 |
| KOSHA Guide C-시리즈 | 화학물질 (Chemicals) | FR-05 물질 속성 |
| KOSHA Guide M-시리즈 | 기계·설비 (Machinery) | FR-05 고장률 |

주요 수록 대상 (예시, 확정은 `data/kb/manifest.csv`):
- `KOSHA-Guide-P-xxx` : HAZOP 실시에 관한 기술지침
- `KOSHA-Guide-P-xxx` : LOPA 실시에 관한 기술지침
- `KOSHA-Guide-P-xxx` : PSM 위험성평가 작성 지침
- `KOSHA-Guide-H-xxx` : 위험성평가 체계 및 방법

문서 메타 형식 (`data/kb/manifest.csv`):
```
code,title,revision_year,file_path,license
KOSHA-Guide-P-001,HAZOP 실시에 관한 기술지침,2023,data/kb/kosha/P-001.pdf,공공누리 1유형
```

인용 규칙:
- `evidence[]`의 `source_id`는 manifest.csv의 `code` 값과 일치해야 한다.
- 모델이 자체적으로 생성한 KOSHA 코드는 허용하지 않는다. verifier가 manifest에 없는 코드를 플래그 처리한다.
- 인용 텍스트(`quote`)는 반드시 tool이 반환한 문단 텍스트에서 발췌한다.
