import pytest
import discord
from discord.ext import commands
from unittest.mock import AsyncMock
from amc_peripheral.utils.text_utils import split_markdown, is_code_block_open

class MockBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="/", intents=intents)
        self.http_session = AsyncMock()


@pytest.mark.asyncio
async def test_split_markdown():
    # text with newlines to allow splitting
    text = ("A" * 500 + "\n\n") * 5 # 2500+ chars
    chunks = split_markdown(text)
    assert len(chunks) >= 2
    assert all(len(c) <= 2000 for c in chunks)

@pytest.mark.asyncio
async def test_is_code_block_open():
    assert is_code_block_open("```python\nprint(1)")
    assert not is_code_block_open("```python\nprint(1)\n```")
