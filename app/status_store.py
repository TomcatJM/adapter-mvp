import json
from threading import Lock

from app import db
from app.models import AdapterResult, AdapterStatus


class InMemoryStatusStore:
    """内存状态存储。"""
    def __init__(self) -> None:
        """初始化对象。"""
        self._items: dict[str, AdapterStatus] = {}
        self._lock = Lock()

    def put(self, result: AdapterResult) -> None:
        """写入状态。"""
        status = AdapterStatus(
            task_id=result.task_id,
            status=result.status,
            message=result.message,
            data=result.data,
        )
        with self._lock:
            self._items[result.task_id] = status
        self._put_db(status)

    def get(self, task_id: str) -> AdapterStatus:
        """获取状态。"""
        with self._lock:
            status = self._items.get(task_id)
        if status is not None:
            return status
        db_status = self._get_db(task_id)
        if db_status is not None:
            with self._lock:
                self._items[task_id] = db_status
            return db_status
        return AdapterStatus(
            task_id=task_id,
            status="UNKNOWN",
            message="No workflow status found for task_id",
        )

    def _put_db(self, status: AdapterStatus) -> None:
        """内部辅助函数：写入数据库。"""
        if not db.configured():
            return
        try:
            db.ensure_schema()
            with db.connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO adapter_status (task_id, status, message, data_json)
                        VALUES (%s, %s, %s, CAST(%s AS JSON))
                        ON DUPLICATE KEY UPDATE
                            status = VALUES(status),
                            message = VALUES(message),
                            data_json = VALUES(data_json)
                        """,
                        (status.task_id, status.status, status.message, db.dumps(status.data)),
                    )
        except Exception:
            return

    def _get_db(self, task_id: str) -> AdapterStatus | None:
        """内部辅助函数：获取数据库。"""
        if not db.configured():
            return None
        try:
            db.ensure_schema()
            with db.connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT task_id, status, message, data_json FROM adapter_status WHERE task_id = %s",
                        (task_id,),
                    )
                    row = cursor.fetchone()
            if not row:
                return None
            return AdapterStatus(
                task_id=row["task_id"],
                status=row["status"],
                message=row["message"],
                data=self._parse_data(row.get("data_json")),
            )
        except Exception:
            return None

    def _parse_data(self, value) -> dict:
        """内部辅助函数：解析数据。"""
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}


status_store = InMemoryStatusStore()
