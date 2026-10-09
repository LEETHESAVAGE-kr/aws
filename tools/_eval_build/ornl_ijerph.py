"""외부 평가셋 변환 — ORNL 2023 · IJERPH 2017. 원문 문장은 옮기지 않고 (가이드워드, 파라미터) 쌍과 노드 입력(사실)만."""
GW = {"Low": "Less", "High": "More", "No": "No", "Reverse": "Reverse", "Less": "Less", "More": "More",
      "Wrong": "Other than", "Other": "Other than", "Different": "Other than"}
P = {"Temp": "온도", "Pressure": "압력", "Flow": "유량", "Level": "준위", "Speed": "속도",
     "Static Electricity": "정전기", "Static electricity": "정전기", "Corrosion": "부식", "Maintenance": "정비",
     "Mooring": "계류", "Direction": "방향", "Movement": "이동", "Safety": "안전", "Element": "연결 요소",
     "Connection": "연결", "Electrical Isolation": "전기적 절연", "Cleaning": "세정", "Collision": "충돌",
     "Flammability": "인화성", "Entry into the loading bay": "적재장 진입",
     "Manoeuvrability at the loading bay": "적재장 내 조종", "Loading position": "적재 위치", "Stop filled": "충전 정지"}

# ── ORNL/TM-2023/2963 부록 C (pp.17-28). 'No credible cause' 행·Where else·F(가스 방출)·C(심층 분석 안 함) 제외 ──
ORNL_ROWS = {
    "A": ["Temp Low", "Temp High", "Pressure No", "Pressure Low", "Pressure High", "Pressure Reverse",
          "Flow No", "Flow Low", "Flow High", "Flow Reverse"],
    "B": ["Temp Low", "Temp High", "Pressure No", "Pressure Low", "Pressure High", "Pressure Reverse",
          "Flow No", "Flow Low", "Flow High", "Flow Reverse"],
    "D": ["Temp High", "Pressure No", "Pressure Low", "Pressure High", "Flow No", "Flow Low", "Flow High"],
    "E": ["Pressure No", "Pressure Low", "Pressure High", "Pressure Reverse",
          "Flow No", "Flow Low", "Flow High", "Flow Reverse"],
}
ORNL_UTIL = [("No", "전력"), ("No", "공정수"), ("No", "냉각기(칠러)"), ("No", "압축공기")]  # G: Outage
ORNL_NODES = {
    "A": ("암모니아 저장 용기 및 부가 안전 시스템", ["무수 암모니아 저장 탱크", "압력 릴리프 밸브", "과유량 차단밸브"]),
    "B": ("암모니아 연료 펌프", ["암모니아 연료 펌프", "열교환기(칠러)", "배압 조절밸브"]),
    "D": ("암모니아 연료 엔진 시스템", ["엔진 시험실", "연료 분사기", "파열판"]),
    "E": ("퍼지 가스 시스템", ["질소 듀어", "압력 조절기", "3방향 밸브"]),
    "G": ("유틸리티", ["전력", "공정수", "냉각기(칠러)", "압축공기"]),
}

# ── IJERPH 2017 Table 4 (CC BY) — 발렌시아 항 연료 터미널, 절차형 노드 15개 ──
IJ = [
    ("1.1.1", "선박 접안", "Wrong/More", "Mooring/Speed"),
    ("1.1.2", "해상 로딩암 전개", "Other/No/Less", "Direction/Movement/Safety"),
    ("1.1.3", "로딩암-매니폴드 연결", "Other/No/No/Less", "Element/Connection/Electrical Isolation/Safety"),
    ("1.2.1", "하역 밸브 개방", "No/Less/More/More/More", "Flow/Flow/Speed/Static Electricity/Corrosion"),
    ("1.2.2", "제품 이송", "More-Less/Less/Less/More/Yes/More", "Pressure/Maintenance/Flow/Static Electricity/Collision/Corrosion"),
    ("1.2.3", "하역 밸브 폐쇄", "Yes/More/More-Less/More/More", "Flow/Speed/Pressure/Static Electricity/Corrosion"),
    ("1.2.4", "배관 세정", "No/Less", "Cleaning/Pressure"),
    ("2.1.1", "탱크 밸브 개방", "No/Less/More/More/More", "Flow/Flow/Speed/Static Electricity/Corrosion"),
    ("2.1.2", "탱크 충전", "More/More", "Level/Static Electricity"),
    ("2.1.3", "탱크 밸브 폐쇄", "Yes/More/More-Less/More/More", "Flow/Speed/Pressure/Static Electricity/Corrosion"),
    ("2.2.1", "탱크 저장", "Yes/More/More/Less", "Flammability/Corrosion/Pressure/Maintenance"),
    ("3.1.1", "탱크로리 적재장 진입", "Wrong/Wrong/Different", "Entry into the loading bay/Manoeuvrability at the loading bay/Loading position"),
    ("3.1.2", "적재 암 연결", "Less/Less", "Connection/Safety"),
    ("3.2.1", "적재 밸브 개방", "No/Less/More/More/More", "Flow/Flow/Speed/Static Electricity/Corrosion"),
    ("3.2.2", "탱크로리 충전", "More/No/Yes/More/Less", "Level/Connection/Stop filled/Static Electricity/Safety"),
    ("3.2.3", "적재 밸브 폐쇄", "Yes/More/More-Less/More/More", "Flow/Speed/Pressure/Static Electricity/Corrosion"),
]


def build():
    nodes, records, excluded = [], [], []
    for key, (label, equipment) in ORNL_NODES.items():
        nid = f"O{key}"
        nodes.append({"id": nid, "source_id": "ornl2023", "source_node": key, "label": label, "node_meta": {
            "node": nid, "substance": "무수 암모니아(NH3)", "phase": "liquid", "equipment": equipment, "safeguards": []}})
        rows = ORNL_ROWS.get(key, [])
        for r in rows:
            p, g = r.split(" ")
            records.append({"node": nid, "source_node": key, "guideword": GW[g], "parameter": P[p]})
        if key == "G":
            for g, p in ORNL_UTIL:
                records.append({"node": nid, "source_node": key, "guideword": g, "parameter": p})
    excluded.append({"source_id": "ornl2023", "rule": "'No credible cause' 행(팀이 해당 없음으로 판정), 'Where else'(외부 누출 — 7개 가이드워드에 대응 없음), 노드 F 'Ammonia gas release', 노드 C(원문이 심층 분석하지 않음) 제외"})
    for code, label, gws, params in IJ:
        nid = "J" + code.replace(".", "")
        nodes.append({"id": nid, "source_id": "ijerph2017", "source_node": code, "label": label, "node_meta": {
            "node": nid, "substance": "휘발유·경유·등유(석유제품)", "phase": "liquid",
            "equipment": [f"{label} 작업", "연료 터미널(선박 하역·저장 탱크·탱크로리 적재)"], "safeguards": []}})
        for g, p in zip(gws.split("/"), params.split("/"), strict=True):
            g, p = g.strip(), p.strip()
            if g == "Yes":
                excluded.append({"source_id": "ijerph2017", "node": nid, "pair": f"Yes / {p}"})
                continue
            for gg in (["More", "Less"] if g == "More-Less" else [g]):
                records.append({"node": nid, "source_node": code, "guideword": GW[gg], "parameter": P[p]})
    return nodes, records, excluded


if __name__ == "__main__":
    n, r, e = build()
    from collections import Counter
    print(len(n), "nodes", len(r), "records", Counter(x["node"][0] for x in r))
