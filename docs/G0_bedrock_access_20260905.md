# G0 킬체크① — Bedrock 접근 확인 (2026-09-05)

**결과: ❌ 실패 — 자격증명 없음. 모델 목록을 얻지 못했다.**

지시문 0에 따라 **1회만** 실행했고 재시도·자격증명 추측 없이 여기서 멈춘다.

## 환경

| 항목 | 값 |
|---|---|
| Python | 3.12.3 |
| boto3 | 1.43.89 |
| botocore | 1.43.89 |
| 실행 위치 | `.venv` (이 세션에서 `make setup` 상당으로 생성) |
| 리전 | `ap-northeast-2` |

시스템 Python에는 boto3가 없었다. `python -m venv .venv` 후 `pip install -e ".[dev]"`로 설치한 뒤 실행했다.

## 실행 명령

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tools/check_bedrock_access.py --region ap-northeast-2
```

## 출력 (종료 코드 1)

```
# region = ap-northeast-2

## 파운데이션 모델 (TEXT 출력 · ON_DEMAND/INFERENCE_PROFILE 지원)
Traceback (most recent call last):
  File "tools\check_bedrock_access.py", line 74, in <module>
    sys.exit(main())
  File "tools\check_bedrock_access.py", line 26, in main
    models = br.list_foundation_models(byOutputModality="TEXT")["modelSummaries"]
  ...
  File ".venv\Lib\site-packages\botocore\auth.py", line 429, in add_auth
    raise NoCredentialsError()
botocore.exceptions.NoCredentialsError: Unable to locate credentials
```

(트레이스백 중간 프레임은 botocore 내부 호출 사슬이라 생략. 마지막 프레임이 원인이다.)

## 원인

`botocore.exceptions.NoCredentialsError: Unable to locate credentials` — 이 PC에서 AWS 자격증명 체인이 비어 있다.
`AWS_PROFILE`·`AWS_ACCESS_KEY_ID` 환경변수도, `~/.aws/credentials` 프로필도 boto3가 찾지 못했다.
**네트워크·권한 문제가 아니라 인증 이전 단계에서 멈춘 것이다.** 대회 계정에서 어떤 모델이 열려 있는지는 **아직 알 수 없다**.

## 사람이 해야 할 일 (다음 세션 전)

1. 대회 AWS 계정 자격증명을 이 PC에 설정 — `aws configure --profile <name>` 또는 SSO 로그인.
2. `.env`에 `AWS_PROFILE=<name>` 기입 (`.env.example` 참고, `.env`는 git 제외).
3. 위 명령을 다시 1회 실행해 이 파일을 갱신.
4. 목록에서 Claude 계열 모델 ID를 사람이 고른 뒤 `--try-model <id>`로 Converse 1회 확인.
5. 통과한 ID를 `config/models.yaml`의 `generation.model_id`에 기록 (코드 하드코딩 금지 — CLAUDE.md 불변규칙 3).

## 부수 발견 (수정하지 않음)

`tools/check_bedrock_access.py`는 `ClientError`만 잡는다(26~29행). `NoCredentialsError`는 `ClientError`의 하위 클래스가 아니라서
"list_foundation_models 실패:" 안내 대신 트레이스백으로 죽는다. 자격증명 확보 후에는 실행에 지장이 없지만,
같은 상황이 재발하면 메시지가 불친절하다. 지시문 0 범위 밖이라 손대지 않았다.

## G0 게이트 영향

PRD §8의 G0 킬체크①(9/7) 통과 조건 중 **"Bedrock 실호출 성공"은 미충족 상태로 남아 있다.**
나머지 조건(steering 4종·spec 2종)은 충족, 골드셋 JSON은 지시문 A에서 생성 예정.
자격증명 확보가 G0의 잔여 blocker다.
