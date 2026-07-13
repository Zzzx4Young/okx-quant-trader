# **OKX 高杠杆短线合约交易：回测系统与架构设计方案白皮书**

本报告针对在 OKX 交易所进行 3-10 倍杠杆短线交易（BTC/ETH 永续合约）的回测系统设计，深入论证 5 个核心决策点，提供量化逻辑与工程落地的标准方案。

## **决策点 1：撮合模型 (Matching Model)**

### **选项评估**

* **A. 当根 Close 信号 \+ 下根 Open 成交**：这是 Bar 级别（K线级别）回测的黄金标准。当 ![][image1] 时间周期的 K 线收盘时，价格 ![][image2] 确定，策略计算出交易信号，并在 ![][image3] 周期开始时以开盘价 ![][image4] 成交。  
* **B. 当根 Close 产生并成交**：这是一种极其危险的“未来函数”陷阱（Look-ahead Bias）。在实际交易中，当 ![][image1] 收盘价 ![][image2] 产生的瞬间，该周期已经结束，你无法以 ![][image2] 价格买入。强行在回测中使用此模型，会导致严重的“纸面富贵”，实盘必亏。  
* **C. Tick 级模拟 A**：利用更小周期（如 1 分钟或 Tick 数据）去模拟大周期（如 1 小时）K 线内部的波动。虽然精度最高，但数据存储和计算开销呈指数级增长。

### **论证与建议**

**坚定采用：A 方案（当根 Close 信号 \+ 下根 Open 成交）。**

#### **1\. 规避未来函数（Look-ahead Bias）的数学定义**

如果在回测中，你在 ![][image1] 时刻计算出的信号，使用了 ![][image1] 周期内尚未发生或仅在结束瞬间才确定的价格进行成交，就会产生偏差：

![][image5]在 B 方案中，你假定能以 ![][image2] 完美成交，但在实盘中，从信号发出到 API 接收并执行，存在网络延迟 ![][image6]。你实际的成交价（假设为做多）为：

#### **![][image7]2\. 代码级规避逻辑（Bug 1 教训避坑）**

在编写回测循环时，必须严格执行**时间轴隔离**：

\# 错误示范 (Bug 1: 引入了未来函数)  
for i in range(len(df)):  
    signal \= generate\_signal(df.iloc\[:i+1\]) \# 包含了当前 bar 的 Close  
    if signal \== "BUY":  
        execute\_trade(price=df\['close'\].iloc\[i\]) \# 错误：无法以当前收盘价完美成交

\# 正确示范 (A方案：信号与成交隔离)  
for i in range(1, len(df)):  
    \# 1\. 仅使用已经完全闭合的 T-1 周期及之前的数据计算信号  
    historical\_data \= df.iloc\[:i\]   
    signal \= generate\_signal(historical\_data)   
      
    \# 2\. 在第 T 周期的 Open 价格执行成交  
    if signal \== "BUY":  
        execute\_trade(price=df\['open'\].iloc\[i\], timestamp=df\['timestamp'\].iloc\[i\])

## **决策点 2：数据范围 (Data Range) 路线图**

### **选项评估**

* **1h K线优先**：1h 数据量适中。1 年的 1h 数据仅有 ![][image8] 条，便于快速开发、调整数据库 Schema、编写向量化（Vectorized）回测代码。  
* **5m K线优先**：数据量是 1h 的 12 倍（1 年约 ![][image9] 条）。虽然更贴近短线实盘，但开发早期的调试等待时间会拉长。  
* **1m K线优先**：1 年约 ![][image10] 条。调用 OKX API 获取历史 K 线（Get history candlestick）单次限制 100 条（部分历史最高 1440 条），1m 数据会迅速触发 API 限流。

### **论证与建议**

**坚定采用：先 1h 跑通框架，再向下兼容 5m/1m 的渐进路线。**

#### **1\. 数据量级与计算效率平衡**

在 Phase 1 阶段，你需要频繁重构回测引擎的底层类（如 Position, Account, Order）。如果一上来就使用 5m 或 1m 数据，每次回测耗时从 0.5 秒延长至 10 秒以上，会严重阻碍开发迭代。

#### **2\. 渐进式兼容设计**

在设计数据结构时，将 K线时间步长（Timeframe）作为参数配置，避免硬编码：

\# 配置文件 config.json  
{  
  "backtest": {  
    "symbol": "BTC-USDT-SWAP",  
    "timeframe": "1h",  \# 跑通后直接无缝切换为 "5m"  
    "start\_date": "2026-01-01"  
  }  
}

## **决策点 3：是否包含资金费率 (Funding Rate)？**

### **选项评估**

* **包含（推荐）**：资金费率是永续合约回测中最容易被忽略，但对高杠杆短线交易杀伤力最大的“隐藏摩擦成本”。  
* **不包含**：不包含等于自欺欺人，回测盈利的策略实盘可能因为资金费率磨损而亏光。

### **论证与建议**

**必须包含。它是高杠杆合约回测的核心物理量。**

#### **1\. 高杠杆下的资金费率磨损模型**

在 3-10 倍杠杆下，资金费率的支付是基于持仓名义价值（Nominal Value）计算的，而不是你的保证金（Margin）。

假设你的账户本金 ![][image11]，使用 ![][image12] 倍杠杆，开多名义价值 ![][image13] 的 BTC 永续合约。

若当前的资金费率 ![][image14]：

![][image15]这笔费用占你保证金的比例为：

![][image16]OKX 的资金费率结算频率在 2025/2026 年升级了自动调整机制（常态为每 8 小时结算，极端波动下会自动缩短至每 4 小时、2 小时甚至 1 小时结算）。如果你的短线持仓跨越了结算点，单日仅资金费率就能磨损掉你 ![][image17] **甚至更多** 的本金！

#### **2\. 回测中的计算实现**

在回测时间轴推进到结算时刻（例如 UTC 00:00, 08:00, 16:00 等）时，必须检查是否有未平仓位：

def apply\_funding\_rate(position, current\_timestamp, funding\_rate\_data):  
    """  
    检查并扣除/奖励资金费率  
    funding\_rate\_data: 包含时间戳和对应费率的字典  
    """  
    \# 检查当前时间戳是否属于 OKX 资金结算时间点 (根据 OKX 最新机制，需动态匹配)  
    if is\_settlement\_time(current\_timestamp):  
        rate \= funding\_rate\_data.get(current\_timestamp, 0.0)  
        \# 多头持仓 (size \> 0)：费率为正时支付，费率为负时收取  
        \# 空头持仓 (size \< 0)：费率为正时收取，费率为负时支付  
        funding\_fee \= position.nominal\_value \* rate  
        position.account.balance \-= funding\_fee  
        position.accumulated\_funding\_fee \+= funding\_fee

## **决策点 4：Phase 1 是否进 main 分支？**

### **选项评估**

* **是（合并至 main 目录）**：方便进行持续集成（CI），通过特定的功能开关（Feature Flag）或独立子目录（如 src/backtester/）来隔离，确保实盘交易器（Live Runner）的运行环境绝对安全。  
* **否（独立分支开发）**：分支长期分离会导致后续合并时产生海量冲突（Merge Hell），极易引发生产环境故障。

### **论证与建议**

**支持建议。合并至主分支，但采用严密的“物理目录 \+ 配置隔离”架构。**

#### **1\. 推荐的目录划分**

openclaw/  
├── config/  
│   ├── config.live.json      \# 实盘配置文件  
│   └── config.backtest.json  \# 回测配置文件  
├── src/  
│   ├── runner/               \# 绝对隔离的实盘执行引擎 (Live Runner)  
│   │   └── live\_trader.py  
│   ├── backtester/           \# 本次新增：回测引擎核心模块  
│   │   ├── engine.py         \# 回测驱动器  
│   │   ├── matcher.py        \# 决策点1：A 方案撮合器  
│   │   └── data\_loader.py    \# 历史数据加载器  
│   └── common/               \# 公共数据结构（解耦核心）  
│       ├── models.py         \# 共享的 Position, Order, Trade 定义  
│       └── okx\_client.py     \# 统一封装的 API 客户端

#### **2\. Feature Flag 隔离机制**

在启动脚本入口（如 main.py）中进行严格的运行模式分流，确保在回测模式下，**交易 API 的写入权限被绝对物理锁死**。

\# main.py  
import sys  
import json

def main():  
    mode \= sys.argv\[1\] if len(sys.argv) \> 1 else "BACKTEST"  
      
    if mode \== "LIVE":  
        \# 启动实盘逻辑，加载私钥，连接 WebSocket  
        from src.runner.live\_trader import run\_live  
        run\_live()  
    elif mode \== "BACKTEST":  
        \# 启动回测逻辑，严禁加载任何实盘写权限的 API Key  
        from src.backtester.engine import run\_backtest  
        run\_backtest()

if \_\_name\_\_ \== "\_\_main\_\_":  
    main()

## **决策点 5：复用 demo OKX 账户拉历史费率？**

### **选项评估**

* **可以（推荐）**：无需实盘入金，甚至无需加载敏感的实盘私钥，直接通过公共 API 就能获取完整的数据。  
* **否**：单独为其设计一套爬虫或第三方数据源接口，增加系统复杂度。

### **论证与建议**

**完全可行且推荐。但需要注意 API 的请求限制。**

#### **1\. 接口可行性分析**

OKX API 提供了获取历史资金费率的公共接口：

GET /api/v5/public/funding-rate-history

该接口属于**公共接口 (Public Endpoint)**：

* **无需鉴权 (No Auth Required)**：不需要 API Key 签名即可调用，调用限频独立。  
* **Demo 与 Live 共享数据**：在模拟盘环境（携带 x-simulated-id: 1）下调用的数据与实盘完全一致，因为历史费率是客观市场事实，两盘共享。

#### **2\. 工程实现代码示例**

以下是利用 OKX 模拟盘连接直接拉取并保存 BTC 历史费率的轻量化脚本实现：

import requests  
import pandas as pd  
import time

def fetch\_historical\_funding\_rates(inst\_id="BTC-USDT-SWAP", limit=100):  
    """  
    拉取 OKX 永续合约的历史资金费率  
    """  
    url \= "\[https://www.okx.com/api/v5/public/funding-rate-history\](https://www.okx.com/api/v5/public/funding-rate-history)"  
    params \= {  
        "instId": inst\_id,  
        "limit": limit  
    }  
    headers \= {  
        "x-simulated-id": "1"  \# 使用模拟盘标识，降低被实盘 WAF 拦截的概率  
    }  
      
    try:  
        response \= requests.get(url, params=params, headers=headers, timeout=10)  
        data \= response.json()  
        if data.get("code") \== "0":  
            records \= data.get("data", \[\])  
            df \= pd.DataFrame(records)  
            \# 格式化数据  
            df\['fundingTime'\] \= pd.to\_datetime(df\['fundingTime'\].astype(float), unit='ms')  
            df\['fundingRate'\] \= df\['fundingRate'\].astype(float)  
            print(f"成功拉取到 {len(df)} 条 {inst\_id} 历史费率记录")  
            return df  
        else:  
            print(f"拉取失败: {data.get('msg')}")  
    except Exception as e:  
        print(f"网络异常: {e}")  
    return None

if \_\_name\_\_ \== "\_\_main\_\_":  
    df\_rates \= fetch\_historical\_funding\_rates()  
    if df\_rates is not None:  
        print(df\_rates.head())

## **总结：Phase 1 架构实施建议表**

| 决策点 | 采纳方案 | 核心工程落地动作 |
| :---- | :---- | :---- |
| **1\. 撮合模型** | **A (Close 信号 \+ Open 成交)** | 严格在回测循环中使用 df.iloc\[:i\] 计算信号，df\['open'\].iloc\[i\] 执行成交。 |
| **2\. 数据范围** | **1h 优先，向下兼容** | Timeframe 参数化配置。首期在本地 SQLite/CSV 中只存储 1h 数据，架构稳定后无缝拉取 5m 数据。 |
| **3\. 资金费率** | **必须包含** | 在回测推进器中设置 8h（或动态）结算检查点，根据 Nominal Value \* Rate 扣除/分配账户余额。 |
| **4\. 分支集成** | **进 main，物理隔离** | 在 src/ 下新建 backtester/ 子目录。入口脚本根据命令行参数和环境变量（Feature Flag）进行启动隔离。 |
| **5\. 费率获取** | **Demo 账户拉取** | 直接调用非鉴权的 /api/v5/public/funding-rate-history，并将其缓存至本地，避免重复请求被封禁。 |

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAA8AAAAaCAYAAABozQZiAAAA0klEQVR4XmNgGAV0BsbGxqwKCgqF8vLys4jBMjIyQnDNcnJy5UDBfUjmMQD50UD8HygniC4OFwOawgkUWCMrK2uLpIYRqGA+SDOSGBgAxX2BruQAc4CadICKloIMQVIgCBQ7jU0zUCwIzgGakgDEGUjyIM3GQEVfgfgtsjgIAMWK0MWQAdzJQDwJXRIvkJKSEgFqugrVHI0ujxcgOxmINdHl8QKg/9Ohtp5Gjya8YOCcDNRcD7X1CtD5CujyGEBRUVEcqPguVBMGBnkFXc8oGHIAAKS5RTYSE2fOAAAAAElFTkSuQmCC>

[image2]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACgAAAAaCAYAAADFTB7LAAACTklEQVR4Xu2WP2uTURTGE2zFohREQ2j+vYkGpHGoJbjVTaRSREfBQcVBv4CIHdwcOjg0WAUptB9A0KV06eAggu3iN7AUpFM7iO0iVn9Pc9/2cJKoYHwtkgce8t7znHvvOffcP0mleuihh/8IURQNw2fwRalUWgt8rXZgo1gsXqrX6/2+b6IgkMtwtVAo5J2Uxv4Ufue7z2nJgQAew4VyuXzEa6zoAwUIh7yWCLLZ7FEmX1IgXgN9aC8VYKVSyXoxERDYKQJY53fMayq5Sh9KnPZ6IgjlbdljlPsh9m/wXT6fL1gtMWQymWME8EYBmlO8RnsTvoUTuB3y/XSqtSfVP5hafLqCqHnNbMAdr7VDtVodxLehJFjhm3y/4vc27efelz0bYX9vE3eLMJP6VWI43dDqwVWveRDIOfw+Mvgj9uaAbFpJ2nNK0vtrbPpMx760t2UzemPfuw0Y+DhOKwqQge563UKlxGeZvXjCazpcaFPezriTpqn7dEVzxga+Lxq9FTjU6bSlzHgtznvdggCu2+wtdNJVTm+3yOVyJ+k/6+0/BR3ua/XgJyY443WDdCjjsBd+F1rlTgm2gGBGcP4cgtuj7N5XiE+6LY9BularHfZGD22hTuP/MeIAzZWyh1Lzkrd7rR12X6MOCXYHTDDKKtxKmdeE9j0mvbLvtWubwveDvdhDeb9av78CJlmHi1HzarrDwbrgXHRSn8AdOEFg8+G++6ItpG8SuOr6dA/hzjvLJNcI7rTXY6CPi95+UKBVnIQVLxwU6On6N/96ksIPc2eTU8fM2gQAAAAASUVORK5CYII=>

[image3]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADIAAAAaCAYAAAD1wA/qAAABfElEQVR4Xu2UO0sDQRSFs4igaKO4LC77cAsLwW7/gmBlY5vGSq1t0gT8D9oJIhZ2tvb2FjamTGMppFSwcT0XxnA9rNmXyaLMB5ewZ+bMnTPMpNOxWCyWP0eapvNxHF+UrH4QBKu8xrSRPW4A1r8RRVGPN4cNZ6gHjK0orctaEZ7nLWHtTdbLgD476PeBejP7uec5Y9BkERNuSXaM8UyLWHgP2h0OZkHrk4Anheec9TJIHynTd3KQMAy3MeFGa3LixtjVOr73OVwRTYJ8USoIEh+gjrVmmo9QW1rH9wnmHmmtiJkFycGB8arqyf9Ea0F831+DYRDTtapLa0FM49eYrlUZkiTx4FvXhau4i99L1qVgcXiNPGoFkTcgJnnwPFYEfEP4nnVBe0G9sy4lf828Rh6Vg6hrlfFYXVq5WupajXisLjMP4rruMgynxvDE43X5hSBzWOPQ7OuRB8eYBzo0E7kGct3YU4UmQYyX95ThHV/z3KnTJIjFYrH8Xz4B6Z2Uk7BWf/wAAAAASUVORK5CYII=>

[image4]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADoAAAAaCAYAAADmF08eAAACrklEQVR4Xu2Xv2sUQRTH70gsxJ/RHIf3Y+fuODgsRGW10sJCRREF44FCOisLQbDQP0BSWBnEKlEsU6ilNjZBG9FGBFEIggRBEFQUY2HQ+HnszGV87i0XueAt7BceN/v9vtmZ7+ybySSXy5AhQ4YM/wnGmKPEFHErCIJ5fp9L23JTcBfK5fJW3S+1wNR14qbma7XaEfhfxFypVKpqPVUoFArrMTJLjGuNLxrCLxBL8vW1nipgpoGJ9/V6fafW4MesyUXy9ms9VahWqyfEDEZGlJSHvyEaJfw01XvVK9slJQ3BvSK+pL5kBa5s7RedtyfvO+In7UvNZnOj7iPgC28mZxvNIa0NJFzZEi+1FgfM7yP3Ib/XiLZdlK5fHO21W8C40Pm9gDkfZqF3aT4RTGTCGr2rtRjInn3CIDVH8HzKRBWx28vrAP5izn512mPegZbnNVc7iRZhGK6RatG8QMal/22ZL7/Htd4VwXLZfmeV9mrdhxghPmve2+Oz0vY1z1Su1WptIOcxzWHH2UX4A/QJ8XNO8z7ot7Aio37ZchkY1bqHYXJmZFG0wIAj8M/ijPpA30581LzGqhilw7Q1+iBpkpVKpUzOW+K+1pwBKSke81p3IGecWNS8Rl+NysWA5K/WZCeKxeI6nSuQweXlxITW4M5LXyZ3Rms+THTFfKN5FnEt7z9EtG1cJm/ae24zX+P36dnoSuGMyiS0ZqLD6VGj0dikNYdgubz/OvAGyijI8+JJBpjzOQyehjvmcTKJO0ZtBWPLNujhCimL2rfS/RdIWQfR0X5SBrHtGZ0Hd4/4JBOWK2MQXUB+mGh7fOAA3KP7+EgyytffgfbCvuubvJs4qPP6AjHJYAeSDi8mcTbuH4RekGR0oCB7DqNXkvZsEqQ/sUXzgwi5BXX9M5NhFfAbtjTPlmEUZlgAAAAASUVORK5CYII=>

[image5]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAmwAAAAuCAYAAACVmkVrAAAEjklEQVR4Xu3dO4hdRRgH8Fyy4vuFxiX7uLs3u7oEFJFFRdEq8YGgCIqNEOzsTSEGC3EbO0UCFlZaqSAWNpbBND4aBQMiBFQiomJpk6Dr921mbiZn742J2U2y4feDYR5nzutukT9zziHbtgEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADABTMzM3N1v99/tlOejE3bu3Mvhrm5uQdHXFuvO2+riOvf0/29p6enb+nOAwBYJ4LR6o4dO65r+gejDLI9Pz//XoSKmVOzL6y8tk7/WFzTi+3YVhLX/2cEtYdqf3Z29t4Y+6edAwCwzojAdiBCxXI752KJa/m601+NkPNUO7aVlAA6UfvxO78cY381UwAA1msDW66s1VWtCBN7s52homx7P9rPZZiL9h/N/rnqdVWUV8pjyw0xNTV1axz7+dqP9jNx/J/bOVtJXP/uKCeaoV7+vhdzBRMA2CLawBZ6JRStvSuWYa0GtghkT9dwEfscHgwGd+d+0T5a9s1HfA/XdrE9tu8cVzLodeYP5aPPDIN5PVF/s2vXrjvKpuEK1Vm6JN57i3t4O8rxvJ9yT/u7cwAARuoEtgxpN0f5rLSHgS0/Uoi5v0eQ+jDq73Olrcz5II+RZSNXi+J4R7pjKd+r646dSXtvKa53b9sfJ+73ru5Y1R/xAUEt4/abO/n+2lmd+/9qjx/nOzo5OXltux0A2KJGBbYYO1Taw8CW85aXl68o7UMZ2CKc3F5XvjKsZUiox0m54tYvK0qjSsx/vZ3fyvN1x9KowDYYDCbbfvn6cm1lrb23uNYb+6c/tt3erPL1on1T1BNRz+f9NfPOW97PuBXFhYWF27pjrfZr0jjOznZbK47/eXcslfNeEl//AgDnpj6uXI3gtZjtCD5Rzf2dwSz/kY/Q8mb0V7Kf8zLwlP2ORxh7NMNPlB/yYCUMvdU5xznLc5WvJ08LklUNJVF/FNVEzPst+1EfK/WPpV57X6w8tv24jO2sgS0DWZznzgydMf5AHO+FOl5L9jdCHP+JvJ88f3dbv6xmxrYvSv1rziurlXl/B7edDJ/5Nzi0uLh4Q9SfLC0tXd8/FaZ/auvSPpD3Xv4mvRpqc075+64LvgDAZSCDRF0lKmEqg0QvV4jGrR5ttBo0SljMDyD2R3k1yi853oaWMu/LCCv3lW3DwJbHqUG1BJs3or2aoXWjA9s4ee4oK1nXQBWB7Moa4sp17MvtGWJrQEvlmscGttxWwurwK9TSX5uT9z8qEAMAnLcRK2yHsx/1iRJ+1lbcYvtjWZeQ8l00e/nl6fzJjxly3j0Rah7JOVHvifHHy3FeirI7xvbG2Gs5tpniXN+W+kCp343z3l8+4Mj7+zTH49qvifGvypyVfD+tBLb82rQGtiO58la3lVD3Ts6J/WfLHIENANh8nf8hoNcNHmf6HwQ6c9t96ztsa9r2Zvuvd9ja7W07H22Wx5vDa+3+FmneO2wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACXt38BOY0CxR+oUGcAAAAASUVORK5CYII=>

[image6]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABkAAAAZCAYAAADE6YVjAAABj0lEQVR4Xu2TvUoDQRRGs0QRwUY0SrK7SZZsKVgEBCstFGxsrAR9AItUNraCL2ARsLGx1sZGxFIbIY2p0ipoo4UgWIhgPDfOyuRmggG12wMfzNzfuTO7mUxKik2pVKqhNqqz9bT/T6B4yzR5DsNwRvtdlMvlxUKhMKntfaH4DXqURsVicV/7XZhDbWu7kyiKpjnVAgl7JvFJxzjwiPvgQEva0UOlUpkiuGG2nkwhjYIgiLsCFRxslrgTlkPa1wNFN9Fpspf3kHdhsl0rrIPv+xP4mmZaW3cor+M7SBLFLmmybJnlGuroHkWWXciayfPomLxVWUsdyVOxX9BgnaAzrmbUtptp2q5pBIqP42+Q52tfF/0aJOB7lUYU3HH4NsSn7T3Q5ILANW1PwHcohVBLvj6H7922OZEmuVxuTNsTKDKP3kyjWmJPrgrdyl5qyGRxHI98Jws0WDHJA4ucLck1n+4L+yPWc6yvePigq4G8Aac510UGUFPyq9XqMPkH7B/Q9U//02/wzGeb1Y6UlP/lE7rGgIAP7rPrAAAAAElFTkSuQmCC>

[image7]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAmwAAAAuCAYAAACVmkVrAAAFCUlEQVR4Xu3bX6hlUxwH8HtDjRDFGOaec/a9dzANCk3RIHkgxFBMeVAevIyH4YEkbwoPlELShMKDojx4wYsyeRLlidRoYuRPTaEUqWnw+81Za2bZzr3GmLn3Dp9PrfZav732Pvuc+3C/rb331BQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAALKfp0Wi0pW3D4XBtf9JSmpub6/rXFO2C/ryVKq7/qrjer6Kd33XdE1mL7R3Rnu/PBQA4JGvXrj0jwsTvdTwzMzNox8shPv+ZaG80pem8ptnZ2VVNbUnF5z/Xr/VFSHsp5m2o4+j/1PQP/KbR/zQ203UMALCoCEFbI0B8VMfD4fDmFRDYvo/wc2UdDwaDmXJNyxZy4nd6pV/ri2t8N+Y9VMfxHd5s9i3rbwoAHMNytSfaHc14X4SOi9s5S62Em+PrOILPzqhta6YsuUMJbHk7N689W97KbffVwBb118qcs+Ocd5f+e1G/N8YfxnZ7mf9J+d652vhCjrM+Pz9/avT35PF56zU/M+sbN248IWq/Ru2m2P4W57olti9Guz9DZNTvjP47B68IADhmlMDwdf7zj+1jU/98FWvi/NWrV5+coWKhNrXAcbFvQ15TeQ4s28sZRnpz8vjj2trRdiiBLQ0GgxObUPZZree46e8u32H/eWP+5mbf3uFweGHd19Q/jrYtf4uoP5y1cvt6V9n/aleCd2x31HNG/5fmHD/NLuNtZQDgMPSfXzsccfzX/dq/0Y1XlN7q11M3Xi2aLf3bol3S239fbkfj26nTMXVr3dcPfXmemP9FG5Zaa9asOWnUvPgQ099vx3Hs5f1jorapGf7pubv2d+4WD2wZth6s+2o9a7mv1B/vxqtsD+S5ynG3Rnu29D+Ov+2w9H9sr7v/OwAAK1wGmm78APyiZmZmTq/9DCA1hKQaGPoiHLw8OrhK9pc2Pz9/Xv+Y1I2fX7tmQv2SrrktWlbwdtTxqDzztn79+lOmyu3UrnkBIPZvrP22NlogsPW14Wkh8Xnv9cY/Tx28lkMNbN/V799+ZtTfiPZM7HspA1up5Wrl7qhdkcdEm4/xc+3fq2tW2KbGq5oTVzYBgBVobm5uTfwz/zbaIxl+2n0ZFAaDwTkRAO7pSqCL7UcZBGL7YgaDmHN9qU8MbIejnP/3/OypXrCI+pe9oLghw0s7p9QPPI/XWqLAtiPau9mP+Wd15bmz+uZt/ublO+6J/kVlXga2ndmP2qWx78fmfPtiM12eW9v/0kVsn6zfO7bb81zR3o62KdoPUfsqzvl6s8KWL0JcV/oTVy4BgGNQb2Xnm6557iy2u6LdOCq37bojGNgW041Xq9rxBxlk2lqpH3jjNcV1Xjsa3w58sGy31Af1j3Rgq8EotldPCoiTlMC2OYNc9E/r78swvW7dujPbetYy/NV+bjOY1XnlBYT8O83lOM6zqs4HAP4jeoFt/wpb1C6LtjVXi8K5UX+03JZcksAWoeapumoU13F7hsbSXxX9t+u86O+t/dakAPVPAtvRUgNbv57av8PfKYH2wKpkHPtQfXkBAPgfmG1Wftr+UstVovj8q/v1CCt39Wt9kwLbcovrviHa89nie822+2L4dNl3Q1tfTIboaPuifV7DLQDAirDQChUAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAh+8P2GA6oLyaTw4AAAAASUVORK5CYII=>

[image8]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACkAAAAZCAYAAACsGgdbAAAC8UlEQVR4Xu2WPWiUQRCG7zCCouJvOHJ/3+VATlGQcGghIhYKprCJAQUF7bRIpyBa2VjZWipiFQQJiNiIhAMLBSsLiYiFBsmhYoKBpAmePu/dTNhvcwmopffC8O28Mzs7uzs7d5lMDz308B+gv79/c6lU2i+JbUmSDCBXq9Xq1ti2GiqVyrZyuXykWCzurtfr62O7OOKViXtYvrF9BXC8jczg/AB5yHic4DvcTuIH4RaRX/Jj8elQmHM5jIdewW/WYjWQd6EdZOG+m+0eMd5rTuSTQh+Od0lqoxPok8x5ptM1fcQS7CqDg4OHfK7GcLMej/Ew8oN4G4L4p9EvMsxK1w3BTRUKhaL7pMAu6vEV65qYNKev6deQx8iohEQwJwMstIfvS58nXqcC13BOt6ON+IYtoVf4bXcfAa6F782QW4Yl9I3viYztjPF5LZbP50vSsY/F16HTQJ56nXJyBfSPyKLKI/QNoQ0r6ZiH+4TMs9EDsa39YDTJZEKJ8f2MjMS+Dhbah/2NvgF3HK6FNK2GZ5QwMh5eo5+s6w5LsqU4sa0NjK8tybbgWI99QuDzJL4a9Es2fyGxEtDjYzxJvOnAb60ktfap2NYGE0/i8DXpnIQWmkL2xn4ObF+61HH7Gk3GAl7ltOQP6a+SVL/C+EFJ6Vr4TthCc8hQ7G/l8aJWq20J+SDJVE3CV+GaSlb6HyfpL41hX8hXOq9WNfWWGt0V2uBuITdCTghqUosNOK+xOG3C/NZ6OAsrSs0DpEiD7TiVZC6X2wT33BcMEbxuNenlUrHb0UMclq6vkqwEfdP4+Xi9NuzqGmEjN6jBP0LGNXbSN9UtyUznV+QOsuRXK+hk4Ba8ndFicuhT5S59UvMz1gZTSDrd/zrDdc6hn4Fvhr8kgnqYdrxKkoo1lHR+BO4blVVsuJ+R3xWt4bq9C/Xq5Za2Ajp65BiO5/ie7faHwJDVyXQ5+RRUFsS5oEfAde+M7YJOFvuo1mTzR2N7Dz308A/4De21/J8nPaHtAAAAAElFTkSuQmCC>

[image9]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEcAAAAZCAYAAABjNDOYAAADxklEQVR4Xu1XTUgVURSeQYOiX6rXK9/zzVNfSX9UPCq0HyIikqhFCAUtCoLaCC0Co021iRbtolUW0qKCsigiiAiKigiV2hQtIjIXBkEJooKK1vfN3DservPezEOUhPngcOd+55x7zz33zLzzLCtGjBgxYsSYibDT6XTOJAXsmpqaZY7j1OG5zFTmcrkF1dXVCw3arqqqShpcZOTz+VlZAI+2qSMSicQ8rL+lsrJynamTwBKLEHc91zN1YbAzmcwayGMs0GUqCQYI3TvIJ8h1yFdQG6UN/A+A/6ttMH+EsR92z6VdVPAw8G3H+IpJCNBfgfRin26Mw5CHsF8ubXDZi8Hd47kgNyG/IQ3SpiDgvB7Go5BBxzvYD9NGVQsP3Ab7OeQQ0GXMv6lbdSGS4wsDY4D+YhGAdfbAt0fEFJSccvA3dDwcle0LXb2KewLpQFUnyCGe45j3YdwqFwsEy4wbI6A8nAacgOSAa4KMMWjBrXa8W7hmqZJXyemAXMVzM4JcpXWlAIHPxhorRLInJIevES8omUzO1Rzsvij7Js6xzj7GjfGUtqmoqFgK7jN8n+nEhiIkOT/JM2DNMVgGTR/6kuNhEMitcc/JoVhyoFsLvheySXPcW9o73kX58Zl2XF/yBRGSHJd3gpPjb6KTQzvH++acTqVSS8ZXKg3FkkOwwuQcdk9VPK2Y2irmYsk5K/mCCEnOmNooNDmY90NeomRXYrwD+ZMRr2MpCEuOCcerpCG8cjvUnK/9lCeHAUZNjv9BZNVg/gHSo/1KQSnJ4bdTxdJsqe+cOs//kZwg6EBMPgpKSA5bkWbYneGzJjHvm47kTPgg19bWzsf8DWQQZbwZjRgenU4eRNoxAAYScrhAREkOG0Dov0P2c862AX7bLO+nPuiDzG/RbbXuIcEXRkhyuEkfAtkgOH50mbAuBJQSBxnFzezSdqJyyjUXFWHJYTcP3VtIvebgsx3zFstLQpvy95u+oF/ZUBRLDg54EfwIN9acM97n3LW8W6qDvpuVolv0rNevuL8g/mKebwPsGiUXhLDkgO9E1R50vItyBT4XMF6iHvsfUf5HtY/ucyDvA/7qBMLOeg3TCOQX51KpbqgHG7eKg58DN5BVnabqRh9ATmh/PO+GDGXF3wdxc27FaT4I2O+kOtxHvrZSx4MpXZC4yeAPAvZuh7zWicDzYeiHOcr1Jg12o7ipvVj4mOxMDZSxClkZsMtaBTpkBNgiX9OpBC8Ue+1k0ibTd00bEOh9lrjJx7DcV+a8ycWwvJ9flHfa5GPEmPn4BxF7c6sMPR8xAAAAAElFTkSuQmCC>

[image10]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEcAAAAZCAYAAABjNDOYAAAEdUlEQVR4Xu2XW4iVVRTHv4NTKF3Npsm57TMXG5wHA4eKSkpCwaELVFKBDwZBPkYEii++9CoIQ/RghkSYXUyEEkWlhnqJjCCwt4IpROghA5kGVMbp9z/f2mfW7O98p5O+JHx/WOyz/nvttdde39qXk2UVKlSoUKHCzYIasswTPT09t/X19a3ynDAxMXFLf3//msHBwQ1ZPm4JRkdH7xweHr4roWtDQ0M9Cdcxuru7bw8hrNe8aZ8QY5JN2udRr9fvxuYx2ad9pbDJZ1nwMdr9yPvIlYGBgeecWY3+Z+D/QM4jF5FfmPBJZ5Nh8yz8AnJOvsznLHanvF2nYOxRG/8J7TRJDr7fYvoT+VJxo3+cfhwSdw/jP6V/RjZmP+ltSmHJ0YKaokkzVxlKFPxPTDRqVA19HvmLgB+Odi45TVFgCjDadAolAhxSNUrn9yRywNugX8X/q5nFin6WGA7G6mDeFXBfiMdPtzjZo1+ifWTRUwksOaoYyZQWmNrAnaTvBF/lgcihv6PFq09BmJ2Sc9b87DT7wvb7NygmVVtvb+9A5NA/wO9x2uXSbeE/Y3Ovs9kBd412i+lbTN8RbWSvcT7uUigQDCdS3sOyv4C8FTlXJX/H8eK0iMWR14UufB6R77TDg/5t6VyKQ/Eg0/bR9aGa8UVYovVhC4WwBHKirYHx08i7yFSWHNDSx8bG7vCEfSUlZ4Yv0CcuJgdudcjPnDdaHeztoMObsb8iVxm/j/YCMocc9nb07WqTnN8sBrXtkrPL8wVYhmcw3KN9TvsS+oe6sVJbj8F8qy0gb2e2dayaZpGv7Qb5CLkIvykZXgq3wDkW8TJUTWcW+lf+QEaf6iA5OnxvODkvek4Dg1t0K9B/DTnjbwdLTpNT1aD/iFxYHNkeboHaVs354TeEvHq6pGuBHSRHv68/Oa1gTnVlD6V9gm1DHdDpm6aAGEjKlyFJTsqrEtZKpz3QQXIu3Uhyahi+idHrnjTnhQNLyYA/jew1qgubx1X2dvX+gEwrsDhGAciXKjRy7eDOnDnP22KbMYUWBzJPjoc0DvlWZ2RofSDX4A7JF/KC45fCttQ0g4+Nj4/fGnk5DPmBqJdwA3Z17ieg3Zkd2PSvhDvK9ulX0DbhPDYb4zhXOY3t0AFa3lboa31MatHP+LMxxkB7MMuT0PAT3KMvrjkUk1aAAjnM11rnyZCfJ9/FbaNHVcjfQXv5Or0h/4qrcb6J9rQl6VHa31Up8RFGYpbDH1eAif9J7LZ6zoNxr6RjrCqaMVkV69G3MtrU7QbVeNMbfpBt0Sa+c7yvUuB8M07uj7pVyLz/+4DNTpuklRzBpMvGfY68ltlByu+nkMt19/fBfbnmEyDFyMjIffSfc8Fr++8OxYtDVaobrQF+fyPxFwL6956TPeOu+HFtYbfK8yHfxxvT/v+IZSpXVQa+6lnJjcdc71GxD6a8B/1P4GK7tkvZe0mvaM2l2LPi+6wBVbJ8yabMz/8KBPqZf/pXcOBr70m5Cln+TtINl/IVKtz8+AfbQowVUipKJAAAAABJRU5ErkJggg==>

[image11]: <data:image/png;base64,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>

[image12]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAD4AAAAaCAYAAADv/O9kAAACC0lEQVR4Xu2WP0vDQBjGE6ogqKBCjWCbPy1YBbdM3RxcK1IchI6COrn6AcRVobgoSnFw09Gh4CA4OPQDuOgmbgoKFRykPq9e6/X10qaDCZT7wQPe+7yXy5O7pBqGRqPRaPoU13WXHcc5gY5koX7Ie+MglUpNZLPZSV6XSafT86RkMjnCva4gbNm27Qr+NLkXNbiXPegF+oQauK9t3kNgczbhv0vjWYyfjLAZcrncKCbcQCXuxQECjIldTgQF9zzPgncHXcp12kDafbkWCJrnoGcs4HMvboKCI9wSeRRUrlMvHtyGXAsEk4tigXHuxU1QcNR3VR7GBQQ/lWtKpGPe4F4YsMgCFlsJKxxRh1+jE6pwWHOIjrjKo+CoX3f90DnimENv3AtDHMEpFIVTeb0E/z7mUI17IGH/HP9wX8l/QBXOsqxh1K9UXi/ByyL4scLLi/oA96JCFY6g91jlhQru/B7zuq34oqN+Sz8bvC6DeVXx4MKqyK/RCZrDw4l6SVyvbcOoV9XfhjS5Jo50CzzRKdQPjBiPOdEhuAc9QuesTic4L9f+gIYLEfwMQ9P3/UH8iziN8Rr0igUX+ZwoEe8yBd+nLzmzTXg7UL1ZQI+L8QPlkBtb0BOBPkToQPFTEBW0w/xepHsqNPvowWBcgbagdfj39OrJ1+pnTGz0KkKXMpnMDI15g0aj0Wj6kS+GusQeC0Y3mwAAAABJRU5ErkJggg==>

[image13]: <data:image/png;base64,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>

[image14]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAFsAAAAaCAYAAADYMiBQAAAESUlEQVR4Xu1YX2iOURj/vjZFhGG+7Ptz3n1bSkisLMufpZEVLvyJGlEuuHC3In8uuHDnSkRDywUrhgsmtJqxC1kpZZdqJAtRZBeabX4/73PW8x3f93l9/sz0/urpnPOc55z3PL/zvOc87xuJhAgRIkSIEP8HovF4fDpLt0OjqqpqnKsL8RNIp9NTjDG3UqlUJ8rjiURigmtDlJeXo9ssdPVjCowWOLHI87ypbt8PEK2oqJiJsUsgs9zOysrKySTSUUdBWkxFaDFIPg25TR3KZqzjEearQV+R2BRBvwq6XmmPPYgDA3BuJ9sgpxTtbjrsmH4HIblVRWER2s8wl2dtMM866Ia1oPsyxkxzbViyzU2DtJWVlc2wNvKsDjNWo5okMZrgQI92DGTshm5I22YDbPZifJ2jewc5GZFzV4jshpyANCHKZ9s+ixxk32MpJsWon4I0qmFjC3CuCg70Q9pA8Hil/+a8tnVRWlo6SQiZo/VoPzdq8zgX5r6gbVzAvp7Pg2xgG5dkAvVrGFvCdjKZXI/2TT4zc2RAuGdjwRP9AuBAA510ybCbkG9NsEnDps8457RsQD/nELsgZPPWewk5yDbs16DeFJE3APUHppDjQ27dVixiPx2FvIXUQD5wofkcxCKqMW5TUMExMd+dQ8P4r3ZOsk2WC88CNnXoH3Jt6APnJMlix7fkE6QDEboM5SXIe47X4+SCboS8Rt/2iBDNqM7HSV7IIpuUo3uoZx3SgmqxM2QEv5tskixrKIRse/EFIbvdZiTMo9F+DHmF9VXqsS4kzeuSZhRzrUW7F3IoUK4Nw3pMstz4r0YfJkhTD4dXxGKxia79nwSef47EFEI2/eBY18Y4ZGeD2uQjbp+FpIBnjFyKKT9r6gN3i1E22SANBOPf2hkX099GSo6yQsjOZROEbPQfow39d/ss0LfRyKWosqZWdBXjaJnHviz5e3bIw+pdfT7ITnNcIAGJB9w5NDDfUtgNQNr1W2WPiEiez2bYlMCmG5G2QOuNn430gqC4tLmWQayl1trYyDY+eRlwI5qwG6uCgqngeeqtTU5I2jRyhIwW5LJ+SNJIntV7fp6dkfohmlbTVut4DHDDtM74b+zI3YP+F3yD7BnLNxn9bZwf9a16LGH8iL6iP9e5odB9tGQLf9fdjc4KkswHjuYRYoG1bDN+5G1hmxuA+n2KtVE59bDODHjBYXyzuqyixo/AamuD9lXILvZJeyXkM2zuZssyMF8nZK7WMWfHmB7IRTSjfGtQv6E/xHICD6rlbrv60YCkXIeNn3o2eP4/iadOpkASmZYNsq70JO8NpIVRivIs/NqsbeQDpcv4CQGzsC+e87luwbV4OS4+eX4PojmGZ+yD3dFInmNOgz9X7A+WfwKIkiTJlnMw8Np41vOIgfM7WLr9Av5E4rnLzfQiOUhiTp0rpZNLkmf5E5R3Al+OIUKECBEiRIgQo4avjPxkkFJzirAAAAAASUVORK5CYII=>

[image15]: <data:image/png;base64,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>

[image16]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAmwAAAA4CAYAAABAFaTtAAAHL0lEQVR4Xu3dX4iUVRjH8REtioqysm3dmffMrpVoQclSIhnRn4u8qKAE+wcaEXXRlVCRNxUSVIRlUEQtlRddJJZdZJB1oXkjGFJhfyCFDFEIvOhiBZW03zNzznr22Xf277iz5fcDh3Pe55x558zsxftw5rzvVioAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPxPhBAOqZxWOdzT03OFxeoSY/+oudS/BgAAANMsJmfdLvZ9fgwAAIAOUnJ2siiK/nSs9mPVavXCfEyuXq+/VhJ73McAAADQJkrYDirheioeztHx+mEDRpqlMT+mg7yd6+3tvUXnXa2ySWM+UPnDjwEAAMA4KJH61pIqa6ve7vtbaCRtKg/6jkR924qiWK56d19f36WqT/gxAAAAGAclUutU9ii5ut6K729Fyd0ave4XH8+p/xOd824fBwAAwAQoobpXidWgrbT5vlaUrK3q7e0N1k51GZ3zmMZe4OMAAACYACVcXUqsfvXxVpSAbSyJjbjpYN68eRezb+2/T3/b2/V3PN7V1XVRHrdEvVqtXpvHOkVz3Kw5/lASX+1jAABgmhVF8bHtjVM5rPKN759pNMd3S2J2Q8ZpJRcP+77J0Hfyqp1P5Vnfl2jMrTZG9c4Umz9//pU6fkvxbs3l0xi2m1B2WUOx79TeqzEr7bsOE1iRHSfbF/mb/T17enqqvtNWavXeH1mfxqxQ+TzGH6rVajdbW7EjOt5oMbX/Hn4GAADQMbowH/CxmUZzfMIel2JJkosPpFUqJRlr8r7J0jnvSLXe83nfr8Sspr6t1u7v7z9P7d+trbrb5mclPdbFHvdSjzek5OfSmHdUzUrH7aBzDlbiOdXe67rTim1jfvXs0TI63mFzt7bm+EUW35baAACgw+wC7mOeLuRP+lgY+/Elbefnmh/bylHZypLGvOJjZZ/HKL7cEhtrL1y48BK99pgfo9gW27eYHdscbHWr2xK0bGj6uXxLHPeh1TZHe2RLPm6q9L5zQzNha1B7Xd5v7HPl8040dkDxvth+P9ZtTygBAMAkxYRizIStWq1erov6c+k4NH8+HXFBt31Z9nOaynaN2aqyu2zcZPm55scxYRqRkMjsON8G+xz2mJR8QGKrYClhSytSfoxiB33CZu9tRZ97teojKkuy/n36Xm5U/Ug8bvvKlSWKIUvY8s+RxM/zjMpfKvsr8e8SVwn3q6y39tlIKAEAQKWZrLQq6X+cllH/WpU9Pl4mJW2hmfzM9v1GfZ/Zao3qQ5Xm/q0RCU8lrka1Kn5wzp8vP7bXtkjYTCNps/nb5/CdyVQSNtsjllb4dDxoP52eedXQ2MbKVdxHtkuv2ezHGP+d5KVS8t2PJ2Ezer+brNZ30JOPz4WYUKp+I4zx2BkAAGY8XRRf7ETx85gKXZAPqDyaHS+zxCMfk9P771T/Cz6e0znW1c/854e2CmMkbCor8v6c5vRSGGOjv/rXjiNhO1C4hM1WKitZIhWa+8KG/RRrq49p5Up9x62u1Wo3tFrtm4i4gjcsYfN3pVaaK2pDq53xs80509143XuqZsUHNW+zvXiql+VjAADAJFiCpQvtn61KKNmAnthFW2PmpmOd66e8PxeTncbFvMh+HvU07pDdMenjiV5/nZ9jXkZLGH0CpeNTKTHRa/tbva8lmTExstW9lnfDqm9RTL5SAni0ZMzbKmuz48acVB+0JCe1fdKa+mK78Zq4r2zYvjfjv5O8KMm7zY+37yz/burxRodcaCaRP1u7LBnNE0qbUzpHUXLjBQAAmAZ2gbdHOdhF2xITu9NS9QnF7/FjjS7aX1ey1ZnRkjafCLSDJRjxZ8TTVmuel1lc9dMqq2K79OdFm6dbxRo1aavHFUSNWZ+SI7UH0ueKq06NO2vVvia9r8bep/bVcbyNHfq+iubK1RD1n7S6XStsRufcl84V4gpePm/VS1QWWdu+kxBvMEh0/GVqF82bGFhhAwCcW3Qhv18XwZUqd/k+xZZbn43xff9FKZmaLvExG6/bhnnfNxm250/n21Dyk2Jutj7ny7ZamAfjXDbksZhoDt2EkMV2qXyVx6dK57uzPsrP0emz+f11obm3bpjQ3MPWeGQJAADnjNDcLzZio3do/hP4oX1kAAAA6BBb+Qju50LFlip2yn6CyuMAAACYZnYXn22IL0nYRiRxAAAA6AAlZQOxHkx3IdbjP4EP43wOGgAAAM6iEP8BuCVndnfmggULrrJiG9vZvwYAADADpDv3VG+y51qpvGnH9igI9q8BAAB0WJE90DWE8IDdZJD61N4xNBAAAADTTwnZUbupwEr8dz+LVJYsXrz4/BS34l8HAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADPYv3O4za2iV08FAAAAAElFTkSuQmCC>

[image17]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGIAAAAZCAYAAADKQPsMAAAFDElEQVR4Xu2YXYhVVRTHz2UmKPr+mIb53Hc+aCgJs6F6sYJISPp40CBjfM+HIaLAMAiKXorIworAMOhBdAqsMCEsJJpIywcJSn0RxrAkg4TB8cFS+/1n733vmj1n7tx7kzs+nD8szlprr7PPXnutvfbeJ8sKFChQoECBAgUihoaGbi2XyzekeovR0dErOjs7r071lyM01o6OjmtSvQX+XilK9XWhu7u7L9UthOHh4evyJq63t/eqyPf09NzMYH6CLWnw8J8Eua36RlaSDtq7mHOtgBLGOdeVN4n4NkzbH9C4fON5oL+//wvoDmPWhrwK+gC+3egXx8DAQCedvgmdS9sWAh96EfuLDPhjnlt5TvD8va+vbyjaoFuH7oJ5ZyXytzx/i4T8l5yDXxbtlgKMtayxQYehSY0b2sHk32RsXkE3zXwtlww/Bu1m7DuNP39DR1UFqr0vAhnz0nnobHheTG0WQgxEQj9YG+Qt0EyUyaJe5F3WRiuFvtZbXasR5uEXJvq5zK/WEvJr8imuVK0Q5D3QcahL75F098B/lJnMDytlX5TrRZuWoj7kfDY0GoiDzq+GVwcHB29DXbI2YbVUAiEH9B1jIpsNCobVtRqMabV8DxO/Tjr8ezzoLsA/bOaoEgj0o9DnpqSWkN+hj02VzhtBs4HQRKd6C9ofkSNRJoOeQH5XPIG73vkMW1t9Y8lQUiKFkjObTGbFH1Hplg5+HDqrlWBsxsVjA+u+53lvpddG8X8CwTsvQ1v1TDf7sKT3atLjQKEVmd+gN/U3s6G1ALFUOV+uK4kSSusR+asJ5zkpndrgt0EvVHtpAs0GAvszyvowydrs/8mS8qTNzvkN7E9otXRk1P3w+1RPrW0DmM1gxvAk334gbbRopOzpxKcxOl9+NOEPZfPLrTb13dBR2LuMfqKRb+WimUBguwb6JsoaBPJnKj/WLg/YTTLw+4y8H5rWGGKG1QIB2On8qUZHyXP09VSWTFiEC/W8HphAfKi++c7reUf0FNgtU4CiDPtg8Ge7qoExrY1mApEHrRLoK3uXyEE7NhuzMHE6m0eZ76+FvpxrPg+y2657TJDbkE9Bm/O+qxWb6uoBY1qv+YAO1kqOMHeVMYfVfhpWG/dG+Pezestvo4HA4Tux/dWZFSH0+5PGDM9Rq49Q1tD2Y5Thb5Sj9iKHyTORz4ML5S2FMldOQ2dUsqBn4adCkGsCuy7sHtMz6uycyFdrH6FVTdv+GCj6GEQ+WTaHGOeP8Guqb9VAo4FQ5ocBnrd65OehY/GUYRFu1hPQhqiT49BxGwgFM/J5oH1VqjMoac+gz3+hKb71dDb3Fp8LbA8Ef36O+9bIyMi1zl/spJ8XiPDX4Ds7HiUgtjM2EJorUZRrolYglGl09DZtX5sTguroqTTbnI/+e1lOvVYAaNtmNzQFDN0xGwhXb/ZcQmii44Rz8rtFunBCOhH0O9J3+qv3hYqv+LMc2+lkRbwEjUW5Jgb8qeeQPpru/M5cdqC3pIt3gLLfJGcx4I9zp9VX9W0P9CucP2PPaSuH22p0PthusTatgPO3aJ3q7o66kDjy+SR0u7UXNO50I5Yfzgd1j+Tg36cEbaW1u+QIJ6Wxsv+npMHmlgHaNmc5qyRAm++Jsv9XNQU9mhq0Cio3Ko3yJ+9PQUC78xtwLkIJfgObXdDhsjniLjnSVZYilMYuW6IuZ2j/SHUp5I9WRKovUKBAgQIF6sV/96p81Vfp6DUAAAAASUVORK5CYII=>