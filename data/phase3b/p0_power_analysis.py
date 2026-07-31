"""
P0 supplement: Power Analysis
=============================

If A strategy's true alpha were EXACTLY what our backtest shows ($13/trade A×A×LONG,
$250 std), could we ever detect it? Compute required sample size.
"""
import numpy as np
from scipy import stats


def required_n(effect_size: float, alpha: float = 0.05, power: float = 0.80, one_sided: bool = True) -> int:
    """Required sample size to detect effect with given power."""
    # Cohen's d = mean / std
    z_alpha = stats.norm.ppf(1 - alpha) if one_sided else stats.norm.ppf(1 - alpha / 2)
    z_beta = stats.norm.ppf(power)
    n = ((z_alpha + z_beta) / effect_size) ** 2
    return int(np.ceil(n))


def main():
    print("=== Statistical Power Analysis ===\n")
    print("Question: If true alpha is X, how many trades do we need to detect it?\n")

    # Observed effect sizes from our backtest
    scenarios = [
        ("A × A × LONG (current 'winning')", 13.02, 248.33),
        ("C × SIDE × SHORT (best by p-value)", 27.47, 277.39),  # rough std estimate
        ("C × SIDE (best mean regime)", 17.12, 274.78),
        ("A × SIDE (good regime, over-restrictive)", 9.35, 262.79),
        ("A × A (DOWN regime, all dir)", 6.00, 250.62),
        ("A × ALL (no regime filter)", -2.30, 255.30),
    ]

    print(f"{'Cell':<40} {'d':>8} {'n_have':>8} {'n_need_α=0.05':>16} {'n_need_α=0.001':>18}")
    print("-" * 95)

    n_have_map = {
        "A × A × LONG (current 'winning')": 165,
        "C × SIDE × SHORT (best by p-value)": 138,
        "C × SIDE (best mean regime)": 276,
        "A × SIDE (good regime, over-restrictive)": 261,
        "A × A (DOWN regime, all dir)": 204,
        "A × ALL (no regime filter)": 561,
    }

    for name, mean, std in scenarios:
        d = mean / std
        n_need_05 = required_n(d, alpha=0.05)
        n_need_001 = required_n(d, alpha=0.001)
        n_have = n_have_map[name]
        ratio = n_need_05 / n_have
        print(f"{name:<40} {d:>8.3f} {n_have:>8} {n_need_05:>16} {n_need_001:>18} ({ratio:.1f}x)")

    # Implication
    print("\n=== Implication ===")
    print("Cohen's d ~ 0.05 means 'tiny effect'. To detect tiny effects reliably,")
    print("we need 2000-5000+ trades. We have 138-561. We are 4-14x UNDERPOWERED.")
    print()
    print("Even if true alpha were EXACTLY what backtest shows, our sample size")
    print("cannot statistically distinguish it from zero. We are searching for a")
    print("signal smaller than our noise floor.")
    print()
    print("Implication for strategy development:")
    print("  - Either get MUCH larger sample (longer history, more instruments, or higher timeframe)")
    print("  - Or design strategies with much LARGER effect size (Sharpe > 0.2 per trade)")
    print("  - Or accept we're doing exploratory research, not deployment-ready trading")


if __name__ == "__main__":
    main()