"""시험 공통 — 재생 데이터 고정(질문봉쇄 Q-01).

기존 화면·편집·mock 시험은 9/29~10/10 재생의 모양(골드셋 기준 곱 위험도, 84셀 등)을 전제로 쓰였다.
10/14 재캡처가 그 전제를 바꾸므로 기본은 `HAZOP_REPLAY_BEFORE=2026-10-14` 로 옛 재생에 묶는다 — 앱의 되돌리기 장치와 같은 경로.
현재 재생을 봐야 하는 시험은 `current_replays` 픽스처를 쓴다(tests/test_web_consistency.py·test_replay_current.py).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from apps.web.replay import REPLAY_BEFORE_ENV

if TYPE_CHECKING:
    from collections.abc import Iterator

PINNED_BEFORE = "2026-10-14"


@pytest.fixture(autouse=True)
def _pin_replays(request: pytest.FixtureRequest) -> Iterator[None]:
    if "current_replays" in request.fixturenames:
        yield
        return
    old = os.environ.get(REPLAY_BEFORE_ENV)
    os.environ[REPLAY_BEFORE_ENV] = PINNED_BEFORE
    yield
    if old is None:
        os.environ.pop(REPLAY_BEFORE_ENV, None)
    else:
        os.environ[REPLAY_BEFORE_ENV] = old


@pytest.fixture
def current_replays() -> Iterator[None]:
    """화면에 실제로 나가는(날짜 상한 없는) 재생으로 시험한다."""
    old = os.environ.pop(REPLAY_BEFORE_ENV, None)
    yield
    if old is not None:
        os.environ[REPLAY_BEFORE_ENV] = old
