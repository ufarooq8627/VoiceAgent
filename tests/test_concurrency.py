import asyncio
import inspect
from app.routes.receptionist_api import process_turn


def test_process_turn_is_async_coroutine():
    assert inspect.iscoroutinefunction(process_turn), "process_turn must be an async def function"
