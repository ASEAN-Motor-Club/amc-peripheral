from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


class TranslationResponse(BaseModel):
    translation: str


class MultiTranslation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    indonesian: Optional[str] = Field(default="", alias="Indonesian")
    thai: Optional[str] = Field(default="", alias="Thai")
    vietnamese: Optional[str] = Field(default="", alias="Vietnamese")
    chinese: Optional[str] = Field(default="", alias="Chinese")
    japanese: Optional[str] = Field(default="", alias="Japanese")


class MultiTranslationWithEnglish(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    english: Optional[str] = Field(default="", alias="English")
    indonesian: Optional[str] = Field(default="", alias="Indonesian")
    thai: Optional[str] = Field(default="", alias="Thai")
    vietnamese: Optional[str] = Field(default="", alias="Vietnamese")
    chinese: Optional[str] = Field(default="", alias="Chinese")
    japanese: Optional[str] = Field(default="", alias="Japanese")


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


class ContentTriageResult(BaseModel):
    """Structured triage result for YouTube video content analysis."""
    controversialness: int = Field(
        description="How controversial or polarizing the claims are (0=neutral, 10=extremely controversial)"
    )
    confidence: int = Field(
        description="How confident the speaker sounds about uncertain/unverified claims (0=hedged, 10=absolute certainty on dubious claims)"
    )
    info_quality: int = Field(
        description="Overall quality as an information source — sourcing, nuance, accuracy (0=terrible, 10=excellent)"
    )
    needs_analysis: bool = Field(
        description="Whether the content warrants a critical analysis (true if controversialness >= 5 or info_quality <= 4)"
    )
    topics: List[str] = Field(
        description="Key claims or topics identified that may need fact-checking"
    )


