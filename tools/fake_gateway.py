"""가짜 게이트웨이 — 대회 API 키 수령 전 F-01 전환 경로를 키 없이 끝까지 돌려 보는 로컬 서버.

Anthropic Messages 형식(`POST /v1/messages`)으로 응답한다. 앱은 `ANTHROPIC_BASE_URL` 을 이 서버로
돌리기만 하면 실 SDK·`AnthropicClient`·`service.run_quick` 경로를 그대로 탄다(코드 분기 없음).
응답 내용은 재생 레코드에서 만든다(`service._mock_factory` 재사용) — LLM 품질 시험이 아니라 **배선 시험**이다.

용도
- F-01 리허설: 키 형식(`x-api-key` / `Bearer`)·모델 ID 전달·tool 강제(`tool_choice`)가 게이트웨이까지 가는지 본다.
- 발표 리허설: `--latency real` 이면 J-03 실측 지연(해석 3·열거 22·판정 41초)을 흉내 내 대본 시간을 잰다.
- 실패 경로 리허설: `--fail 529:3` 이면 처음 3요청을 529 로 돌려 재시도·실패 상자·"실측 사례 보기"를 확인한다.

실행 예
    .venv/Scripts/python -m tools.fake_gateway --port 8787 --latency real
    # 다른 셸에서
    $env:ANTHROPIC_BASE_URL="http://127.0.0.1:8787"; $env:ANTHROPIC_API_KEY="fake"; $env:HAZOP_ALLOW_LIVE="true"
    .venv/Scripts/python -m streamlit run apps/web/app.py
"""

from __future__ import annotations

import argparse
import contextlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Final

from apps.web import service
from apps.web.replay import load_replays
from core.llm.client import STRUCTURED_OUTPUT_TOOL
from core.llm.types import Message

#: J-03 실측(docs/진행로그.md 2026-09-29 J 항): 열거 22초 + 판정 41초, 해석 약 3초.
REAL_LATENCY_S: Final[dict[str, float]] = {"parse": 3.0, "enumerate": 22.0, "judge": 41.0}
_PARSE_MARKER: Final[str] = "노드 정의"


def stage_of(system: str) -> str:
    if _PARSE_MARKER in system:
        return "parse"
    if "파라미터 축" in system:
        return "enumerate"
    return "judge"


class Gateway:
    """요청 처리 상태 — 로그·실패 주입·지연. 스레드 여러 개가 같이 쓴다(병렬 4)."""

    def __init__(self, node: str = "N1", latency: dict[str, float] | None = None,
                 fail_status: int = 0, fail_count: int = 0) -> None:
        self.answer = service._mock_factory(load_replays()[node])  # noqa: SLF001
        self.latency = latency or {}
        self.fail_status, self.fail_left = fail_status, fail_count
        self.log: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def handle(self, headers: dict[str, str], body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        system = "\n".join(b.get("text", "") for b in body.get("system") or [] if isinstance(b, dict))
        stage = stage_of(system)
        entry = {
            "stage": stage,
            "model": body.get("model"),
            "auth": "bearer" if headers.get("authorization", "").lower().startswith("bearer ")
            else "x-api-key" if headers.get("x-api-key") else "none",
            "tool_choice": (body.get("tool_choice") or {}).get("name"),
            "has_temperature": "temperature" in body,
        }
        with self._lock:
            failing = self.fail_left > 0
            if failing:
                self.fail_left -= 1
            entry["status"] = self.fail_status if failing else 200
            self.log.append(entry)
        if failing:
            return self.fail_status, {"type": "error", "error": {"type": "overloaded_error", "message": "fake"}}
        time.sleep(self.latency.get(stage, 0.0))
        if stage == "parse":
            content = service._mock_parse_factory().content  # noqa: SLF001
        else:
            user = body["messages"][0]["content"]
            text = user if isinstance(user, str) else "".join(b.get("text", "") for b in user)
            # Y-2: 기준별 S·F 상한은 구조화 출력 tool 의 input_schema 에 있다 — 재생 응답을 그 상한에 맞춘다
            schema = next((t.get("input_schema") for t in body.get("tools") or []
                           if t.get("name") == STRUCTURED_OUTPUT_TOOL), None)
            content = self.answer(system, [Message(role="user", content=text)], response_schema=schema).content
        return 200, {
            "id": f"msg_fake_{len(self.log)}",
            "type": "message",
            "role": "assistant",
            "model": body.get("model"),
            "content": [{"type": "tool_use", "id": f"toolu_fake_{len(self.log)}",
                         "name": STRUCTURED_OUTPUT_TOOL, "input": json.loads(content or "{}")}],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 500,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        }


def make_server(gateway: Gateway, port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 — http.server 규약
            if not self.path.startswith("/v1/messages"):
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
            status, payload = gateway.handle({k.lower(): v for k, v in self.headers.items()}, body)
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_: Any) -> None:  # 요청 로그는 gateway.log 로만
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--node", default="N1", help="응답을 만들 재생 노드(data/replay)")
    parser.add_argument("--latency", choices=["none", "real"], default="none")
    parser.add_argument("--fail", default="", help="STATUS:N — 처음 N 요청을 STATUS 로 실패(예: 529:3)")
    args = parser.parse_args(argv)
    status, _, count = args.fail.partition(":")
    gateway = Gateway(args.node, REAL_LATENCY_S if args.latency == "real" else None,
                      int(status or 0), int(count or 0))
    server = make_server(gateway, args.port)
    print(f"fake gateway http://127.0.0.1:{server.server_port} (node={args.node}, latency={args.latency}, "
          f"fail={args.fail or '없음'}) — Ctrl+C 로 종료", flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    for entry in gateway.log:
        print(json.dumps(entry, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
