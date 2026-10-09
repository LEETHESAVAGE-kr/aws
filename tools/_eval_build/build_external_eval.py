"""외부 공개 HAZOP 평가셋(평가 전용) 빌더 — 2026-10-10.

    python -m tools._eval_build.build_external_eval

원문 문장(원인·결과·권고)은 옮기지 않는다. 각 출처 워크시트에서 (노드 입력 사실, 가이드워드, 파라미터)만 옮겨
`data/reference/external_eval_202610.json` 에 쓴다 — `data/reference/iocl_lpg_2014.json` 과 같은 원칙.
이 파일의 노드·쌍은 **평가 전용**이다: 검색 풀·few-shot·열거 예시(`enumerate_examples`)·합성 시드·미세조정에 넣지 않는다.
출처별 추출 규칙과 제외 항목은 산출 파일의 `sources[].rules`·`excluded` 에 남긴다.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from tools._eval_build.ornl_ijerph import build as build_ornl_ijerph

OUT = Path(__file__).resolve().parents[2] / "data" / "reference" / "external_eval_202610.json"

SOURCES = [
    {"id": "ornl2023", "title": "ORNL/TM-2023/2963 Ammonia fuel system HAZOP (Gillespie, Kaul, Curran 2023), Appendix C pp.17-28",
     "url": "https://info.ornl.gov/sites/publications/Files/Pub196547.pdf", "process": "무수 암모니아 연료 저장·공급(엔진 시험동)",
     "language": "en", "license": "이용 조건 표시 없음(28쪽 전체 확인) — DOE 계약사(UT-Battelle) 보고서. 사실(쌍)만 옮김",
     "rules": "Temp/Pressure/Flow × No/Low/High/Reverse → (No/Less/More/Reverse, 온도/압력/유량). G Outage → (No, 유틸리티). 'No credible cause' 행·'Where else'·F 'gas release'·노드 C(심층 분석 안 함) 제외"},
    {"id": "ijerph2017", "title": "IJERPH 2017 fuel terminal HAZOP+FTA (Port of Valencia), Table 4", "license": "CC BY",
     "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5551143/", "process": "석유제품 터미널(선박 하역·탱크 저장·탱크로리 적재) 절차형 노드",
     "language": "en", "rules": "Wrong/Other/Different → Other than, More-Less → More·Less 둘 다, 'Yes'(대응 가이드워드 없음) 제외"},
    {"id": "ioclv2016", "title": "IOCL Vijayawada terminal EIA Annexure II HAZOP worksheets (UltraTech, Dec 2016), pp.257-299",
     "url": "https://environmentclearance.nic.in/writereaddata/Online/EDS/14_Jul_2017_141533297HPQ28CFGFinalEIAReport14072017.pdf",
     "process": "석유제품 터미널(HSD·MS·에탄올 입고·출하)", "language": "en",
     "license": "이용 조건 표시 없음(EIA 공시). 기존 평가셋 IOCL 2014 와 같은 운영사 — 평가 전용",
     "rules": "'No/ Less Flow' → Less 유량(IOCL 2014 매핑과 같음), Lower/Higher Level → Less/More 준위, Misdirected flow → Other than 유량, 'Not significant for this Node' 행 제외"},
    {"id": "assam2010", "title": "Assam Gas Co. HAZOP study report (Green Circle Consultants, 2010), worksheets pp.17-24",
     "url": "https://aidcltd.assam.gov.in/sites/default/files/Report.HAZOP%20Report_0.pdf",
     "process": "천연가스 압축기지·배관", "language": "en", "license": "이용 조건 표시 없음(컨설턴트 산출물)",
     "rules": "Parameter 머리글이 있는 행만. 'Less/No' → Less. 파라미터가 불분명한 As well as/Part of/Other than 은 이탈 문구가 조성을 가리킬 때만 '조성'(parameter_inferred) — 나머지 제외. PDF 텍스트 층에서 표 셀이 섞여 사람이 읽어 옮김"},
    {"id": "kais2019", "title": "Park et al. (2019) 회분식 라디칼 반응 공정 HAZOP, 한국산학기술학회논문지 20(2), Table 2 이탈 매트릭스",
     "url": "https://doi.org/10.5762/KAIS.2019.20.2.385", "process": "아크릴 수지 회분식 라디칼 중합", "language": "ko",
     "license": "KISTI 약관 — 영리 복제·배포는 사전 허락. 사실(쌍)만 내부 평가에 사용",
     "rules": "이탈 매트릭스 O 칸 전부. None → No, Parts of → Part of, Step → 조작 단계, Addition → 오염(부가), Phase(Other then) → Other than 상(phase)"},
]

IOCLV = {
    "1": ("HSD 파이프라인 매니폴드 → HSD 탱크 3A", "경유(HSD)", ["파이프라인 매니폴드", "10인치 입고 배관", "바스켓 스트레이너", "ROSOV(원격 차단밸브)", "콘루프 저장탱크"],
          ["Less|유량", "More|유량", "Less|준위", "More|준위", "Other than|유량"]),
    "2": ("HSD 탱크 3B → 충전 지점(HSD 펌프)", "경유(HSD)", ["콘루프 저장탱크", "HSD 이송 펌프", "탱크로리 충전 지점"],
          ["Less|유량", "More|유량", "Reverse|유량", "Less|준위", "More|준위", "Other than|유량"]),
    "3": ("MS 파이프라인 매니폴드 → MS 탱크 1A", "휘발유(MS)", ["파이프라인 매니폴드", "입고 배관", "바스켓 스트레이너", "ROSOV(원격 차단밸브)", "저장탱크"],
          ["Less|유량", "More|유량", "Less|준위", "More|준위", "Other than|유량"]),
    "4": ("MS 탱크 1B → 충전 지점(MS 펌프)", "휘발유(MS)", ["저장탱크", "MS 이송 펌프", "탱크로리 충전 지점"],
          ["Less|유량", "More|유량", "Reverse|유량", "Less|준위", "More|준위", "Other than|유량"]),
    "5": ("에탄올 탱크로리 하역 → 에탄올 탱크", "에탄올", ["탱크로리 하역장", "하역 펌프", "에탄올 저장탱크"],
          ["Less|유량", "Reverse|유량", "Less|준위", "More|준위", "Other than|유량"]),
    "6": ("에탄올 탱크 5A → 충전 지점(에탄올 펌프)", "에탄올", ["에탄올 저장탱크", "에탄올 이송 펌프", "충전 지점"],
          ["Less|유량", "More|유량", "Reverse|유량", "Less|준위", "More|준위", "Other than|유량"]),
    "7": ("HSD/MS 탱크 → 충전 지점(TWL 펌프)", "경유·휘발유", ["저장탱크", "TWL 펌프", "충전 지점"],
          ["Less|유량", "More|유량", "Reverse|유량", "Less|준위", "More|준위"]),
}

ASSAM = {
    "1": ("압축기(5호기) 흡입 배관~스크러버 출구", ["가스 압축기", "흡입 배관", "스트레이너", "스크러버"], ["Less|압력", "More|압력"]),
    "2": ("압축기 토출", ["가스 압축기", "토출 배관", "압력 릴리프 밸브(PRV)", "플레어"], ["Less|압력", "More|압력", "Less|온도", "More|온도"]),
    "3": ("BVFCL 16인치 저압 배관(10.5→6 kg/cm2)", ["저압 가스 배관", "오리피스 유량계", "드레인 포트", "벤트", "라인 밸브", "피그 트랩"],
          ["More|압력", "Less|압력", "More|유량", "Less|유량", "Reverse|유량", "As well as|조성*", "Other than|조성*"]),
    "4": ("BVFCL 20인치 저압 배관(LPG 설비 → 압축기)", ["저압 가스 배관", "압력계", "온도계(RTD)", "오리피스"],
          ["Less|압력", "More|유량", "Other than|조성*"]),
    "5": ("Duliajan → NTPS 20인치 고압 배관", ["고압 가스 배관"], ["More|압력"]),
}

KAIS_NODES = {
    "01": ("반응기 질소 공급 계통(불활성화)", ["회분식 반응기", "질소 공급 배관"]),
    "02": ("반응기 용제 투입 배관", ["회분식 반응기", "용제 투입 배관"]),
    "03": ("모노머 투입 배관 → 계량 탱크", ["모노머 투입 배관", "계량 탱크"]),
    "04": ("개시제 투입 호퍼 → 계량 탱크", ["개시제 투입 호퍼", "계량 탱크"]),
    "05": ("반응용 질소 공급(반응기 불활성화)", ["회분식 반응기", "질소 공급 배관"]),
    "06": ("반응용 용제 공급", ["회분식 반응기", "용제 공급 배관"]),
    "07": ("반응 가열", ["회분식 반응기", "가열 재킷"]),
    "08": ("모노머·개시제 반응기 투입(반응 시작)", ["회분식 반응기", "계량 탱크"]),
    "09": ("반응 중(3시간 중합)", ["회분식 반응기", "교반기"]),
    "10": ("반응기 냉각(포장 전)", ["회분식 반응기", "냉각 재킷"]),
    "11": ("반응기 벤트(증기 응축·환류)", ["회분식 반응기", "벤트 배관", "응축기"]),
}
KAIS = {
    "01": ["More|압력", "No|유량", "More|유량", "Less|유량", "More|조성", "Other than|상(phase)"],
    "02": ["More|압력", "More|준위", "Less|준위", "No|유량", "More|유량", "Less|유량"],
    "03": ["More|압력", "More|준위", "Less|준위", "No|유량", "More|유량", "Less|유량"],
    "04": ["More|압력", "More|준위", "Less|준위", "No|유량", "More|유량", "Less|유량"],
    "05": ["More|압력", "More|조성"],
    "06": ["More|준위", "Less|준위"],
    "07": ["More|온도", "Less|온도"],
    "08": ["More|준위", "Less|준위", "More|조성", "Less|조성"],
    "09": ["More|압력", "More|준위", "Less|준위", "More|온도", "Less|온도", "More|조성", "Less|조성", "Less|혼합",
           "More|반응", "Less|반응", "More|시간", "Less|시간"],
    "10": ["More|온도", "Less|온도"],
    "11": ["More|압력", "More|준위", "Less|준위", "More|온도", "Less|온도", "No|유량", "More|유량", "Less|유량",
           "Other than|상(phase)"],
}
KAIS_SUBSTANCE = "아크릴 수지 원료(자일렌 용제, 스티렌·MMA·아크릴산·부틸아크릴레이트 모노머, 과산화벤조일 개시제)"


def _pairs(nid: str, source_node: str, items: list[str]) -> list[dict]:
    out = []
    for it in items:
        g, p = it.split("|")
        rec = {"node": nid, "source_node": source_node, "guideword": g, "parameter": p.rstrip("*")}
        if p.endswith("*"):
            rec["parameter_inferred"] = True
        out.append(rec)
    return out


def build() -> dict:
    nodes, records, excluded = build_ornl_ijerph()
    for k, (label, sub, eq, items) in IOCLV.items():
        nid = f"V{k}"
        nodes.append({"id": nid, "source_id": "ioclv2016", "source_node": k, "label": label,
                      "node_meta": {"node": nid, "substance": sub, "phase": "liquid", "equipment": eq, "safeguards": []}})
        records += _pairs(nid, k, items)
    excluded.append({"source_id": "ioclv2016", "rule": "Reverse Flow(노드 1·3), More Flow(노드 5), Misdirected flow(노드 7) — 원문이 'Not significant for this Node'"})
    for k, (label, eq, items) in ASSAM.items():
        nid = f"S{k}"
        nodes.append({"id": nid, "source_id": "assam2010", "source_node": k, "label": label,
                      "node_meta": {"node": nid, "substance": "천연가스", "phase": "gas", "equipment": eq, "safeguards": []}})
        records += _pairs(nid, k, items)
    excluded.append({"source_id": "assam2010", "rule": "압축기 흡입 구간의 As well as(벤트 개방·스크러버 매체)·Part of(공기 유입)·Other than(정비) — 파라미터 불분명"})
    for k, (label, eq) in KAIS_NODES.items():
        nid = f"K{k}"
        nodes.append({"id": nid, "source_id": "kais2019", "source_node": f"#{k}", "label": label,
                      "node_meta": {"node": nid, "substance": KAIS_SUBSTANCE, "phase": "liquid", "equipment": eq, "safeguards": []}})
        records += _pairs(nid, f"#{k}", KAIS[k])
    return {
        "_comment": "외부 공개 HAZOP 평가셋(골드셋 아님, 평가 전용). 다른 팀이 쓴 워크시트의 (가이드워드, 파라미터) 쌍과 노드 입력 사실만 — 원인·결과 문장 없음. 검색 풀·few-shot·열거 예시·합성 시드·미세조정 금지.",
        "metric": "점검 항목 포괄률 = 출처 팀이 점검한 (가이드워드, 파라미터) 쌍 중 생성 결과에 있는 비율. 출처별로 따로 내고, 합칠 때는 출처마다 같은 무게(평균)로.",
        "contamination_note": "ORNL·IJERPH 의 파라미터 이름은 2026-10-08 F-06 실험의 열거 예시(data/kb/hazop_param_examples.json)에 들어 있었다 — enumerate_examples 는 계속 false 여야 한다.",
        "sources": SOURCES, "nodes": nodes, "records": records, "excluded": excluded,
    }


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    by_src = Counter(n["source_id"] for n in data["nodes"])
    node_src = {n["id"]: n["source_id"] for n in data["nodes"]}
    rec_src = Counter(node_src[r["node"]] for r in data["records"])
    for s in by_src:
        print(f"{s:12s} nodes {by_src[s]:3d}  pairs {rec_src[s]:3d}")
    print("total nodes", len(data["nodes"]), "pairs", len(data["records"]))
