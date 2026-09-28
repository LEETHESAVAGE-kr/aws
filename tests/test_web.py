"""오프라인 시험 — FR-10 H-04 (PRD v2.0 §5 FR-10, 지시문 H (a)~(g)). 네트워크 0회."""

from __future__ import annotations

import io
import json
from datetime import date
from typing import TYPE_CHECKING

import openpyxl
import pytest
from jsonschema import Draft7Validator

from apps.web import service
from apps.web.replay import REPLAY_DIR, load_replay
from core.agent.generate import STANDARD_GUIDEWORDS

if TYPE_CHECKING:
    from pathlib import Path

_ROOT = REPLAY_DIR.parents[1]
_SCHEMA = json.loads((_ROOT / "schemas" / "deviation.schema.json").read_text(encoding="utf-8"))
_APP = _ROOT / "apps" / "web" / "app.py"


@pytest.fixture(autouse=True)
def _reset_daily_counter() -> None:
    service._daily_runs.clear()


def _write(path: Path, source: str, captured_at: str) -> None:
    payload = json.loads(next(REPLAY_DIR.glob("*.json")).read_text(encoding="utf-8"))
    payload.update(source=source, captured_at=captured_at)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# (a) live 가 gold 보다 우선 — 파일명·시각 순서가 gold 쪽에 유리해도 live 를 고른다.
def test_load_replay_prefers_live_over_gold(tmp_path: Path) -> None:
    _write(tmp_path / "a_live.json", "live", "2026-09-01T00:00:00+00:00")
    _write(tmp_path / "z_gold.json", "gold", "2026-09-28T00:00:00+00:00")
    assert load_replay(tmp_path).meta["source"] == "live"
    (tmp_path / "a_live.json").unlink()
    assert load_replay(tmp_path).meta["source"] == "gold"


# (b) 커밋된 재생 파일이 스키마를 100% 통과하고 risk_score == S×F.
def test_replay_records_are_schema_valid() -> None:
    result = load_replay()
    assert result.records
    payload = [r.model_dump() for r in result.records]
    assert not list(Draft7Validator(_SCHEMA).iter_errors(payload))
    assert all(r.risk_score == r.S * r.F for r in result.records)


# (c) 재생 → export_all 3개 파일, 워크시트 데이터 행 수 == records 수.
def test_export_files_from_replay() -> None:
    result = load_replay()
    files = service.export_files(result)
    assert set(files) == {"xlsx", "lopa", "report"}
    assert all(data for _, data in files.values())
    ws = openpyxl.load_workbook(io.BytesIO(files["xlsx"][1]))["HAZOP워크시트"]
    data_rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if isinstance(r[0], int)]
    assert len(data_rows) == len(result.records)
    assert len(service.worksheet_table(result)) == len(result.records)


# (d) 실호출 활성 판정.
@pytest.mark.parametrize(
    ("environ", "enabled"),
    [
        ({"ANTHROPIC_API_KEY": "k"}, False),  # ALLOW 없음
        ({"HAZOP_ALLOW_LIVE": "true"}, False),  # 키 없음
        ({"HAZOP_ALLOW_LIVE": "true", "ANTHROPIC_API_KEY": "  "}, False),  # 빈 키
        ({"HAZOP_ALLOW_LIVE": "false", "ANTHROPIC_API_KEY": "k"}, False),
        ({"HAZOP_ALLOW_LIVE": "true", "ANTHROPIC_API_KEY": "k"}, True),
    ],
)
def test_live_mode_gate(environ: dict[str, str], enabled: bool) -> None:
    assert (service.live_block_reason(environ) is None) is enabled


def test_sync_secrets_copies_into_environ() -> None:
    environ: dict[str, str] = {}
    service.sync_secrets({"HAZOP_ALLOW_LIVE": "true", "ANTHROPIC_API_KEY": "k", "X": "y"}, environ)
    assert environ == {"HAZOP_ALLOW_LIVE": "true", "ANTHROPIC_API_KEY": "k"}
    assert service.live_block_reason(environ) is None


# (e) 상한 — 세션 1회·일 5회.
def test_quota_rejects_second_session_run_and_sixth_daily_run() -> None:
    day = date(2026, 9, 29)
    assert service.reserve_live_run(0, day) is None
    reason = service.reserve_live_run(1, day)
    assert reason and "세션" in reason
    for _ in range(service.DAILY_LIMIT - 1):
        assert service.reserve_live_run(0, day) is None
    reason = service.reserve_live_run(0, day)
    assert reason and "5회" in reason
    assert service.reserve_live_run(0, date(2026, 9, 30)) is None  # 날짜가 바뀌면 초기화


# (f) mock + ALLOW 로 실호출 경로가 끝까지 돈다.
def test_live_path_runs_end_to_end_on_mock() -> None:
    environ = {"HAZOP_USE_MOCK": "true", "HAZOP_ALLOW_LIVE": "true"}
    assert service.live_block_reason(environ) is None
    replay = load_replay()
    result = service.run_live(json.dumps(replay.meta["node_meta"]), replay, environ)
    assert result.meta["source"] == "mock"
    assert result.meta["judged_cells"] == result.meta["expected_cells"] > 0
    assert result.meta["review_guidewords"] == []
    assert {(r.guideword, r.parameter) for r in result.records} == {
        (r.guideword, r.parameter) for r in replay.records if r.guideword in STANDARD_GUIDEWORDS
    }
    assert "판정 셀" in service.summary_line(result)
    assert set(service.export_files(result)) == {"xlsx", "lopa", "report"}


# (g) AppTest — 기동 → 프리셋 → 결과표, 예외 0건.
def test_app_preset_click_shows_table(monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("HAZOP_ALLOW_LIVE", raising=False)
    at = AppTest.from_file(str(_APP), default_timeout=30).run()
    assert not at.exception
    assert len(at.dataframe) == 0
    at.button[0].click().run()
    assert not at.exception
    assert len(at.dataframe) == 1
    assert len(at.dataframe[0].value) == len(load_replay().records)
