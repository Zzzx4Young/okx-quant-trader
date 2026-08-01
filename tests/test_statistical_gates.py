# -*- coding: utf-8 -*-
"""
Layer 3 · Statistical Significance Gate Tests (2026-08-02)

════════════════════════════════════════════════════════════════════
目的: 强制 backtest 结果必须通过统计显著性门, 否则视为 theater。

铁律 #10 (MEMORY.md): "Backtest 后第一件事 = t-test / Bonferroni / power analysis,
不是 fragility_scan / direction filter / regime filter. 2026-07-29 P0 实证:
3 策略 × 4 regime × 2 direction × 9 cost cell × 2 filter = 432 hypothesis 测试,
0 个 cell p<0.05. 1 个月精致 backtest 基础设施优化从未验证统计显著的
point estimate. Pre-registration 必须先冻结假设 + 成功标准"

测试覆盖:
  S-1: Sharpe 计算正确性 (sanity, 防计算 bug)
  S-2: Sharpe 显著性 (t-test, p<0.05 vs 0)
  S-3: Bonferroni 多重比较修正 (防假阳性)
  S-4: 策略 vs buy-and-hold 配对 t-test
  S-5: Power analysis (样本量是否足够)
  S-6: 真实 fragility_scan 输出 (data/experiments) 显著性回放
════════════════════════════════════════════════════════════════════
"""
import json
import math
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from scipy import stats


# ──────────── Helpers ────────────

def sharpe_ratio(returns: np.ndarray, rf: float = 0.0) -> float:
    """标准 Sharpe ratio (无风险利率默认 0)"""
    if len(returns) < 2:
        return 0.0
    excess = returns - rf
    std = np.std(excess, ddof=1)
    if std == 0:
        return 0.0
    return float(np.mean(excess) / std * math.sqrt(len(returns)))


def sharpe_pvalue(sharpe: float, n: int) -> float:
    """
    Sharpe ratio 的 t-test: H0: sharpe == 0

    t = sharpe * sqrt(n-1) / sqrt(1 + sharpe^2)
    p = 2 * (1 - t_cdf(|t|, df=n-1))

    来源: Jobson & Korkie (1981) 测试, Memmel (2003) 修正
    """
    if n < 3:
        return 1.0
    t = sharpe * math.sqrt(n - 1) / math.sqrt(1 + sharpe ** 2)
    p = 2 * (1 - stats.t.cdf(abs(t), df=n - 1))
    return float(p)


def paired_ttest_pvalue(strategy_returns: np.ndarray, baseline_returns: np.ndarray) -> float:
    """策略 vs baseline (buy-hold) 配对 t-test: H0: 差 == 0"""
    if len(strategy_returns) != len(baseline_returns) or len(strategy_returns) < 3:
        return 1.0
    diff = strategy_returns - baseline_returns
    if np.std(diff, ddof=1) == 0:
        return 1.0
    t, p = stats.ttest_rel(strategy_returns, baseline_returns)
    return float(p)


def required_n_for_power(target_sharpe: float, power: float = 0.8, alpha: float = 0.05) -> int:
    """
    给定目标 Sharpe, 计算达到 power=0.8 所需的样本量

    简化公式: n ≈ ((z_alpha + z_beta) / sharpe)^2 + 1
    """
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    z_beta = stats.norm.ppf(power)
    if abs(target_sharpe) < 1e-6:
        return float("inf")
    n = ((z_alpha + z_beta) / target_sharpe) ** 2 + 1
    return int(math.ceil(n))


# ──────────── S-1: Sharpe 计算正确性 ────────────

class TestSharpeCalculationCorrectness:
    """Sharpe ratio 必须等于标准公式 (sanity, 防计算 bug)"""

    def test_sharpe_zero_when_all_returns_equal(self):
        """所有 return 相等 → Sharpe = 0 (除零防护 + 正确性)"""
        returns = np.array([0.01] * 50)
        assert sharpe_ratio(returns) == 0.0

    def test_sharpe_positive_for_positive_returns(self):
        """正收益 → Sharpe > 0"""
        np.random.seed(42)
        returns = np.random.normal(0.005, 0.01, 100)  # mean=0.5%, std=1%
        s = sharpe_ratio(returns)
        assert s > 0, f"正收益应得 Sharpe > 0, got {s}"

    def test_sharpe_matches_known_formula(self):
        """对比手动计算: Sharpe = mean/std * sqrt(n)"""
        np.random.seed(123)
        returns = np.random.normal(0.01, 0.02, 100)
        expected = float(np.mean(returns) / np.std(returns, ddof=1) * math.sqrt(100))
        actual = sharpe_ratio(returns)
        assert abs(actual - expected) < 1e-9, f"Sharpe 公式错: {actual} vs {expected}"


# ──────────── S-2: Sharpe 显著性 (铁律 #10 核心) ────────────

class TestSharpeSignificanceGate:
    """Sharpe ratio 必须显著 > 0 (p<0.05) 才视为真 Alpha"""

    def test_strong_sharpe_passes_significance(self):
        """Sharpe=2.0, n=100 → p < 0.001 (显著)"""
        s = 2.0
        n = 100
        p = sharpe_pvalue(s, n)
        assert p < 0.05, f"Sharpe=2.0, n=100 应显著, got p={p}"

    def test_weak_sharpe_fails_significance(self):
        """Sharpe=0.3, n=10 → p > 0.05 (不显著, 视为噪声)

        教训: 432 hypothesis 教训——Sharpe=0.3, n=10 看起来还行,
        但 t-test 揭示这是统计噪声.
        """
        s = 0.3
        n = 10
        p = sharpe_pvalue(s, n)
        assert p > 0.05, (
            f"Sharpe=0.3, n=10 应不显著 (铁律 #10 实证). got p={p:.4f}. "
            f"如果这是真实 backtest 结果, 它是 theater."
        )

    def test_random_returns_have_unbiased_sharpe_distribution(self):
        """随机 walk 多次采样: Sharpe 均值应接近 0

        实证: 如果 random data 平均 Sharpe 远高于 0, 说明公式有偏.
        单次采样不能验证 (随机性大); 多次采样平均才稳定.
        """
        sharpes = []
        for seed in range(50):
            np.random.seed(seed)
            random_returns = np.random.normal(0, 0.01, 200)
            sharpes.append(sharpe_ratio(random_returns))
        mean_sharpe = np.mean(sharpes)
        # 50 次随机 walk 平均 Sharpe 应接近 0 (±0.2)
        assert abs(mean_sharpe) < 0.2, (
            f"50 次随机 walk 平均 Sharpe 应接近 0, got {mean_sharpe:.3f}. "
            f"Sharpe 公式可能有偏."
        )

    def test_known_distribution_pvalues_are_correct(self):
        """验证 p-value 公式输出与 scipy 一致

        用 scipy.stats.ttest_1sample 作为 ground truth, 验证 sharpe_pvalue 公式.
        """
        np.random.seed(42)
        # 模拟显著数据: mean=0.01, std=0.01, n=50 → Sharpe ≈ sqrt(50) * 0.01/0.01 ≈ 7.07
        # 应该非常显著
        returns = np.random.normal(0.01, 0.01, 50)
        s = sharpe_ratio(returns)
        p_formula = sharpe_pvalue(s, len(returns))

        # Ground truth: scipy t-test on the same returns
        t_stat, p_scipy = stats.ttest_1samp(returns, popmean=0)
        # Note: scipy 用 df = n-1 = 49, 我们也是 n-1
        assert abs(p_formula - p_scipy) < 0.01, (
            f"sharpe_pvalue 公式 ({p_formula:.6f}) 应 ≈ scipy ({p_scipy:.6f}). "
            f"Sharpe={s:.3f}, t_stat={t_stat:.3f}"
        )


# ──────────── S-3: Bonferroni 多重比较修正 ────────────

class TestBonferroniCorrection:
    """
    多策略 × 多 regime × 多 cost cell 测试时, 必须 Bonferroni 修正。

    教训: 432 hypothesis × 0 p<0.05 教训 (7-29 P0).
    若不修正, 假阳性率膨胀: α_eff = 1 - (1-α)^K.
    """

    def test_bonferroni_threshold_for_432_tests(self):
        """432 个 hypothesis 测试, Bonferroni 修正后阈值 = 0.05/432"""
        K = 432
        alpha = 0.05
        bonferroni_threshold = alpha / K

        # 实证: 如果有一个 cell 出现 raw p=0.01 (没修正时显著),
        # Bonferroni 修正后不显著 (0.01 > 0.000116)
        raw_p = 0.01
        assert raw_p > bonferroni_threshold, (
            f"432 次测试, raw p=0.01 在 Bonferroni 后应不显著. "
            f"threshold={bonferroni_threshold:.6f}, raw_p={raw_p}"
        )

    def test_family_wise_error_rate_inflation(self):
        """不修正时, 假阳性率膨胀"""
        K = 432
        alpha = 0.05
        fwer_uncorrected = 1 - (1 - alpha) ** K

        # 不修正时 432 次测试至少 1 次假阳性的概率 ≈ 99.99%
        assert fwer_uncorrected > 0.99, (
            f"432 次独立测试, FWER > 99%. 必须 Bonferroni 或 FDR 修正."
        )


# ──────────── S-4: 策略 vs buy-and-hold ────────────

class TestStrategyBeatsBuyAndHold:
    """
    策略回报必须显著高于 buy-and-hold (配对 t-test)
    """

    def test_strategy_beats_baseline_when_actually_better(self):
        """策略明显胜出 → 应显著 (大效应 + 足够样本)"""
        np.random.seed(42)
        n = 200  # 足够样本量
        # 策略平均 +0.5%/bar, baseline 平均 +0.1%/bar (效应 0.4%, std 1% → Cohen's d ≈ 0.4)
        strategy = np.random.normal(0.005, 0.01, n)
        baseline = np.random.normal(0.001, 0.01, n)
        p = paired_ttest_pvalue(strategy, baseline)
        assert p < 0.05, f"n=200, 效应 0.4% 应显著, got p={p:.4f}"

    def test_strategy_equal_to_baseline_fails_gate(self):
        """策略 = baseline (相同分布) → 应不显著

        教训: 如果 backtest 显示策略胜出但配对 t-test 不显著, 那胜出是噪声.
        """
        np.random.seed(42)
        n = 50
        common = np.random.normal(0.005, 0.01, n)
        strategy = common.copy()
        baseline = common.copy()
        p = paired_ttest_pvalue(strategy, baseline)
        # 完全相同 → diff = 0 → std = 0 → 返回 1.0
        assert p > 0.05, f"完全相同的策略 vs baseline 应不显著, got p={p}"


# ──────────── S-5: Power analysis ────────────

class TestPowerAnalysis:
    """
    给定目标 Sharpe, 验证样本量是否足够达到 80% power
    """

    def test_required_n_for_strong_sharpe(self):
        """Sharpe=1.0 → 需要 ~9 个样本达到 80% power

        公式: n = ((z_alpha/2 + z_beta) / sharpe)^2 + 1
            = ((1.96 + 0.84) / 1.0)^2 + 1 = 2.80^2 + 1 ≈ 8.84 → 9
        """
        n_required = required_n_for_power(target_sharpe=1.0, power=0.8)
        assert 8 <= n_required <= 12, f"Sharpe=1.0 应需 ~9 样本, got {n_required}"

    def test_required_n_for_weak_sharpe_is_huge(self):
        """Sharpe=0.3 → 需要 ~89 个样本, 否则不可信

        公式: n = ((1.96 + 0.84) / 0.3)^2 + 1 = 9.33^2 + 1 ≈ 88.1 → 89

        432 hypothesis 教训: n=10, Sharpe=0.3 完全不可信.
        """
        n_required = required_n_for_power(target_sharpe=0.3, power=0.8)
        assert 80 <= n_required <= 120, (
            f"Sharpe=0.3 需 ~89 样本. got {n_required}. "
            f"如果某个 backtest n=10 Sharpe=0.3, 那是 theater."
        )

    def test_required_n_for_zero_sharpe_is_infinite(self):
        """Sharpe=0 → n=∞ (无信号)"""
        n_required = required_n_for_power(target_sharpe=0.0, power=0.8)
        assert n_required == float("inf")


# ──────────── S-6: 真实 fragility_scan 输出回放 ────────────

class TestRealFragilityScanOutput:
    """
    实证: 读取 data/walkforward/ 或 data/phase3b/ 真实 backtest 输出,
    应用显著性门. 如果真实 backtest 没通过 gate, 这是 theater 的实证.
    """

    def test_walkforward_results_pass_significance_or_are_flagged(self):
        """walkforward 输出的 Sharpe 必须过显著性门

        如果失败, 说明现有 walkforward backtest 输出了统计噪声,
        我们应该:
          (a) 增加样本量 (延长回测期)
          (b) 接受 noise 但用 Bonferroni 修正
          (c) 重新设计策略
        """
        walkforward_dir = Path("data/walkforward")
        if not walkforward_dir.exists():
            pytest.skip(f"{walkforward_dir} 不存在, 跳过真实数据回放")

        # 收集所有 meta.json 中的 Sharpe 数据
        sharpe_data = []
        for meta_file in walkforward_dir.glob("*/meta.json"):
            try:
                meta = json.loads(meta_file.read_text())
                if "sharpe" in meta and "num_trades" in meta:
                    sharpe_data.append((meta["sharpe"], meta["num_trades"]))
            except (json.JSONDecodeError, KeyError):
                continue

        if not sharpe_data:
            pytest.skip("未找到 walkforward Sharpe 数据")

        # 应用显著性门
        passed = 0
        failed = 0
        for sharpe, n in sharpe_data:
            p = sharpe_pvalue(sharpe, n)
            if p < 0.05:
                passed += 1
            else:
                failed += 1

        # 实证: 任何 backtest 输出, 至少 1 个 cell 应显著 (否则整套 backtest 没意义)
        assert passed >= 1, (
            f"walkforward 共 {len(sharpe_data)} 个 Sharpe 数据, "
            f"但 0 个通过显著性门 (p<0.05). "
            f"全部 {failed} 个是 theater. "
            f"Sharpe/n 样本: {sharpe_data[:5]}"
        )


class TestRealPhase3BOutput:
    """data/phase3b/ 的 verdict 是否真的统计显著"""

    def test_phase3b_verdict_pvalues_valid(self):
        """phase3b 的 verdict 应基于真实 p-value, 不是 raw 数字"""
        verdict_file = Path("data/phase3b/VERDICT_P0_P1.md")
        if not verdict_file.exists():
            pytest.skip(f"{verdict_file} 不存在")

        content = verdict_file.read_text()
        # 验证 verdict 提及 p-value (而非只展示 raw 数字)
        # 这是 theater 检测: 如果 verdict 只说 "Sharpe=1.5, 看起来不错",
        # 没提 p-value, 那它不严格.
        assert "p-value" in content.lower() or "p_value" in content.lower() or "p <" in content, (
            "VERDICT_P0_P1.md 没提及 p-value, 可能违反铁律 #10."
        )