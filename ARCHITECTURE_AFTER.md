# ARCHITECTURE_AFTER — Golden PAPER Reference

## مسار البيانات

```text
Official / licensed / configured sources
        ↓
Source Adapters + Source Health + Provenance
        ↓
Normalization / Vintage / Data Quality
        ↓
Redis live state        nexus-data single DuckDB writer
        ↓                         ↓
Macro | Monetary | Cross-Asset | Geopolitics | Flows
        ↓
Dynamic Fundamental Fusion
        ↓
Gold Impact + Confidence/Coverage/Conflict + Horizons
        ↓
Arabic Explanation + Reasoning Steps + Outcome/Replay contracts
        ↓
Fundamental API
        ↓
Arabic RTL Fundamental Workspace
```

## مسار فتح التعرض — إلزامي

```text
ML / A7 / internal proposal
        ↓
CENTRAL nexus-risk
  - auto-trade explicit ON
  - canonical blackout available + clear
  - deterministic risk rules
        ↓ signed short-lived approval
Executor FINAL HARD GUARD
  - kill switch
  - auto trade
  - canonical blackout (fail closed)
  - signal TTL
  - signed central-risk approval
        ↓
PAPER -> PaperExecutor only
LIVE  -> real broker adapter (NOT CERTIFIED by this pack)
```

A9 لم يعد يرسل أمرًا إلى Executor؛ يجهز proposal فقط حتى يمر بالـCentral Risk.

## التشغيل المحلي

- Docker artifacts removed.
- Native Windows/Python supervisor (`run.py`).
- Internal services bind to `127.0.0.1` by default.
- Local Redis at `127.0.0.1:6379`.
- Local AI only through Ollama/OpenAI-compatible endpoint (default `127.0.0.1:11434/v1`).
- Dashboard cannot switch to LIVE. LIVE requires process restart with explicit CLI confirmation and remains outside this certificate.

## الأمان عند البداية

- `.env.example` defaults to PAPER.
- `config/settings.yaml` defaults auto-trade OFF.
- API gateway resets `system:auto_trade=false` at startup; enabling it requires admin PIN.
- Missing/degraded blackout state blocks new exposure; closing/risk-reducing position management is not blocked by the opening guard.
