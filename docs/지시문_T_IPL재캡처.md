# 지시문 T — IPL 크레딧 재캡처 (초안 · 키 수령 후 실행)

상위: 지시문 S(10/14, 실호출 0) — `ipl_credit: true`, 규칙 `data/kb/criteria/ipl_credit.json`, 검증기 V-IPL-1~3.
**선행 조건: 게이트웨이 키 예산 확인(10/14 18:09 `budget_exceeded` $36/36).** 예산이 없으면 시작하지 않는다.

## T-0 사전 점검 (실호출 0)
1. `config/models.yaml` — `frequency_basis: true`, `ipl_credit: true`, 기본 기준 KOSHA C-C-37.
2. `pytest -m "not live"` 통과, `git status` 깨끗.
3. 예산 상한 **$3.5**. 노드 1회 약 $1.07~1.20(10/14 P1 $1.072, N2 $1.199) → 3회 약 $3.4. 한 회차가 $1.3 를 넘거나 429 가 나오면 그 자리에서 멈추고 보고.

## T-1 캡처 3회 (이 순서)
| 회차 | 명령 | 입력 안전장치 |
|---|---|---|
| ① N2 | `python -m tools.capture_replay --node N2 --out data/replay/n2_ipl_<날짜>.json` | 없음(미상) |
| ② N2_sg | `python -m tools.capture_replay --node N2 --out results/n2sg_<날짜>.json --safeguards "계류 감시(육안),육안 확인,연 1회 수압시험(명목),항만 VTS(간접),예냉 절차"` | D1 워크시트 N2 5종(진행로그 10/14 R-3-1) |
| ③ P1 | `python -m tools.capture_replay --node P1 --out data/replay/p1_ipl_<날짜>.json` | 안전밸브 · 긴급차단밸브(ESV) · 가스누출감지기 |

- 저장 JSON 에 `ipl_credit: true`·`ipl_credit_effective: true` 가 있는지 먼저 본다(없으면 플래그가 안 들은 캡처 — 폐기).
- N2_sg 는 재생 폴더(`data/replay/`)가 아니라 `results/` 에 둔다 — 같은 노드 id 라 재생 우선순위를 흔든다.

## T-2 수용 기준
- **N2_sg·P1**: 빈도 단일값 비율 ≤ 70%, V-IPL review 0건(요약 줄 `IPL 인정 n행 / 검토 0행`).
- N2: 크레딧 0(안전장치 미상) · `frequency == frequency_base` 전 행 · 근거 `안전장치 정보 없음 — 보수적 상한`.

### 예상 — N2_sg 는 크레딧 0 이 맞다 (사전 기록, 10/14)
D1 N2 의 5종은 분류표(`ipl_credit.json`)상 **전부 비적격**이다 — 계류 감시(육안)·육안 확인·항만 VTS(간접) = `detection_only`, 연 1회 수압시험(명목)·예냉 절차 = `procedural`(`tests/test_ipl_credit.py::test_d1_n2_safeguards_earn_no_credit`).
따라서 N2_sg 는 **빈도가 내려가지 않는 것이 정답**이고, 단일값 ≤ 70% 수용 기준은 N2_sg 에서 **실패가 예상된다**.
그 경우 N2_sg 는 "안전장치를 넣어도 감지·절차만으로는 안 내려가는 올바른 사례"(근거 열의 `– 육안 확인(감지만)` 접두어)로 쓰고,
분포 증거는 P1(안전밸브·ESV 적격, 감지기 비적격)으로 든다. 이 예상을 결과를 본 뒤에 바꾸지 않는다.
- N2_sg 에서 IPL 이 1건이라도 인정되면 그것 자체가 V-IPL-3 review 여야 한다 — review 0 이면서 크레딧 > 0 이면 검증기 결함으로 보고.

## T-3 사람 검토
1. `python -m tools.extract_ipl_rows data/replay/p1_ipl_<날짜>.json results/n2sg_<날짜>.json --limit 20 --out docs/IPL검토_20261015.md`
2. 사용자가 표의 `동의/비동의`·`메모` 열을 채운다(행마다: 그 장치가 그 이탈의 발생을 실제로 막는가, applies_to 가 맞는가).
3. 비동의 비율과 사유를 README §6 에 그대로(불리해도) 적는다.

## 하지 않는 것
심각도 크레딧. 분류표에 없는 장치 자동 인정. KOSHA C-C-37 빈도 정의 문구 수정. LPG 충전소 I1~I4 재캡처. 예산 초과 재시도.
