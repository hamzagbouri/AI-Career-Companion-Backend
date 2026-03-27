import os
import time
from contextlib import contextmanager


def _enabled() -> bool:
    return bool(os.getenv("MLFLOW_TRACKING_URI"))


def _noop_run():
    return {"log_metric": lambda *_a, **_k: None, "log_param": lambda *_a, **_k: None}


class _MlflowRunCtx:
    """
    Safe MLflow run context.

    - Never raises due to MLflow problems
    - Never interferes with exceptions from the wrapped application code
    """

    def __init__(self, name: str, tags: dict | None = None):
        self.name = name
        self.tags = tags or {}
        self.mlflow = None
        self.active = False

    def __enter__(self):
        if not _enabled():
            return _noop_run()
        try:
            import mlflow  # type: ignore

            mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
            mlflow.start_run(run_name=self.name)
            if self.tags:
                mlflow.set_tags({k: str(v) for k, v in self.tags.items()})
            self.mlflow = mlflow
            self.active = True
        except Exception:
            self.mlflow = None
            self.active = False
            return _noop_run()

        def log_metric(key: str, value: float):
            try:
                self.mlflow.log_metric(key, float(value))  # type: ignore[union-attr]
            except Exception:
                pass

        def log_param(key: str, value: object):
            try:
                self.mlflow.log_param(key, str(value))  # type: ignore[union-attr]
            except Exception:
                pass

        return {"log_metric": log_metric, "log_param": log_param}

    def __exit__(self, exc_type, exc, tb):
        if self.active and self.mlflow is not None:
            try:
                self.mlflow.end_run()  # type: ignore[union-attr]
            except Exception:
                # Never block request/exception handling.
                pass
        # Don't suppress exceptions from the wrapped code.
        return False


@contextmanager
def mlflow_run(name: str, tags: dict | None = None):
    """
    Optional MLflow tracking context.

    Enabled only when MLFLOW_TRACKING_URI is set. Otherwise it's a no-op.
    """
    with _MlflowRunCtx(name, tags=tags) as run:
        yield run


@contextmanager
def timed_run(name: str, tags: dict | None = None):
    start = time.perf_counter()
    with mlflow_run(name, tags=tags) as run:
        try:
            yield run
            run["log_metric"]("success", 1.0)
        except Exception:
            run["log_metric"]("success", 0.0)
            raise
        finally:
            run["log_metric"]("duration_ms", (time.perf_counter() - start) * 1000.0)

