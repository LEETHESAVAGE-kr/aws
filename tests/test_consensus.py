"""§8 C 합의 생성 — 셀 투표·문장 합의·S/F·스위치(사전등록 docs/사전등록_C_합의생성_20261009.md §1)."""

from __future__ import annotations

import itertools
import json
from collections import Counter
from typing import Any

import numpy as np
import pytest

from core.agent import HazopGenerator, NodeMeta
from core.agent import consensus as cs
from core.agent.generate import STANDARD_GUIDEWORDS, GeneratorConfig
from core.llm import ConverseResponse, Message, MockBedrockClient
from core.llm.config import ConfigValidationError, _read_consensus_runs

PARAMS = ["유량", "압력", "온도", "조성", "계측", "밀봉"]
META = NodeMeta(node="N1", substance="NH3", phase="liquid", equipment=["매니폴드"])


def _cell(param: str, *, causes: list[str] | None = None, s: int = 3, f: int = 2) -> dict[str, Any]:
    return {"parameter": param, "applicable": True, "deviation": f"{param} 이탈", "causes": causes or ["원인 가"],
            "consequences": ["결과"], "safeguards_before": [], "S": s, "F": f, "recommendations": ["권고"],
            "evidence": [], "confidence": "inferred"}


def _na(param: str) -> dict[str, Any]:
    return {"parameter": param, "applicable": False}


def _held(param: str, missing: str = "설계압력") -> dict[str, Any]:
    return {"parameter": param, "applicable": True, "insufficient": True, "missing": [missing],
            "deviation": f"{param} 초안"}


def _batch(*cells: dict[str, Any]) -> dict[str, Any]:
    return {"guideword": "More", "cells": list(cells)}


# ── 셀 투표 ───────────────────────────────────────────────────────────────────
def test_vote_majority_two_to_one() -> None:
    assert cs.vote([cs.APPLICABLE, cs.APPLICABLE, cs.NOT_APPLICABLE]) == cs.APPLICABLE
    assert cs.vote([cs.NOT_APPLICABLE, cs.APPLICABLE, cs.NOT_APPLICABLE]) == cs.NOT_APPLICABLE


def test_vote_three_way_tie_is_held() -> None:
    """1:1:1 은 덜하는 쪽 — 정보 부족(Z 원칙)."""
    for states in itertools.permutations([cs.APPLICABLE, cs.NOT_APPLICABLE, cs.HELD]):
        assert cs.vote(list(states)) == cs.HELD


def test_vote_ignores_missing_and_two_way_tie_is_held() -> None:
    assert cs.vote([cs.MISSING, cs.APPLICABLE, cs.APPLICABLE]) == cs.APPLICABLE
    assert cs.vote([cs.MISSING, cs.APPLICABLE, cs.NOT_APPLICABLE]) == cs.HELD
    assert cs.vote([cs.MISSING] * 3) is None


def test_cell_state_matches_record_rules() -> None:
    assert cs.cell_state(None) == cs.MISSING
    assert cs.cell_state(_na("유량")) == cs.NOT_APPLICABLE
    assert cs.cell_state(_held("유량")) == cs.HELD
    assert cs.cell_state(_cell("유량")) == cs.APPLICABLE
    incomplete = _cell("유량")
    del incomplete["S"]
    assert cs.cell_state(incomplete) == cs.MISSING  # _build_records 가 버릴 셀
    incomplete["missing"] = ["용량"]
    assert cs.cell_state(incomplete) == cs.HELD  # 보류 표시 없이 missing 만 — 보류로 받는 규칙과 같다


# ── 문장 합의 ─────────────────────────────────────────────────────────────────
def _fake_similarity(pairs: set[frozenset[str]]):
    """주어진 쌍만 0.95, 나머지 0.80 — e5 없이 τ 경계를 시험한다."""

    def sim(texts: list[str]) -> Any:
        m = np.full((len(texts), len(texts)), 0.80)
        for i, a in enumerate(texts):
            for j, b in enumerate(texts):
                if i == j or frozenset((a, b)) in pairs:
                    m[i, j] = 0.95
        return m

    return sim


def test_cluster_identical_paraphrase_and_different() -> None:
    sim = _fake_similarity({frozenset(("토출 밸브 오조작", "토출측 밸브 잘못 닫힘"))})
    runs = [["토출 밸브 오조작", "전원 상실"], ["토출측 밸브 잘못 닫힘", "전원 상실."], ["토출 밸브 오조작", "배관 막힘"]]
    clusters = cs.cluster_sentences(runs, 3, sim)
    by_text = {c["text"]: c["agree"] for c in clusters}
    assert by_text["토출 밸브 오조작"] == 3  # 동일 + 바꿔 쓴 문장
    assert by_text["전원 상실"] == 2  # 정규화 문자열 일치(마침표)
    assert by_text["배관 막힘"] == 1  # 다른 문장
    assert [c["agree"] for c in clusters] == [3, 2, 1]  # agree 내림차순


def test_cluster_never_merges_two_sentences_of_same_run() -> None:
    sim = _fake_similarity({frozenset(("가", "나"))})
    clusters = cs.cluster_sentences([["가", "나"]], 3, sim)
    assert [c["agree"] for c in clusters] == [1, 1]


def test_cluster_below_tau_stays_apart() -> None:
    """0.80 < τ — 비슷한 주제라도 문턱 아래면 다른 묶음(0.85 였으면 합쳐졌을 값)."""
    clusters = cs.cluster_sentences([["가"], ["나"], ["다"]], 3, _fake_similarity(set()))
    assert [c["agree"] for c in clusters] == [1, 1, 1]
    assert pytest.approx(0.92) == cs.TAU


def test_kept_threshold_two_thirds() -> None:
    assert cs.kept(3, 3) and cs.kept(2, 3) and not cs.kept(1, 3)


# ── 묶음 합치기 ───────────────────────────────────────────────────────────────
def test_merge_keeps_agreed_sentences_and_median_grades() -> None:
    runs = [
        _batch(_cell("유량", causes=["가", "나"], s=3, f=2)),
        _batch(_cell("유량", causes=["가"], s=4, f=2)),
        _batch(_cell("유량", causes=["가", "다"], s=4, f=2)),
    ]
    merged = cs.merge_batches(runs, ["유량"], None)
    assert merged is not None
    cell = merged["cells"][0]
    assert cell["causes"] == ["가"]  # 나·다 는 1/3 → 참고
    meta = cell["_consensus"]
    assert [(c["text"], c["agree"]) for c in meta["causes"]] == [("가", 3), ("나", 1), ("다", 1)]
    assert cell["S"] == 4 and meta["S_values"] == [3, 4, 4]
    assert cell["F"] == 2 and meta["F_values"] == [2, 2, 2]


def test_merge_even_count_takes_upper_grade() -> None:
    runs = [_batch(_cell("유량", s=2)), _batch(_cell("유량", s=4)), None]
    cell = cs.merge_batches(runs, ["유량"], None)["cells"][0]
    assert cell["S"] == 4  # 위험을 낮춰 잡지 않는다


def test_merge_tie_without_held_run_gets_split_reason() -> None:
    runs = [_batch(_cell("유량")), _batch(_na("유량")), None]
    cell = cs.merge_batches(runs, ["유량"], None)["cells"][0]
    assert cell["insufficient"] is True
    assert cell["missing"] == [cs.SPLIT_REASON]


def test_merge_held_majority_keeps_model_missing() -> None:
    runs = [_batch(_held("유량", "용량")), _batch(_held("유량", "설계압력")), _batch(_cell("유량"))]
    cell = cs.merge_batches(runs, ["유량"], None)["cells"][0]
    assert cell["insufficient"] is True
    assert cell["missing"] == ["용량", "설계압력", cs.SPLIT_REASON]


def test_merge_all_failed_is_none_and_all_missing_cell_dropped() -> None:
    assert cs.merge_batches([None, None, None], ["유량"], None) is None
    merged = cs.merge_batches([_batch(_cell("유량")), _batch(_cell("유량")), _batch()], ["유량", "압력"], None)
    assert [c["parameter"] for c in merged["cells"]] == ["유량"]


def test_merge_matches_parameter_names_loosely() -> None:
    runs = [_batch(_cell("유량 (액상)")), _batch(_cell("유량(액상)")), _batch(_na("유량(액상)"))]
    merged = cs.merge_batches(runs, ["유량(액상)"], None)
    assert len(merged["cells"]) == 1 and merged["cells"][0]["_consensus"]["votes"] == {
        cs.APPLICABLE: 2, cs.NOT_APPLICABLE: 1}


# ── 생성기 경로 ───────────────────────────────────────────────────────────────
def _factory(fail: str | None = None, flip: str | None = None):
    """판정 호출마다 번호를 매겨 실행마다 다른 원인을 돌려준다. `flip` 가이드워드는 셋 중 한 번만 해당 없음."""
    seen: dict[str, int] = {}

    def make(system: str, messages: list[Message], **_: Any) -> ConverseResponse:
        if "파라미터 축" in system:
            return ConverseResponse(content=json.dumps(
                {"parameters": [{"name": p, "rationale": "r"} for p in PARAMS]}, ensure_ascii=False), cost_usd=0.01)
        user = messages[0].content
        gw = next(g for g in STANDARD_GUIDEWORDS if f"\n{g} —" in user)
        k = seen.get(gw, 0)
        seen[gw] = k + 1
        if gw == fail:
            return ConverseResponse(content=None, cost_usd=0.1)
        cells = []
        for p in PARAMS:
            if gw == flip and k == 0:
                cells.append(_na(p))
            else:
                cells.append(_cell(p, causes=["공통 원인", f"실행{k} 원인"], s=3 + (k == 2)))
        return ConverseResponse(content=json.dumps({"guideword": gw, "cells": cells}, ensure_ascii=False),
                                cost_usd=0.1)

    return make


def test_generate_three_runs_merges_and_records_consensus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cs, "e5_similarity", lambda: None)
    client = MockBedrockClient(response_factory=_factory(fail="Reverse", flip="Less"))
    gen = HazopGenerator(client, GeneratorConfig(consensus_runs=3))
    records = gen.generate(META)
    # 열거 1회 공유 + 판정 21회 + 실패한 Reverse 3회의 클라이언트 재시도 3회
    assert len(client.calls) == 1 + 3 * 7 + 3
    assert gen.total_cost_usd >= 0.01 + 0.1 * 21 - 1e-9  # 실행 3벌의 비용이 모두 합산된다
    assert gen.review_guidewords == ["Reverse"]  # 세 번 다 실패한 가이드워드만
    assert len(gen.consensus_raw["More"]) == 3
    assert gen.judged_cells == gen.expected_cells - len(PARAMS)
    more = [r for r in records if r.guideword == "More"]
    assert more and all(r.causes == ["공통 원인"] for r in more)  # 실행별 원인(1/3)은 칸에서 빠진다
    assert all(r.S == 3 and r.consensus["S_values"] == [3, 3, 4] for r in more)
    less = [r for r in records if r.guideword == "Less"]
    assert all(r.consensus["votes"] == {cs.NOT_APPLICABLE: 1, cs.APPLICABLE: 2} for r in less)
    dumped = more[0].model_dump()
    assert dumped["consensus"]["causes"][0] == {"text": "공통 원인", "agree": 3, "runs": [0, 1, 2], "of": 3}


def test_generate_parallel_three_runs_same_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cs, "e5_similarity", lambda: None)
    serial = HazopGenerator(MockBedrockClient(response_factory=_factory()), GeneratorConfig(consensus_runs=3))
    para = HazopGenerator(MockBedrockClient(response_factory=_factory()),
                          GeneratorConfig(consensus_runs=3, parallel_calls=7))
    assert [r.model_dump() for r in serial.generate(META)] != []
    # 병렬은 같은 가이드워드의 실행 번호가 도착 순서로 섞이지만, 합의 결과(칸 내용·S 가운데 값)는 같다
    a = {(r.guideword, r.parameter): (r.causes, r.S) for r in serial.generate(META)}
    b = {(r.guideword, r.parameter): (r.causes, r.S) for r in para.generate(META)}
    assert a == b


def test_single_run_has_no_consensus_key() -> None:
    """consensus_runs=1 — 지금 경로. 레코드 직렬화에 consensus 키가 없다(재생 파일과 바이트 동일)."""
    client = MockBedrockClient(response_factory=_factory())
    gen = HazopGenerator(client, GeneratorConfig(consensus_runs=1))
    records = gen.generate(META)
    assert len(client.calls) == 1 + 7
    assert records and all("consensus" not in r.model_dump() for r in records)
    assert gen.consensus_raw == {}


def test_config_consensus_runs_only_one_or_three() -> None:
    assert _read_consensus_runs({}) == 1
    assert _read_consensus_runs({"consensus_runs": 3}) == 3
    for bad in (2, 0, True, "3"):
        with pytest.raises(ConfigValidationError):
            _read_consensus_runs({"consensus_runs": bad})


# ── 실측 도구(오프라인) ───────────────────────────────────────────────────────
def test_stability_metric_on_known_states() -> None:
    from tools.measure_consensus import stability, vote_states

    keys = [("More", "a"), ("More", "b")]
    app, na = cs.APPLICABLE, cs.NOT_APPLICABLE
    singles = [{keys[0]: app, keys[1]: app}] * 2 + [{keys[0]: app, keys[1]: na}] + [{keys[0]: app, keys[1]: app}] * 3
    st = stability(singles, keys)
    assert st["consensus_A_vs_B"] == 1.0  # 2:1 투표가 한 번의 흔들림을 흡수
    assert st["single_A1_vs_B1"] == 1.0
    assert st["single_mean_15pairs"] == pytest.approx((10 + 5 * 0.5) / 15)
    assert vote_states([{keys[0]: cs.MISSING, keys[1]: na}], keys) == {keys[0]: cs.MISSING, keys[1]: na}


def test_measure_run_input_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """A·B 두 벌, B 는 열거 호출 없음, 지표·recall 이 채워진다(모의 클라이언트)."""
    from tools import measure_consensus as mc

    clients: list[MockBedrockClient] = []

    def client() -> MockBedrockClient:
        clients.append(MockBedrockClient(response_factory=_factory(flip="Less")))
        return clients[-1]

    monkeypatch.setattr(mc, "get_bedrock_client", client)
    monkeypatch.setattr(cs, "e5_similarity", lambda: None)
    row = mc.run_input("N1", GeneratorConfig(consensus_runs=3))
    assert len(clients) == 2
    assert len(clients[0].calls) == 1 + 21 and len(clients[1].calls) == 21  # B 는 열거 없음
    assert row["stability"]["cells"] == 7 * len(PARAMS)
    assert 0 <= row["stability"]["single_mean_15pairs"] <= 1
    assert row["recall_internal"]["consensus_A"]["total"] == 8
    assert len(row["recall_internal"]["single_6"]) == 6
    json.dumps(row, ensure_ascii=False)  # 저장 가능(발췌 객체 제거)
    v = mc.verdict([row])
    assert v["complete"] is False and v["latency_ok"] is False  # 직접 입력 없음 → 판정 불가 쪽


# ── 화면·Excel (C-4·C-6) ──────────────────────────────────────────────────────
def _consensus_result(monkeypatch: pytest.MonkeyPatch) -> Any:
    from apps.web import service

    monkeypatch.setattr(cs, "e5_similarity", lambda: None)
    records = HazopGenerator(MockBedrockClient(response_factory=_factory(flip="Less", fail="Reverse")),
                             GeneratorConfig(consensus_runs=3)).generate(META)
    return service.Result(meta={"source": "live-run"}, records=records)


def test_screen_repeat_column_and_reference_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.web import service

    result = _consensus_result(monkeypatch)
    table = service.worksheet_table(result)
    more = next(row for row in table if str(row["가이드워드"]).startswith("More"))
    assert more[service.REPEAT_COLUMN] == "판정 3/3 · 원인 ●●● · 결과 ●●● · 권고 ●●● (+참고 3) · 심각도 3·3·4 갈림"
    less = next(row for row in table if str(row["가이드워드"]).startswith("Less"))
    assert less[service.REPEAT_COLUMN].startswith("판정 2/3 · 원인 ●●○")
    assert service.REPEAT_COLUMN in service.review_column_order(table)
    reference = service.reference_rows(result)
    assert {r["문장"] for r in reference} >= {"실행0 원인", "실행1 원인", "실행2 원인"}
    assert all(r["구분"] == "원인" and r["일치"] == "●○○ 1/3" for r in reference)
    assert service.repeat_counts(result).startswith("같은 입력으로 판정 3번 · 원인 문장")


def test_screen_single_run_has_no_repeat_column() -> None:
    from apps.web import service

    records = HazopGenerator(MockBedrockClient(response_factory=_factory()), GeneratorConfig()).generate(META)
    result = service.Result(meta={"source": "live-run"}, records=records)
    assert service.REPEAT_COLUMN not in service.worksheet_table(result)[0]
    assert service.reference_rows(result) == [] and service.repeat_counts(result) is None


def test_excel_repeat_sheet(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from openpyxl import load_workbook

    from core.export import export_all
    from core.export.xlsx import REPEAT_HEADERS, REPEAT_SHEET

    result = _consensus_result(monkeypatch)
    path = export_all(result.records, tmp_path)["xlsx"]
    wb = load_workbook(path)
    assert REPEAT_SHEET in wb.sheetnames
    rows = list(wb[REPEAT_SHEET].iter_rows(values_only=True))
    assert rows[0] == REPEAT_HEADERS
    used = Counter(r[6] for r in rows[1:])
    assert used["참고(한 번만 나옴)"] > 0 and used["워크시트"] > 0
    assert any(r[3] == "심각도" and r[5] == "갈림" for r in rows[1:])
    single = HazopGenerator(MockBedrockClient(response_factory=_factory()), GeneratorConfig()).generate(META)
    assert REPEAT_SHEET not in load_workbook(export_all(single, tmp_path / "s")["xlsx"]).sheetnames
