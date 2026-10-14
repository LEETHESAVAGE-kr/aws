## 빈도 크레딧 — 독립방호계층(IPL)

- 성립하는 셀마다 `frequency_base` 에 **안전장치를 고려하지 않은** 빈도 등급을 적는다.
- `ipl_credited` 에는 이 이탈의 발생을 실제로 막는다고 인정한 IPL 만 넣는다(`name` 은 입력 안전장치 이름 그대로, `class` 는 아래 분류표의 class, `applies` 는 true). 없으면 빈 배열.
- 입력 safeguards 중 분류표에서 IPL 적격이고 이 이탈에 applies 하는 것만 센다. frequency = max({min_frequency}, frequency_base − min({max_credits}, 인정 수)). 감지기 단독·완화·절차는 세지 않되 frequency_basis 에 이유를 적는다. safeguards 가 비어 있으면 frequency = frequency_base, frequency_basis = '안전장치 정보 없음 — 보수적 상한'.
- `F` 에는 크레딧을 반영한 뒤의 등급을 적는다. `frequency_basis` 에는 "어떤 장치를 왜 인정/불인정했는지" 한 줄.
- 심각도(S)에는 크레딧이 없다. {severity_note}
- 분류표에 없는 장치는 인정하지 않는다.

분류표:
{classes}

참고:
{notes}

- 해당 없음(`applicable=false`) 셀은 `frequency_base` 1, `ipl_credited` 빈 배열로 둔다.
