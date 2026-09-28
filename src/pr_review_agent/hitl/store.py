"""Human-in-the-loop review queue: SQLite locally, DynamoDB on AWS."""
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from pr_review_agent.config import get_settings
from pr_review_agent.models import Review, ReviewStatus


class ReviewStore(Protocol):
    def save(self, review: Review) -> None: ...
    def get(self, review_id: str) -> Review | None: ...
    def list(self, status: ReviewStatus | None = None) -> list[Review]: ...


class SQLiteReviewStore:
    def __init__(self, path: str | None = None):
        self.path = path or get_settings().hitl_db_path
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, status TEXT, body TEXT)")

    def save(self, review: Review) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT OR REPLACE INTO reviews VALUES (?, ?, ?)",
                      (review.id, review.status, review.model_dump_json()))

    def get(self, review_id: str) -> Review | None:
        with sqlite3.connect(self.path) as c:
            row = c.execute("SELECT body FROM reviews WHERE id = ?", (review_id,)).fetchone()
        return Review.model_validate_json(row[0]) if row else None

    def list(self, status: ReviewStatus | None = None) -> list[Review]:
        q, args = "SELECT body FROM reviews", ()
        if status:
            q, args = q + " WHERE status = ?", (status,)
        with sqlite3.connect(self.path) as c:
            return [Review.model_validate_json(r[0]) for r in c.execute(q, args)]


class DynamoReviewStore:
    """Table: partition key `id` (S); GSI `status-index` on `status` (see infra/aws/service.yaml)."""

    def __init__(self, table: str | None = None):
        import boto3

        s = get_settings()
        self.table = boto3.resource("dynamodb", region_name=s.aws_region).Table(table or s.hitl_table)

    def save(self, review: Review) -> None:
        self.table.put_item(Item={"id": review.id, "status": str(review.status),
                                  "body": review.model_dump_json()})

    def get(self, review_id: str) -> Review | None:
        item = self.table.get_item(Key={"id": review_id}).get("Item")
        return Review.model_validate_json(item["body"]) if item else None

    def list(self, status: ReviewStatus | None = None) -> list[Review]:
        from boto3.dynamodb.conditions import Key

        if status:
            items = self.table.query(IndexName="status-index",
                                     KeyConditionExpression=Key("status").eq(str(status)))["Items"]
        else:
            items = self.table.scan()["Items"]
        return [Review.model_validate_json(i["body"]) for i in items]


@lru_cache
def get_store() -> ReviewStore:
    return DynamoReviewStore() if get_settings().hitl_backend == "dynamodb" else SQLiteReviewStore()
