"""Tests for ShareCog - Sharry file sharing integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from amc_peripheral.bot.share_cog import ShareCog, SharryClient


def create_mock_response(status=200, json_data=None):
    """Create a mock aiohttp response that works with async context manager."""
    mock_response = AsyncMock()
    mock_response.status = status
    mock_response.json = AsyncMock(return_value=json_data or {})
    return mock_response


def create_mock_session(response):
    """Create a mock aiohttp session with properly configured post/get methods."""
    session = MagicMock()

    # Create an async context manager mock for post
    post_cm = AsyncMock()
    post_cm.__aenter__.return_value = response
    post_cm.__aexit__.return_value = None
    session.post.return_value = post_cm

    # Create an async context manager mock for get
    get_cm = AsyncMock()
    get_cm.__aenter__.return_value = response
    get_cm.__aexit__.return_value = None
    session.get.return_value = get_cm

    return session


class TestSharryClient:
    """Tests for the SharryClient REST API wrapper."""

    @pytest.fixture
    def client(self):
        """Create a SharryClient with a placeholder session."""
        return SharryClient(MagicMock(), "http://localhost:9090")

    @pytest.mark.asyncio
    async def test_login_success(self, client):
        """Test successful login sets token."""
        response = create_mock_response(200, {"success": True, "token": "test-token-123"})
        client.session = create_mock_session(response)

        result = await client.login("testuser", "testpass")

        assert result is True
        assert client.token == "test-token-123"

    @pytest.mark.asyncio
    async def test_login_failure(self, client):
        """Test failed login does not set token."""
        response = create_mock_response(200, {"success": False, "message": "Invalid credentials"})
        client.session = create_mock_session(response)

        result = await client.login("testuser", "wrongpass")

        assert result is False
        assert client.token is None

    @pytest.mark.asyncio
    async def test_create_alias_success(self, client):
        """Test successful alias creation returns ID."""
        client.token = "test-token"
        response = create_mock_response(200, {"success": True, "id": "alias-id-123"})
        client.session = create_mock_session(response)

        result = await client.create_alias("test-alias")

        assert result == "alias-id-123"

    @pytest.mark.asyncio
    async def test_create_alias_without_auth(self, client):
        """Test alias creation fails with 401 status."""
        response = create_mock_response(401)
        client.session = create_mock_session(response)

        result = await client.create_alias("test-alias")

        assert result is None

    @pytest.mark.asyncio
    async def test_publish_share_returns_url(self, client):
        """Test publishing share returns public URL."""
        client.token = "test-token"
        response = create_mock_response(200, {"success": True, "id": "publish-id-456"})
        client.session = create_mock_session(response)

        result = await client.publish_share("share-id-123")

        assert result == "http://localhost:9090/app/open/publish-id-456"


class TestShareCog:
    """Tests for the ShareCog Discord cog."""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot with properly configured session."""
        bot = MagicMock()
        bot.http_session = MagicMock()
        return bot

    @pytest.fixture
    def cog(self, mock_bot):
        """Create a ShareCog with mock bot."""
        return ShareCog(mock_bot)

    @pytest.mark.asyncio
    async def test_ensure_client_creates_sharry_client(self, cog, mock_bot):
        """Test _ensure_client creates SharryClient on first call."""
        with patch(
            "amc_peripheral.bot.share_cog.SHARRY_ACCOUNT", "testuser"
        ), patch("amc_peripheral.bot.share_cog.SHARRY_PASSWORD", "testpass"):
            # Setup mock session for login
            response = create_mock_response(200, {"success": True, "token": "test-token"})
            mock_session = create_mock_session(response)
            mock_bot.http_session = mock_session

            client = await cog._ensure_client()

            assert client is not None
            assert client.token == "test-token"

    @pytest.mark.asyncio
    async def test_ensure_client_no_credentials(self, cog):
        """Test _ensure_client returns None without credentials."""
        with patch("amc_peripheral.bot.share_cog.SHARRY_ACCOUNT", ""), patch(
            "amc_peripheral.bot.share_cog.SHARRY_PASSWORD", ""
        ):
            client = await cog._ensure_client()
            assert client is None

    def test_share_command_exists(self, cog):
        """Test /share command is registered."""
        # Check that the command exists
        assert hasattr(cog, "share_cmd")
        # Verify it has app_commands decorator attributes
        assert hasattr(cog.share_cmd, "_params")
