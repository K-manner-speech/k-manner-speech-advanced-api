from urllib.error import HTTPError

from app.adapters.interview_provider import InterviewProviderError, OpenAIInterviewProvider
from app.core.dependencies import get_settings


def main() -> None:
    settings = get_settings()
    provider = OpenAIInterviewProvider(
        settings.openai_api_key.get_secret_value(), settings.openai_interview_model
    )
    try:
        result = provider.analyze_document(
            "FastAPI와 PostgreSQL 기반 백엔드 개발 및 테스트 자동화 경험이 있습니다. " * 5
        )
    except InterviewProviderError as error:
        cause = error.__cause__
        print(f"provider_error={error.code} retryable={error.retryable}")
        if isinstance(cause, HTTPError):
            print(f"http_status={cause.code}")
            print(cause.read().decode("utf-8", errors="replace"))
        raise SystemExit(1) from error
    print(
        "OPENAI_INTERVIEW_OK "
        f"sections={len(result.sections.model_dump())} citations={len(result.citations)}"
    )


if __name__ == "__main__":
    main()
