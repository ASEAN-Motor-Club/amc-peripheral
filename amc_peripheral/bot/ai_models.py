from typing import Optional, List
from pydantic import BaseModel


class TranslationResponse(BaseModel):
    translation: str


class MultiTranslation(BaseModel):
    indonesian: str
    thai: str
    vietnamese: str
    chinese: str
    japanese: str


class MultiTranslationWithEnglish(BaseModel):
    english: str
    indonesian: str
    thai: str
    vietnamese: str
    chinese: str
    japanese: str


class ModerationResponse(BaseModel):
    conflict_detected: bool
    players_involved: List[str]
    offenders: List[str]
    severity: int
    announcement: Optional[str]


class ParticipantResult(BaseModel):
    rank: int
    player_name: str
    time: str
    points: int
    team: Optional[str]


class TeamResult(BaseModel):
    rank: int
    team_name: str
    points: int


class RaceResult(BaseModel):
    markdown_table: str
    participants: List[ParticipantResult]
    team_results: List[TeamResult]


class ThreadTranslationResponse(BaseModel):
    """Response for translating a conversation thread in one go."""
    translated_thread: str

