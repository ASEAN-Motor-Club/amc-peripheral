"""Tests for the radio_server module."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from amc_peripheral.radio.radio_server import (
    get_current_song_metadata,
    parse_song_info,
    get_current_song,
)


class TestParseFileInfo:
    """Tests for parse_song_info function."""

    def test_parse_valid_filename(self):
        """Test parsing a valid metadata dict."""
        metadata = {"filename": "/var/lib/radio/requests/JohnDoe-Cool_Song.mp3"}
        result = parse_song_info(metadata)

        assert result is not None
        assert result["folder"] == "requests"
        assert result["requester"] == "JohnDoe"
        assert result["song_title"] == "Cool_Song"

    def test_parse_prev_requests_folder(self):
        """Test parsing a song from prev_requests folder."""
        metadata = {"filename": "/var/lib/radio/prev_requests/Alice-Another_Track.mp3"}
        result = parse_song_info(metadata)

        assert result is not None
        assert result["folder"] == "prev_requests"
        assert result["requester"] == "Alice"
        assert result["song_title"] == "Another_Track"

    def test_parse_song_with_hyphens_in_title(self):
        """Test parsing a song with hyphens in the title."""
        metadata = {"filename": "/var/lib/radio/requests/Bob-Song-With-Hyphens.mp3"}
        result = parse_song_info(metadata)

        assert result is not None
        assert result["requester"] == "Bob"
        assert result["song_title"] == "Song-With-Hyphens"

    def test_parse_invalid_format_missing_hyphen(self):
        """Test parsing fails gracefully for invalid format."""
        metadata = {"filename": "/var/lib/radio/requests/InvalidNoHyphen.mp3"}
        result = parse_song_info(metadata)

        assert result is None

    def test_parse_invalid_format_missing_folder(self):
        """Test parsing fails gracefully for missing folder structure."""
        metadata = {"filename": "just_a_file.mp3"}
        result = parse_song_info(metadata)

        assert result is None

    def test_parse_empty_filename(self):
        """Test parsing fails gracefully for empty filename."""
        metadata = {"filename": ""}
        result = parse_song_info(metadata)

        assert result is None

    def test_parse_missing_filename_key(self):
        """Test parsing fails gracefully when filename key is missing."""
        metadata = {}
        result = parse_song_info(metadata)

        assert result is None


class TestGetCurrentSongMetadata:
    """Tests for get_current_song_metadata function."""

    @pytest.mark.asyncio
    async def test_get_metadata_success(self):
        """Test successfully fetching metadata."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(
            return_value={"filename": "/var/lib/radio/requests/User-Song.mp3"}
        )

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

        result = await get_current_song_metadata(mock_session)

        assert result is not None
        assert result["filename"] == "/var/lib/radio/requests/User-Song.mp3"

    @pytest.mark.asyncio
    async def test_get_metadata_error(self):
        """Test handling of HTTP errors."""
        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=Exception("Connection refused"))

        result = await get_current_song_metadata(mock_session)

        assert result is None


class TestGetCurrentSong:
    """Tests for get_current_song function."""

    @pytest.mark.asyncio
    async def test_get_current_song_success(self):
        """Test getting a human-readable current song string."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(
            return_value={"filename": "/var/lib/radio/requests/Alice-My_Favorite_Song.mp3"}
        )

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

        result = await get_current_song(mock_session)

        assert result == "My_Favorite_Song (requested by Alice)"

    @pytest.mark.asyncio
    async def test_get_current_song_no_metadata(self):
        """Test returns None when metadata fetch fails."""
        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=Exception("Connection refused"))

        result = await get_current_song(mock_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_current_song_invalid_format(self):
        """Test returns None when metadata format is invalid."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={"filename": "invalid_format.mp3"})

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

        result = await get_current_song(mock_session)

        assert result is None
