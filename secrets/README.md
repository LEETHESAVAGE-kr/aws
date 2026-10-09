# secrets/ — 키 파일 보관 (커밋 안 됨)

Kiro API 등 받은 키를 **파일로** 둘 곳. 이 폴더의 다른 파일은 `.gitignore` 로 전부 제외된다.

- 키 문자열은 가능하면 `.env`(로컬)·Streamlit Secrets(배포)에 환경변수로 넣는다(CLAUDE.md 불변 규칙 3).
- 여기 둔 파일은 경로만 환경변수로 넘긴다. 예: `KIRO_API_KEY_FILE=secrets/kiro_api_key.txt`.
- 형식(Anthropic / OpenAI / Bedrock)에 따른 배선은 `docs/PRD_본선_추론경계_Kiro연동.md` §4.
