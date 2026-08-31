from __future__ import annotations

import argparse
import base64
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

FIXTURES = {
    "short": "좋습니다. 그 경험에서 본인이 맡은 역할을 말씀해 주세요.",
    "medium": (
        "답변 감사합니다. 말씀하신 프로젝트에서 예상하지 못한 문제가 발생했을 때 "
        "어떤 기준으로 우선순위를 정했고, 팀원들과 어떻게 해결했는지 구체적으로 설명해 주세요."
    ),
    "long": (
        "지금까지의 설명을 바탕으로 조금 더 자세히 질문드리겠습니다. 서비스 장애가 발생한 상황에서 "
        "사용자 영향을 최소화하기 위해 가장 먼저 확인한 지표는 무엇이었는지, "
        "원인을 좁혀 가는 과정에서 "
        "어떤 가설을 세웠는지, 그리고 임시 조치와 근본적인 재발 방지 대책을 각각 어떻게 결정했는지 "
        "본인의 역할과 팀원들과의 협업 과정을 포함하여 순서대로 말씀해 주세요."
    ),
}


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def find_audio(value: object) -> str:
    if isinstance(value, dict):
        if value.get("type") == "audio" and isinstance(value.get("data"), str):
            return value["data"]
        for nested in value.values():
            try:
                return find_audio(nested)
            except LookupError:
                pass
    elif isinstance(value, list):
        for nested in value:
            try:
                return find_audio(nested)
            except LookupError:
                pass
    raise LookupError("audio data not found")


def batch_call(api_key: str, model: str, text: str, voice: str) -> tuple[float, int]:
    body = {
        "model": model,
        "input": (
            "차분하고 자연스러운 한국어 면접관의 목소리로 말하세요.\n"
            f"다음 문장만 한국어로 발화하세요: {text}"
        ),
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }
    request = Request(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={
            "x-goog-api-key": api_key,
            "Api-Revision": "2026-05-20",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.perf_counter()
    with urlopen(request, timeout=60) as response:  # noqa: S310
        payload = json.loads(response.read())
    elapsed_ms = (time.perf_counter() - started) * 1000
    pcm = base64.b64decode(find_audio(payload), validate=True)
    return elapsed_ms, len(pcm)


def streaming_call(
    api_key: str, model: str, text: str, voice: str
) -> tuple[float, float, int]:
    body = {
        "model": model,
        "input": (
            "차분하고 자연스러운 한국어 면접관의 목소리로 말하세요.\n"
            f"다음 문장만 한국어로 발화하세요: {text}"
        ),
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
        "stream": True,
    }
    request = Request(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={
            "x-goog-api-key": api_key,
            "Api-Revision": "2026-05-20",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    started = time.perf_counter()
    first_chunk_ms: float | None = None
    pcm_bytes = 0
    with urlopen(request, timeout=60) as response:  # noqa: S310
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            event = json.loads(data)
            delta = event.get("delta", {})
            if event.get("event_type") != "step.delta" or delta.get("type") != "audio":
                continue
            chunk = base64.b64decode(delta["data"], validate=True)
            if first_chunk_ms is None:
                first_chunk_ms = (time.perf_counter() - started) * 1000
            pcm_bytes += len(chunk)
    complete_ms = (time.perf_counter() - started) * 1000
    if first_chunk_ms is None:
        raise RuntimeError("stream completed without audio")
    return first_chunk_ms, complete_ms, pcm_bytes


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--voice", default="Kore")
    parser.add_argument("--mode", choices=("batch", "stream"), default="batch")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    env = load_env(Path(".env"))
    api_key = env["GEMINI_API_KEY"]
    model = env["GEMINI_TTS_MODEL"]
    results: dict[str, object] = {
        "mode": args.mode,
        "model": model,
        "voice": args.voice,
        "generated_at": datetime.now(UTC).isoformat(),
        "fixtures": {},
    }
    for name, text in FIXTURES.items():
        for _ in range(args.warmups):
            if args.mode == "batch":
                batch_call(api_key, model, text, args.voice)
            else:
                streaming_call(api_key, model, text, args.voice)
        samples: list[float] = []
        complete_samples: list[float] = []
        sizes: list[int] = []
        for run in range(args.runs):
            if args.mode == "batch":
                elapsed, size = batch_call(api_key, model, text, args.voice)
                complete = elapsed
            else:
                elapsed, complete, size = streaming_call(api_key, model, text, args.voice)
            samples.append(elapsed)
            complete_samples.append(complete)
            sizes.append(size)
            print(
                f"{args.mode} {name} {run + 1}/{args.runs}: "
                f"first={elapsed:.0f} ms complete={complete:.0f} ms",
                flush=True,
            )
        results["fixtures"][name] = {
            "characters": len(text),
            "samples_ms": samples,
            "p50_ms": percentile(samples, 0.50),
            "p95_ms": percentile(samples, 0.95),
            "mean_ms": statistics.mean(samples),
            "complete_samples_ms": complete_samples,
            "complete_p50_ms": percentile(complete_samples, 0.50),
            "complete_p95_ms": percentile(complete_samples, 0.95),
            "pcm_bytes": sizes,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
