import pytest
from amc_peripheral.db import RadioDB

@pytest.fixture
def db(tmp_path):
    # Use a real file in tmp_path for testing or :memory:
    # sqlite-utils works fine with :memory:
    db_path = tmp_path / "test_radio.db"
    return RadioDB(str(db_path))

def test_add_request(db):
    pk = db.add_request(
        discord_id="123456",
        song_title="Test Song",
        song_url="https://youtube.com/v=test",
        requester_name="TestUser"
    )
    assert pk is not None
    
    requests = db.get_requests_by_user("123456")
    assert len(requests) == 1
    assert requests[0]["song_title"] == "Test Song"
    assert requests[0]["requester_name"] == "TestUser"

def test_top_requested(db):
    db.add_request("1", "Song A", "url_a", "User 1")
    db.add_request("2", "Song A", "url_a", "User 2")
    db.add_request("3", "Song B", "url_b", "User 3")
    
    top = db.get_top_requested_songs(limit=5)
    assert len(top) == 2
    assert top[0]["song_title"] == "Song A"
    assert top[0]["request_count"] == 2
    assert top[1]["song_title"] == "Song B"
    assert top[1]["request_count"] == 1

def test_likes(db):
    # Add like
    db.add_like("123", "Cool Song", "url_cool")
    likes = db.get_likes_by_user("123")
    assert len(likes) == 1
    assert likes[0]["song_title"] == "Cool Song"
    assert likes[0]["is_liked"] == 1
    
    # Duplicate like should be updated (is_liked=1)
    db.add_like("123", "Cool Song", "url_cool")
    likes = db.get_likes_by_user("123")
    assert len(likes) == 1
    
    # Top liked
    db.add_like("456", "Cool Song", "url_cool")
    db.add_like("123", "Other Song", "url_other")
    
    top = db.get_top_liked_songs()
    assert top[0]["song_title"] == "Cool Song"
    assert top[0]["like_count"] == 2
    
    # Dislike a song
    success = db.add_dislike("123", "Cool Song")
    assert success is True
    likes = db.get_likes_by_user("123")
    assert len(likes) == 2 # "Cool Song" now has is_liked=0
    
    # Verify Stats
    stats = db.get_all_song_stats()
    # Cool song has 1 like (456) and 1 dislike (123)
    cool_stat = next(s for s in stats if s["song_title"] == "Cool Song")
    assert cool_stat["like_count"] == 1
    assert cool_stat["dislike_count"] == 1
    
    # Other song has 1 like
    other_stat = next(s for s in stats if s["song_title"] == "Other Song")
    assert other_stat["like_count"] == 1
    assert other_stat["dislike_count"] == 0

def test_add_dislike_new_song(db):
    # Testing disliking a song that was never liked
    success = db.add_dislike("999", "Bad Song")
    assert success is True
    stats = db.get_all_song_stats()
    bad_stat = next(s for s in stats if s["song_title"] == "Bad Song")
    assert bad_stat["like_count"] == 0
    assert bad_stat["dislike_count"] == 1


def test_add_auto_queue(db):
    """Test recording an auto-queued song."""
    pk = db.add_auto_queue("Artist A - Song A")
    assert pk is not None

    recent = db.get_recent_auto_queued(hours=1)
    assert len(recent) == 1
    assert recent[0]["song_title"] == "Artist A - Song A"


def test_get_recent_auto_queued_filtering(db):
    """Test that get_recent_auto_queued respects the time window."""
    db.add_auto_queue("Recent Song")

    # Should appear in a 1-hour window
    recent = db.get_recent_auto_queued(hours=1)
    assert len(recent) == 1

    # Should also appear in a 24-hour window
    recent_24 = db.get_recent_auto_queued(hours=24)
    assert len(recent_24) == 1

    # Add another
    db.add_auto_queue("Another Song")
    recent = db.get_recent_auto_queued(hours=1)
    assert len(recent) == 2


def test_add_and_get_news(db):
    """Test recording and retrieving generated news segments."""
    pk = db.add_news("Breaking news: Gangjung traffic jam reaches record levels!", "news_20260317.mp3")
    assert pk is not None

    news = db.get_recent_news(limit=5)
    assert len(news) == 1
    assert "Gangjung traffic jam" in news[0]["content"]
    assert news[0]["audio_filename"] == "news_20260317.mp3"

    # Add another and verify ordering (most recent first)
    db.add_news("Second news segment about racing.", "news2.mp3")
    news = db.get_recent_news(limit=5)
    assert len(news) == 2
    assert "Second news" in news[0]["content"]


def test_add_and_get_jingles(db):
    """Test recording and retrieving generated jingles."""
    pk = db.add_jingle("You're listening to Radio ASEAN, where the roads are long and the songs are longer!", "jingle0.mp3")
    assert pk is not None

    jingles = db.get_recent_jingles(limit=10)
    assert len(jingles) == 1
    assert "Radio ASEAN" in jingles[0]["script"]
    assert jingles[0]["audio_filename"] == "jingle0.mp3"

    # Add more and test limit
    for i in range(5):
        db.add_jingle(f"Jingle number {i}", f"jingle{i+1}.mp3")

    jingles = db.get_recent_jingles(limit=3)
    assert len(jingles) == 3


def test_add_news_no_audio(db):
    """Test adding news without audio filename."""
    pk = db.add_news("Text-only news segment")
    assert pk is not None

    news = db.get_recent_news(limit=1)
    assert news[0]["audio_filename"] is None
    assert "Text-only" in news[0]["content"]
