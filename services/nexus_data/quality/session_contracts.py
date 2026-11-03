"""Strict, secret-free contracts for the read-only terminal session export."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from dataclasses import dataclass
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

MAX_EXPORT_BYTES = 1_048_576
Name = Annotated[str, StringConstraints(min_length=1,max_length=128,strip_whitespace=True)]
SessionState = Literal['ok','no_sessions','error','truncated']


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True,frozen=True)


class SessionWindow(FrozenModel):
    start_seconds: int = Field(ge=0,lt=86400)
    end_seconds: int = Field(ge=0,le=86400)

    @model_validator(mode='after')
    def unambiguous(self):
        if self.start_seconds == self.end_seconds:
            raise ValueError('Equal session endpoints are ambiguous, not proof of full day')
        return self


class DaySessions(FrozenModel):
    day: int = Field(ge=0,le=6)
    quote_status: SessionState
    trade_status: SessionState
    quote_error: int = Field(ge=0)
    trade_error: int = Field(ge=0)
    quote_sessions: tuple[SessionWindow,...] = Field(max_length=32)
    trade_sessions: tuple[SessionWindow,...] = Field(max_length=32)

    @model_validator(mode='after')
    def coherent_status(self):
        for kind in ('quote','trade'):
            state, error, windows = (getattr(self,f'{kind}_{suffix}') for suffix in ('status','error','sessions'))
            if state in ('ok','no_sessions') and error:
                raise ValueError('Successful session collection cannot carry an error')
            if state == 'ok' and not windows or state == 'no_sessions' and windows:
                raise ValueError('Session list contradicts collection status')
        return self


class SymbolSessions(FrozenModel):
    broker_symbol: Name
    days: tuple[DaySessions,...] = Field(min_length=7,max_length=7)

    @model_validator(mode='after')
    def complete_week(self):
        if {d.day for d in self.days} != set(range(7)):
            raise ValueError('Seven unique weekdays required')
        return self


class SessionExport(FrozenModel):
    schema_version: Literal[1]
    server: Name
    company: Name
    captured_at_utc: AwareDatetime
    connected: bool
    observed_server_offset_seconds: int = Field(ge=-86400,le=86400)
    symbols: tuple[SymbolSessions,...] = Field(min_length=1,max_length=32)

    @field_validator('captured_at_utc')
    @classmethod
    def utc_capture(cls,value):
        if value.utcoffset() != timedelta(0):
            raise ValueError('Capture timestamp must be UTC')
        return value

    @model_validator(mode='after')
    def unique_symbols(self):
        if len({s.broker_symbol for s in self.symbols}) != len(self.symbols):
            raise ValueError('Duplicate broker symbol')
        return self


def strict_json(raw: bytes) -> object:
    if len(raw) > MAX_EXPORT_BYTES:
        raise ValueError('Export exceeds 1 MiB')
    def pairs(items):
        result = {}
        for key,value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('Nonfinite JSON constant')
    return json.loads(raw.decode('utf-8-sig'),object_pairs_hook=pairs,parse_constant=constant)


def parse_session_export(raw: bytes, *, now: datetime) -> SessionExport:
    if now.tzinfo is None:
        raise ValueError('Aware current time required')
    data = strict_json(raw)
    # JSON-mode strict validation accepts RFC3339 dates and JSON arrays without
    # relaxing bool/int field types, unlike Python-mode coercion.
    result = SessionExport.model_validate_json(json.dumps(data,allow_nan=False))
    if result.captured_at_utc > now + timedelta(seconds=60):
        raise ValueError('Future capture timestamp')
    return result


class Evidence(FrozenModel):
    evidence_id: Name
    source_uri: str = Field(min_length=1,max_length=2048)
    published_at: AwareDatetime
    effective_from: AwareDatetime
    effective_to: AwareDatetime

    @model_validator(mode='after')
    def evidence_range(self):
        if not self.source_uri.startswith('https://') or self.effective_from >= self.effective_to:
            raise ValueError('HTTPS source and nonempty effective period required')
        return self


class ClockEvidence(Evidence):
    timezone_name: str | None = None
    utc_offset_seconds: int | None = Field(default=None,ge=-50400,le=50400)

    @model_validator(mode='after')
    def clock_rule(self):
        if (self.timezone_name is None) == (self.utc_offset_seconds is None):
            raise ValueError('Exactly one attested clock conversion is required')
        if self.timezone_name:
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(self.timezone_name)
            except (ValueError,KeyError) as exc:
                raise ValueError('Unknown timezone') from exc
        return self


class UTCWindow(FrozenModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode='after')
    def nonempty(self):
        if self.start >= self.end:
            raise ValueError('Empty quote interval')
        return self


class CalendarException(Evidence):
    server: Name
    broker_symbols: tuple[Name,...] = Field(min_length=1,max_length=32)
    kind: Literal['closed','modified']
    quote_windows_utc: tuple[UTCWindow,...] = Field(default=(),max_length=32)

    @model_validator(mode='after')
    def contained_windows(self):
        if self.kind == 'closed' and self.quote_windows_utc:
            raise ValueError('Closed exception cannot have quote windows')
        if any(w.start < self.effective_from or w.end > self.effective_to for w in self.quote_windows_utc):
            raise ValueError('Exception quote windows outside coverage')
        return self


class CalendarPolicy(FrozenModel):
    expected_server: str = Field(default='',max_length=128)
    symbol_map: dict[Name,Name] = Field(default_factory=dict,max_length=32)
    clock_evidence: ClockEvidence | None = None
    exceptions: tuple[CalendarException,...] = Field(default=(),max_length=256)


CalendarState = Literal['not_configured','unavailable','ready','stale','identity_mismatch','clock_unverified','invalid','conflict']


class CalendarStatus(FrozenModel):
    state: CalendarState
    snapshot_id: str | None = None
    content_hash: str | None = None
    captured_at: datetime | None = None
    imported_at: datetime | None = None
    expires_at: datetime | None = None
    reason: str = ''


@dataclass(frozen=True)
class CalendarContext:
    export: SessionExport | None
    policy: CalendarPolicy
    status: CalendarStatus


def load_calendar_policy(path: Path | None) -> CalendarPolicy:
    if path is None:
        return CalendarPolicy()
    with path.open('rb') as handle:
        raw=handle.read(MAX_EXPORT_BYTES+1)
    return CalendarPolicy.model_validate_json(json.dumps(strict_json(raw),allow_nan=False))
