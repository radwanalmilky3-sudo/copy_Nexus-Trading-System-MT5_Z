from services.nexus_agents.research.registry import PromotionRules


def _qualifying_metrics(source):
    return {
        "evaluation_source": source,
        "profit_factor": 2.0,
        "win_rate": 0.60,
        "sharpe": 1.2,
        "max_dd_pct": 10.0,
        "total_trades": 100,
        "net_pnl_pct": 20.0,
    }


def test_synthetic_metrics_cannot_promote_a_strategy():
    passed, reasons = PromotionRules().evaluate(_qualifying_metrics("synthetic"))

    assert not passed
    assert any("not eligible for promotion" in reason for reason in reasons)


def test_real_backtest_metrics_remain_eligible_for_threshold_evaluation():
    passed, reasons = PromotionRules().evaluate(_qualifying_metrics("backtester"))

    assert passed
    assert reasons == []
