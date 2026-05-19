import pytest
from unittest.mock import AsyncMock, patch

import chat_manager  # доступен через sys.path из conftest.py


@pytest.mark.asyncio
async def test_reload_updates_chats():
    chat_manager._chats.clear()
    chat_manager._chats.add("-111")

    mock_r = AsyncMock()
    mock_r.smembers.return_value = {"-222"}

    with patch("chat_manager.aioredis.Redis", return_value=mock_r):
        await chat_manager.reload()

    assert "-222" in chat_manager._chats
    assert "-111" not in chat_manager._chats


@pytest.mark.asyncio
async def test_reload_no_change_when_equal():
    chat_manager._chats.clear()
    chat_manager._chats.add("-111")

    mock_r = AsyncMock()
    mock_r.smembers.return_value = {"-111"}

    with patch("chat_manager.aioredis.Redis", return_value=mock_r):
        await chat_manager.reload()

    assert chat_manager._chats == {"-111"}
