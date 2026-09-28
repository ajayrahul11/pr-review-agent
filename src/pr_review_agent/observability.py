"""Metrics via CloudWatch Embedded Metric Format (EMF).

Locally these are just JSON log lines. On ECS the awslogs driver ships them to CloudWatch,
which turns them into metrics automatically - no agent or SDK needed. They feed the
dashboard + alarms defined in infra/aws/service.yaml (online monitoring of the model).
"""
import json
import logging
import time

from pr_review_agent.config import get_settings

log = logging.getLogger("metrics")


def emit(metrics: dict[str, float], **dims: str) -> None:
    s = get_settings()
    dims = {"Environment": s.environment, **dims}
    payload = {
        "_aws": {"Timestamp": int(time.time() * 1000), "CloudWatchMetrics": [{
            "Namespace": s.metrics_namespace,
            "Dimensions": [list(dims)],
            "Metrics": [{"Name": k, "Unit": "Milliseconds" if k.endswith("Ms") else "Count"}
                        for k in metrics],
        }]},
        **dims, **metrics,
    }
    log.info(json.dumps(payload))
