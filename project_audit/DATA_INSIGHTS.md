# DATA_INSIGHTS — Agent A1 (Data) audit of the reference project

Scope: read-only review of `src/fx_system/{data, dukascopy_intake, dukascopy_event_data,
dukascopy_daily_cache, dukascopy_daily, dukascopy_commissioning, point_in_time}.py` under
`fx-trading-system-main`. Principles and contracts only; no code reproduced.

## Ingestion pipeline design: providers behind a single validated contract

The reference system treats every market-data source as an *adapter* that must end in the same
normalization funnel rather than as a script that emits DataFrames. Whatever the upstream is —
CSV directory, public quote API, practice-only broker API, synthetic generator, or a tick
feed — the data is forced through one validator that canonicalizes column names, coerces types,
establishes a timezone-aware UTC DatetimeIndex, rejects duplicate timestamps, sorts, and only
then evaluates OHLC sanity and bid/ask cross constraints. The crucial architectural decision is
that provenance and quality are *attached to the frame* as machine-readable attributes
(provider, parser version, price divisor, hour coverage ratios, tick counts, volume semantics,
dropped-row counts, a "manifest complete" flag) instead of living in prose documentation, so
every downstream artifact inherits its own lineage automatically. A companion directory
manifest records per-symbol SHA-256, row counts, start/end bounds, price mode, mean spread and
drop counts, and the loader refuses to read a CSV whose hash disagrees with that manifest —
making tampering or silent file replacement a hard failure rather than a subtle research error.
Two further contracts sharpen this: certain providers are domain-locked in code (the historical
broker adapter refuses any non-practice base URL, so a production token cannot be used
accidentally), and the still-forming live candle is always dropped before validation so an
incomplete bar can never enter a backtest. Slicing to the requested range happens last, after
validation, and fails loudly if fewer than two bars survive.

## Tick and cache layering: raw bytes are the source of truth, derived layers are disposable

Storage is deliberately stratified into three tiers with an explicit trust direction. The
bottom tier is the provider's original compressed hourly tick payload, preserved byte-for-byte;
nothing above it may rewrite or "clean" those bytes. The middle tier is a per-symbol SQLite
database holding one row per UTC hour with the payload blob, its SHA-256, tick count, first/last
millisecond offsets, HTTP status, retrieval time and source URL, plus a metadata table pinning
provider, base URL, schema version, parser version, symbol and price divisor. The top tier is a
derived daily-bar cache SQLite containing only aggregated bars, a session-level audit table and
a transfer-audit table, with a single-row contract JSON embedded inside the database itself.
The invariant that makes this safe is that the derived cache is *never* authoritative: it can
only be opened if its own whole-file hash and sidecar receipt agree, its table set, column order
and row counts match the declared contract, an embedded contract equals the external receipt by
canonical JSON, and — critically — every source database still matches the formal transfer
receipt recorded at build time (byte length, mtime, whole-file hash, manifest hash, both
sidecar hashes). If a source database changes, cached rows are untrustworthy and load fails.
Writes are atomic (temporary file, integrity check, rename; symlinks refused; orphan temporaries
treated as errors), and long extractions are resumable through a checkpoint keyed by
(source SHA, session) so a restarted run redoes only sessions whose source bytes actually
changed. A single verification receipt is computed once and threaded through many narrow reads,
so multi-gigabyte hashing happens per file rather than per query.

## Point-in-time and vintage handling: availability, not observation, governs every join

Look-ahead prevention is implemented as a data-model rule rather than a code-review habit. Every
external row carries two distinct timestamps — when the value describes (`observation_time`) and
when it became knowable (`available_time`) — and the validator rejects any row where the
observation is later than availability, plus duplicates on (entity, availability). All joins to
the price timeline are backward as-of merges keyed on `available_time` with an explicit staleness
tolerance measured in days, so a factor can only ever see the newest datum that was already
published at that bar's close; nothing is forward-filled and nothing is backfilled, and a datum
that has aged past the tolerance becomes NaN rather than being silently reused. Vintage quality
is a first-class per-row attribute, not a dataset-level claim: an enumerated closed vocabulary of
quote qualities (historical market quote, policy-rate proxy, synthetic curve, broker-financing
proxy, software synthetic, unknown-unverified) must be present, non-blank and in-vocabulary, and
rows are flagged individually as historical-market only when their quality tag *and* the values
themselves qualify. A source manifest binds the CSV hash to a declared catalog of
(source, provenance, quality) triples, and undeclared triples fail verification — so a dataset
cannot quietly upgrade its own provenance. The same discipline applies to positioning data:
"verified" mode demands per-row proof that availability was the actual publication moment and
that values are the as-published vintage, explicitly rejecting a *revised* historical archive as
point-in-time data. Finally, the whole carry dataset exposes a fingerprint that can be computed
"as known through" an arbitrary cutoff, allowing any experiment to prove which vintage of
auxiliary data it consumed.

## Data quality auditing: invariants checked at every layer, with honest accounting of absence

Quality control is layered so each tier validates what it can actually see. At the tick level,
decoded records must have monotonically increasing millisecond offsets inside the hour, positive
and uncrossed bid/ask, finite non-negative sizes, a payload length that is an exact multiple of
the record size, and a recomputed SHA-256 that matches the stored hash; decoded output must be
strictly ordered and unique with no crossed quotes. At the hourly level, the row's declared
status must be internally consistent (a "no data" hour must carry zero payload, zero bytes, zero
ticks and null offsets) and the declared tick count and boundary offsets must be reproduced from
the payload itself. At the bar level, high/low must bracket open/close, prices must be positive,
bid and ask must not cross, the mid must lie inside the spread, and violations are either raised
or dropped-with-a-count recorded in attributes — never ignored. At the run level, audits are
checked for *rectangular completeness*: the symbol-by-session audit grid must equal the requested
cartesian product exactly, so a missing row is itself a detectable failure rather than an absent
line. Three-way hour accounting (`decoded` / `confirmed no data` / `missing`) is propagated into
coverage ratios and into an explicit "manifest complete" boolean, and whole-file verification
detects mutation during hashing by comparing size and mtime before and after. The design stance
is that an integrity error aborts the run; it is never converted into a gap.

## Commissioning contracts: a data source must earn its way into use, and cannot promote itself

Rather than assuming a freshly downloaded database is usable, the system requires a staged
commissioning artifact that exercises the real code paths on a small, frozen sample. The
commissioning run recomputes whole-file hashes and cross-checks them against the sidecar, the
JSON receipt and an independent deep-audit report; probes real New York session boundaries for
tick coverage and boundary quote latency; and probes fixed intraday event boundaries (Tokyo fix,
London WMR, New York 17:00) for both the last-quote-before and first-quote-after selectors under
a strict staleness/delay tolerance. Each probe emits a structured verdict with its own
rejection reasons, and the overall verdict is a narrow string such as "pass, research only" —
never a green light for anything else. The most important property is *self-limitation*: the
report hard-codes `formal_research_ready=false`, `return_labels_opened=false`,
`factor_outcome_evaluations_added=0` and `trading_approval=false`, and it additionally reports
which formal universe gates (full 14-symbol intake, slow-horizon subset, nine-leg subset) remain
closed, so a passing two-symbol commissioning can never be misread as full readiness. The intake
ledger itself is a state machine over a frozen, in-code universe contract: symbol statuses
(pending / present-incomplete / legacy-range-mismatch / transfer-failed / formal-ready) are
derived by a documented priority order, every issue is deduplicated but retained, partial files
are *recorded* rather than allowed to shrink the universe, and the top-level verdict is
"formal_ready" only if all fourteen symbols are individually ready and no issues exist. A
universe-level boolean therefore encodes a conjunction of per-symbol contracts: exact unified
date range, both sidecars agreeing with each other and with the batch manifest, matching parser
and schema versions, and a passing transfer verification.

## Gap and timezone handling: absence is classified, calendars are explicit, nothing is invented

Time and gap semantics are handled with unusual care. All timestamps are normalized or
converted to UTC at the boundary, and timezone-aware localization is mandatory for point-in-time
fields (naive timestamps are rejected, not assumed). Provider calendars are expressed as an
explicit "broad FX week" candidate rule shared by both the downloader and the reader, so the
expected-hour set used to judge completeness is identical whether hours are being fetched or
being verified — over-requesting near the DST boundary is intentional, because it makes genuine
provider gaps visible instead of hiding them inside a narrower guess. Gaps are then classified,
not merely counted: `no_data` means the provider affirmatively reported the market was closed
(weekend, holiday, early close) and is treated as complete-but-empty, while `missing` means no
row exists and therefore makes a window incomplete. Daily bar emission is conservative under
this classification — a session emits a bar only when every expected hour has a validated
payload, the session contains at least one quote, and the first/last quotes sit within a
configured age of the session boundary; a confirmed no-data hour proves transfer completeness
but cannot prove that hour's high, low or volume, so that session is suppressed rather than
repaired. Every suppressed session carries an explicit suppression reason in the audit, and
suppressed sessions are dropped, never filled. The session calendar itself is defined as
Sunday-through-Thursday 17:00 New York starts (the Friday/Saturday starts are excluded rather
than producing weekend fragments), holidays are *not* guessed from a table — they are inferred
from verified no-data rows and observed ticks. Bar timestamps keep the real close instant
(21:00 or 22:00 UTC depending on DST) instead of being backdated to midnight, so downstream
alignment never fudges the anchor. Cross-symbol panels are built only over sessions where every
symbol is complete for the same reason: intersection with an explicit rule, never interpolation.
Two adapter paths exist for common-session construction — a strict gate that fails on any
non-holiday suppression, and a cache-audit path that trusts build-time emit verdicts — but both
share the invariant that incompleteness removes rows rather than manufacturing them.

## Key Principles for Nexus

- **Provenance travels with the data.** Attach provider, parser/schema version, source hash,
  coverage ratios and completeness flags to every frame/table `nexus-data` writes into DuckDB;
  downstream consumers should never need a wiki page to know what they are reading.
- **Raw is immutable, derived is disposable.** Keep MT5/raw ticks or hourly payloads as the
  byte-for-byte source of truth, and treat every DuckDB aggregate (1H/1D bars, spread stats) as
  rebuildable — with the rebuild keyed to a hash of the source, so a changed source invalidates
  the cache instead of silently coexisting with it.
- **Hash-chained manifests + receipts at every boundary.** Each hand-off (collector → DuckDB →
  service → backtest) should emit a small receipt: file/table hash, byte/row counts, schema
  version, source URL/account, and verification status; loading fails closed on disagreement.
- **Availability time, not observation time.** Any non-price input (economic releases,
  financing/swap schedules, broker parameter changes, calendar events) must carry
  `available_time` and be joined with a backward as-of lookup plus a staleness TTL — no
  forward-fill, no backfill, NaN when stale.
- **Classify absence; never invent values.** Distinguish "market closed / no session" from
  "feed failed / hour missing" from "still forming", record the reason on every suppressed row,
  and let incomplete bars be dropped rather than completed by interpolation. The live candle is
  always excluded from anything used for decisions.
- **Fail closed, abort on integrity errors.** A corrupted payload, crossed quote, duplicate
  timestamp or hash mismatch must raise, not degrade into a gap or a warning; only explicitly
  counted, attribute-recorded drops are acceptable.
- **Commission a source before trusting it.** Before a new MT5 symbol, timeframe or third-party
  feed goes live, run a frozen sample through the *real* decode/aggregate/select code paths and
  emit a verdict artifact that is structurally incapable of granting extra approval (explicit
  `ready=false` flags for anything beyond what was actually tested).
- **Keep the audit rectangle complete.** For every (symbol × period) the pipeline is asked to
  cover, persist one audit row with counts and a reason; completeness of the grid — not
  completeness of the bars — is what proves the pipeline ran everywhere it claimed to.
