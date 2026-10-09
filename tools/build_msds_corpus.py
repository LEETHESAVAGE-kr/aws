"""Y-3 MSDS 근거 코퍼스 수집 — 안전보건공단 물질안전보건자료 Open API(data.go.kr 15157612).

    python -m tools.build_msds_corpus

`.env` 의 `KOSHA_MSDS_API_KEY` 로 CAS 번호마다 화학물질ID 를 찾고(getChemList001, searchCnd=1),
HAZOP 판정에 쓰는 6개 항목(2 유해성·위험성 · 5 폭발·화재 · 6 누출 · 7 취급·저장 · 9 물리화학적 특성 ·
10 안정성·반응성)을 받아 `data/kb/msds/MSDS-<CAS>.json` 과 `data/kb/manifest.csv` 행으로 쓴다.
문단 본문 = API 응답의 `항목명: 상세내용` 줄을 응답 순서대로 이은 것(상세내용 원문 그대로, '자료없음' 줄 제외).
API 키는 파일·로그에 남기지 않는다(문단 `url` 은 키를 뺀 요청 주소). 이용 조건: 이용허락범위 제한 없음.
"""

from __future__ import annotations

import csv
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE = "https://apis.data.go.kr/B552468/msdschem1"
OUT_DIR = REPO_ROOT / "data" / "kb" / "msds"
MANIFEST = REPO_ROOT / "data" / "kb" / "manifest.csv"
LICENSE = "공공데이터포털 이용허락범위 제한 없음(data.go.kr 15157612, 안전보건공단 물질안전보건자료 조회 서비스)"
#: 카탈로그·예시 칩·골드셋 물질 + 공정에서 흔한 위험물질. (CAS, 표기)
SUBSTANCES: tuple[tuple[str, str], ...] = (
    ("7664-41-7", "암모니아"), ("1333-74-0", "수소"), ("74-98-6", "프로판"), ("106-97-8", "부탄"),
    ("75-28-5", "이소부탄"), ("7782-50-5", "염소"), ("67-56-1", "메탄올"), ("7803-62-5", "실란"),
    ("7681-52-9", "차아염소산나트륨"), ("7647-01-0", "염화수소"), ("7664-93-9", "황산"), ("7727-37-9", "질소"),
    ("74-82-8", "메탄"), ("7783-06-4", "황화수소"), ("630-08-0", "일산화탄소"), ("74-85-1", "에틸렌"),
    ("71-43-2", "벤젠"), ("108-88-3", "톨루엔"), ("74-86-2", "아세틸렌"), ("7782-44-7", "산소"),
)
SECTIONS: tuple[tuple[str, str], ...] = (
    ("021", "2. 유해성·위험성"), ("051", "5. 폭발·화재시 대처방법"), ("061", "6. 누출사고시 대처방법"),
    ("071", "7. 취급 및 저장방법"), ("091", "9. 물리화학적 특성"), ("101", "10. 안정성 및 반응성"),
)
MAX_CHARS = 1500


def _key() -> str:
    key = os.environ.get("KOSHA_MSDS_API_KEY", "").strip()
    env = REPO_ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("KOSHA_MSDS_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        raise SystemExit("KOSHA_MSDS_API_KEY 없음 (.env)")
    return key


def _get(op: str, params: dict[str, Any], key: str) -> ET.Element:
    url = f"{BASE}/{op}?serviceKey={key}&" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            root = ET.fromstring(urllib.request.urlopen(url, timeout=30).read())  # noqa: S310 — 고정 호스트
            code = root.findtext("header/resultCode")
            if code != "00":
                raise RuntimeError(f"{op} resultCode={code} {root.findtext('header/resultMsg')}")
            return root
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)
    raise AssertionError


def _chunks(lines: list[str]) -> list[str]:
    out: list[str] = []
    cur = ""
    for line in lines:
        if cur and len(cur) + 1 + len(line) > MAX_CHARS:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    return [*out, cur] if cur else out


def build() -> list[dict[str, str]]:
    key = _key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, str]] = []
    for cas, label in SUBSTANCES:
        items = _get("getChemList001", {"searchWrd": cas, "searchCnd": 1, "numOfRows": 10, "pageNo": 1}, key)
        hit = next((i for i in items.iter("item") if i.findtext("casNo") == cas), None)
        if hit is None:
            print(f"SKIP {cas} {label}: 목록에 없음", flush=True)
            continue
        chem_id, name, last = hit.findtext("chemId"), hit.findtext("chemNameKor"), hit.findtext("lastDate")
        code = f"MSDS-{cas}"
        entries: list[dict[str, Any]] = []
        for op_no, section in SECTIONS:
            root = _get(f"getChemDetail{op_no}", {"chemId": chem_id}, key)
            lines = []
            for item in root.iter("item"):
                detail = (item.findtext("itemDetail") or "").strip()
                if detail and detail != "자료없음":
                    lines.append(f"{(item.findtext('msdsItemNameKor') or '').strip()}: {detail}")
            for n, text in enumerate(_chunks(lines), start=1):
                entries.append({
                    "source_id": code, "chunk_id": f"{code}#{op_no}-{n}",
                    "doc_title": f"물질안전보건자료(MSDS) {name}", "issuer": "안전보건공단",
                    "year": int(str(last)[:4]) if last else None, "version": f"최종 갱신일 {last} · chemId {chem_id}",
                    "locator": section + (f" ({n})" if n > 1 else ""), "text": text,
                    "url": f"{BASE}/getChemDetail{op_no}?chemId={chem_id}", "license": LICENSE,
                })
        (OUT_DIR / f"{code}.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest.append({"code": code, "title": f"물질안전보건자료(MSDS) {name} (CAS {cas})",
                         "revision_year": str(last)[:4] if last else "", "file_path": f"data/kb/msds/{code}.json",
                         "license": LICENSE})
        print(f"OK {cas} {name} chemId={chem_id} 문단 {len(entries)}", flush=True)
    rows = [r for r in csv.DictReader(MANIFEST.open(encoding="utf-8")) if not r["code"].startswith("MSDS-")]
    with MANIFEST.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["code", "title", "revision_year", "file_path", "license"], lineterminator="\n")
        writer.writeheader()
        writer.writerows([*rows, *manifest])
    return manifest


if __name__ == "__main__":
    build()
