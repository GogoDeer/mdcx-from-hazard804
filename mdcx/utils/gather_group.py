import asyncio
from collections.abc import Awaitable, Coroutine
from typing import Any


class GatherGroup[T = Any]:
    """
    类似 asyncio.TaskGroup 的 API, 但底层使用 asyncio.gather 实现, 因此可在部分任务抛出异常时继续运行.

    始终将异常作为结果返回, 调用方需手动检查. 如果需要直接抛出异常, 可使用 TaskGroup.
    """

    def __init__(self, timeout: float | None = None):
        self._tasks: list[Coroutine] = []
        self._results: list[Any]
        self._entered = False
        self._timeout = timeout

    def add(self, coro: Coroutine[Any, Any, T]) -> Awaitable[T]:
        """
        创建一个任务并添加到组中.

        Args:
            coro: 要执行的协程或可等待对象

        Returns:
            创建的 Task 对象
        """
        if not self._entered:
            raise RuntimeError("create_task() 只能在 async with 语句内部调用")

        self._tasks.append(coro)
        return coro

    async def __aenter__(self) -> "GatherGroup[T]":
        self._entered = True
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if not self._tasks:
            return

        futures = [asyncio.ensure_future(t) for t in self._tasks]
        # 支持组级别的超时控制（可选）。
        # 超时只取消未完成任务并逐个填 TimeoutError——已完成任务的成功结果必须保留
        # （2026-09-23 审查：wait_for(gather) 超时会连已完成结果一起丢弃，慢子请求拖满
        # 整组即废掉全部成功详情，DMM 跨 category 合并因此整站降级）。
        if self._timeout is not None:
            _done, pending = await asyncio.wait(futures, timeout=self._timeout)
            if pending:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
            timeout_error = TimeoutError(f"GatherGroup 整体超时 ({self._timeout}s)")
            results: list[Any] = []
            for fut in futures:
                if fut.cancelled():
                    results.append(timeout_error)
                elif (exc := fut.exception()) is not None:
                    results.append(exc)
                else:
                    results.append(fut.result())
            self._results = results
        else:
            self._results = list(await asyncio.gather(*futures, return_exceptions=True))

    @property
    def results(self) -> list[T | Exception]:
        """
        获取所有任务的结果, 只有在上下文管理器退出后才可用.
        """
        return self._results


if __name__ == "__main__":

    async def task(i: int):
        await asyncio.sleep(i)
        if i == 2:
            raise ValueError(f"Error in task {i}")
        print(f"Task {i} completed")
        return f"Result of task {i}"

    async def main():
        async with GatherGroup[str]() as group:
            group.add(task(1))
            group.add(task(3))
            group.add(task(2))
        r = group.results
        print("All tasks completed with results:", r)

    asyncio.run(main())
