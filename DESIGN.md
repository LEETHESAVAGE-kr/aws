---
version: alpha
name: hazop-copilot-design
description: HAZOP 코파일럿 데모 화면의 디자인 규칙. 구조는 Airbnb 디자인 분석(흰 캔버스·잉크 텍스트·포인트 색 1개·부드러운 모서리·그림자 1단)을 따르고, 포인트 색 Rausch(#ff385c) 자리에 Kiro 보라(#9046ff)를 넣었다. 워크시트 표가 화면의 주인공이다 — 사진이 하던 역할을 표가 맡는다.

# 출처
#   구조·간격·모서리·그림자: DESIGN-airbnb.md (Airbnb-design-analysis, alpha)
#   보라 계열: kiro.dev CSS 변수 (2026-09-29 확인) — --form-purple-500 #9046ff,
#              --purple-300~900 (HSL 값을 hex 로 환산). "파생"이라 적은 값은 Kiro 에 없는 값이다.

colors:
  primary: "#9046ff"            # Kiro --form-purple-500. 흰 글자 대비 4.66:1 (AA 통과)
  primary-active: "#7a0ecd"     # Kiro --purple-700 (hsl 274 87% 43%). 흰 글자 대비 7.58:1
  primary-hover: "#8728e6"      # Kiro --purple-600 (hsl 270 79% 53%)
  primary-soft: "#c59eff"       # Kiro --purple-300 (hsl 264 100% 81%). 배경·테두리 전용 — 흰 글자 금지(2.16:1)
  primary-tint: "#f3ecff"       # 파생 — 선택 행·배지 바탕
  primary-disabled: "#e3d1ff"   # 파생 — 비활성 버튼 바탕
  ink: "#222222"
  body: "#3f3f3f"
  muted: "#6a6a6a"
  muted-soft: "#929292"
  hairline: "#dddddd"
  hairline-soft: "#ebebeb"
  border-strong: "#c1c1c1"
  canvas: "#ffffff"
  surface-soft: "#f7f7f7"
  surface-strong: "#f2f2f2"
  on-primary: "#ffffff"
  error-text: "#c13515"         # 포인트 색과 구분되는 오류 빨강(Airbnb 그대로)
  risk-high: "#c13515"          # 위험도 ≥ 15
  risk-mid: "#b25e09"           # 위험도 8~14
  risk-low: "#3f3f3f"           # 위험도 ≤ 7 — 색을 쓰지 않는다
  notice: "#b25e09"             # "참고용"·"M-01 이전 프롬프트" 같은 공개 문구
  scrim: "#000000"

typography:
  fontFamily: "Pretendard, 'Noto Sans KR', Inter, -apple-system, system-ui, sans-serif"
  display-xl: { fontSize: 28px, fontWeight: 700, lineHeight: 1.43 }   # 페이지 제목 1개
  display-sm: { fontSize: 20px, fontWeight: 600, lineHeight: 1.20 }   # ①②③ 절 제목
  title-md:   { fontSize: 16px, fontWeight: 600, lineHeight: 1.25 }   # 요약 줄
  body-md:    { fontSize: 16px, fontWeight: 400, lineHeight: 1.5 }
  body-sm:    { fontSize: 14px, fontWeight: 400, lineHeight: 1.43 }   # 표 본문·출처 줄
  caption-sm: { fontSize: 13px, fontWeight: 400, lineHeight: 1.23 }
  badge:      { fontSize: 12px, fontWeight: 600, lineHeight: 1.18 }
  button-md:  { fontSize: 16px, fontWeight: 500, lineHeight: 1.25 }
  metric:     { fontSize: 40px, fontWeight: 700, lineHeight: 1.1 }    # recall 같은 핵심 수치 1개에만

rounded: { none: 0px, xs: 4px, sm: 8px, md: 14px, full: 9999px }
spacing: { xs: 4px, sm: 8px, md: 12px, base: 16px, lg: 24px, xl: 32px, xxl: 48px, section: 64px }
shadow: "rgba(0,0,0,0.02) 0 0 0 1px, rgba(0,0,0,0.04) 0 2px 6px, rgba(0,0,0,0.1) 0 4px 8px"

components:
  button-primary:   { backgroundColor: "{colors.primary}", textColor: "{colors.on-primary}", rounded: "{rounded.sm}", height: 48px, padding: 14px 24px }
  button-primary-active:   { backgroundColor: "{colors.primary-active}" }
  button-primary-disabled: { backgroundColor: "{colors.primary-disabled}", textColor: "{colors.on-primary}" }
  button-secondary: { backgroundColor: "{colors.canvas}", textColor: "{colors.ink}", border: "1px {colors.ink}", rounded: "{rounded.sm}" }
  node-tab-active:  { textColor: "{colors.ink}", underline: "2px {colors.primary}" }
  node-tab-inactive: { textColor: "{colors.muted}" }
  badge-gold:       { backgroundColor: "{colors.primary-tint}", textColor: "{colors.primary-active}", rounded: "{rounded.full}", padding: 4px 10px }
  badge-notice:     { backgroundColor: "#fff4e5", textColor: "{colors.notice}", rounded: "{rounded.full}", padding: 4px 10px }
  worksheet-table:  { backgroundColor: "{colors.canvas}", border: "1px {colors.hairline}", rounded: "{rounded.md}", headerBackground: "{colors.surface-soft}" }
  input-card:       { backgroundColor: "{colors.canvas}", border: "1px {colors.hairline}", rounded: "{rounded.md}", padding: 24px }
  text-input:       { rounded: "{rounded.sm}", border: "1px {colors.hairline}", focusBorder: "2px {colors.ink}" }
---

## 개요

Airbnb 분석 문서의 뼈대를 그대로 가져온다: **흰 캔버스 + 잉크(#222222) 텍스트 + 포인트 색 하나**. 포인트 색만 Airbnb Rausch 에서
**Kiro 보라 `#9046ff`** 로 바꿨다. 이 앱은 Kiro 로 spec 을 쓰고 Claude Code 로 구현한 출품작이라, 보라가 "Kiro 개발 방식"(README §5)과 시각적으로 이어진다.

Airbnb 에서 사진이 하던 일을 여기서는 **HAZOP 워크시트 표**가 한다. 표가 화면 무게를 지고, 글자는 크게 키우지 않는다.

## 색

### 보라는 한 화면에 1~2번만
- **쓰는 곳**: 주 버튼("빠른 실호출"), 선택된 노드 탭의 밑줄, 골드셋 배지 바탕(`primary-tint`), 링크.
- **안 쓰는 곳**: 표 본문, 위험도 칸, 경고·공개 문구. 보라가 위험 신호처럼 읽히면 안 된다.
- Airbnb 원칙("화면의 90%는 흰색과 잉크")을 그대로 지킨다.

### 보라와 위험 색을 섞지 않는다
- 위험도는 보라가 아니라 `risk-high`(빨강)·`risk-mid`(주황) 글자색으로만 표시한다. 낮은 위험도는 색을 쓰지 않는다.
- 오류 빨강 `error-text` 는 Airbnb 값 그대로. 보라 계열에 빨강을 섞은 값을 새로 만들지 않는다.

### 공개 문구는 주황
"S·F 기준은 NH3 선박용 — 참고용", "M-01 이전 프롬프트", "전문가 골드셋 재생 — 생성 결과 아님" 같은 **불리한 사실 공개**(NFR-03)는
`notice` 주황 배지로 통일한다. 숨기지는 않되 경보처럼 보이지 않게 한다.

### 대비
| 조합 | 대비 | 판정 |
|---|---|---|
| 흰 글자 on `#9046ff` | 4.66:1 | AA 통과(본문 크기) |
| 흰 글자 on `#7a0ecd` | 7.58:1 | AAA |
| 흰 글자 on `#c59eff` | 2.16:1 | **금지** — 배경·테두리 전용 |

## 글꼴

Airbnb Cereal 은 쓸 수 없다. Airbnb 문서는 Inter 를 대체로 권하지만 이 앱은 한글이 주라서 **Pretendard → Noto Sans KR → Inter** 순으로 둔다.
굵기는 Airbnb 처럼 절제한다: 제목 28px/700 하나, 절 제목 20px/600, 나머지는 400~600. 크게 강조하는 곳은 `metric`(recall 같은 핵심 수치 1개)뿐이다.

## 모양·간격·그림자

- 모서리: 버튼·입력 8px, 카드·표 테두리 14px, 배지 완전 원형. 각진 모서리는 없다.
- 간격: 8px 격자. 절(①②③) 사이 64px, 카드 안쪽 24px, 표 셀 12px.
- 그림자: **한 단계만**(frontmatter `shadow`). 입력 카드와 드롭다운에만 쓴다. 표는 그림자 없이 1px 테두리.

## 화면 구성 (현재 app.py 흐름 기준)

1. **제목 + 한 단락 설명** — 흰 바탕, 28px 제목.
2. **① 공정 선택** — 셀렉트 + 노드 버튼 줄. 선택 노드는 보라 밑줄(`node-tab-active`), 나머지는 회색 글자.
3. **② 입력 → 생성 과정** — 좌우 2단 카드(`input-card`). 출처 줄은 13px 회색, 공개 문구는 주황 배지.
4. **③ 워크시트** — 요약 줄(16px/600) → 표 → 다운로드 버튼 3개(보조 버튼 스타일, 주 버튼 아님).
5. **평가 결과(접힘)** — 흰 바탕, 표만.

## Streamlit 적용 방법 (`.streamlit/config.toml`)

**적용됨.** 화면 바탕은 흰색이고, 보라는 포인트에만 들어간다.

```toml
[theme]
base = "light"
primaryColor = "#9046ff"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f7f7f7"
textColor = "#222222"
borderColor = "#dddddd"
baseRadius = "8px"
```

- `primaryColor` 하나로 주 버튼·선택 강조·링크·포커스 테두리가 보라가 된다. 바탕·보조 바탕은 흰색·옅은 회색이다 — 보라 바탕은 없다.
  로컬 mock 화면 실측: `.stApp` 바탕 `rgb(255,255,255)`, 보라(`rgb(144,70,255)`)가 쓰인 요소는 선택된 노드 버튼 하나(바탕·테두리)뿐.
- `:orange-background[...]` 배지는 Streamlit 내장 팔레트를 따른다.
- `font` 는 **지정하지 않았다** — Pretendard 는 웹폰트를 따로 불러와야 해서, 지금은 Streamlit 기본 글꼴을 쓴다.
- 다크 모드는 두지 않는다(Airbnb 도 공개 웹에 다크 모드가 없다). `base = "light"` 로 고정한다.

## 하지 않는 것

- 보라 그라데이션, 네온 글로우 같은 Kiro 마케팅 페이지의 어두운 배경 연출은 가져오지 않는다. Kiro 에서는 **색 값만** 빌린다.
- 이모지 배지 추가, 그림자 여러 단계, 카드 안에 카드.
