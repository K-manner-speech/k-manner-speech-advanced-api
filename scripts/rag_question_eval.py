"""운영 RAG 근거로 실제 면접 질문을 생성하고 질문 자체의 품질을 평가한다."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.interview_provider import (  # noqa: E402
    InterviewQuestionResult,
)
from app.ai.prompts.composer import PromptComposer  # noqa: E402
from app.ai.providers.openai import (  # noqa: E402
    OpenAIEmbeddingClient,
    OpenAIResponsesClient,
)
from app.core.config import AppSettings  # noqa: E402
from app.schemas.base import ContractModel  # noqa: E402
from scripts.rag_eval import (  # noqa: E402
    CaseResult,
    GoldCase,
    _embed_batches,
    apply_relevance_check,
    build_corpus,
    build_query_text,
    evaluate,
    load_dataset,
    stratified_cases,
)


class QuestionQualityDecision(ContractModel):
    case_id: str
    grounding: bool
    premise_accuracy: bool
    role_relevance: int
    specificity: int
    clarity: int
    answer_leakage: bool
    duplicate_with_case_ids: list[str]
    reason: str


class QuestionQualityResult(ContractModel):
    decisions: list[QuestionQualityDecision]


@dataclass(frozen=True, slots=True)
class GeneratedCaseQuestion:
    case_id: str
    expected_behavior: str
    desired_role: str
    query: str
    question: str
    source_chunk_keys: tuple[str, ...]
    evidence: tuple[str, ...]
    supported_claims: tuple[str, ...]
    unsupported_claims: tuple[str, ...]


def _chunk_uuid(document_id: str, chunk_index: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"rag-eval:{document_id}:{chunk_index}")


def generate_questions(
    *,
    cases: list[GoldCase],
    relevance_results: list[CaseResult],
    provider: OpenAIResponsesClient,
) -> tuple[list[GeneratedCaseQuestion], int, float]:
    case_by_id = {case.case_id: case for case in cases}
    generated: list[GeneratedCaseQuestion] = []
    calls = 0
    started = time.monotonic()
    instructions = PromptComposer.default().task_instruction(
        "interview_question_generation"
    ).format(question_count=1)
    for result in relevance_results:
        if result.expected_behavior == "insufficient_evidence" or not result.retrieved:
            continue
        case = case_by_id[result.case_id]
        details = {
            (str(item["document_id"]), int(item["chunk_index"])): item
            for item in result.relevance_details
        }
        evidence_payload = []
        allowed: set[tuple[UUID, UUID, str]] = set()
        document_uuid = uuid5(NAMESPACE_URL, f"rag-eval-document:{case.document_id}")
        for item in result.retrieved:
            chunk_uuid = _chunk_uuid(item.document_id, item.chunk_index)
            detail = details[(item.document_id, item.chunk_index)]
            evidence_payload.append(
                {
                    "chunk_id": str(chunk_uuid),
                    "document_id": str(document_uuid),
                    "section": "resume",
                    "text": item.text,
                    "support_level": detail["support_level"],
                    "supported_claims": detail["supported_claims"],
                    "unsupported_claims": detail["unsupported_claims"],
                }
            )
            allowed.add((chunk_uuid, document_uuid, "resume"))
        output = provider.generate_structured(
            instructions=instructions,
            input_text=json.dumps(
                {
                    "conditions": {"evaluation_query": case.query},
                    "desired_role": case.desired_role,
                    "evidence": evidence_payload,
                },
                ensure_ascii=False,
            ),
            schema_name="rag_eval_interview_question_generation",
            result_type=InterviewQuestionResult,
        )
        output.validate_count(1)
        question = output.questions[0]
        actual = {
            (ref.chunk_id, ref.document_id, ref.section) for ref in question.source_refs
        }
        if not actual or not actual <= allowed:
            raise ValueError(f"invalid source refs for {case.case_id}")
        generated.append(
            GeneratedCaseQuestion(
                case_id=case.case_id,
                expected_behavior=case.expected_behavior,
                desired_role=case.desired_role,
                query=case.query,
                question=question.text,
                source_chunk_keys=tuple(
                    f"{item.document_id}#{item.chunk_index}" for item in result.retrieved
                ),
                evidence=tuple(item.text for item in result.retrieved),
                supported_claims=tuple(
                    claim
                    for item in result.relevance_details
                    for claim in item["supported_claims"]
                ),
                unsupported_claims=tuple(
                    claim
                    for item in result.relevance_details
                    for claim in item["unsupported_claims"]
                ),
            )
        )
        calls += 1
    return generated, calls, time.monotonic() - started


def judge_questions(
    questions: list[GeneratedCaseQuestion], provider: OpenAIResponsesClient
) -> tuple[list[QuestionQualityDecision], float]:
    instructions = """
당신은 이력서 기반 구조화 면접 질문 품질 평가자입니다. 각 질문을 독립적으로 평가하세요.
grounding은 질문의 전제가 제공된 evidence와 supported_claims에 직접 근거할 때만 true입니다.
premise_accuracy는 unsupported_claims를 지원자가 수행했다고 가정하지 않을 때만 true입니다.
role_relevance, specificity, clarity는 1~5 정수로 평가하세요.
answer_leakage는 '이력서 주장 확인'과 '정답 유도'를 엄격히 구분해 판정하세요.
- evidence 또는 supported_claims에 명시된 프로젝트명, 문제, 기술, 수행 행동, 수치, 결과를
  질문의 배경으로 인용하는 것은 answer_leakage가 아닙니다. 여러 항목을 함께 인용해도
  모두 이력서에 있고 지원자에게 구체적인 본인 행동과 판단을 설명하게 한다면 허용합니다.
- 이력서에 적힌 'fetch join과 DTO로 개선했다'를 언급한 뒤 재현 과정, 선택 이유, 본인 역할,
  적용 범위 또는 검증 방법을 묻는 것은 정상적인 사실 검증 질문입니다.
- evidence에 없는 해결책·모범답안·판단을 새로 알려주거나, 질문 자체가 원인 분석부터
  해결 순서·선택 이유·트레이드오프·검증 방법까지 대신 설명하여 지원자가 동의만 하면
  답할 수 있게 만들 때만 answer_leakage=true입니다.
- 단순히 질문이 구체적이거나 기술명이 포함됐다는 이유만으로 true로 판정하지 마세요.
다른 질문과 실질적으로 같은 경험과 요구를 반복하면 해당 case_id를
duplicate_with_case_ids에 적으세요.
입력된 모든 case_id를 정확히 한 번씩 반환하세요.
""".strip()
    started = time.monotonic()
    result = provider.generate_structured(
        instructions=instructions,
        input_text=json.dumps(
            {"questions": [asdict(item) for item in questions]}, ensure_ascii=False
        ),
        schema_name="rag_question_quality_evaluation",
        result_type=QuestionQualityResult,
    )
    expected = {item.case_id for item in questions}
    actual = {item.case_id for item in result.decisions}
    if actual != expected or len(actual) != len(result.decisions):
        raise ValueError("question quality judge returned invalid case ids")
    return result.decisions, time.monotonic() - started


def quality_metrics(
    questions: list[GeneratedCaseQuestion], decisions: list[QuestionQualityDecision]
) -> dict[str, float | int]:
    if not decisions:
        raise ValueError("quality decisions must not be empty")
    total = len(decisions)
    passing = [
        item
        for item in decisions
        if item.grounding
        and item.premise_accuracy
        and item.role_relevance >= 4
        and item.specificity >= 4
        and item.clarity >= 4
        and not item.answer_leakage
    ]
    return {
        "generated_questions": len(questions),
        "grounding_rate": sum(item.grounding for item in decisions) / total,
        "premise_accuracy_rate": sum(item.premise_accuracy for item in decisions) / total,
        "role_relevance_ge4_rate": sum(item.role_relevance >= 4 for item in decisions)
        / total,
        "specificity_ge4_rate": sum(item.specificity >= 4 for item in decisions) / total,
        "clarity_ge4_rate": sum(item.clarity >= 4 for item in decisions) / total,
        "answer_leakage_rate": sum(item.answer_leakage for item in decisions) / total,
        "cross_case_similarity_flag_rate": sum(
            bool(item.duplicate_with_case_ids) for item in decisions
        )
        / total,
        "all_quality_gates_rate": len(passing) / total,
    }


def usage_delta(current: dict[str, int], previous: dict[str, int]) -> dict[str, int]:
    return {key: value - previous.get(key, 0) for key, value in current.items()}


def render_question_review(
    questions: list[GeneratedCaseQuestion],
    decisions: list[QuestionQualityDecision],
) -> str:
    """사람이 질문과 근거 및 판정을 한 화면에서 검토할 수 있게 출력한다."""
    decision_by_id = {item.case_id: item for item in decisions}
    lines = [
        "# AI 생성 면접 질문 검토 목록",
        "",
        "> 답 노출은 이력서에 적힌 사실을 인용했는지가 아니라, 이력서에 없는 "
        "정답을 알려주거나 지원자가 설명할 판단 과정을 질문이 대신 말했는지로 "
        "판정합니다.",
        "",
    ]
    for index, item in enumerate(questions, start=1):
        decision = decision_by_id[item.case_id]
        lines.extend(
            [
                f"## {index}. {item.case_id}",
                "",
                f"- 지원 직무: {item.desired_role}",
                f"- 평가 의도: {item.query}",
                f"- 답 노출 판정: {'예' if decision.answer_leakage else '아니요'}",
                f"- 품질 판정 이유: {decision.reason}",
                "",
                f"**생성 질문**: {item.question}",
                "",
                "**검색된 이력서 근거**",
                "",
                *[f"> {evidence}" for evidence in item.evidence],
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit-per-behavior", type=int, default=10)
    args = parser.parse_args()
    settings = AppSettings()
    documents, all_cases = load_dataset(args.dataset_dir)
    cases = stratified_cases(all_cases, args.limit_per_behavior)
    chunks = build_corpus(documents, maximum_tokens=250, overlap_tokens=50)
    embedding_client = OpenAIEmbeddingClient(
        settings.openai_api_key.get_secret_value(),
        settings.openai_embedding_model,
        dimensions=settings.openai_embedding_dimensions,
    )
    chunk_vectors, chunk_calls, chunk_seconds = _embed_batches(
        embedding_client, [item.text for item in chunks]
    )
    query_vectors, query_calls, query_seconds = _embed_batches(
        embedding_client, [build_query_text(case) for case in cases]
    )
    retrieved = evaluate(
        cases=cases,
        chunks=chunks,
        chunk_embeddings=chunk_vectors,
        query_embeddings=query_vectors,
        threshold=0.35,
        top_k=15,
    )
    provider = OpenAIResponsesClient(
        settings.openai_api_key.get_secret_value(),
        settings.openai_interview_model,
        60,
        max_output_tokens=6000,
    )
    relevance_started = time.monotonic()
    checked = apply_relevance_check(cases=cases, results=retrieved, provider=provider)
    relevance_seconds = time.monotonic() - relevance_started
    relevance_usage = provider.usage_snapshot()
    questions, generation_calls, generation_seconds = generate_questions(
        cases=cases, relevance_results=checked, provider=provider
    )
    after_generation_usage = provider.usage_snapshot()
    generation_usage = usage_delta(after_generation_usage, relevance_usage)
    decisions, judge_seconds = judge_questions(questions, provider)
    after_judge_usage = provider.usage_snapshot()
    judge_usage = usage_delta(after_judge_usage, after_generation_usage)
    metrics = quality_metrics(questions, decisions)
    blocked_negatives = sum(
        item.expected_behavior == "insufficient_evidence" and not item.retrieved
        for item in checked
    )
    negative_count = sum(
        item.expected_behavior == "insufficient_evidence" for item in checked
    )
    metrics["negative_question_block_rate"] = blocked_negatives / negative_count
    report = {
        "settings": {
            "chunk_size": 250,
            "overlap": 50,
            "threshold": 0.35,
            "top_k": 15,
            "embedding_model": settings.openai_embedding_model,
            "question_model": settings.openai_interview_model,
        },
        "metrics": metrics,
        "timing": {
            "embedding_seconds": round(chunk_seconds + query_seconds, 3),
            "relevance_seconds": round(relevance_seconds, 3),
            "question_generation_seconds": round(generation_seconds, 3),
            "quality_judge_seconds": round(judge_seconds, 3),
        },
        "calls": {
            "embedding": chunk_calls + query_calls,
            "relevance": len([item for item in retrieved if item.retrieved]),
            "question_generation": generation_calls,
            "quality_judge": 1,
        },
        "token_usage": {
            "embedding": embedding_client.usage_snapshot(),
            "relevance": relevance_usage,
            "question_generation": generation_usage,
            "quality_judge": judge_usage,
            "responses_total": after_judge_usage,
        },
        "questions": [asdict(item) for item in questions],
        "decisions": [item.model_dump(mode="json") for item in decisions],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "question_quality.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# RAG Question Quality",
        "",
        "| Metric | Score |",
        "|---|---:|",
        *[
            f"| {key} | {value:.3f} |" if isinstance(value, float) else f"| {key} | {value} |"
            for key, value in metrics.items()
        ],
    ]
    (args.output_dir / "question_quality.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    (args.output_dir / "generated_questions_review.md").write_text(
        render_question_review(questions, decisions), encoding="utf-8"
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
