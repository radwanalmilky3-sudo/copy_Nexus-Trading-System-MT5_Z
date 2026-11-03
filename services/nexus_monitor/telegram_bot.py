"""
Nexus Monitor — Telegram notification bot.

Sends formatted trade alerts, error notifications, daily summaries,
and kill-switch alerts to a configured Telegram chat with rate limiting.

Safety invariants:
  * the bot token is never written to logs — exception text is redacted
    first, because Telegram/httpx errors embed the request URL
    (``https://api.telegram.org/bot<TOKEN>/...``),
  * missing/incomplete configuration fails closed (no sends, no retries),
  * the outbound rate limit counts *attempts*, not just successes, so a
    persistently failing sender cannot hammer the API,
  * outbound payloads are truncated to Telegram's 4096-char message limit.
"""
from __future__ import annotations

import re
import time
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_MAX_MESSAGES_PER_MINUTE = 20
_MINUTE_WINDOW = 60.0
_MAX_MESSAGE_CHARS = 4096
# Telegram rejects messages longer than 4096 chars; leave headroom for
# truncation ellipsis / parse-mode escaping.
_SAFE_MESSAGE_CHARS = 4000

# Matches ``123456789:AAH...`` bot tokens wherever they appear in text.
_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
# Matches a token embedded in a Telegram API URL, e.g. /bot<TOKEN>/sendMessage.
_URL_TOKEN_RE = re.compile(r"/bot\d{6,}:[A-Za-z0-9_-]{20,}/", re.IGNORECASE)


def _redact(text: str) -> str:
    """Strip any bot token from text before it reaches a log sink."""
    if not text:
        return text
    text = _URL_TOKEN_RE.sub("/bot[REDACTED]/", text)
    return _TOKEN_RE.sub("[REDACTED]", text)


def _coerce_float(value: Any, default: float = 0.0) -> float:
    """Best-effort numeric coercion for alert formatting (never raises)."""
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


class TelegramNotifier:
    """Async Telegram bot with rate limiting and formatted message templates."""

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
    ) -> None:
        # Fail closed: whitespace-only values must not count as configured,
        # and a token without a chat target (or vice-versa) disables sending.
        self._bot_token = (bot_token or "").strip()
        self._chat_id = (chat_id or "").strip()
        self._bot: Any = None
        self._message_times: list[float] = []
        self._enabled = bool(self._bot_token and self._chat_id)
        self._logged_disabled = False
        if not self._enabled:
            # Never log the token itself — only which inputs are missing.
            log.warning(
                "telegram.disabled_missing_config",
                token_configured=bool(self._bot_token),
                chat_id_configured=bool(self._chat_id),
            )

    async def _get_bot(self) -> Any:
        if self._bot is None:
            try:
                from telegram import Bot
                self._bot = Bot(token=self._bot_token)
            except ImportError:
                log.warning("telegram.import_failed", msg="python-telegram-bot not installed")
                self._enabled = False
                return None
            except Exception as exc:
                # Bot() validation errors can embed the token in the message.
                log.warning("telegram.init_failed", error=_redact(str(exc)))
                self._enabled = False
                return None
        return self._bot

    def _check_rate_limit(self) -> bool:
        now = time.monotonic()
        self._message_times = [t for t in self._message_times if now - t < _MINUTE_WINDOW]
        if len(self._message_times) >= _MAX_MESSAGES_PER_MINUTE:
            log.warning("telegram.rate_limited", count=len(self._message_times))
            return False
        return True

    # ── Core Send ─────────────────────────────────────────────────────────

    async def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        if not self._enabled:
            if not self._logged_disabled:
                log.debug("telegram.disabled")
                self._logged_disabled = True
            return False

        # Record the *attempt* before sending: a failing sender must still be
        # rate-limited, otherwise retries are unbounded.
        if not self._check_rate_limit():
            return False
        self._message_times.append(time.monotonic())

        bot = await self._get_bot()
        if bot is None:
            return False

        if len(text) > _SAFE_MESSAGE_CHARS:
            text = text[: _SAFE_MESSAGE_CHARS - 1] + "…"

        try:
            await bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode=parse_mode,
            )
            log.debug("telegram.message_sent", length=len(text))
            return True
        except Exception as exc:
            # Telegram/httpx errors embed the bot URL — redact before logging.
            log.error("telegram.send_failed", error=_redact(str(exc))[:500])
            return False

    # ── Trade Alerts ──────────────────────────────────────────────────────

    async def alert_new_trade(self, trade_details: dict[str, Any]) -> bool:
        symbol = trade_details.get("symbol", "???")
        side = trade_details.get("side", "???")
        entry = trade_details.get("entry_price", 0)
        sl = trade_details.get("sl", 0)
        tp = trade_details.get("tp", trade_details.get("tp1", 0))
        size = trade_details.get("size", 0)
        conviction = _coerce_float(trade_details.get("conviction"), 0.0)

        arrow = "\U0001F7E2" if str(side).upper() == "BUY" else "\U0001F534"
        text = (
            f"{arrow} *NEW TRADE*\n"
            f"\n"
            f"\U0001F4B1 *{symbol}* | {str(side).upper()}\n"
            f"\U0001F3AF Entry: `{entry}`\n"
            f"\U0001F6D1 SL: `{sl}`\n"
            f"\U00002705 TP: `{tp}`\n"
            f"\U0001F4E6 Size: `{size}` lots\n"
            f"\U0001F4CA Conviction: `{conviction:.0%}`"
        )
        return await self.send_message(text)

    async def alert_trade_closed(self, trade_result: dict[str, Any]) -> bool:
        symbol = trade_result.get("symbol", "???")
        pnl_pips = _coerce_float(trade_result.get("pnl_pips"), 0.0)
        pnl_usd = _coerce_float(trade_result.get("pnl_usd"), 0.0)
        rr = _coerce_float(trade_result.get("rr_ratio"), 0.0)
        duration = _coerce_float(trade_result.get("duration"), 0.0)

        emoji = "\U0001F4B0" if pnl_usd >= 0 else "\U0001F4A8"
        sign = "+" if pnl_usd >= 0 else ""
        text = (
            f"{emoji} *TRADE CLOSED*\n"
            f"\n"
            f"\U0001F4B1 *{symbol}*\n"
            f"\U0001F4B5 P&L: `{sign}{pnl_usd:.2f}` USD (`{sign}{pnl_pips:.1f}` pips)\n"
            f"\U0001F4CA R:R: `{rr:.2f}`\n"
            f"\U000023F1 Duration: `{duration:.0f}` min"
        )
        return await self.send_message(text)

    async def alert_error(self, service: str, error: str) -> bool:
        # Redact first: upstream error strings may embed the bot token/URL.
        safe_error = _redact(str(error))[:200]
        text = (
            f"\U000026A0\U0000FE0F *SERVICE ERROR*\n"
            f"\n"
            f"\U0001F3E2 Service: `{service}`\n"
            f"\U0000274C Error: `{safe_error}`"
        )
        return await self.send_message(text)

    async def alert_daily_summary(self, metrics: dict[str, Any]) -> bool:
        total_pnl = _coerce_float(metrics.get("total_pnl"), 0.0)
        total_trades = metrics.get("total_trades", 0)
        win_rate = _coerce_float(metrics.get("win_rate"), 0.0)
        profit_factor = _coerce_float(metrics.get("profit_factor"), 0.0)
        max_dd = _coerce_float(metrics.get("max_drawdown"), 0.0)

        sign = "+" if total_pnl >= 0 else ""
        emoji = "\U0001F4C8" if total_pnl >= 0 else "\U0001F4C9"
        text = (
            f"{emoji} *DAILY SUMMARY*\n"
            f"\n"
            f"\U0001F4B5 P&L: `{sign}{total_pnl:.2f}` USD\n"
            f"\U0001F4CA Trades: `{total_trades}`\n"
            f"\U00002705 Win Rate: `{win_rate:.1f}%`\n"
            f"\U0001F4AA Profit Factor: `{profit_factor:.2f}`\n"
            f"\U0001F4C9 Max Drawdown: `{max_dd:.2f}%`"
        )
        return await self.send_message(text)

    async def alert_kill_switch(self, reason: str = "") -> bool:
        safe_reason = _redact(str(reason))[:500] if reason else "Manual activation"
        text = (
            f"\U0001F6A8\U0001F6A8 *KILL SWITCH ACTIVATED* \U0001F6A8\U0001F6A8\n"
            f"\n"
            f"All trading has been *immediately halted*.\n"
            f"\U0001F4CB Reason: `{safe_reason}`\n"
            f"\n"
            f"_Check the dashboard for details._"
        )
        return await self.send_message(text)
