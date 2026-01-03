from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


class TranslationResponse(BaseModel):
    translation: str


class MultiTranslation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    indonesian: str = Field(alias="Indonesian")
    thai: str = Field(alias="Thai")
    vietnamese: str = Field(alias="Vietnamese")
    chinese: str = Field(alias="Chinese")
    japanese: str = Field(alias="Japanese")


class MultiTranslationWithEnglish(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    english: str = Field(alias="English")
    indonesian: str = Field(alias="Indonesian")
    thai: str = Field(alias="Thai")
    vietnamese: str = Field(alias="Vietnamese")
    chinese: str = Field(alias="Chinese")
    japanese: str = Field(alias="Japanese")


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

