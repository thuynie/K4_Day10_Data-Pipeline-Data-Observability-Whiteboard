from .testset import build_test_set

__all__ = ["build_test_set"]


def __getattr__(name: str):
    if name in {"EvaluationBundle", "JudgeVerdict", "evaluate_pipeline"}:
        from .metrics import EvaluationBundle, JudgeVerdict, evaluate_pipeline

        mapping = {
            "EvaluationBundle": EvaluationBundle,
            "JudgeVerdict": JudgeVerdict,
            "evaluate_pipeline": evaluate_pipeline,
        }
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
