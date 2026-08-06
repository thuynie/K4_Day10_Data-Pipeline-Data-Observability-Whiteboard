from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
import os
import sys
import types
from typing import Any

from datasets import Dataset
from pydantic import BaseModel, Field

from core.config import Settings
from core.utils import normalize_whitespace, read_json, write_json
from retrieval.agent import build_agent, run_agent_question
from retrieval.embeddings import MiniLMEmbeddings
from retrieval.index import LocalEmbeddingIndex
from retrieval.llm import build_llm
from retrieval.qa import answer_question


class JudgeVerdict(BaseModel):
    score: int = Field(ge=1, le=5)
    correct: bool
    reasoning: str


@dataclass(frozen=True)
class EvaluationBundle:
    summary: dict[str, Any]
    answers: list[dict[str, Any]]


def _token_f1(reference: str, prediction: str) -> float:
    ref_tokens = normalize_whitespace(reference).lower().split()
    pred_tokens = normalize_whitespace(prediction).lower().split()
    if not ref_tokens or not pred_tokens:
        return 0.0
    ref_set = set(ref_tokens)
    pred_set = set(pred_tokens)
    overlap = len(ref_set & pred_set)
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_set)
    recall = overlap / len(ref_set)
    return 2 * precision * recall / (precision + recall)


def _judge_answer(settings: Settings, question: str, reference: str, prediction: str) -> JudgeVerdict:
    prompt = f"""
Evaluate the model answer against the reference answer.

Question: {question}
Reference answer: {reference}
Model answer: {prediction}

Return:
- score from 1 to 5
- correct = true only when the answer is materially correct
- short reasoning
""".strip()
    try:
        llm = build_llm(settings=settings, temperature=0.0).with_structured_output(JudgeVerdict)
        return llm.invoke(prompt)
    except Exception:
        score = 5 if _token_f1(reference, prediction) >= 0.95 else 3 if _token_f1(reference, prediction) >= 0.5 else 1
        return JudgeVerdict(
            score=score,
            correct=score >= 3,
            reasoning="Fallback heuristic judge used because the LLM evaluator was unavailable.",
        )


def _run_ragas(settings: Settings, answers: list[dict[str, Any]]) -> dict[str, Any]:
    if os.getenv("RUN_RAGAS", "").lower() not in {"1", "true", "yes"}:
        return {"skipped": "Set RUN_RAGAS=1 to enable the slower Ragas pass."}
    try:
        if "langchain_community.chat_models.vertexai" not in sys.modules:
            shim = types.ModuleType("langchain_community.chat_models.vertexai")
            shim.ChatVertexAI = type("ChatVertexAI", (), {})
            sys.modules["langchain_community.chat_models.vertexai"] = shim
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

        dataset = Dataset.from_dict(
            {
                "question": [item["question"] for item in answers],
                "answer": [item["answer"] for item in answers],
                "ground_truth": [item["ground_truth"] for item in answers],
                "contexts": [item["retrieved_contexts"] for item in answers],
            }
        )
        result = evaluate(
            dataset,
            metrics=[answer_relevancy, context_precision, context_recall, faithfulness],
            llm=build_llm(settings=settings, temperature=0.0),
            embeddings=MiniLMEmbeddings(settings.embedding_model),
        )
        return dict(result)
    except Exception as exc:  # pragma: no cover
        return {"error": f"Ragas evaluation failed: {exc}"}


def evaluate_pipeline(
    settings: Settings,
    index: LocalEmbeddingIndex,
    test_set_path,
    metrics_output_path,
    answers_output_path,
) -> EvaluationBundle:
    test_set = read_json(test_set_path)
    answers: list[dict[str, Any]] = []

    for item in test_set:
        result = answer_question(item["question"], settings=settings, index=index)
        judge = _judge_answer(settings, item["question"], item["ground_truth"], result.answer)
        retrieval_hit = any(doc_id in item["ground_truth_doc_ids"] for doc_id in result.retrieved_doc_ids)
        answers.append(
            {
                "id": item["id"],
                "question_type": item["question_type"],
                "question": item["question"],
                "ground_truth": item["ground_truth"],
                "ground_truth_doc_ids": item["ground_truth_doc_ids"],
                "answer": result.answer,
                "retrieved_doc_ids": result.retrieved_doc_ids,
                "retrieved_contexts": result.retrieved_contexts,
                "retrieval_hit": retrieval_hit,
                "token_f1": _token_f1(item["ground_truth"], result.answer),
                "judge": judge.model_dump(),
            }
        )

    summary = {
        "samples": len(answers),
        "retrieval_hit_rate": mean(1.0 if item["retrieval_hit"] else 0.0 for item in answers),
        "mean_token_f1": mean(item["token_f1"] for item in answers),
        "judge_accuracy": mean(1.0 if item["judge"]["correct"] else 0.0 for item in answers),
        "mean_judge_score": mean(item["judge"]["score"] for item in answers),
    }
    summary["ragas"] = _run_ragas(settings, answers)

    bundle = EvaluationBundle(summary=summary, answers=answers)
    write_json(metrics_output_path, summary)
    write_json(answers_output_path, answers)
    return bundle


def evaluate_agent_pipeline(
    settings: Settings,
    index: LocalEmbeddingIndex,
    test_set_path,
    metrics_output_path,
    answers_output_path,
) -> EvaluationBundle:
    """Chay LLM agent tren cung test set va tinh cung bo metric.

    Khac `evaluate_pipeline` o cho: duong nay di qua `create_agent`, agent tu
    quyet dinh goi tool nao va tu dien dat cau tra loi. Vi vay:
      - Ket qua KHONG deterministic - chay hai lan co the ra so khac nhau.
      - Ton nhieu luot goi LLM (moi cau vai vong + mot lan judge).
    Dung de tra loi cau hoi "agent that co lam duoc khong", con bang so sanh
    baseline/corrupted/repaired o Pha 2 van dua tren `evaluate_pipeline`.

    Loi o tung cau duoc bat lai va ghi vao answers thay vi lam vo pipeline -
    rate limit giua chung khong duoc pha hong ca lan chay.
    """
    test_set = read_json(test_set_path)

    # Agent goi tool -> callback nay gom lai `paper_id` ma agent thuc su nhin
    # thay, nho do `retrieval_hit_rate` do dung thu agent dung, khong phai suy
    # doan tu mot lan search rieng.
    retrieved: list[str] = []

    def _on_retrieve(paper_ids: list[str]) -> None:
        retrieved.extend(paper_ids)

    agent = build_agent(settings, index, on_retrieve=_on_retrieve)

    answers: list[dict[str, Any]] = []
    errors = 0

    for item in test_set:
        retrieved.clear()
        error = ""
        try:
            prediction = run_agent_question(agent, item["question"])
        except Exception as exc:
            prediction = ""
            error = f"{type(exc).__name__}: {exc}"
            errors += 1

        # Giu thu tu xuat hien, bo trung.
        seen: dict[str, None] = {}
        for paper_id in retrieved:
            seen.setdefault(paper_id, None)
        retrieved_doc_ids = list(seen)

        judge = (
            _judge_answer(settings, item["question"], item["ground_truth"], prediction)
            if prediction
            else JudgeVerdict(score=1, correct=False, reasoning=f"Agent failed: {error}")
        )
        answers.append(
            {
                "id": item["id"],
                "question_type": item["question_type"],
                "question": item["question"],
                "ground_truth": item["ground_truth"],
                "ground_truth_doc_ids": item["ground_truth_doc_ids"],
                "answer": prediction,
                "retrieved_doc_ids": retrieved_doc_ids,
                "retrieval_hit": any(
                    doc_id in item["ground_truth_doc_ids"] for doc_id in retrieved_doc_ids
                ),
                "token_f1": _token_f1(item["ground_truth"], prediction),
                "judge": judge.model_dump(),
                "error": error,
            }
        )

    if not answers:
        raise RuntimeError(f"Test set rong: {test_set_path}")

    summary = {
        "mode": "agent",
        "samples": len(answers),
        "agent_errors": errors,
        "retrieval_hit_rate": mean(1.0 if item["retrieval_hit"] else 0.0 for item in answers),
        "mean_token_f1": mean(item["token_f1"] for item in answers),
        "judge_accuracy": mean(1.0 if item["judge"]["correct"] else 0.0 for item in answers),
        "mean_judge_score": mean(item["judge"]["score"] for item in answers),
    }

    write_json(metrics_output_path, summary)
    write_json(answers_output_path, answers)
    return EvaluationBundle(summary=summary, answers=answers)
