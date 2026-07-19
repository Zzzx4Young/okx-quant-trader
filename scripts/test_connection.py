#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKX 连接性测试 v2（生产级）

测试范围：
1. 环境预检（凭据、代理连通性）
2. 公开 API（system time / ticker / instruments / K 线 / funding rate）
3. 私有 API（balance / positions / trade-fee / leverage-info / account-config）
4. 错误路径（不存在的 symbol）

每个端点测量延迟。失败时给出 OKX 错误码含义与诊断建议。

执行：./run.sh scripts/test_connection.py
选项：
  --json          输出 JSON 报告
  --symbols=X,Y  自定义要测的 symbol（默认从 config.json 的 whitelist）
  --skip-private  跳过私有 API 测试
  --bar=1m|5m|15m  K 线周期（默认 15m）
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from okx.code import OKXClient
from okx.code.utils import OKXError
from okx.code.risk import RiskCalculator


# ──────────── 颜色（终端） ────────────

class C:
    """终端颜色"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"

    @classmethod
    def disable(cls):
        for attr in ["RESET", "BOLD", "DIM", "RED", "GREEN", "YELLOW", "BLUE", "CYAN"]:
            setattr(cls, attr, "")


# ──────────── OKX 错误码诊断 ────────────

ERROR_CODES: Dict[str, Dict[str, str]] = {
    "50102": {
        "name": "Timestamp request expired",
        "zh": "时间戳过期",
        "fix": "检查本地时钟是否准确（±30s 容差）；用 NTP 同步",
    },
    "50103": {
        "name": "Invalid OK-ACCESS-KEY",
        "zh": "API Key 无效",
        "fix": "检查 .env 的 OKX_API_KEY 与 OKX 网页一致",
    },
    "50104": {
        "name": "Invalid OK-ACCESS-PASSPHRASE",
        "zh": "Passphrase 错误",
        "fix": "创建 API 时设置的 passphrase 与 .env 不一致；可在 OKX 重新设置",
    },
    "50105": {
        "name": "Invalid OK-ACCESS-SIGN",
        "zh": "签名错误",
        "fix": "签名算法问题：prehash = timestamp + method + path + body；HMAC-SHA256 后 base64",
    },
    "50106": {
        "name": "Invalid IP",
        "zh": "IP 不在白名单",
        "fix": "OKX API 设置里把当前 IP 加入 IP 白名单",
    },
    "50107": {
        "name": "Invalid permissions",
        "zh": "权限不足",
        "fix": "API 需要开启对应权限（读取/交易）",
    },
    "50111": {
        "name": "Invalid request",
        "zh": "请求参数无效",
        "fix": "检查参数格式与必填项",
    },
    "50112": {
        "name": "Invalid OK-ACCESS-TIMESTAMP",
        "zh": "时间戳格式无效",
        "fix": "格式应为 ISO 8601 毫秒精度：YYYY-MM-DDTHH:mm:ss.SSSZ",
    },
    "50113": {
        "name": "Invalid Sign",
        "zh": "签名算法/secret 错误",
        "fix": "secret_key 直接做 HMAC key（不要先 sha256）；结果 base64 编码（不要 hex）",
    },
    "51111": {
        "name": "Instrument ID does not exist",
        "zh": "交易对不存在",
        "fix": "检查 symbol 拼写；用 get_instruments 列出可用交易对",
    },
}


def explain_error(code: str) -> str:
    """把 OKX 错误码转成中文诊断建议"""
    info = ERROR_CODES.get(code)
    if not info:
        return f"未知错误码 {code}（参考 https://www.okx.com/docs-v5/en/#error-code ）"
    return f"[{code}] {info['name']}（{info['zh']}）\n    建议：{info['fix']}"


# ──────────── 计时装饰器 ────────────

class Probe:
    """单个端点测试记录"""

    def __init__(self, name: str, kind: str, run: Callable[[], Any]):
        self.name = name
        self.kind = kind  # 'public' / 'private'
        self.run = run
        self.ok = False
        self.latency_ms: Optional[float] = None
        self.summary: str = ""
        self.error: Optional[str] = None
        self.error_code: Optional[str] = None
        self.data_preview: Any = None

    def execute(self) -> None:
        t0 = time.perf_counter()
        try:
            result = self.run()
            self.latency_ms = (time.perf_counter() - t0) * 1000
            self.ok = True
            # 生成摘要
            self.summary, self.data_preview = self._summarize(result)
        except OKXError as e:
            self.latency_ms = (time.perf_counter() - t0) * 1000
            self.ok = False
            self.error = str(e)
            self.error_code = str(e).split("]")[0].strip("[") if "[" in str(e) else None
        except Exception as e:
            self.latency_ms = (time.perf_counter() - t0) * 1000
            self.ok = False
            self.error = f"{type(e).__name__}: {e}"

    @staticmethod
    def _summarize(result: Any) -> Tuple[str, Any]:
        """根据返回类型生成摘要"""
        if isinstance(result, list):
            n = len(result)
            if n == 0:
                return "空列表", None
            first = result[0]
            if isinstance(first, dict):
                # 挑选关键字段
                preview = {k: first[k] for k in list(first.keys())[:4] if k in first}
                return f"{n} 项", preview
            elif isinstance(first, list):
                # K 线格式：[ts, o, h, l, c, vol]
                return f"{n} 根K线（首根 ts={first[0]}）", first[-1] if first else None
            return f"{n} 项", str(first)[:80]
        elif isinstance(result, dict):
            return f"dict({len(result)} 字段)", {k: result[k] for k in list(result.keys())[:4]}
        return type(result).__name__, None


# ──────────── 预检 ────────────

def precheck() -> Tuple[bool, Dict[str, Any]]:
    """环境预检：凭据 + 代理连通性（双模式感知）

    按当前 OKX_TRADING_MODE 选对应变量（OKX_LIVE_* 或 OKX_DEMO_*），
    同时回退检查 OKX_API_* 旧变量（仅 demo 模式兼容）。
    """
    info: Dict[str, Any] = {"creds": {}, "proxy": {}, "mode": None}
    creds_ok = True

    mode = os.getenv("OKX_TRADING_MODE", "demo").strip().lower()
    if mode not in ("live", "demo"):
        mode = "demo"
    info["mode"] = mode

    # 新格式：OKX_<MODE>_*；回退：OKX_API_*（仅 demo）
    primary = [f"OKX_{mode.upper()}_API_KEY", f"OKX_{mode.upper()}_API_SECRET", f"OKX_{mode.upper()}_PASSPHRASE"]
    legacy = ["OKX_API_KEY", "OKX_API_SECRET", "OKX_PASSPHRASE"]

    primary_present = [bool(os.getenv(v, "")) for v in primary]
    legacy_present = [bool(os.getenv(v, "")) for v in legacy] if mode == "demo" else [False, False, False]

    # 凭据齐全：primary 全有 或（仅 demo）legacy 全有
    creds_ok = all(primary_present) or (mode == "demo" and all(legacy_present))

    for var, present in zip(primary, primary_present):
        val = os.getenv(var, "")
        info["creds"][var] = {"present": present, "length": len(val), "via": "primary"}
    if mode == "demo":
        for var, present in zip(legacy, legacy_present):
            val = os.getenv(var, "")
            info["creds"][var] = {"present": present, "length": len(val), "via": "legacy-fallback"}

    info["flag"] = "1" if mode == "demo" else "0"

    # 代理连通性：直接打 www.okx.com/api/v5/public/time（不需要签名）
    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    info["proxy"]["url"] = proxy_url
    info["proxy"]["reachable"] = False
    info["proxy"]["latency_ms"] = None
    if proxy_url:
        import requests
        t0 = time.perf_counter()
        try:
            r = requests.get(
                "https://www.okx.com/api/v5/public/time",
                proxies={"http": proxy_url, "https": proxy_url},
                timeout=10,
            )
            info["proxy"]["latency_ms"] = (time.perf_counter() - t0) * 1000
            info["proxy"]["reachable"] = r.status_code == 200
        except Exception as e:
            info["proxy"]["error"] = str(e)

    return creds_ok, info


# ──────────── 测试套件 ────────────

def build_probes(client: OKXClient, symbols: List[str], bar: str, skip_private: bool) -> List[Probe]:
    """构建所有探测"""
    probes: List[Probe] = []

    # ──── 公开 API ────
    probes.append(Probe("public.time", "public",
                        lambda: client.public.get_system_time()))

    probes.append(Probe("public.instruments (SWAP)", "public",
                        lambda: client.public.get_instruments(inst_type="SWAP")))

    probes.append(Probe(f"market.ticker {symbols[0]}", "public",
                        lambda: client.market.get_ticker(symbols[0])))

    if len(symbols) >= 2:
        sym2 = symbols[1]
        probes.append(Probe(f"market.ticker {sym2}", "public",
                            lambda s=sym2: client.market.get_ticker(s)))

    probes.append(Probe(f"market.candles {symbols[0]} {bar}", "public",
                        lambda: client.market.get_candles(symbols[0], bar=bar, limit=20)))

    probes.append(Probe(f"market.orderbook {symbols[0]}", "public",
                        lambda: client.market.get_orderbook(symbols[0], depth=5)))

    probes.append(Probe(f"market.funding-rate {symbols[0]}", "public",
                        lambda: client.market.get_funding_rate(symbols[0])))

    # ──── 错误路径：故意用不存在的 symbol ────
    def expect_error():
        try:
            client.market.get_ticker("INVALID-USDT-SWAP")
            raise AssertionError("预期应该报错但成功了")
        except OKXError as e:
            return [{"expected_error": str(e)}]

    p = Probe("market.ticker INVALID (预期失败)", "public", expect_error)
    p.expect_failure = True
    probes.append(p)

    if skip_private:
        return probes

    # ──── 私有 API ────
    probes.append(Probe("account.balance", "private",
                        lambda: client.account.get_balance()))

    probes.append(Probe("account.positions (SWAP)", "private",
                        lambda: client.account.get_positions(inst_type="SWAP")))

    probes.append(Probe("account.config", "private",
                        lambda: client.account.get_config()))

    probes.append(Probe("account.trade-fee (SWAP)", "private",
                        lambda: client.account.get_trade_fee(inst_type="SWAP")))

    probes.append(Probe(f"account.leverage-info {symbols[0]}", "private",
                        lambda: client.account.get_leverage_info(symbols[0], "isolated")))

    probes.append(Probe("account.max-withdrawal", "private",
                        lambda: client.account.get_max_withdrawal()))

    return probes


# ──────────── 报告输出 ────────────

def print_report(probes: List[Probe], precheck_info: Dict[str, Any], json_mode: bool) -> bool:
    """输出报告，返回是否全部成功"""
    if json_mode:
        return print_json_report(probes, precheck_info)

    print(f"\n{C.BOLD}{C.CYAN}{'=' * 70}{C.RESET}")
    print(f"{C.BOLD}  OKX API 连通性测试报告{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'=' * 70}{C.RESET}\n")

    # 预检
    print(f"{C.BOLD}[ 预检 ]{C.RESET}")
    creds = precheck_info["creds"]
    for var, c in creds.items():
        icon = f"{C.GREEN}✓{C.RESET}" if c["present"] else f"{C.RED}✗{C.RESET}"
        print(f"  {icon} {var}: {'已配置' if c['present'] else '缺失'} (长度 {c['length']})")
    print(f"  {C.DIM}模式：{'模拟盘' if precheck_info['flag'] == '1' else '实盘'}{C.RESET}")
    px = precheck_info["proxy"]
    if px.get("url"):
        if px.get("reachable"):
            print(f"  {C.GREEN}✓{C.RESET} 代理 {px['url']}: 通 ({px['latency_ms']:.0f} ms)")
        else:
            print(f"  {C.RED}✗{C.RESET} 代理 {px['url']}: 不通 ({px.get('error', '')})")
    else:
        print(f"  {C.YELLOW}⚠{C.RESET} 未配置代理")

    # 测试结果
    public_total = sum(1 for p in probes if p.kind == "public")
    public_pass = sum(1 for p in probes if p.kind == "public" and p.ok)
    private_total = sum(1 for p in probes if p.kind == "private")
    private_pass = sum(1 for p in probes if p.kind == "private" and p.ok)

    print(f"\n{C.BOLD}[ 测试结果 ]{C.RESET}")
    print(f"  公开 API: {public_pass}/{public_total}")
    print(f"  私有 API: {private_pass}/{private_total}")

    # 详细表格
    print(f"\n{C.BOLD}[ 详情 ]{C.RESET}")
    print(f"  {C.DIM}{'端点':<46} {'类型':<8} {'延迟':>10}  状态{C.RESET}")
    print(f"  {'-' * 70}")
    for p in probes:
        icon = f"{C.GREEN}✓{C.RESET}" if p.ok else f"{C.RED}✗{C.RESET}"
        kind_color = f"{C.CYAN}{p.kind:<8}{C.RESET}" if p.kind == "public" else f"{C.BLUE}{p.kind:<8}{C.RESET}"
        lat_str = f"{p.latency_ms:>8.1f} ms" if p.latency_ms is not None else "    -"
        line = f"  {p.name:<46} {kind_color} {lat_str}  {icon}"
        print(line)
        if p.ok and p.summary:
            print(f"    {C.DIM}└─ {p.summary}{C.RESET}")
        elif not p.ok:
            err_msg = p.error or "未知错误"
            print(f"    {C.RED}└─ {err_msg}{C.RESET}")
            if p.error_code and p.error_code in ERROR_CODES:
                print(f"    {C.YELLOW}└─ {explain_error(p.error_code).split(chr(10))[0]}{C.RESET}")

    # 汇总
    avg_lat = sum(p.latency_ms for p in probes if p.ok and p.latency_ms) / max(1, sum(1 for p in probes if p.ok))
    slowest = max(probes, key=lambda p: p.latency_ms or 0) if probes else None

    print(f"\n{C.BOLD}[ 汇总 ]{C.RESET}")
    print(f"  总测试数: {len(probes)}")
    print(f"  通过: {sum(1 for p in probes if p.ok)}/{len(probes)}")
    print(f"  平均延迟: {avg_lat:.1f} ms")
    if slowest and slowest.latency_ms:
        print(f"  最慢端点: {slowest.name} ({slowest.latency_ms:.1f} ms)")

    all_ok = all(p.ok for p in probes)
    print(f"\n{C.BOLD}{C.CYAN}{'=' * 70}{C.RESET}")
    if all_ok:
        print(f"{C.GREEN}{C.BOLD}  ✓ 所有测试通过{C.RESET}")
    else:
        failed = [p for p in probes if not p.ok]
        print(f"{C.RED}{C.BOLD}  ✗ {len(failed)} 个测试失败{C.RESET}")
        for p in failed:
            print(f"\n  {C.RED}● {p.name}{C.RESET}")
            print(f"    {explain_error(p.error_code) if p.error_code in ERROR_CODES else p.error}")
    print(f"{C.BOLD}{C.CYAN}{'=' * 70}{C.RESET}\n")

    return all_ok


def print_json_report(probes: List[Probe], precheck_info: Dict[str, Any]) -> bool:
    """JSON 模式输出"""
    report = {
        "precheck": precheck_info,
        "probes": [
            {
                "name": p.name,
                "kind": p.kind,
                "ok": p.ok,
                "latency_ms": round(p.latency_ms, 2) if p.latency_ms else None,
                "summary": p.summary,
                "error": p.error,
                "error_code": p.error_code,
            }
            for p in probes
        ],
        "summary": {
            "total": len(probes),
            "passed": sum(1 for p in probes if p.ok),
            "avg_latency_ms": round(
                sum(p.latency_ms for p in probes if p.ok and p.latency_ms)
                / max(1, sum(1 for p in probes if p.ok)),
                2,
            ),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return all(p.ok for p in probes)


# ──────────── 主入口 ────────────

def to_okx_swap_symbol(s: str) -> str:
    """⚠️ v1.8.3 已迁移到 code/utils.to_okx_swap_symbol()

    本函数保留为薄包装转发，保持向后兼容（test_connection.py 是脚本，
    其他 code 模块可能 import 这里）。所有调用应该改用 code.utils 版。
    """
    from okx.code.utils import to_okx_swap_symbol as _impl
    return _impl(s)


def get_default_symbols() -> List[str]:
    """从 config.json 读取白名单，转成 OKX SWAP 合约名"""
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "state", "config.json")
    try:
        with open(cfg_path) as f:
            data = json.load(f)
        raw = data.get("trading", {}).get("whitelist_symbols", ["BTCUSDT", "ETHUSDT"])
        return [to_okx_swap_symbol(s) for s in raw]
    except Exception:
        return ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]


def main() -> int:
    parser = argparse.ArgumentParser(description="OKX API 连通性测试")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    parser.add_argument("--symbols", type=str, help="自定义测试 symbol，逗号分隔")
    parser.add_argument("--skip-private", action="store_true", help="跳过私有 API")
    parser.add_argument("--bar", type=str, default="15m", help="K 线周期（默认 15m）")
    parser.add_argument("--no-color", action="store_true", help="禁用颜色")
    args = parser.parse_args()

    if args.no_color or not sys.stdout.isatty():
        C.disable()

    # 加载 .env（兼容直接 python 调用）
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)

    # 预检
    creds_ok, info = precheck()
    if not creds_ok and not args.skip_private:
        if not args.json:
            print(f"{C.RED}✗ 凭据不完整，请先配置 .env{C.RESET}")
            print(f"  参考：cp .env.example .env && 编辑填值")
        return 2

    raw_symbols = args.symbols.split(",") if args.symbols else get_default_symbols()
    symbols = [to_okx_swap_symbol(s) for s in raw_symbols]

    # 构建客户端（mode 优先用预检解析的结果，避免 .env 与环境变量混淆）
    client = OKXClient(
        mode=info.get("mode", os.getenv("OKX_TRADING_MODE", "demo")),
        timeout=10,
    )

    # 执行探测
    probes = build_probes(client, symbols, args.bar, args.skip_private)
    for p in probes:
        p.execute()

    return 0 if print_report(probes, info, args.json) else 1


if __name__ == "__main__":
    sys.exit(main())