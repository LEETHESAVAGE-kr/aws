"""spec:gold-dataset 오프라인 테스트 (T-02~T-11 검증 항목).

fixture xlsx 는 저장소에 바이너리로 커밋하지 않고 `tmp_path` 에 생성한다
(design.md §2 의 `tests/fixtures/gold/*.xlsx` 를 코드로 대체 — 압축 구현 원칙).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import openpyxl
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools._gold.models import REQUIRED_COLUMNS  # noqa: E402
from tools.build_gold import (  # noqa: E402  (위 sys.path 보정 이후여야 한다)
    SCHEMA_PATH,
    ColumnMapper,
    DatasetValidator,
    GuidewordParser,
    JsonWriter,
    MultiValueParser,
    NodeSplitter,
    RowTransformer,
    StratifiedSplitter,
    XlsxLoader,
    build_parser,
    decide_splitter,
    parse_rating_scale,
    validate_sf,
)

SHEET = "HAZOP워크시트"
NODE_N1 = "N1 벙커링선 매니폴드"

SAMPLE_VALID_ROWS: list[list[Any]] = [
    [1, NODE_N1, "No (유량)", "이송 개시 후 유량 전무",
     "1. 펌프 기동 실패\n2. 토출밸브 미개방", "데드헤드 과압", "압력계 감시; 절차서",
     2, 3, 6, "PB-04 감시", "기타"],
    [2, NODE_N1, "More (압력)", "토출압 과다",
     "하류 밸브 폐쇄", "개스킷 밀림 → 누출", "수동 ESD",
     3, 3, 9, "MB-01 자동연동", "S2"],
    [3, NODE_N1, "Less(유량)", "유량 부족",
     "스트레이너 막힘", "이송 지연", "유량계",
     3, 2, 6, "PB-03", None],
    [4, NODE_N1, "Reverse", "역류",
     "체크밸브 고장", "인벤토리 역이동", "체크밸브",
     1, 1, 1, "PB-01", "S3"],
    [5, NODE_N1, "고(온도)", "라인 온도 상승",
     "예냉 절차 생략", "플래싱·서지", "절차서",
     5, 1, 5, "PB-03 예냉 확인", "S1"],
]

EXPECTED_NODE_META = {
    "substance": "NH3",
    "phase": "unknown",
    "P_kPag": None,
    "T_degC": None,
    "equipment": ["벙커링선 매니폴드"],
    "safeguards": [],
}


def _write_xlsx(
    path: Path,
    rows: list[list[Any]],
    header: list[str] | None = None,
    sheet: str = SHEET,
) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    worksheet.append(list(header or REQUIRED_COLUMNS))
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    return path


@pytest.fixture
def sample_valid(tmp_path: Path) -> Path:
    return _write_xlsx(tmp_path / "sample_valid.xlsx", SAMPLE_VALID_ROWS)


@pytest.fixture
def sample_merged(tmp_path: Path) -> Path:
    """`노드` 열이 병합되어 2·3행이 빈 셀인 상황 (REQ-05 forward-fill)."""
    rows = [
        [1, NODE_N1, "No (유량)", "유량 전무", "펌프 정지", "과압", "압력계", 2, 3, 6, "PB-04", "기타"],
        [2, None, "More (압력)", "토출압 과다", "밸브 폐쇄", "누출", "ESD", 3, 3, 9, "MB-01", "S2"],
        [3, "", "Less (온도)", "과냉", "냉동계 이상", "저온취성", "온도계", 3, 2, 6, "PB-04", "S3"],
    ]
    return _write_xlsx(tmp_path / "sample_merged.xlsx", rows)


@pytest.fixture
def sample_bad_sf(tmp_path: Path) -> Path:
    """2행 S=6(범위 밖), 3행 위험도 셀 불일치, 4행 deviation 공백."""
    rows = [
        [1, NODE_N1, "No (유량)", "유량 전무", "펌프 정지", "과압", "압력계", 2, 3, 6, "PB-04", "기타"],
        [2, NODE_N1, "More (압력)", "토출압 과다", "밸브 폐쇄", "누출", "ESD", 6, 3, 18, "MB-01", "S2"],
        [3, NODE_N1, "Less (온도)", "과냉", "냉동계 이상", "저온취성", "온도계", 3, 2, 99, "PB-04", "S3"],
        [4, NODE_N1, "More (온도)", "  ", "예냉 생략", "서지", "절차서", 3, 3, 9, "PB-03", "S2"],
    ]
    return _write_xlsx(tmp_path / "sample_bad_sf.xlsx", rows)


def _transform(path: Path, sheet: str = SHEET) -> tuple[list[Any], RowTransformer]:
    rows = ColumnMapper().validate_and_rename(XlsxLoader().load(path, sheet))
    transformer = RowTransformer(prefix="nh3", substance="NH3")
    return transformer.transform(rows), transformer


# ── T-02 XlsxLoader (REQ-01) ────────────────────────────────────────────────
def test_loader_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        XlsxLoader().load(tmp_path / "nope.xlsx", SHEET)


def test_loader_missing_sheet(sample_valid: Path) -> None:
    with pytest.raises(ValueError, match="sheet '없는시트' not found"):
        XlsxLoader().load(sample_valid, "없는시트")


def test_loader_returns_rows(sample_valid: Path) -> None:
    rows = XlsxLoader().load(sample_valid, SHEET)
    assert len(rows) == 5
    assert rows[0]["가이드워드"] == "No (유량)"


def test_loader_skips_blank_rows(tmp_path: Path) -> None:
    rows_in = [SAMPLE_VALID_ROWS[0], [None] * 12, SAMPLE_VALID_ROWS[1]]
    path = _write_xlsx(tmp_path / "blank.xlsx", rows_in)
    assert len(XlsxLoader().load(path, SHEET)) == 2


# ── T-03 ColumnMapper (REQ-02) ──────────────────────────────────────────────
def test_column_order_invariant(tmp_path: Path) -> None:
    order = [11, 0, 5, 2, 9, 1, 7, 3, 10, 4, 8, 6]  # 열 순서 뒤섞기
    header = [REQUIRED_COLUMNS[i] for i in order]
    rows = [[row[i] for i in order] for row in SAMPLE_VALID_ROWS]
    path = _write_xlsx(tmp_path / "shuffled.xlsx", rows, header=header)
    records, _ = _transform(path)
    assert [r.id for r in records] == [f"nh3-{i:03d}" for i in range(1, 6)]
    assert records[0].guideword == "No"
    assert records[0].deviation == "이송 개시 후 유량 전무"


def test_column_missing_raises(tmp_path: Path) -> None:
    header = list(REQUIRED_COLUMNS)
    header[6] = "안전장치"  # "기존 안전장치(Before)" 누락
    path = _write_xlsx(tmp_path / "missing.xlsx", SAMPLE_VALID_ROWS, header=header)
    with pytest.raises(ValueError, match=r"missing columns: \['기존 안전장치\(Before\)'\]"):
        ColumnMapper().validate_and_rename(XlsxLoader().load(path, SHEET))


def test_column_strip_whitespace(tmp_path: Path) -> None:
    header = [f"  {c} " for c in REQUIRED_COLUMNS]
    path = _write_xlsx(tmp_path / "spaced.xlsx", SAMPLE_VALID_ROWS, header=header)
    records, _ = _transform(path)
    assert len(records) == 5


def test_column_strip_whitespace_without_loader() -> None:
    """ColumnMapper 자체의 strip 을 고정한다 (XlsxLoader 가 이미 strip 하므로 직접 호출)."""
    row = {f"  {c} ": value for c, value in zip(REQUIRED_COLUMNS, SAMPLE_VALID_ROWS[0], strict=True)}
    mapped = ColumnMapper().validate_and_rename([row])
    assert mapped[0]["deviation"] == "이송 개시 후 유량 전무"
    assert mapped[0]["node_raw"] == NODE_N1


# ── T-04 GuidewordParser (REQ-04) ───────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("More (압력)", ("More", "압력")),
        ("Less(유량)", ("Less", "유량")),
        ("Reverse", ("Reverse", "")),
        ("고(온도)", ("More", "온도")),
    ],
)
def test_guideword_split(raw: str, expected: tuple[str, str]) -> None:
    assert GuidewordParser().parse(raw) == expected


def test_guideword_fullwidth_paren() -> None:
    assert GuidewordParser().parse("Less（온도）") == ("Less", "온도")


def test_guideword_empty_returns_blank() -> None:
    assert GuidewordParser().parse(None) == ("", "")
    assert GuidewordParser().parse("   ") == ("", "")


def test_guideword_unmapped_kept_as_is() -> None:
    """원본 워크시트의 `Too early (개시)` 처럼 표준 7종 밖이면 원본을 유지한다 (REQ-04)."""
    assert GuidewordParser().parse("Too early (개시)") == ("Too early", "개시")


# ── T-05 MultiValueParser (REQ-06) ──────────────────────────────────────────
def test_multivalue_newline() -> None:
    assert MultiValueParser().parse("1. 압력 상승\n2. 배관 파열") == ["압력 상승", "배관 파열"]


def test_multivalue_semicolon() -> None:
    assert MultiValueParser().parse("PSV 설치; 압력계") == ["PSV 설치", "압력계"]


def test_multivalue_single() -> None:
    assert MultiValueParser().parse("펌프 기동 실패") == ["펌프 기동 실패"]


def test_multivalue_none() -> None:
    assert MultiValueParser().parse(None) == []
    assert MultiValueParser().parse("   ") == []


# ── T-06 NodeParser (REQ-05) ────────────────────────────────────────────────
def test_node_forwardfill(sample_merged: Path) -> None:
    records, _ = _transform(sample_merged)
    assert [r.node for r in records] == ["N1", "N1", "N1"]
    assert records[0].node_meta is records[2].node_meta  # 같은 노드는 같은 객체


def test_node_unknown_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    rows = [[1, "벙커링선 매니폴드", "No (유량)", "유량 전무", "펌프 정지", "과압",
             "압력계", 2, 3, 6, "PB-04", "기타"]]
    path = _write_xlsx(tmp_path / "unknown_node.xlsx", rows)
    with caplog.at_level(logging.WARNING, logger="build_gold"):
        records, _ = _transform(path)
    assert records[0].node == "UNKNOWN"
    assert any("UNKNOWN" in message for message in caplog.messages)


def test_node_meta_parsed_from_cell(tmp_path: Path) -> None:
    rows = [[1, "N9 액상 NH3 저장탱크 (300 kPag, −33 °C)", "No (유량)", "유량 전무",
             "펌프 정지", "과압", "압력계", 2, 3, 6, "PB-04", "기타"]]
    path = _write_xlsx(tmp_path / "meta.xlsx", rows)
    records, _ = _transform(path)
    meta = records[0].node_meta
    assert (meta.substance, meta.phase) == ("NH3", "liquid")
    assert (meta.P_kPag, meta.T_degC) == (300.0, -33.0)


# ── T-07 FieldValidator (REQ-07) ────────────────────────────────────────────
def test_risk_score(sample_valid: Path) -> None:
    records, _ = _transform(sample_valid)
    assert all(r.risk_score == (r.S or 0) * (r.F or 0) for r in records)


def test_invalid_sf_to_null(sample_bad_sf: Path) -> None:
    records, _ = _transform(sample_bad_sf)
    bad = next(r for r in records if r.id == "nh3-002")
    assert bad.S is None
    assert bad.risk_score is None


def test_risk_mismatch_recomputed(sample_bad_sf: Path) -> None:
    records, transformer = _transform(sample_bad_sf)
    mismatched = next(r for r in records if r.id == "nh3-003")
    assert mismatched.risk_score == 6  # 셀 값 99 를 버리고 S×F 채택
    assert transformer.field_validator.risk_mismatch_rows == 1


def test_skip_empty_deviation(sample_bad_sf: Path) -> None:
    records, transformer = _transform(sample_bad_sf)
    assert [r.id for r in records] == ["nh3-001", "nh3-002", "nh3-003"]
    assert transformer.field_validator.skipped_rows == 1


@pytest.mark.parametrize(
    ("value", "expected"), [(1, 1), (5, 5), (0, None), (6, None), (3.0, 3), (2.5, None),
                            (None, None), ("", None), ("4", 4)]
)
def test_validate_sf(value: Any, expected: int | None) -> None:
    assert validate_sf(value) == expected


# ── T-08 DatasetValidator (REQ-03) ──────────────────────────────────────────
def test_schema_valid(sample_valid: Path) -> None:
    records, _ = _transform(sample_valid)
    assert DatasetValidator().validate([r.to_dict() for r in records], SCHEMA_PATH) == []


def test_record_count(sample_valid: Path) -> None:
    records, _ = _transform(sample_valid)
    assert len(records) == 5


def test_id_unique(sample_valid: Path) -> None:
    records, _ = _transform(sample_valid)
    ids = [r.id for r in records]
    assert len(set(ids)) == len(ids)


def test_schema_catches_bad_record(sample_valid: Path) -> None:
    records, _ = _transform(sample_valid)
    payload = [r.to_dict() for r in records]
    payload[0]["S"] = 9  # 스키마 범위 밖
    payload[1]["id"] = payload[0]["id"]  # 중복 id
    errors = DatasetValidator().validate(payload, SCHEMA_PATH)
    assert len(errors) >= 2
    assert any("duplicate id" in e for e in errors)


# ── T-09 Splitter (REQ-08) ──────────────────────────────────────────────────
@pytest.fixture
def multinode_records(tmp_path: Path) -> list[Any]:
    rows: list[list[Any]] = []
    for index in range(1, 13):
        node = f"N{(index - 1) // 4 + 1} 노드{(index - 1) // 4 + 1}"
        guideword = ["No (유량)", "More (압력)", "Less (온도)", "Reverse (유량)"][index % 4]
        rows.append([index, node, guideword, f"이탈 {index}", "원인", "결과", "안전장치",
                     3, 2, 6, "권고", "S1"])
    path = _write_xlsx(tmp_path / "multinode.xlsx", rows)
    records, _ = _transform(path)
    return records


def test_node_split(multinode_records: list[Any]) -> None:
    tune, holdout = NodeSplitter().split(multinode_records, ["N1"])
    assert {r.node for r in tune} == {"N1"}
    assert "N1" not in {r.node for r in holdout}


def test_split_count_sum(multinode_records: list[Any]) -> None:
    tune, holdout, config = decide_splitter(multinode_records, "node", ["N1"], 42)
    assert len(tune) + len(holdout) == len(multinode_records)
    assert config.tune_count == len(tune)


def test_stratified_reproducible(multinode_records: list[Any]) -> None:
    first = StratifiedSplitter().split(multinode_records, seed=42)
    second = StratifiedSplitter().split(multinode_records, seed=42)
    assert [r.id for r in first[0]] == [r.id for r in second[0]]
    assert [r.id for r in first[1]] == [r.id for r in second[1]]
    assert len(first[0]) + len(first[1]) == len(multinode_records)


def test_split_config_fields(multinode_records: list[Any]) -> None:
    _, _, config = decide_splitter(multinode_records, "node", ["N1"], 42)
    payload = config.to_dict()
    for key in ("split_type", "tune_nodes", "tune_count", "eval_count", "timestamp"):
        assert key in payload
    assert payload["split_type"] == "node"


def test_split_node_fallback_single_node(sample_valid: Path) -> None:
    """노드가 1개뿐이면 stratified 로 자동 전환된다 (design.md §6)."""
    records, _ = _transform(sample_valid)
    _, _, config = decide_splitter(records, "node", ["N1"], 42)
    assert config.split_type == "stratified"
    assert config.fallback_reason is not None


# ── T-10 JsonWriter (REQ-03·09, NFR-G04) ────────────────────────────────────
def test_writer_utf8(tmp_path: Path, sample_valid: Path) -> None:
    records, _ = _transform(sample_valid)
    out = tmp_path / "out.json"
    JsonWriter().write([r.to_dict() for r in records], out)
    assert not out.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM 없음
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded[0]["deviation"] == "이송 개시 후 유량 전무"


def test_writer_dry_run(tmp_path: Path) -> None:
    out = tmp_path / "dry.json"
    JsonWriter().write([{"id": "nh3-001"}], out, dry_run=True)
    assert not out.exists()


def test_writer_indent(tmp_path: Path) -> None:
    out = tmp_path / "indent.json"
    JsonWriter().write([{"id": "nh3-001"}], out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[1].startswith("  {")
    assert lines[2].startswith('    "id"')


# ── 평가기준 시트 ───────────────────────────────────────────────────────────
def test_parse_rating_scale() -> None:
    matrix: list[tuple[Any, ...]] = [
        ("구분", "등급", "정의"),
        ("S 강도", 1, "아차사고 — 부상 없음"),
        ("F 빈도", 3, "가능 — 설비 수명 중 1회 정도"),
        (None, None, None),
        ("위험도 구간", "판정", "조치"),
        ("15~25", "높음", "허용 불가 — 즉시 개선"),
        ("주: 스크리닝용 정성 등급임.", None, None),
    ]
    scale = parse_rating_scale(matrix, "평가기준")
    assert scale["severity"] == [{"grade": 1, "definition": "아차사고 — 부상 없음"}]
    assert scale["frequency"][0]["grade"] == 3
    assert scale["risk_bands"] == [
        {"range": "15~25", "judgement": "높음", "action": "허용 불가 — 즉시 개선"}
    ]
    assert scale["notes"] and scale["notes"][0].startswith("주:")


# ── T-11 CLI 통합 (REQ-01·09) ───────────────────────────────────────────────
def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "build_gold.py"), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )


def test_cli_missing_input() -> None:
    assert _run_cli([]).returncode == 2


def test_cli_missing_file_exit_1(tmp_path: Path) -> None:
    result = _run_cli(["--input", str(tmp_path / "nope.xlsx")])
    assert result.returncode == 1
    assert "FileNotFoundError" in result.stderr


def test_cli_dry_run_no_files(sample_valid: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "gold"
    result = _run_cli(
        ["--input", str(sample_valid), "--output-dir", str(out_dir), "--dry-run"]
    )
    assert result.returncode == 0
    assert not out_dir.exists()


def test_cli_summary_output(sample_valid: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "gold"
    result = _run_cli(["--input", str(sample_valid), "--output-dir", str(out_dir)])
    assert result.returncode == 0
    assert "완료:" in result.stdout
    assert "5 레코드" in result.stdout
    assert (out_dir / "hazop_nh3.json").exists()
    assert (out_dir / "split_node.json").exists()


def test_cli_parser_defaults() -> None:
    args = build_parser().parse_args(["--input", "data/raw/x.xlsx"])
    assert args.sheet == "HAZOP워크시트"
    assert args.split == "node"
    assert args.seed == 42


def test_golden_snapshot(sample_valid: Path) -> None:
    """sample_valid.xlsx 전체 변환 결과 스냅샷 (T-11 `expected_valid.json` 대체)."""
    records, _ = _transform(sample_valid)
    payload = [r.to_dict() for r in records]
    expected_head = {
        "id": "nh3-001",
        "node": "N1",
        "node_meta": EXPECTED_NODE_META,
        "guideword": "No",
        "parameter": "유량",
        "deviation": "이송 개시 후 유량 전무",
        "causes": ["펌프 기동 실패", "토출밸브 미개방"],
        "consequences": ["데드헤드 과압"],
        "safeguards_before": ["압력계 감시", "절차서"],
        "S": 2,
        "F": 3,
        "risk_score": 6,
        "recommendations": ["PB-04 감시"],
        "scenario": "기타",
    }
    assert payload[0] == expected_head
    assert [(r["guideword"], r["parameter"]) for r in payload] == [
        ("No", "유량"), ("More", "압력"), ("Less", "유량"), ("Reverse", ""), ("More", "온도"),
    ]
    assert payload[2]["scenario"] is None
    assert [r["id"] for r in payload] == [f"nh3-{i:03d}" for i in range(1, 6)]
