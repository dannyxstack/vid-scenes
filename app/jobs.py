"""进程内任务队列：单 worker 线程，保证 GPU 任务串行执行。

任务状态持久化在 jobs 表里；服务重启后，未完成的任务会重新入队。
"""

import logging
import queue
import threading
import traceback
from typing import Callable

from sqlalchemy import select

from .db import session_scope
from .models import Job

log = logging.getLogger(__name__)

# handler(job_id, target_id, report)；report(progress: 0..1, message)
Handler = Callable[[int, int, Callable[[float, str | None], None]], None]

_handlers: dict[str, Handler] = {}
_queue: "queue.Queue[int]" = queue.Queue()
_worker: threading.Thread | None = None
_lock = threading.Lock()


def register(kind: str):
    def deco(fn: Handler) -> Handler:
        _handlers[kind] = fn
        return fn

    return deco


def enqueue(kind: str, target_id: int) -> int:
    with session_scope() as s:
        job = Job(kind=kind, target_id=target_id)
        s.add(job)
        s.flush()
        job_id = job.id
    _queue.put(job_id)
    return job_id


def _update(job_id: int, **fields) -> None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None:
            return
        for k, v in fields.items():
            setattr(job, k, v)


def _run(job_id: int) -> None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None or job.status not in ("queued", "running"):
            return
        kind, target_id = job.kind, job.target_id
        job.status, job.progress, job.error = "running", 0.0, None

    handler = _handlers.get(kind)
    if handler is None:
        _update(job_id, status="error", error=f"未知任务类型: {kind}")
        return

    def report(progress: float, message: str | None = None) -> None:
        _update(job_id, progress=max(0.0, min(1.0, progress)), message=message)

    try:
        handler(job_id, target_id, report)
        _update(job_id, status="done", progress=1.0)
    except Exception as e:  # noqa: BLE001
        log.exception("job %s (%s) failed", job_id, kind)
        _update(job_id, status="error", error=f"{e}\n{traceback.format_exc(limit=5)}")


def _loop() -> None:
    while True:
        job_id = _queue.get()
        try:
            _run(job_id)
        finally:
            _queue.task_done()


def start_worker() -> None:
    global _worker
    with _lock:
        if _worker and _worker.is_alive():
            return
        # 重启后恢复未完成的任务
        with session_scope() as s:
            pending = s.scalars(
                select(Job.id).where(Job.status.in_(("queued", "running"))).order_by(Job.id)
            ).all()
            for jid in pending:
                s.get(Job, jid).status = "queued"
        for jid in pending:
            _queue.put(jid)
        _worker = threading.Thread(target=_loop, name="job-worker", daemon=True)
        _worker.start()


def wait_idle() -> None:
    """阻塞直到队列清空（测试用）。"""
    _queue.join()
