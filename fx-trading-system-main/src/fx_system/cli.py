from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer
from rich.console import Console
from rich.table import Table

from .analytics import calculate_metrics, equity_frame, trades_frame
from .broker_cost_contract import (
    ALLOWED_PRODUCT_PROFILES,
    audit_cost_coverage,
    load_cost_dataset,
    load_swap_directory,
    write_cost_coverage_report,
)
from .brokers import OandaPracticeBroker
from .cftc import CFTCFinancialFuturesProvider
from .config import SystemConfig
from .data import YahooFXProvider, load_from_config, save_csv_directory
from .dukascopy_commissioning import (
    DEFAULT_EVENT_DATE,
    DEFAULT_SESSION_DATES,
    run_two_symbol_commissioning,
    write_commissioning_report,
)
from .dukascopy_intake import build_intake_ledger, write_intake_ledger
from .engine import BacktestEngine
from .factor_config import FactorMiningConfig
from .factor_forward import build_forward_predictions, load_frozen_model
from .factor_research import audit_factor_data, run_factor_mining, write_factor_artifacts
from .long_horizon import build_long_horizon_research, write_long_horizon_artifacts
from .long_horizon_config import LongHorizonConfig
from .long_horizon_research import (
    run_long_horizon_screen,
    write_long_horizon_screen_artifacts,
)
from .long_horizon_runner import (
    LongHorizonCandidateDeclaration,
    run_long_horizon_candidate_freeze_from_sqlite,
    write_long_horizon_candidate_freeze_artifacts,
)
from .planner import create_paper_plan
from .point_in_time import load_point_in_time_data
from .reporting import data_fingerprint, write_backtest_artifacts
from .research import generate_ensemble_signals, screen_strategies, walk_forward
from .research_registry import audit_research_registry, write_registry_audit

app = typer.Typer(no_args_is_help=True, help="Multi-currency FX research and paper-trading CLI")
console = Console()


def _load(path: Path) -> SystemConfig:
    return SystemConfig.from_yaml(path)


def _metrics_table(metrics: dict[str, object], title: str) -> Table:
    table = Table(title=title)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for label, key, formatter in (
        ("Return", "total_return", lambda v: f"{v:.2%}"),
        ("Sharpe", "sharpe", lambda v: f"{v:.3f}"),
        ("Max drawdown", "max_drawdown", lambda v: f"{v:.2%}"),
        ("Trades", "trades", lambda v: str(v)),
        ("Win rate", "win_rate", lambda v: f"{v:.2%}"),
        ("Payoff ratio", "payoff_ratio", lambda v: f"{v:.3f}"),
        ("Profit factor", "profit_factor", lambda v: f"{v:.3f}"),
        ("Average hold", "average_holding_hours", lambda v: f"{v:.1f} h"),
        ("Maximum hold", "max_holding_hours", lambda v: f"{v:.1f} h"),
    ):
        table.add_row(label, formatter(metrics[key]))
    return table


@app.command("cost-coverage-audit")
def cost_coverage_audit(
    required_symbols: Annotated[
        str,
        typer.Option(
            "--symbols",
            help="Comma-separated symbols required for formal cost coverage",
        ),
    ] = (
        "EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,NZDUSD,USDCAD,"
        "EURGBP,EURJPY,GBPJPY,AUDJPY,CADJPY,USDNOK,USDSEK"
    ),
    swap_csv: Annotated[
        Path | None,
        typer.Option("--swap-csv", help="Canonical financing CSV with adjacent manifest"),
    ] = None,
    swap_dir: Annotated[Path | None, typer.Option("--swap-dir")] = None,
    forward_csv: Annotated[
        Path | None,
        typer.Option("--forward-csv", help="Canonical forward quote CSV with adjacent manifest"),
    ] = None,
    broker_entity: Annotated[str | None, typer.Option("--broker-entity")] = None,
    account_currency: Annotated[str | None, typer.Option("--account-currency")] = None,
    product_profile: Annotated[
        str,
        typer.Option(
            "--product-profile",
            help="Cost gate: spot_plus_forward or rolling_spot_margin",
        ),
    ] = "spot_plus_forward",
    output: Annotated[Path, typer.Option("--output", "-o")] = Path(
        "outputs/cost_contract/cost_coverage_audit.json"
    ),
) -> None:
    """Audit broker-neutral swap/forward coverage; never opens return labels."""
    symbols = tuple(item.strip() for item in required_symbols.split(",") if item.strip())
    if product_profile not in ALLOWED_PRODUCT_PROFILES:
        raise typer.BadParameter(
            f"--product-profile must be one of {sorted(ALLOWED_PRODUCT_PROFILES)}"
        )
    if swap_csv is not None and swap_dir is not None:
        raise typer.BadParameter("choose either --swap-csv or legacy --swap-dir, not both")
    swap_import = (
        load_cost_dataset(swap_csv, dataset_kind="broker_financing_schedule")
        if swap_csv is not None
        else None
    )
    swap_frame = (
        swap_import.frame
        if swap_import is not None
        else load_swap_directory(swap_dir)
        if swap_dir is not None
        else None
    )
    forward_import = (
        load_cost_dataset(forward_csv, dataset_kind="tradable_forward_quotes")
        if forward_csv is not None
        else None
    )
    forward_frame = None
    if forward_import is not None:
        forward_frame = forward_import.frame
    report = audit_cost_coverage(
        swap_frame=swap_frame,
        forward_frame=forward_frame,
        required_symbols=symbols,
        broker_entity=broker_entity,
        account_currency=account_currency,
        swap_manifest_verified=bool(swap_import and swap_import.manifest_verified),
        forward_manifest_verified=bool(forward_import and forward_import.manifest_verified),
        product_profile=product_profile,
    )
    destination = write_cost_coverage_report(report, output)
    console.print(f"Verdict: [bold]{report.verdict}[/bold]")
    console.print(f"formal_net_returns_ready={report.formal_net_returns_ready}")
    if report.issues:
        for issue in report.issues[:12]:
            console.print(f"- {issue}")
    console.print(f"Saved: [cyan]{destination}[/cyan]")


@app.command("dukascopy-intake-ledger")
def dukascopy_intake_ledger(
    database_dir: Annotated[
        Path, typer.Option("--database-dir", help="Directory of per-symbol SQLite files")
    ] = Path("data/dukascopy_sqlite"),
    config: Annotated[Path, typer.Option("--config", "-c")] = Path(
        "configs/dukascopy_intake_universe.yaml"
    ),
    output: Annotated[Path, typer.Option("--output", "-o")] = Path(
        "outputs/dukascopy_intake/intake_ledger.json"
    ),
) -> None:
    """Build the 14-symbol receive ledger; does not open return labels."""
    ledger = build_intake_ledger(database_dir, config_path=config)
    destination = write_intake_ledger(ledger, output)
    table = Table(title="Dukascopy SQLite intake ledger")
    table.add_column("Symbol")
    table.add_column("Role")
    table.add_column("Status")
    table.add_column("Range OK")
    table.add_column("Issues")
    for record in ledger.symbols:
        if record.range_matches_unified is None:
            range_ok = "n/a"
        elif record.range_matches_unified:
            range_ok = "yes"
        else:
            range_ok = "no"
        table.add_row(
            record.symbol,
            record.role,
            record.status,
            range_ok,
            "; ".join(record.issues[:2]) if record.issues else "",
        )
    console.print(table)
    console.print(
        f"Verdict: [bold]{ledger.verdict}[/bold]  "
        f"formal_ready={len(ledger.formal_ready_symbols)}/14  "
        f"pending={len(ledger.pending_symbols)}  "
        f"blocked={len(ledger.blocked_symbols)}"
    )
    console.print(
        "Role gates: "
        f"slow={len(ledger.slow_horizon_formal_ready_symbols)}/12 "
        f"ready={ledger.slow_horizon_ready}  "
        f"FIX-W={len(ledger.fix_w_formal_ready_symbols)}/9 "
        f"ready={ledger.fix_w_ready}  "
        f"full_14_ready={ledger.full_intake_ready}"
    )
    console.print(f"Saved: [cyan]{destination}[/cyan]")


@app.command("dukascopy-two-symbol-commission")
def dukascopy_two_symbol_commission(
    database_dir: Annotated[
        Path, typer.Option("--database-dir", help="Directory of per-symbol SQLite files")
    ] = Path("data/dukascopy_sqlite"),
    audit_dir: Annotated[
        Path, typer.Option("--audit-dir", help="Directory of deep-audit JSON reports")
    ] = Path("outputs/dukascopy_audit"),
    intake_config: Annotated[Path, typer.Option("--intake-config")] = Path(
        "configs/dukascopy_intake_universe.yaml"
    ),
    session_dates: Annotated[
        str,
        typer.Option(
            "--session-dates",
            help="Comma-separated New York session start dates",
        ),
    ] = ",".join(value.isoformat() for value in DEFAULT_SESSION_DATES),
    event_date: Annotated[str, typer.Option("--event-date")] = DEFAULT_EVENT_DATE.isoformat(),
    output: Annotated[Path, typer.Option("--output", "-o")] = Path(
        "outputs/dukascopy_commissioning/EURUSD_GBPUSD_commissioning.json"
    ),
) -> None:
    """Commission real EURUSD/GBPUSD boundaries without labels or returns."""
    parsed_dates = tuple(value.strip() for value in session_dates.split(",") if value.strip())
    report = run_two_symbol_commissioning(
        database_dir,
        audit_directory=audit_dir,
        intake_config_path=intake_config,
        session_dates=parsed_dates,
        event_date=event_date,
    )
    destination = write_commissioning_report(report, output)
    checks = report["checks"]
    table = Table(title="EURUSD/GBPUSD research-only commissioning")
    table.add_column("Gate")
    table.add_column("Passed")
    for label, key in (
        ("Database evidence", "database_evidence_ok"),
        ("New York session boundaries", "session_boundaries_ok"),
        ("Event boundaries", "event_boundaries_ok"),
    ):
        table.add_row(label, str(checks[key]))
    console.print(table)
    console.print(f"Verdict: [bold]{report['commissioning_verdict']}[/bold]")
    console.print("return_labels_opened=False  trading_approval=False")
    console.print(f"Saved: [cyan]{destination}[/cyan]")


@app.command("research-registry-audit")
def research_registry_audit(
    registry: Annotated[Path, typer.Option("--registry", "-r")] = Path(
        "configs/factor_research_registry.yaml"
    ),
    output: Annotated[Path, typer.Option("--output", "-o")] = Path(
        "outputs/research_registry_audit.json"
    ),
) -> None:
    """Verify disclosed prior searches, preregistered hypotheses, and artifact hashes."""
    audit = audit_research_registry(registry)
    destination = write_registry_audit(audit, output)
    table = Table(title="Factor research registry")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for label, key in (
        ("Prior search rounds", "search_rounds"),
        ("Disclosed fold tests", "disclosed_fold_level_hypothesis_tests"),
        ("Outcome evaluations", "disclosed_factor_outcome_evaluations"),
        ("Registered hypotheses", "registered_hypotheses"),
        ("Active hypotheses", "active_hypotheses"),
        ("Active directional", "active_directional_hypotheses"),
    ):
        table.add_row(label, str(audit[key]))
    table.add_row("Artifacts verified", str(audit["all_supplied_artifacts_verified"]))
    table.add_row("Fresh forward required", str(audit["fresh_forward_required"]))
    console.print(table)
    console.print(f"Audit: [cyan]{destination.resolve()}[/cyan]")


@app.command("validate-config")
def validate_config(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("configs/default.yaml"),
) -> None:
    parsed = _load(config)
    console.print(f"[green]Valid[/green]: {config} ({len(parsed.data.symbols)} symbols)")


@app.command()
def download(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("configs/default.yaml"),
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    parsed = _load(config)
    console.print("Downloading public Yahoo midpoint bars; these are research-only data…")
    data = YahooFXProvider.download(
        parsed.data.symbols, parsed.data.start, parsed.data.end, parsed.data.interval
    )
    destination = output or parsed.data.directory
    save_csv_directory(data, destination)
    console.print(f"[green]Saved[/green] {len(data)} symbols to {destination}")


@app.command("factor-download")
def factor_download(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("configs/factors_daily.yaml"),
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    parsed = FactorMiningConfig.from_yaml(config)
    if parsed.data.provider in {"oanda", "dukascopy"}:
        label = (
            "OANDA fxPractice bid/ask candles"
            if parsed.data.provider == "oanda"
            else "Dukascopy bid/ask ticks and aggregating executable-side bars"
        )
        console.print(f"Downloading {label} for factor research…")
        data = load_from_config(parsed.data)
    else:
        console.print("Downloading long-horizon public FX data for factor research…")
        data = YahooFXProvider.download(
            parsed.data.symbols, parsed.data.start, parsed.data.end, parsed.data.interval
        )
    destination = output or parsed.data.directory
    save_csv_directory(data, destination)
    console.print(f"[green]Saved[/green] {len(data)} symbols to {destination}")


@app.command("cftc-download")
def cftc_download(
    start_year: Annotated[int, typer.Option("--start-year")] = 2006,
    end_year: Annotated[int | None, typer.Option("--end-year")] = None,
    output: Annotated[Path, typer.Option("--output", "-o")] = Path(
        "data/point_in_time/currency_positioning.csv"
    ),
) -> None:
    """Download public CFTC TFF currency positioning with a conservative PIT lag."""
    final_year = end_year if end_year is not None else datetime.now(UTC).year
    console.print(f"Downloading CFTC financial-futures archives {start_year}–{final_year}…")
    positioning = CFTCFinancialFuturesProvider.download(
        start_year,
        final_year,
        cache_directory=output.parent / "cftc_archives",
    )
    destination = CFTCFinancialFuturesProvider.save(positioning, output)
    console.print(
        f"[green]Saved[/green] {len(positioning)} PIT rows to {destination}; "
        "conservative availability lag=60 days"
    )


@app.command("long-horizon-build")
def long_horizon_build(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path(
        "configs/long_horizon_free.yaml"
    ),
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Build purged 1–3 month factor-research inputs; never fit or approve a model."""
    parsed = LongHorizonConfig.from_yaml(config)
    console.print("Loading market data and building isolated long-horizon research inputs…")
    data = load_from_config(parsed.data)
    result = build_long_horizon_research(data, parsed)
    destination = write_long_horizon_artifacts(result, parsed, output)
    table = Table(title="Long-horizon research readiness")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Tier", str(result.audit["tier"]))
    table.add_row("Empirical ready", str(result.audit["empirical_ready"]))
    table.add_row("Daily rows", f"{len(result.dataset):,}")
    table.add_row("Factors", str(len(result.catalog)))
    table.add_row("Walk-forward folds", str(len(result.folds)))
    table.add_row("Minimum history", f"{result.audit['minimum_history_years']:.2f} y")
    table.add_row(
        "Minimum strict coverage",
        f"{result.audit['minimum_strict_factor_coverage']:.1%}",
    )
    console.print(table)
    console.print(
        "This command generated research inputs only; no fitting, selection, or trading approval "
        "occurred."
    )
    console.print(f"Artifacts: [cyan]{destination.resolve()}[/cyan]")


@app.command("long-horizon-freeze-sqlite")
def long_horizon_freeze_sqlite(
    database_directory: Annotated[Path, typer.Option("--database-dir")],
    config: Annotated[Path, typer.Option("--config", "-c")] = Path(
        "configs/long_horizon_dukascopy_sqlite.yaml"
    ),
    declaration: Annotated[Path, typer.Option("--declaration", "-d")] = Path(
        "configs/long_horizon_dukascopy_candidates.yaml"
    ),
    registry: Annotated[Path, typer.Option("--registry", "-r")] = Path(
        "configs/factor_research_registry.yaml"
    ),
    start: Annotated[str | None, typer.Option("--start")] = None,
    end: Annotated[str | None, typer.Option("--end")] = None,
    transfer_manifest: Annotated[
        Path | None, typer.Option("--transfer-manifest")
    ] = None,
    checkpoint: Annotated[Path | None, typer.Option("--checkpoint")] = None,
    output: Annotated[Path, typer.Option("--output", "-o")] = Path(
        "outputs/long_horizon_dukascopy_freeze"
    ),
) -> None:
    """Verify SQLite and freeze outcome-blind next-open targets; never build PnL."""

    parsed = LongHorizonConfig.from_yaml(config)
    frozen = LongHorizonCandidateDeclaration.from_yaml(declaration)
    requested_start = start or parsed.data.start
    requested_end = end or parsed.data.end
    if requested_end is None:
        raise typer.BadParameter("--end or config.data.end is required and exclusive")
    if checkpoint is not None:
        console.print(f"Resume checkpoint enabled: {checkpoint}")
    console.print(
        "Verifying transferred SQLite and freezing factor-only next-open target schedules…"
    )
    result = run_long_horizon_candidate_freeze_from_sqlite(
        database_directory=database_directory,
        config=parsed,
        declaration=frozen,
        start=requested_start,
        end=requested_end,
        registry_path=registry,
        transfer_manifest_path=transfer_manifest,
        checkpoint_path=checkpoint,
    )
    destination = write_long_horizon_candidate_freeze_artifacts(result, output)
    table = Table(title="Slow-horizon factor-only freeze")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Verified SQLite databases", str(len(result.daily_run.transfer_audit)))
    table.add_row("Common daily sessions", str(result.manifest["common_daily_sessions"]))
    table.add_row("Declared candidates", str(len(result.declaration.candidates)))
    table.add_row(
        "Ready next-open decisions",
        str(result.manifest["scheduled_candidate_decisions_ready"]),
    )
    table.add_row("Future labels generated", "False")
    table.add_row("Portfolio PnL generated", "False")
    table.add_row("Trading approval", "False")
    console.print(table)
    console.print(
        "The runner stopped before portfolio accounting because next-open execution, "
        "capital-weight conversion, account-currency conversion, historical target-broker "
        "financing/forward costs, and slippage are not yet integrated."
    )
    console.print(f"Artifacts: [cyan]{destination.resolve()}[/cyan]")


@app.command("long-horizon-screen")
def long_horizon_screen(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path(
        "configs/long_horizon_free.yaml"
    ),
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Run training-only FDR screens and report non-overlapping OOS factor diagnostics."""
    parsed = LongHorizonConfig.from_yaml(config)
    destination = output or parsed.research.output_directory
    console.print("Building long-horizon inputs and running purged factor diagnostics…")
    data = load_from_config(parsed.data)
    build = build_long_horizon_research(data, parsed)
    write_long_horizon_artifacts(build, parsed, destination)
    screen_result = run_long_horizon_screen(build, parsed)
    write_long_horizon_screen_artifacts(screen_result, destination)
    table = Table(title="Long-horizon factor screen")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for label, key in (
        ("Non-overlapping folds", "folds"),
        ("Factors", "factors"),
        ("Hypotheses per fold", "hypotheses_per_fold"),
        ("Training selections", "selected_train_hypotheses"),
        ("Directional selections", "selected_directional_train_hypotheses"),
        (
            "Repeated factor/horizons",
            "factor_horizons_selected_in_at_least_two_folds",
        ),
        ("OOS evaluations", "selected_oos_evaluations"),
    ):
        table.add_row(label, str(screen_result.summary[key]))
    table.add_row(
        "OOS sign match",
        f"{screen_result.summary['selected_oos_sign_match_fraction']:.1%}",
    )
    console.print(table)
    console.print(
        "These are exploratory factor diagnostics, not a cost-adjusted portfolio or a trading "
        "approval."
    )
    console.print(f"Artifacts: [cyan]{Path(destination).resolve()}[/cyan]")


@app.command("factor-mine")
def factor_mine(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("configs/factors_daily.yaml"),
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    parsed = FactorMiningConfig.from_yaml(config)
    data = load_from_config(parsed.data)
    point_in_time = load_point_in_time_data(parsed.point_in_time, data)
    mining = run_factor_mining(data, parsed, point_in_time)
    destination = write_factor_artifacts(mining, data, parsed, output)
    table = Table(title="Purged walk-forward multi-factor results")
    for column in ("Fold", "Kind", "Test", "AUC", "Trades", "Return", "PF", "Max DD"):
        table.add_column(column)
    for fold in mining.folds:
        table.add_row(
            str(fold.fold),
            fold.kind,
            f"{fold.test_start.date()} → {fold.test_end.date()}",
            f"{fold.model_metrics['roc_auc']:.3f}",
            str(fold.trading_metrics["trades"]),
            f"{fold.trading_metrics['total_return']:.2%}",
            f"{fold.trading_metrics['profit_factor']:.3f}",
            f"{fold.trading_metrics['max_drawdown']:.2%}",
        )
    console.print(table)
    console.print(
        f"Compounded OOS return: {mining.summary['compounded_return']:.2%}; "
        f"positive folds: {mining.summary['positive_folds']}/{mining.summary['folds']}"
    )
    console.print(f"Artifacts: [cyan]{destination.resolve()}[/cyan]")


@app.command("factor-data-audit")
def factor_data_audit(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path(
        "configs/factors_broker_carry_dev.yaml"
    ),
    output: Annotated[Path, typer.Option("--output", "-o")] = Path(
        "outputs/factor_data_audit.json"
    ),
) -> None:
    parsed = FactorMiningConfig.from_yaml(config)
    data = load_from_config(parsed.data)
    point_in_time = load_point_in_time_data(parsed.point_in_time, data)
    audit = audit_factor_data(data, parsed, point_in_time)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, indent=2, allow_nan=False), encoding="utf-8")
    discovery_status = "green" if audit["factor_discovery_ready"] else "yellow"
    cost_status = "green" if audit["historical_cost_validation_ready"] else "yellow"
    console.print(
        f"[{discovery_status}]factor_discovery_ready="
        f"{audit['factor_discovery_ready']}[/{discovery_status}]; "
        f"[{cost_status}]historical_cost_validation_ready="
        f"{audit['historical_cost_validation_ready']}[/{cost_status}]; "
        f"tier={audit['tier']}; history={audit['minimum_history_years']:.2f}y; "
        f"bars={audit['minimum_bar_coverage']:.1%}; "
        f"common={audit['cross_symbol_common_coverage']:.1%}; "
        f"source={audit['minimum_known_source_hour_coverage']:.1%}; "
        f"swap={audit['minimum_swap_coverage']:.1%}; carry={audit['carry_coverage']:.1%}; "
        f"positioning={audit['positioning_coverage']:.1%}"
    )
    console.print(f"Audit: [cyan]{output.resolve()}[/cyan]")


@app.command("factor-forward-evaluate")
def factor_forward_evaluate(
    model: Annotated[Path, typer.Option("--model", "-m")],
    config: Annotated[Path, typer.Option("--config", "-c")] = Path(
        "configs/factors_broker_carry_dev.yaml"
    ),
    output: Annotated[Path, typer.Option("--output", "-o")] = Path(
        "outputs/factor_forward"
    ),
) -> None:
    """Evaluate strictly later data with a frozen factor model; never refit or reselect."""
    parsed = FactorMiningConfig.from_yaml(config)
    data = load_from_config(parsed.data)
    point_in_time = load_point_in_time_data(parsed.point_in_time, data)
    frozen = load_frozen_model(model, parsed)
    predictions, signals = build_forward_predictions(data, parsed, frozen, point_in_time)
    output.mkdir(parents=True, exist_ok=True)
    prediction_columns = [
        "_feature_time",
        "_entry_time",
        "_symbol",
        "_direction",
        "_atr",
        "probability",
        "estimated_swap_r",
        "estimated_cost_r",
        "estimated_scenario_cost_r",
        "financing_cost_known",
        "financing_source",
        "expected_gross_r",
        "expected_scenario_r",
        "expected_net_r",
    ]
    predictions[prediction_columns].to_csv(output / "forward_predictions.csv", index=False)
    pd.DataFrame([signal.to_dict() for signal in signals]).to_csv(
        output / "forward_signals.csv", index=False
    )
    research_data_end = pd.Timestamp(frozen["research_data_end"])
    latest_time = min(frame.index[-1] for frame in data.values())
    elapsed_days = max(0.0, (latest_time - research_data_end).total_seconds() / 86400)
    period_complete = elapsed_days >= int(frozen["minimum_forward_days"])
    if predictions.empty:
        metrics = {}
        status = "awaiting_strictly_later_data"
    else:
        forward_start = pd.Timestamp(predictions["_feature_time"].min())
        forward_data = {
            symbol: frame.loc[frame.index >= forward_start] for symbol, frame in data.items()
        }
        result = BacktestEngine(parsed.risk, parsed.costs).run(
            forward_data,
            signals,
            {
                "frozen_contract_sha256": frozen["contract_sha256"],
                "forward_only": True,
            },
            risk_history_data=data,
        )
        metrics = calculate_metrics(result)
        trades_frame(result).to_csv(output / "forward_trades.csv", index=False)
        equity_frame(result).to_csv(output / "forward_equity.csv", index=True)
        status = "duration_complete_requires_review" if period_complete else "collecting"
    manifest = {
        "status": status,
        "contract_sha256": frozen["contract_sha256"],
        "freeze_available_time": frozen["freeze_available_time"],
        "research_data_end": frozen["research_data_end"],
        "latest_common_data_time": latest_time.isoformat(),
        "latest_data_time_by_symbol": {
            symbol: frame.index[-1].isoformat() for symbol, frame in data.items()
        },
        "elapsed_days": elapsed_days,
        "minimum_forward_days": frozen["minimum_forward_days"],
        "period_complete": period_complete,
        "signals": len(signals),
        "market_data_fingerprint_sha256": data_fingerprint(data),
        "point_in_time_fingerprint_sha256": (
            point_in_time.fingerprint() if point_in_time is not None else None
        ),
        "market_prefix_sha256": frozen["market_data_prefix_sha256"],
        "point_in_time_prefix_sha256": frozen["point_in_time_prefix_sha256"],
        "external_feature_coverage": predictions.attrs.get(
            "external_feature_coverage"
        ),
        "external_selected_features": predictions.attrs.get(
            "external_selected_features", []
        ),
        "selected_feature_coverage": predictions.attrs.get(
            "selected_feature_coverage", {}
        ),
        "config": parsed.model_dump(mode="json"),
        "metrics": metrics,
        "note": "No fitting, selection, or automatic trade approval occurs in forward evaluation.",
    }
    (output / "forward_manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8"
    )
    console.print(
        f"Forward status={status}; elapsed={elapsed_days:.1f}d; signals={len(signals)}; "
        f"artifacts=[cyan]{output.resolve()}[/cyan]"
    )


@app.command()
def backtest(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("configs/default.yaml"),
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    parsed = _load(config)
    data = load_from_config(parsed.data)
    signals, raw_signals = generate_ensemble_signals(data, parsed)
    result = BacktestEngine(parsed.risk, parsed.costs).run(
        data, signals, {"raw_signal_count": len(raw_signals)}
    )
    destination = write_backtest_artifacts(result, signals, data, parsed, output)
    metrics = calculate_metrics(result)
    console.print(_metrics_table(metrics, "FX portfolio backtest"))
    console.print(f"Artifacts: [cyan]{destination.resolve()}[/cyan]")


@app.command()
def screen(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("configs/default.yaml"),
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("outputs/screen"),
) -> None:
    parsed = _load(config)
    data = load_from_config(parsed.data)
    runs = screen_strategies(data, parsed)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    table = Table(title="Strategy screening (same data, costs and risk limits)")
    for column in ("Rank", "Strategy", "Score", "Trades", "Sharpe", "Max DD", "Win rate", "PF"):
        table.add_column(column, justify="right" if column != "Strategy" else "left")
    for rank, run in enumerate(runs, 1):
        metric = run.metrics
        rows.append({"rank": rank, "strategy": run.name, **metric})
        table.add_row(
            str(rank),
            run.name,
            f"{metric['screen_score']:.3f}",
            str(metric["trades"]),
            f"{metric['sharpe']:.2f}",
            f"{metric['max_drawdown']:.2%}",
            f"{metric['win_rate']:.2%}",
            f"{metric['profit_factor']:.2f}",
        )
        write_backtest_artifacts(run.result, [], data, parsed, output / run.name)
    pd.DataFrame(rows).to_csv(output / "ranking.csv", index=False)
    console.print(table)
    console.print(f"Artifacts: [cyan]{output.resolve()}[/cyan]")


@app.command("walk-forward")
def walk_forward_command(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("configs/default.yaml"),
    train_bars: Annotated[int, typer.Option(min=200)] = 1200,
    test_bars: Annotated[int, typer.Option(min=100)] = 400,
    top_k: Annotated[int, typer.Option(min=1, max=5)] = 2,
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("outputs/walk_forward.json"),
) -> None:
    parsed = _load(config)
    data = load_from_config(parsed.data)
    folds = walk_forward(data, parsed, train_bars, test_bars, top_k)
    if not folds:
        raise typer.BadParameter("Not enough common bars for one walk-forward fold")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(folds, indent=2, allow_nan=False), encoding="utf-8")
    table = Table(title="Walk-forward out-of-sample folds")
    for column in ("Fold", "Selected", "Trades", "Return", "Sharpe", "Max DD"):
        table.add_column(column)
    for fold in folds:
        metrics = fold["test_metrics"]
        table.add_row(
            str(fold["fold"]),
            ", ".join(fold["selected"]),
            str(metrics["trades"]),
            f"{metrics['total_return']:.2%}",
            f"{metrics['sharpe']:.2f}",
            f"{metrics['max_drawdown']:.2%}",
        )
    console.print(table)
    console.print(f"Saved: [cyan]{output.resolve()}[/cyan]")


@app.command("paper-plan")
def paper_plan(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("configs/default.yaml"),
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("outputs/paper_plan.json"),
    equity: Annotated[float | None, typer.Option(min=1)] = None,
    include_unapproved: Annotated[bool, typer.Option("--include-unapproved")] = False,
) -> None:
    parsed = _load(config)
    data = load_from_config(parsed.data)
    proposals = create_paper_plan(data, parsed, equity, include_unapproved)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps([asdict(item) for item in proposals], indent=2), encoding="utf-8")
    console.print(
        f"Generated {len(proposals)} no-side-effect proposal(s): [cyan]{output.resolve()}[/cyan]"
    )
    if not proposals and not include_unapproved:
        console.print(
            "No strategy is marked paper_enabled; screening candidates were not promoted."
        )


@app.command("oanda-practice-submit")
def oanda_practice_submit(
    plan: Annotated[Path, typer.Option("--plan")] = Path("outputs/paper_plan.json"),
    confirm_practice: Annotated[bool, typer.Option("--confirm-practice")] = False,
) -> None:
    if not confirm_practice:
        raise typer.BadParameter("Pass --confirm-practice to submit orders to fxPractice")
    account_id = os.environ.get("OANDA_PRACTICE_ACCOUNT_ID", "")
    token = os.environ.get("OANDA_PRACTICE_TOKEN", "")
    proposals = json.loads(plan.read_text(encoding="utf-8"))
    with OandaPracticeBroker(account_id, token) as broker:
        for proposal in proposals:
            if datetime.now(UTC) > datetime.fromisoformat(proposal["expires_at"]):
                raise typer.BadParameter(
                    f"Proposal {proposal['proposal_id']} expired at {proposal['expires_at']}"
                )
            response = broker.submit_market_order(
                proposal["symbol"],
                int(proposal["units"]),
                float(proposal["stop_loss"]),
                float(proposal["take_profit"]),
                proposal["proposal_id"],
                confirm_practice=True,
            )
            transaction = response.get("orderCreateTransaction", {})
            console.print(f"Submitted {proposal['symbol']}: {transaction.get('id')}")


if __name__ == "__main__":
    app()
