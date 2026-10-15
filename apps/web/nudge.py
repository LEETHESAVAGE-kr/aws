"""모바일 화면 이동 — 버튼을 눌러 바뀐 곳이 화면 밖이면 그리로 스크롤하고 잠깐 테두리를 깜빡인다(10/15 사용자 요청).

PC 에서는 아무것도 하지 않는다 — 넓은 화면은 버튼과 바뀐 곳이 함께 보여 지금 그대로가 낫다(사용자 확인).
모바일 판정은 브라우저가 한다: 화면 폭 768px 이하(Streamlit 이 열을 세로로 쌓는 폭 640px 을 포함).
`components.html` 은 같은 HTML 이면 다시 그리지 않아 두 번째 누름에 스크립트가 안 돈다 — 누를 때마다 번호를 넣는다.
"""

from __future__ import annotations

import json
from typing import Final

#: 이동할 곳 → 부모 문서의 CSS 선택자. `#result` 는 '분석 결과' 머리, `.st-key-quick_text` 는 공정 설명 칸.
TARGETS: Final[dict[str, str]] = {
    "result": "#result",
    "input": ".st-key-quick_text",
    "rows": "[class*='st-key-rowfilter_']",  # '표에서 볼 행' 선택 — 바로 아래가 걸러 낸 표
}
#: PC 에서도 이동하는 곳 — 판정 막대를 누르면 표가 화면 아래라 PC 에서도 찾아가야 한다(10/15 사용자 요청).
ALWAYS: Final[frozenset[str]] = frozenset({"rows"})
MOBILE_QUERY: Final[str] = "(max-width: 768px)"
FLASH_MS: Final[int] = 1600


def script(target: str, nonce: int) -> str:
    """`target` 으로 스크롤하고 테두리를 깜빡이는 스크립트(iframe 안에서 부모 문서를 만진다). `ALWAYS` 밖은 모바일에서만."""
    selector = json.dumps(TARGETS[target])
    query = json.dumps(MOBILE_QUERY)
    guard = "if (true) {\n" if target in ALWAYS else f"if (window.parent.matchMedia({query}).matches) {{\n"
    return (
        f"<script>/* nudge {nonce} */\n"
        "const doc = window.parent.document;\n"
        f"{guard}"
        "  if (!doc.getElementById('hz-nudge-style')) {\n"
        "    const s = doc.createElement('style'); s.id = 'hz-nudge-style';\n"
        "    s.textContent = '@keyframes hzNudge {0%,100% {box-shadow: 0 0 0 0 rgba(144,70,255,0);} "
        "30% {box-shadow: 0 0 0 3px rgba(144,70,255,.85);}} .hz-nudge {animation: hzNudge .8s ease-in-out 2; border-radius: 12px;}';\n"
        "    doc.head.appendChild(s);\n"
        "  }\n"
        f"  const go = (flash) => {{ const el = doc.querySelector({selector}); if (!el) return;\n"
        "    el.scrollIntoView({behavior: flash ? 'smooth' : 'auto', block: 'start'});\n"
        "    if (!flash) return;\n"
        "    el.classList.remove('hz-nudge'); void el.offsetWidth; el.classList.add('hz-nudge');\n"
        f"    setTimeout(() => el.classList.remove('hz-nudge'), {FLASH_MS}); }};\n"
        "  // 결과 표가 늦게 그려지면 자리가 밀리고, 부드러운 스크롤은 중간에 끊길 수 있다 — 1.2초 뒤 즉시 스크롤로 한 번 더 맞춘다\n"
        "  setTimeout(() => go(true), 300); setTimeout(() => go(false), 1200);\n"
        "}\n"
        "</script>"
    )
