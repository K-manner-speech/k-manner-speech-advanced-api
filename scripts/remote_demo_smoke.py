from __future__ import annotations

import io
import os
import time
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import AppSettings


def load_test_env() -> None:
    for line in Path(".env.test").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", maxsplit=1)
            os.environ.setdefault(key, value)


def make_resume() -> bytes:
    text = (
        "백엔드 개발자 지원자입니다. Python과 FastAPI로 REST API를 개발했습니다. "
        "PostgreSQL 데이터 모델링과 테스트 자동화를 담당했고, 팀 프로젝트에서 장애 원인을 "
        "분석하여 재발 방지 테스트를 추가했습니다. 사용자 피드백을 반영해 응답 시간을 개선한 "
        "경험이 있습니다. 협업 시 작은 단위로 변경하고 검증 결과를 공유합니다."
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def require(response: httpx.Response, status: int) -> dict[str, Any]:
    if response.status_code != status:
        raise RuntimeError(f"{response.request.method} {response.request.url}: {response.text}")
    return response.json() if response.content else {}


def wait_for(
    client: httpx.Client, path: str, headers: dict[str, str], expected: str
) -> dict[str, Any]:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        payload = require(client.get(path, headers=headers), 200)
        status = str(payload["status"])
        if status == expected:
            return payload
        if status in {"failed", "invalidated"}:
            raise RuntimeError(f"remote job failed: {payload}")
        time.sleep(2)
    raise TimeoutError(f"timed out waiting for {path} => {expected}")


def main() -> None:
    load_test_env()
    settings = AppSettings()
    api_base = os.environ["API_BASE_URL"].rstrip("/")
    email = os.environ["SUPABASE_TEST_EMAIL"]
    password = os.environ["SUPABASE_TEST_PASSWORD"]
    with httpx.Client(timeout=30) as client:
        token_response = client.post(
            f"{settings.supabase_url}/auth/v1/token?grant_type=password",
            headers={
                "apikey": settings.supabase_service_role_key.get_secret_value(),
                "Content-Type": "application/json",
            },
            json={"email": email, "password": password},
        )
        token = require(token_response, 200)["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        setup = require(
            client.post(
                f"{api_base}/api/v1/interview-setups",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"desired_role": "백엔드 개발자", "application_type": "신입"},
            ),
            201,
        )
        document = require(
            client.post(
                f"{api_base}/api/v1/interview-documents",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                data={"setup_id": setup["id"], "document_type": "resume"},
                files={
                    "file": (
                        "codex-demo-resume.docx",
                        make_resume(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            ),
            201,
        )
        accepted = require(
            client.post(
                f"{api_base}/api/v1/interview-documents/{document['id']}/analyze",
                headers={**headers, "Idempotency-Key": str(uuid4())},
            ),
            202,
        )
        wait_for(
            client,
            f"{api_base}/api/v1/interview-analyses/{accepted['analysis_id']}",
            headers,
            "succeeded",
        )
        configuration = require(
            client.post(
                f"{api_base}/api/v1/interview-configurations",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={
                    "setup_id": setup["id"],
                    "analysis_ids": [accepted["analysis_id"]],
                    "conditions": {"difficulty": "junior", "language": "ko"},
                    "question_count": 3,
                },
            ),
            202,
        )
        wait_for(
            client,
            f"{api_base}/api/v1/interview-configurations/{configuration['configuration_id']}",
            headers,
            "ready",
        )
        questions = require(
            client.get(
                f"{api_base}/api/v1/interview-configurations/"
                f"{configuration['configuration_id']}/questions",
                headers=headers,
            ),
            200,
        )["questions"]
        if [question["sequence"] for question in questions] != [1, 2, 3]:
            raise RuntimeError(f"question order is invalid: {questions}")
        room = require(
            client.post(
                f"{api_base}/api/v1/interview-configurations/"
                f"{configuration['configuration_id']}/practice-room",
                headers={**headers, "Idempotency-Key": str(uuid4())},
            ),
            201,
        )
        message_url = f"{api_base}/api/v1/rooms/{room['id']}/messages"
        out_of_order_key = uuid4()
        out_of_order = client.post(
            message_url,
            headers={**headers, "Idempotency-Key": str(out_of_order_key)},
            json={
                "content": "두 번째 질문에 먼저 답변합니다.",
                "input_mode": "text",
                "current_interview_question_id": questions[1]["id"],
                "client_request_id": str(out_of_order_key),
            },
        )
        require(out_of_order, 409)
        ordered_key = uuid4()
        require(
            client.post(
                message_url,
                headers={**headers, "Idempotency-Key": str(ordered_key)},
                json={
                    "content": "FastAPI API와 회귀 테스트를 함께 개발했습니다.",
                    "input_mode": "text",
                    "current_interview_question_id": questions[0]["id"],
                    "client_request_id": str(ordered_key),
                },
            ),
            202,
        )
        print(
            "REMOTE_DEMO_OK "
            f"setup={setup['id']} document={document['id']} "
            f"configuration={configuration['configuration_id']} room={room['id']}"
        )


if __name__ == "__main__":
    main()
