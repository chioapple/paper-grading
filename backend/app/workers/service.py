"""阶段十教师批次用例。"""

from typing import Protocol
from uuid import UUID

from app.workers.models import GradingJobCreate, GradingJobCreation, GradingJobView


class GradingJobRepository(Protocol):
    """批次创建与状态读取的持久化边界。"""

    async def create_or_get_job(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        payload: GradingJobCreate,
    ) -> GradingJobCreation: ...

    async def get_job(self, owner_id: UUID, job_id: UUID) -> GradingJobView | None: ...

    async def control_job(
        self,
        owner_id: UUID,
        job_id: UUID,
        action: str,
        item_id: UUID | None = None,
    ) -> GradingJobView | None: ...


class GradingQueue(Protocol):
    """Redis/Celery 投递边界；消息只携带不可猜测的任务标识和版本。"""

    async def enqueue(self, item_id: UUID, dispatch_version: int) -> None: ...


class GradingJobService:
    """提交数据库事实后再投递；重复投递由 Worker 原子 claim 吸收。"""

    def __init__(self, *, repository: GradingJobRepository, queue: GradingQueue) -> None:
        self._repository = repository
        self._queue = queue

    async def create_job(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        payload: GradingJobCreate,
    ) -> GradingJobView:
        creation = await self._repository.create_or_get_job(owner_id, assignment_id, payload)
        for item in creation.job.items:
            if item.status == "queued":
                await self._queue.enqueue(item.id, item.dispatch_version)
        return creation.job

    async def get_job(self, owner_id: UUID, job_id: UUID) -> GradingJobView:
        job = await self._repository.get_job(owner_id, job_id)
        if job is None:
            raise GradingJobNotFoundError("评分批次不存在")
        return job

    async def pause_job(self, owner_id: UUID, job_id: UUID) -> GradingJobView:
        return await self._control(owner_id, job_id, "pause")

    async def resume_job(self, owner_id: UUID, job_id: UUID) -> GradingJobView:
        job = await self._control(owner_id, job_id, "resume")
        await self._enqueue_queued(job)
        return job

    async def cancel_job(self, owner_id: UUID, job_id: UUID) -> GradingJobView:
        return await self._control(owner_id, job_id, "cancel")

    async def retry_item(
        self,
        owner_id: UUID,
        job_id: UUID,
        item_id: UUID,
    ) -> GradingJobView:
        job = await self._control(owner_id, job_id, "retry", item_id)
        await self._enqueue_queued(job)
        return job

    async def _control(
        self,
        owner_id: UUID,
        job_id: UUID,
        action: str,
        item_id: UUID | None = None,
    ) -> GradingJobView:
        job = await self._repository.control_job(owner_id, job_id, action, item_id)
        if job is None:
            raise GradingJobStateError("评分批次状态不允许当前操作")
        return job

    async def _enqueue_queued(self, job: GradingJobView) -> None:
        for item in job.items:
            if item.status == "queued":
                await self._queue.enqueue(item.id, item.dispatch_version)


class GradingJobNotFoundError(LookupError):
    """教师看不到目标批次。"""


class GradingJobStateError(RuntimeError):
    """暂停、继续、取消或重试不满足状态机。"""


class GradingJobIdempotencyConflict(RuntimeError):
    """同一幂等键被用于不同批次请求。"""


class GradingJobConfigurationError(RuntimeError):
    """作业、论文或供应商配置不能形成可信批次。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "grading_job_configuration_invalid",
    ) -> None:
        super().__init__(message)
        self.code = code
