"""Tests for the backend_db module (PostgreSQL query interface)."""

import json
import pytest
from unittest.mock import patch


# We need to mock BACKEND_DB_URL before importing backend_db
@pytest.fixture(autouse=True)
def mock_backend_db_url():
    with patch("amc_peripheral.settings.BACKEND_DB_URL", "postgresql://test:test@localhost:5432/test"):
        # Re-import to pick up the mocked value
        import importlib
        import amc_peripheral.bot.backend_db as backend_db_module
        importlib.reload(backend_db_module)
        yield backend_db_module


class TestQueryValidation:
    """Test that dangerous queries are rejected at the application level."""

    def test_rejects_insert(self, mock_backend_db_url):
        result = mock_backend_db_url.execute_query("INSERT INTO amc_player (name) VALUES ('test')")
        assert "error" in result
        assert "blocked keyword" in result["error"].lower() or "Only SELECT" in result["error"]

    def test_rejects_update(self, mock_backend_db_url):
        result = mock_backend_db_url.execute_query("UPDATE amc_player SET name='test'")
        assert "error" in result

    def test_rejects_delete(self, mock_backend_db_url):
        result = mock_backend_db_url.execute_query("DELETE FROM amc_player")
        assert "error" in result

    def test_rejects_drop(self, mock_backend_db_url):
        result = mock_backend_db_url.execute_query("DROP TABLE amc_player")
        assert "error" in result

    def test_rejects_alter(self, mock_backend_db_url):
        result = mock_backend_db_url.execute_query("ALTER TABLE amc_player ADD COLUMN x int")
        assert "error" in result

    def test_rejects_create(self, mock_backend_db_url):
        result = mock_backend_db_url.execute_query("CREATE TABLE evil (x int)")
        assert "error" in result

    def test_rejects_truncate(self, mock_backend_db_url):
        result = mock_backend_db_url.execute_query("TRUNCATE amc_player")
        assert "error" in result

    def test_rejects_grant(self, mock_backend_db_url):
        result = mock_backend_db_url.execute_query("GRANT ALL ON amc_player TO evil")
        assert "error" in result

    def test_rejects_copy(self, mock_backend_db_url):
        result = mock_backend_db_url.execute_query("COPY amc_player TO '/tmp/evil'")
        assert "error" in result

    def test_rejects_vacuum(self, mock_backend_db_url):
        result = mock_backend_db_url.execute_query("VACUUM amc_player")
        assert "error" in result

    def test_allows_select(self, mock_backend_db_url):
        """SELECT queries should pass validation (will fail at connection since no real DB)."""
        result = mock_backend_db_url.execute_query("SELECT COUNT(*) FROM amc_player")
        assert "error" in result
        # Should NOT be a validation error — it should pass validation and fail downstream
        assert "blocked keyword" not in result["error"].lower()
        assert "Only SELECT" not in result["error"]

    def test_allows_with_cte(self, mock_backend_db_url):
        """WITH (CTE) queries should pass validation."""
        result = mock_backend_db_url.execute_query(
            "WITH top_players AS (SELECT * FROM amc_player LIMIT 5) SELECT * FROM top_players"
        )
        assert "error" in result
        assert "blocked keyword" not in result["error"].lower()
        assert "Only SELECT" not in result["error"]

    def test_strips_whitespace(self, mock_backend_db_url):
        """Leading/trailing whitespace should be stripped."""
        result = mock_backend_db_url.execute_query("  DELETE FROM amc_player  ")
        assert "error" in result

    def test_strips_semicolons(self, mock_backend_db_url):
        """Trailing semicolons should be stripped."""
        result = mock_backend_db_url.execute_query("SELECT 1;")
        assert "error" in result
        # Should pass validation
        assert "blocked keyword" not in result["error"].lower()
        assert "Only SELECT" not in result["error"]

    def test_rejects_sql_injection_comment(self, mock_backend_db_url):
        """SQL with DROP in a subquery should be blocked."""
        result = mock_backend_db_url.execute_query("SELECT 1; DROP TABLE amc_player")
        assert "error" in result

    def test_keyword_in_column_name_not_blocked(self, mock_backend_db_url):
        """Keywords inside column names (like 'updated_at') should NOT be blocked."""
        result = mock_backend_db_url.execute_query("SELECT updated_at FROM amc_player")
        assert "error" in result
        # Should NOT be a validation error
        assert "blocked keyword" not in result["error"].lower()
        assert "Only SELECT" not in result["error"]


class TestResultFormatting:
    """Test result formatting for LLM consumption."""

    def test_format_results_empty(self, mock_backend_db_url):
        result = {"results": [], "count": 0}
        formatted = mock_backend_db_url.format_results(result)
        parsed = json.loads(formatted)
        assert parsed["count"] == 0

    def test_format_results_with_data(self, mock_backend_db_url):
        result = {
            "results": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
            "count": 2,
        }
        formatted = mock_backend_db_url.format_results(result)
        parsed = json.loads(formatted)
        assert parsed["count"] == 2
        assert len(parsed["results"]) == 2

    def test_format_results_truncation(self, mock_backend_db_url):
        """Large results should be truncated at 4000 chars."""
        result = {
            "results": [{"data": "x" * 500} for _ in range(20)],
            "count": 20,
        }
        formatted = mock_backend_db_url.format_results(result)
        assert len(formatted) <= 4100  # 4000 + truncation message

    def test_format_results_with_truncated_flag(self, mock_backend_db_url):
        result = {
            "results": [{"id": 1}],
            "count": 1,
            "truncated": True,
            "note": "Results limited to 100 rows",
        }
        formatted = mock_backend_db_url.format_results(result)
        parsed = json.loads(formatted)
        assert parsed["truncated"] is True


class TestSchemaDescription:
    """Test schema introspection."""

    def test_schema_returns_fallback_when_no_url(self, mock_backend_db_url):
        with patch.object(mock_backend_db_url, 'BACKEND_DB_URL', None):
            # Clear cache
            mock_backend_db_url._schema_cache = None
            result = mock_backend_db_url.get_schema_description()
            assert "not configured" in result

    def test_schema_caches_result(self, mock_backend_db_url):
        mock_backend_db_url._schema_cache = "cached schema"
        result = mock_backend_db_url.get_schema_description()
        assert result == "cached schema"
        mock_backend_db_url._schema_cache = None  # Clean up


class TestNoUrlConfigured:
    """Test behavior when BACKEND_DB_URL is not set."""

    def test_execute_query_returns_error(self):
        with patch("amc_peripheral.settings.BACKEND_DB_URL", None):
            import importlib
            import amc_peripheral.bot.backend_db as backend_db_module
            importlib.reload(backend_db_module)
            result = backend_db_module.execute_query("SELECT 1")
            assert "error" in result
            assert "not configured" in result["error"]
