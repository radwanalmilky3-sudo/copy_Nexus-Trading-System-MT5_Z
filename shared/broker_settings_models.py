"""Owner-scoped metadata and drafts, never a live broker/trading command."""
import json
from datetime import date, timezone
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, field_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ProfileCreate(StrictModel):
    name: Name
    broker_name: Name


class AccountCreate(StrictModel):
    profile_id: Name
    label: Name
    server: Name
    login: Annotated[str, StringConstraints(pattern=r'^[0-9]{1,32}$')]
    account_kind: Literal['demo', 'live'] = 'demo'


class AssetPreference(StrictModel):
    broker_symbol: Name
    mode: Literal['disabled', 'analysis', 'trade'] = 'disabled'


class SupportTransitionDraft(StrictModel):
    from_offset_seconds: int | None = Field(default=None, ge=-50400, le=50400)
    to_offset_seconds: int | None = Field(default=None, ge=-50400, le=50400)
    session_start_date: date | None = None
    effective_at_utc: AwareDatetime | None = None
    during_market_closure: Literal['unknown', 'yes', 'no'] = 'unknown'
    next_open_utc: AwareDatetime | None = None
    support_reply: str = Field(default='', max_length=8000)
    evidence_received_at: AwareDatetime | None = None

    @field_validator('session_start_date', mode='before')
    @classmethod
    def parse_date(cls, value):
        # FastAPI validates a decoded JSON dict, not Pydantic JSON mode.
        return TypeAdapter(date).validate_json(json.dumps(value), strict=True) if isinstance(value,str) else value

    @field_validator('effective_at_utc', 'next_open_utc', 'evidence_received_at', mode='before')
    @classmethod
    def parse_timestamp(cls, value):
        return TypeAdapter(AwareDatetime).validate_json(json.dumps(value), strict=True) if isinstance(value,str) else value

    @field_validator('effective_at_utc', 'next_open_utc', 'evidence_received_at')
    @classmethod
    def normalize_utc(cls, value):
        return value.astimezone(timezone.utc) if value is not None else None


class SessionWindow(StrictModel):
    day: int = Field(ge=0, le=6)
    start_seconds: int = Field(ge=0, le=86400)
    end_seconds: int = Field(ge=0, le=86400)


class SessionObservation(StrictModel):
    server: Name
    broker_symbol: Name
    captured_at_utc: AwareDatetime
    observed_offset_seconds: int = Field(ge=-50400, le=50400)
    windows: list[SessionWindow] = Field(max_length=100)
    source: Literal['NexusSessionReader'] = 'NexusSessionReader'

    @field_validator('captured_at_utc', mode='before')
    @classmethod
    def parse_captured(cls, value):
        return TypeAdapter(AwareDatetime).validate_json(json.dumps(value), strict=True) if isinstance(value,str) else value


class AccountSettings(StrictModel):
    session_observation: SessionObservation | None = None
    session_observations: list[SessionObservation] | None = Field(default=None,max_length=32)
    assets: list[AssetPreference] = Field(default_factory=list, max_length=256)
    transition: SupportTransitionDraft = Field(default_factory=SupportTransitionDraft)

    @field_validator('session_observations')
    @classmethod
    def unique_session_symbols(cls, values):
        if values is not None and len({v.broker_symbol for v in values}) != len(values):
            raise ValueError('Duplicate session symbol')
        return values

    @field_validator('assets')
    @classmethod
    def unique_assets(cls, values):
        if len({v.broker_symbol for v in values}) != len(values):
            raise ValueError('Duplicate broker symbol')
        return values


class SaveSettings(StrictModel):
    expected_version: int = Field(ge=1)
    settings: AccountSettings
