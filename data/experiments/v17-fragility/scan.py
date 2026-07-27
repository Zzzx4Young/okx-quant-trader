# -*- coding: utf-8 -*-
"""
C strategy 脆弱性扫描 (v1.7)
在 BTC 1h 上对策略 C 跑不同 slippage, 验证 alpha 是否对真实成本敏感。
"""
import sys
sys.path.insert(0, '/home/zzzx47/.openclaw/workspace')
sys.path.insert(0, '/home/zzzx47/.openclaw/workspace/okx')

from okx.code.backtest.data_loader import load
from okx.code.backtest.matcher import BacktestEngine
from okx.code.backtest.run_phase2_experiment import STRATEGIES


def run_one(inst_id: str, slippage_bps: float, fee_bps: float = 5.5):
    data = load(inst_id, "1h")
    sig = STRATEGIES["C_VOLATILITY_BREAKOUT"]
    fee_rate = fee_bps / 10000.0
    engine = BacktestEngine(
        data,
        initial_capital=10000.0,
        leverage=5,
        slippage_bps=int(slippage_bps),
        taker_fee=fee_rate,
        signal_provider=sig,
    )
    result = engine.run()
    m = result.metrics()
    return {
        "inst": inst_id,
        "slippage_bps": slippage_bps,
        "fee_bps": fee_bps,
        "ret_pct": round(m.get("total_return_pct", 0), 3),       # metrics已为 %，不 ×100
        "sharpe": round(m.get("sharpe", 0), 3),
        "maxDD_pct": round(m.get("max_drawdown_pct", 0), 3),       # 同上
        "trades": result.n_trades,
        "win_rate_pct": round(result.win_rate * 100, 1),          # property 返回 fraction
        "slip_cost": round(result.slippage_cost_total, 2),
        "fee_paid": round(result.fee_paid_total, 2),
    }


def main():
    print("=" * 80)
    print("脆弱性扫描 · C_VOLATILITY_BREAKOUT · 1h · 5x leverage")
    print("=" * 80)
    print()

    # ====================== 轴 1: slippage (BTC) ======================
    print("【轴 1】Slippage 敏感性 (BTC, fee=5.5bps)")
    print("-" * 80)
    slip_results_btc = []
    for slip in [5, 10, 15, 20]:
        r = run_one("BTC-USDT-SWAP", slip)
        slip_results_btc.append(r)
        print(f"  slip={slip:>4}bps  ret={r['ret_pct']:>+7.2f}%  sharpe={r['sharpe']:>+6.3f}  "
              f"maxDD={r['maxDD_pct']:>+6.2f}%  trades={r['trades']:>3}  "
              f"win={r['win_rate_pct']:>5.1f}%  slip_cost=${r['slip_cost']:>8.2f}  fee=${r['fee_paid']:>8.2f}")
    print()

    # ====================== 轴 2: fee (BTC, slippage=10bps 作为基准) ======================
    print("【轴 2】Fee 敏感性 (BTC, slip=10bps)")
    print("-" * 80)
    fee_results_btc = []
    for fee in [4.5, 5.5, 7.0, 8.5]:
        r = run_one("BTC-USDT-SWAP", 10, fee)
        fee_results_btc.append(r)
        print(f"  fee={fee:>4.1f}bps  ret={r['ret_pct']:>+7.2f}%  sharpe={r['sharpe']:>+6.3f}  "
              f"maxDD={r['maxDD_pct']:>+6.2f}%  trades={r['trades']:>3}  win={r['win_rate_pct']:>5.1f}%")
    print()

    # ====================== ETH 验证 (slip=5 基准) ======================
    print("【验证】ETH (slip=5bps, fee=5.5bps) — v1.7 已确认负收益,这里复测一下不同 slip")
    print("-" * 80)
    eth_results = []
    for slip in [5, 10]:
        r = run_one("ETH-USDT-SWAP", slip)
        eth_results.append(r)
        print(f"  slip={slip:>4}bps  ret={r['ret_pct']:>+7.2f}%  sharpe={r['sharpe']:>+6.3f}  "
              f"maxDD={r['maxDD_pct']:>+6.2f}%  trades={r['trades']:>3}  win={r['win_rate_pct']:>5.1f}%")
    print()

    # ====================== 决策矩阵 ======================
    print("=" * 80)
    print("【决策矩阵】")
    print("-" * 80)
    print("  alpha 判定（BTC side，C 跑赢 buy-and-hold -6.49% 即为真 alpha）:")
    print()
    for r in slip_results_btc:
        delta_vs_buy_hold = r['ret_pct'] - (-6.49)
        viable = delta_vs_buy_hold > 0
        marker = "✅ alpha still viable" if viable else "❌ alpha destroyed"
        print(f"  slip={r['slippage_bps']:>3}bps:  C ret = {r['ret_pct']:>+6.2f}%  vs buy-hold = {delta_vs_buy_hold:>+6.2f}pp  {marker}")
    print()
    print("  fee 敏感性结论:")
    for r in fee_results_btc:
        delta_vs_buy_hold = r['ret_pct'] - (-6.49)
        viable = delta_vs_buy_hold > 0
        marker = "✅" if viable else "❌"
        print(f"  fee={r['fee_bps']:>4.1f}bps:  C ret = {r['ret_pct']:>+6.2f}%  {marker}")
    print()
    print("  ETH 验证:")
    for r in eth_results:
        print(f"  slip={r['slippage_bps']:>3}bps:  C ret = {r['ret_pct']:>+6.2f}%  "
              f"({'✅ viable' if r['ret_pct'] > -27.76 else '❌ alpha gone'})")

    print()
    print("=" * 80)


if __name__ == "__main__":
    main()
