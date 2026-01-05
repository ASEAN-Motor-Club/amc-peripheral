"""Unit tests for AnnouncementsDB."""

import os
import tempfile
import pytest
from amc_peripheral.announcements import AnnouncementsDB


@pytest.fixture
def db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_announcements.db")
        yield AnnouncementsDB(db_path)


def test_add_announcement(db):
    """Test adding an announcement."""
    announcement_id = db.add_announcement("Test announcement", "test_user")
    assert announcement_id is not None
    assert announcement_id == 1


def test_add_multiple_announcements(db):
    """Test adding multiple announcements."""
    id1 = db.add_announcement("First announcement", "user1")
    id2 = db.add_announcement("Second announcement", "user2")
    assert id1 == 1
    assert id2 == 2


def test_list_announcements(db):
    """Test listing all announcements."""
    db.add_announcement("Announcement 1", "user")
    db.add_announcement("Announcement 2", "user")

    announcements = db.list_announcements()
    assert len(announcements) == 2
    assert announcements[0]["text"] == "Announcement 1"
    assert announcements[1]["text"] == "Announcement 2"


def test_list_enabled_only(db):
    """Test listing only enabled announcements."""
    id1 = db.add_announcement("Enabled", "user")
    id2 = db.add_announcement("Disabled", "user")
    db.toggle_announcement(id2, False)

    all_announcements = db.list_announcements()
    enabled_announcements = db.list_announcements(enabled_only=True)

    assert len(all_announcements) == 2
    assert len(enabled_announcements) == 1
    assert enabled_announcements[0]["id"] == id1


def test_remove_announcement(db):
    """Test removing an announcement."""
    announcement_id = db.add_announcement("To be removed", "user")
    assert db.get_announcement_count() == 1

    result = db.remove_announcement(announcement_id)
    assert result is True
    assert db.get_announcement_count() == 0


def test_remove_nonexistent_announcement(db):
    """Test removing a non-existent announcement."""
    result = db.remove_announcement(999)
    # sqlite-utils delete raises on missing row, caught by exception handler
    assert result is False


def test_toggle_announcement(db):
    """Test enabling/disabling announcements."""
    announcement_id = db.add_announcement("Toggle test", "user")

    # Verify starts enabled
    announcements = db.list_announcements()
    assert announcements[0]["enabled"] == 1

    # Disable
    db.toggle_announcement(announcement_id, False)
    announcements = db.list_announcements()
    assert announcements[0]["enabled"] == 0

    # Re-enable
    db.toggle_announcement(announcement_id, True)
    announcements = db.list_announcements()
    assert announcements[0]["enabled"] == 1


def test_get_announcement_count(db):
    """Test counting announcements."""
    assert db.get_announcement_count() == 0

    db.add_announcement("One", "user")
    db.add_announcement("Two", "user")
    assert db.get_announcement_count() == 2


def test_get_announcement_count_enabled_only(db):
    """Test counting only enabled announcements."""
    id1 = db.add_announcement("Enabled", "user")
    db.add_announcement("Also enabled", "user")
    db.toggle_announcement(id1, False)

    assert db.get_announcement_count() == 2
    assert db.get_announcement_count(enabled_only=True) == 1


def test_seed_announcements_empty_db(db):
    """Test seeding announcements in empty database."""
    default = ["Ann 1", "Ann 2", "Ann 3"]
    db.seed_announcements(default)

    announcements = db.list_announcements()
    assert len(announcements) == 3
    assert [a["text"] for a in announcements] == default


def test_seed_announcements_non_empty_db(db):
    """Test seeding doesn't overwrite existing announcements."""
    db.add_announcement("Existing", "user")

    default = ["New 1", "New 2"]
    db.seed_announcements(default)

    announcements = db.list_announcements()
    assert len(announcements) == 1
    assert announcements[0]["text"] == "Existing"


def test_empty_database(db):
    """Test empty database handling."""
    assert db.list_announcements() == []
    assert db.get_announcement_count() == 0
