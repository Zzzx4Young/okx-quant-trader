# **OKX 高杠杆短线合约交易：回测系统与架构设计方案白皮书 (v2.0 终稿)**

本规范定义了 OpenClaw 量化回测系统（v2.0）的设计标准。针对 3-10 倍杠杆的 BTC/ETH 永续合约交易，本系统确立了“高精度、零未来函数、多周期共振、成本完全摩擦”的设计哲学，并规划了 Phase 1-4 的实施路线图。

## **一、 核心架构决策与 Q\&A 深挖**

### **❓ 问题 1：缓存格式——Parquet vs SQLite/CSV？**

#### **1\. 为什么 Phase 1 坚定选择 Parquet？**

对于 Python \+ Pandas 生态的量化系统，**Parquet 是绝对的最优解**。

* **读写速度与体积**：Parquet 是列式存储格式，自带高度压缩（GZIP/Snappy）。对于 5m 周期（单标的单年约 105K 条记录），CSV 体积约为 8MB，而 Parquet 仅需约 800KB。Pandas 读取 Parquet 的速度比 CSV 快 10-20 倍，比 SQLite 通过 SQL 引擎转化快 5 倍以上。  
* **多周期对齐（Multi-timeframe Alignment）**：  
  在多周期对齐时，SQL 的 JOIN 必须基于精确的等值条件，一旦遇到“因交易所维护产生的 K 线缺失”或“时间戳微秒级偏移”，SQL JOIN 会直接导致数据错位或产生空值。  
  而 Pandas 提供的 pd.merge\_asof 是量化界处理非等频时间序列的“杀手级武器”。它支持**方向性模糊对齐（Backward Join）**，能自动将高频数据（如 15m）与低频信号（如 1d）安全对齐，且天生具备防未来函数（Look-ahead Bias）的机制。

#### **2\. 数据表设计：按“标的 × timeframe”分文件存储**

避免使用“统一表 \+ 索引列”的大单一表设计。在 Phase 1 中，数据存储目录结构设计如下：

data/  
├── market/  
│   ├── BTC-USDT-SWAP/  
│   │   ├── 1h.parquet  
│   │   └── 5m.parquet  
│   └── ETH-USDT-SWAP/  
│       ├── 1h.parquet  
│       └── 5m.parquet  
└── funding/  
    └── BTC-USDT-SWAP\_funding.parquet

这种“物理隔离”的设计使得单个标的的数据加载完全解耦，读取时无需在内存中进行多余的 groupby 或条件过滤，极大地提升了回测引擎启动速度。

### **❓ 问题 2：资金费率动态调整的检测机制**

OKX 在市场极端波动时，资金费率结算周期会缩短（如 8h ![][image1] 4h ![][image1] 2h ![][image1] 1h）。如果回测系统硬编码为 8h 结算，将产生极其致命的“摩擦成本低估”。

#### **1\. 检测机制：方案 C（基于实际费率时间戳重构）**

* **方案 A 与 B 的缺陷**：实时查询 nextFundingTime（方案 B）无法用于历史回测。而每次回测都拉取一次 API（方案 A）会严重拖慢回测效率并触发限频。  
* **方案 C 的工程实现**：  
  系统在本地缓存一份 funding-rate-history 的 Parquet 文件。回测启动时，一次性将该标的的所有历史结算时间戳加载为**有序时间轴列表（Timeline）**。

#### **2\. 边缘情况：K 线内发生多次结算的“精确结算”设计**

如果策略运行在 4h K 线上，但市场波动导致资金费率缩短至 1h 结算。这意味着在一根 4h K 线内部，发生了 4 次资金费结算。

* **错误做法（按 K 线频率检测）**：在 K 线收盘时只检查一次，会导致漏掉中间 3 次的费用扣除，属于自欺欺人。  
* **正确做法（半开区间事件检查）**：  
  回测引擎在从第 ![][image2] 根 K 线（收盘时间 ![][image3]）推进到第 ![][image4] 根 K 线（收盘时间 ![][image5]）时，必须查询并计算落入**半开区间 ![][image6]** 内的所有资金费率事件。

![][image7]\# 核心代码示例：区间资金费率扣除  
def calculate\_bar\_funding\_fee(position, t\_prev, t\_curr, funding\_df):  
    """  
    计算在 (t\_prev, t\_curr\] 半开区间内发生的所有资金费  
    """  
    if position.nominal\_value \== 0:  
        return 0.0  
      
    \# 筛选落入该 K 线区间内的所有结算事件  
    settlements \= funding\_df\[(funding\_df\['fundingTime'\] \> t\_prev) & (funding\_df\['fundingTime'\] \<= t\_curr)\]  
      
    total\_fee \= 0.0  
    for \_, event in settlements.iterrows():  
        \# 多头：rate \> 0 支付，rate \< 0 收取  
        \# 空头：rate \> 0 收取，rate \< 0 支付  
        \# 这里 nominal\_value 自带方向（多头为正，空头为负）  
        rate \= event\['fundingRate'\]  
        fee \= position.nominal\_value \* rate  
        total\_fee \+= fee  
          
    return total\_fee

#### **3\. 缓存策略设计**

* **文件名**：cache/funding/{symbol}\_funding.parquet。  
* **同步机制**：回测启动时，读取缓存文件中最大的 fundingTime。若该时间距离当前时间超过 8 小时，则调用 OKX 接口，传入 after 参数分页补全最新数据，追加写入 Parquet。

### **❓ 问题 3：Look-ahead Bias 在多 timeframe 策略下的隔离**

#### **1\. 黄金法则：数据可见性判定**

在多 timeframe 策略下，要绝对保证在 ![][image4] 时刻做决策时，只能看到该时刻之前**已经完全收盘/结算**的数据。

我们来拆解你提到的具体场景：

* **时间线**：  
  * ![][image8]：上一根 15m K 线收盘  
  * ![][image9]：Funding 资金费率结算时刻  
  * ![][image10]：当前 15m K 线收盘（策略 D 触发信号）

#### **2\. 三个时间点的数据可见性矩阵：**

| 数据维度 | 11:45 决策点可见性 | 12:00 决策点可见性 | 12:15 决策点（当前）可见性 |
| :---- | :---- | :---- | :---- |
| **15m K线数据** | 可见 ![][image11] 及更早 Bar 的 Close | 可见 ![][image12] 及更早 Bar 的 Close | 可见 ![][image13] 及更早 Bar 的 Close |
| **Funding Rate** | 只能看到上一期（如 ![][image14]）的结算率 | 此时刻**刚刚结算**，回测中可见 ![][image15] 的 Rate | 可见 ![][image15] 结算的 Rate 及更早记录 |

#### **3\. 避免尴尬窗口的工程隔离：基于 merge\_asof**

在 ![][image16] 触发决策时，如何保证调用的日线、资金费等不同维度数据绝对不包含未来信息？

我们通过 Pandas 的 direction='backward' 进行模糊时间戳对齐：

import pandas as pd

\# 假设 df\_15m 是主时间轴，df\_funding 是历史资金费率数据  
df\_15m \= df\_15m.sort\_values('timestamp')  
df\_funding \= df\_funding.sort\_values('fundingTime')

\# 使用 pd.merge\_asof 对齐  
\# 这会保证对于 12:15 的 K 线，只能匹配到 fundingTime \<= 12:15 且最接近的那条资金费记录（即 12:00 结算的数据）  
aligned\_data \= pd.merge\_asof(  
    df\_15m,   
    df\_funding,   
    left\_on='timestamp',   
    right\_on='fundingTime',   
    direction='backward'  
)

**防未来函数核心约束**：

1. 若 K 线的 timestamp 代表**开始时间**（如 12:00 表示 12:00-12:15 的 Bar），对齐时必须使用 left\_on \= timestamp \+ 15m（即收盘时间）进行 merge\_asof。  
2. 若 K 线的 timestamp 代表**收盘时间**，则可直接对齐。

### **⚠️ OKX Header 名称冲突解决方案**

通过实测验证，OKX 的 API 路由网关在实盘和模拟盘切换时存在以下技术细节：

* x-simulated-trading: 1：是最新 OKX V5 API 标准文档推荐的模拟交易 Header，主要用于私有接口（交易、持仓、下单）。  
* x-simulated-id: 1：在某些老版本网关或公共历史数据接口中被识别。

#### **💡 防御性双 Header 方案**

为确保 100% 兼容性、防止因平台网关更新导致的回测中断，我们在 okx\_client.py 中采用**并发双 Header** 设计：

\# common/okx\_client.py 统一请求头封装  
def get\_okx\_headers(is\_sandbox=True):  
    headers \= {}  
    if is\_sandbox:  
        \# 防御性设计：同时发送两个 Header，确保新老网关均能 100% 路由到模拟盘  
        headers\["x-simulated-id"\] \= "1"  
        headers\["x-simulated-trading"\] \= "1"  
    return headers

## **二、 4 策略架构 (ABCD) 与 Constitution 决策分流**

回测引擎必须能够完美支持多策略共存、且受限于统一的账户管理宪法。

                  ┌───────────────────────┐  
                  │   Market Data / KLine │  
                  └───────────┬───────────┘  
                              │  
         ┌────────────┬───────┴────┬────────────┐  
         ▼            ▼            ▼            ▼  
     ┌───────┐    ┌───────┐    ┌───────┐    ┌───────┐  
     │ 策略 A │    │ 策略 B │    │ 策略 C │    │ 策略 D │ (多周期)  
     │ (趋势) │    │ (震荡) │    │(资金费)│    │(多因子)│  
     └───┬───┘    └───┬───┘    └───┬───┘    └───┬───┘  
         │            │            │            │  
         └────────────┼────────────┴────────────┘  
                      ▼  
        ┌──────────────────────────┐  
        │  Constitution 决策宪法   │ \<--- 过滤冲突信号、分配杠杆  
        └─────────────┬────────────┘  
                      ▼  
        ┌──────────────────────────┐  
        │  Portfolio / Account     │ \<--- 模拟交易执行、扣除手续费及资金费  
        └──────────────────────────┘

1. **策略 A（趋势突破策略）**：依靠 EMA20+Volume 追随突破。  
2. **策略 B（震荡均值回归）**：利用布林带 \+ RSI 在无趋势市场下进行高卖低买。  
3. **策略 C（情绪/资金费率套利）**：检测极端资金费率下的反向博弈。  
4. **策略 D（动态多因子策略）**：跨 timeframe 综合决策。  
5. **Constitution（系统决策宪法）**：  
   * 负责解决多策略之间的**信号冲突**（如 A 发出 Buy 信号，B 发出 Sell 信号）。  
   * 负责进行**总仓位重整（Reconciliation）**：根据账户当前的总保证金状态，硬性拦截和重算任何越界的杠杆下单指令。

## **三、 评估指标与回测报告标准**

高杠杆交易的净值曲线通常波动剧烈，报告必须包含针对**极值风险**的量化评估：

### **1\. 核心评估指标数学模型**

* **夏普比率 (Sharpe Ratio)**：评估每承受一单位总风险所能获得的超额回报。  
* ![][image17]**最大回撤 (Max Drawdown)**：衡量系统可能面临的最极端亏损。  
* ![][image18]**卡玛比率 (Calmar Ratio)**：评估收益与最大风险的比率，对于杠杆系统，Calmar ![][image19] 为极佳。

### **![][image20]2\. 报告输出：月度收益率热力图（Markdown 示例）**

回测引擎运行结束时，必须在终端或 Markdown 报告中绘制以下资产表现热力图：

| 年份 | 1月 | 2月 | 3月 | 4月 | 5月 | 6月 | 7月 | 8月 | 9月 | 10月 | 11月 | 12月 | 全年 |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| **2025** | \+12.3% | \-4.5% | \+22.1% | \+8.0% | \-10.2% | \+15.4% | \+3.2% | \-1.5% | \+9.8% | \+14.2% | \-2.1% | \+18.5% | \+112.5% |
| **2026** | \+8.5% | \+11.2% | \-6.3% | \+19.4% | \+5.1% | \-3.2% | \- | \- | \- | \- | \- | \- | \+37.6% |

## **四、 4 阶段实施路线图 (Phase 1-4)**

┌────────────────────────┐      ┌────────────────────────┐  
│ Phase 1: 骨架构建      │ ───\> │ Phase 2: 精细摩擦与缓存│  
│ \* Parquet 数据引擎      │      │ \* 动态资金费率扣除机制 │  
│ \* T+1 严格单线程撮合    │      │ \* 双 Header 模拟盘验证  │  
└────────────────────────┘      └────────────────────────┘  
                                            │  
                                            ▼  
┌────────────────────────┐      ┌────────────────────────┐  
│ Phase 4: 多因子与报告   │ \<─── │ Phase 3: 策略与宪法集成 │  
│ \* 收益率热力图与指标输出│      │ \* ABCD 4策略共振上线    │  
│ \* 极限爆仓压力测试      │      │ \* Portfolio 动态重整    │  
└────────────────────────┘      └────────────────────────┘

### **Phase 1: 骨架构建 (Infrastructure)**

* **目标**：跑通 1h 时间框架下的单线程回测闭环。  
* **交付件**：  
  * 基于 pandas \+ PyArrow 的 Parquet 数据读取器。  
  * 严格遵循 df.iloc\[:i\] 的双指针时间隔离撮合引擎（决策点 1：A方案）。

### **Phase 2: 精细摩擦与缓存 (Friction & Cache)**

* **目标**：实现无损的成本计算与模拟盘环境对接。  
* **交付件**：  
  * 动态结算区间的资金费率扣除器。  
  * 带自动增量更新的本地 funding 缓存机制。  
  * 双 Header (x-simulated-id & x-simulated-trading) 的 OKX 客户端。

### **Phase 3: 策略与宪法集成 (Strategy & Constitution)**

* **目标**：支持多策略冲突分流与真实的账户账目对齐（Reconciliation）。  
* **交付件**：  
  * 4 大策略类抽象接口（A, B, C, D）。  
  * 决策宪法模块：强制拦截任何可能导致账户爆仓或超额杠杆的冲突下单指令。

### **Phase 4: 多因子与报告 (Analytics)**

* **目标**：输出可用于专业评估的回测分析报告。  
* **交付件**：  
  * 夏普率、最大回撤、卡玛比率计算器。  
  * 自动生成月度收益率 Markdown 热力图。

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABUAAAAZCAYAAADe1WXtAAAAkElEQVR4XmNgGAWjYBQMIFBSUuKXl5ffDMSa6HIUATk5uXIQRhenCCgrK4sBXbofXZxioKioaCYjI6OCLg4HoqKiPECbJUnFwCB4BKSTgIZzoptJFhAXF+cGGthHNQOBgAVo4FQgzYguQTYAetsVaOhqdHFKAIuCgsJCIPZAlyAbGBsbswLDUYiBml4fBQMDAJqEFeONn+nOAAAAAElFTkSuQmCC>

[image2]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADIAAAAaCAYAAAD1wA/qAAABTklEQVR4Xu2UP0vEQBDF7xBBwcbDIIb8uZSCXb6CrY3tNVZqbWMjCH4ESxuxuO5ae3sLG1Pa2F+ppfENDMf4MLIJJIuwP5ji3s7LzguTG40CgUDg31GW5Xqe53eOdZUkyYSf0Tcy4xSw/oMsyy55OAxco55xtm20GWt9gnsOcd8X6lPneeKeFQiwiYYFyWM13loRDz6C9ogXs2H1vpB7pPTev4OkaXqAhrnV5I2rcWZ1/D7mcEPgFASJT1DnVoOxhGmJ2rc6fl+g98xqQ+AU5BfGMN77ePNNdAoSx/EODFVOa+WTTkF0rT54rVyIomgLvj2XKopil/1NdAoi34CYuvzFwncD37tLobdifxOtg5i1qvnMJ62DmLVa8plPWgWR/YbhWg2vfO6RNcx1qnO98OEK+ejQ8KaNXJWsG3uGQjeEZ6rxHT9wbyAQCAS88A39rIMtmEfODgAAAABJRU5ErkJggg==>

[image3]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACUAAAAaCAYAAAAwspV7AAABfElEQVR4Xu2UPUvDUBSGKypUEEQ0iPlu/oBDdZGO7joICl38D4KiP0JQEBw66CC4F3F1VBw6OQoizg6iLlX0OTSF22PQBK1xyAMvvfd85L7tPU2pVFBQUPCZKIrGgiC4QDeVSmVK53PB9/0qhp7RaRiGZZ3PBczU0TvmNnUuNzDUQG1M1XTuz7EsaxQz0+gFNR3HcWWv63Lh310dDCRdHf/CgNgluksSPfuUDZo9aQg7rOp4DxwwzgG3rus6ZlyGn+Zd4iOe583FV1yXHPE11ntm/XfQs0VPC72yPtL5HuQg8+rYz7OP+Nw2YsfoSr6A7HnoCuuFbj4t8QyfpzHV6B7AoE+wbybUXEudjmclq6kqDPN5wH49oaYtv6iOZyW1KeZllsIz1MLURilheMk9MvgzOi7Ytj3JIUv0LmtJPDBeMalNCdIoDToeMxQY86Tpm6mv4OG137g64UemaCpj5tDvvI+e0IOsiS/q2rTQf8Jz7tFbrB1dU1DQDz4AVPtu+v9TYL8AAAAASUVORK5CYII=>

[image4]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAA8AAAAaCAYAAABozQZiAAAA0klEQVR4XmNgGAV0BsbGxqwKCgqF8vLys4jBMjIyQnDNcnJy5UDBfUjmMQD50UD8HygniC4OFwOawgkUWCMrK2uLpIYRqGA+SDOSGBgAxX2BruQAc4CadICKloIMQVIgCBQ7jU0zUCwIzgGakgDEGUjyIM3GQEVfgfgtsjgIAMWK0MWQAdzJQDwJXRIvkJKSEgFqugrVHI0ujxcgOxmINdHl8QKg/9Ohtp5Gjya8YOCcDNRcD7X1CtD5CujyGEBRUVEcqPguVBMGBnkFXc8oGHIAAKS5RTYSE2fOAAAAAElFTkSuQmCC>

[image5]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABMAAAAaCAYAAABVX2cEAAABNElEQVR4Xu2SPUsDQRCGL6hgYQgiRwj3fc0RLBMsJKW/IK1ga5+AaW1trSzyE+xELCxtBAtbm4CkFCy1MEV8Bu9kmVzENZb3wMvtvjM7x+ys41RU/Eyapo0oiu7RJEmSpo5bEYZhh0Jv6DqO400dt4Iih2hO0ZGOWUOhMZpRrKdjv8Z13S2KtNA7uvI8z5f9Sq3+W4tQK2uRqe7hP+FPl4n40Dwjk9zGfPZ93zN9Wj3FH7Bckz3rvvHDGvEzdPx9QJBJmi2y35engo4KL8uyOv4dy3Ujb4Daxb4wxxw8kDUD2JFBsN9VOW30anql5MU6sMH3YuEevnLkHc60v0AQBF0Sb9AjxU6c/I5MiJ2jifZLIbElb077Qj6gB3SpY9YULRqTtIcCt/lb+kBz9CJXovMq/s4nYYxLWccR/fcAAAAASUVORK5CYII=>

[image6]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAE8AAAAaCAYAAAD2dwHCAAADVElEQVR4Xu1YS2gTURSd0AqKit8Qms+8SVCCdCESdFV3gnbhBxUUitCdLl0puKoUt4KiIFJQF+668wtuCrqoVuhKXAVUKoWCLsQUodV4TmZeeV4m0/f6wcDkwCUv99yXd+bM3JeXeF4XXXTRRcpRq9U2yFyaoJTqY2Sz2S2SS0ShUCj6vv9S5tMEGHcf8R4+XJVcW1QqlW2Y9CoIgkuSSxtonLV5KOyHcV9h3DHJEciPgG8iBiXXaYgegklEXXK2cDIPC93hglxYcgS4CcQ3xD7JdRpw0TXobCCeSc4WruZ9RNyQeQ1wszTQeRP9D4DOIUTT+uJj4Greb5XQkhSTZG4nATrHEAu4+AHJ2cLVvM+IPjPHI0u5XM4Vi8U94OYwPsQa7H/bzbpOAbsC2o5C4zziCU8OeL9R1tnA2rxcLrcZi72uVqtbJUfgQyoqRS1LWJtHU5LMKZVKJ+JaFh/+FvGlXaCkR85ZDkGI8zJvC6z7IK5l0TUqSS/m3PUMvf5amUfjaKDM4yJvoaU3cQz+IO+6wQ0vFVqA7YX504hFjB9J3haYP4X4BF0FkR+iXo4jrWztll5qxfi2WW9tHtCLyXXub5Lww5ad1caq8KfLaYjba5RlkHuM2h06AUHnDN4K+iau0rx/WhbjWnQN16JUSytN1nqpFeMjeg7hYh4XneEGG5MfpKDobQYLXQ/EL5B8Pr8bNR/M3EpgYx74SfCXMeyVHAH+jzYC17ML436T11oRY2ZewtW8eT7OMfkl8/B6BvFUtjcWGUB+wcytBJbmNRENPlGSIzTHkwJe70lea1XGFhMHV/MaEH1R5qOfOi9oGuI52nWnrOE8cD9knuCdBn8KQs7KYF4ZxyNL834hFjH/uOQIcHOR3mnUXJG81ootar/kTLiaN4EY9+LboYctgNeMJLxwvxxHTEmCWGvzCNSMqjYH+iD84mn7d5LW6hv7cxyczKM5WPgdYkRySfAt28AGNuZhazmswv0q7iYvC1utTuYRkbC6LzbZOPAO++H56KcK96HvyJ2UdbaIDuozKvyZyOD4pqxD7g3igMwnIdL6MNLb0spxkl5n87zw23RYreLfiPWGOCKtC1R4HBt1NY/IYNIFmUwT+FRGT2bq/xTuohPxF4cfD9zJClb6AAAAAElFTkSuQmCC>

[image7]: <data:image/png;base64,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>

[image8]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAG0AAAAZCAYAAAA7S6CBAAAETUlEQVR4Xu2YTUhVQRTH70ODvqCo7JX63uizouyDwKhdiEkUYQsVahG0aBGBELQoImlRSAvBRbhJgkholRspq0ULoSgJoQ+02gQqkWCEFOkiSPv/3zu3htO911v5NGR+cLh3zjl35sycmXtnruc5HA6Hw+FwOBz/RHFxcUrrNOl0OlNaWrpE6/NBVVXVovLy8r22DuUkLgW2juVUKlWMa0LpsyDmRmNMR4BcSCaTyyi8V7b2TCazqQwEPBclB3X70B2CPIVMi0xC7iOuSvYR13P6mRnhQKCSVsg3bbNIIFkb4PMZjVRpYz7AeB3RHUL7vYwT0ieD9BDyFX434L/Y9vWBfQsTB7mI+ylcu1mGfzXMhRTew9bM/kE6IQ3o7yr41eL+O5+R9ihTJjf4/Szj2Zu4jonuqt02bOuolzYrvdzESkBXA9srXO/qPkZSUVGxlgGZXOZ5ndY+CHw79K8loC+QiblImkyQD7pDJpc0xmJLa5zVz7gl/tBBgr2+qKhouV+Gbx0Gd7PymWC7dj1sH7ouJtDXYTFAZQagO+/9/nZgQrmK30XFE0QBnlvJII0MhnaQV1RSfNZLp/OaNBmA20EDzDhlZmdnfUlJyWrbHoWfNEi9tvkwSXxd+mW0ddJTr12pg0mrU/p6SA/vpQ936McxtP1sUMcx3cdYRCXNxsxB0jBBdqONR0hGKZOjO8Q49WDFxVppoc9rm1GvO9ENByUN5QykG7eFsHfRBzJo+wRQqPsYi3wmDf6j8L8SNdts4N+DTcVh3ocljXbY9nBAOVPtlRHF3yQtiLCk+WCVlcA+JEnLrrwo9GYrFvlKGnajSyXwcX4btT0AfqDbeGUhLGmQ97BdQ/K24f4JfEZQ3mn7BTFXSfPboQ/7oO2zQr6SRuD/FtISZ6Vx9djfqJCkdUJ31pPEYjJsNLmd2xu+Um1fjcQ/HDbYJMrms+CTFheciVag7nu2LihpGjt2SJO228xh0jKwj0pMt7R9VpjvpEm9Q5Ax1D3ii8mdx3gG4z1fm/T9BGn2rB0dkysD1Gtv1zXSDpMWOhFgP6N1GtbB9sKSRmBvkpjGtU1jInazocx30kCBnBlZf1bknMa/CJdZLvt1NOFAvPRfo/I3gwds6q/rim24DUfsD+DXom0Cv6ntWqkxMZIm/Rmgnxfyp4bIj41yrZ+RfCYN/n0Y8FNeROBB+DHpVQFdP3T7/DI2O2ugG4RMoZ0Dtm8Q8KuH37Og8x3q3cr6tV4TJ2lEji/j2DDt1zYhkba+z3+EnNyfM5CIDUOCOzT4TKKhWi/ghK+RVTAN+cj/eNoehcxArrRLdkwoP+Yq9MvstLTRERH7T+hjcr+h2uy/KGhvB3QvIA22v0aez/6y4mSMeh0T+NWY3Gv+hIqvALGfNjGOBAsCblo4ezFox5lcbY8DBxB17EIdRyHVZSH/LWcL1s+Vh0Q1Mnb2Qfs4HA6Hw+Fw/Lf8AObslurQGkEnAAAAAElFTkSuQmCC>

[image9]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAG0AAAAZCAYAAAA7S6CBAAAEsUlEQVR4Xu1YTWhVRxR+IRH8g/qXxvy8O++9iKj1Z/FEaAtVREQRN0mhBV0ILkQQBKUtYilupIjgQgQh4KKCi4IuxIqiLtz5Q0ARJSIIulFoKMFACgaM/b53z+jJeTf3vpf3LEHmg8O9c843M2fOmbl3ZnK5gICAgICAgICAgIbQ1dWVtzqFVudcZ09PT3e5XJ5ljc0C2y6VShH6+qZQKCywdo/29vb5+Xx+NTizrc0iiqLv0d5Aghzt6OiYR+G7sZ2BH8vRfiGhXppst/1DtwNyB/Je5F/INfi1iuPF8xdbJxPFYrEDjZyEjFsbAb83wvYU8ko6HYf89AmS14J2/4HchpzDYJ4xaJogAT4NGYXpT/LxPIHJNEfzNMBZycRBfsP7BJ6XWUa9TTC3UfgO26+QN5DzkH60uQi8LXh/xzruY2ImXByHQZZR9w88/xbdad03bEuplz5XQdVCgW4zbI/w/KuupPX29n5Jh1yceT7fWw4SugGN3sNzrZTXgvdcHByw/EaA9voxkD25eGA5zPQvoBvq7u7uURwG7RV4K1imfyiPwMezuTgBUwKcMrhjaUGCvY+r2JfB3en7Upwxjl+3w0kD3UUm0OvgG1TuMXRHUGz1eg9OSMYyzZ8ktKLeAjrp4tldlTTorkIG0fC3Xoc621w8295pbiOQBN1FPwu1nv2gv2Oq/BZyXFGo48qj/mutt/BJg/RZmweTxNXsy+h7X04mkYe0waTtNPo+xovvksQr5KV9kdDG7nqTVkFG0i6Jgx9mMsqdkJdJ/OmCjie1J/2MYtauEz+rgsUy9ZBbOuAWaqVNqq9hbc587kRXGbvlolyCXMZrG+wXxacnmpOAtqYnDWiN4tn/YbaBt9LF/54k/iSA8xr1f0+bbQQ/K0ntSYAmovjfwsmSFCyftCfYTC3RNo3pJC0J4lOVHx7crMH+QnyqrLw0YEJ+Z3WZyEhaFTgzxKEha9NAAOcKbwQDWWPtGhlJqwTIZSeN3E5t0/i/kub7IUf/45qKepKG4C9z8S5yhJsAa7dw8a7zeIMrrSlJk/ovbX2NNJuH9snaiBmXNHBuQYZdxk+/XnxmSSvB/lp8umDtTUEtSeNKgX2AZxev47dbcxpBlL4R4SetXMNG5Lberlu4j0mb8scP+yGrsxCfqvzQgP2A+DRibRYuZTc7JbKSxoRx222Xetrg6wX63s7+C+aGA7pRpzYYwuE2XHMOSYCqdnoa3IbD5+vOHBkUWmA7Y5UWroakyRn4scR00pFBoxhfbBStPhMZSWuBcz8zYXK9xNnaKQfHm5ZsAc5d1N2fS3GcEOeHooRzmgSyUl/KSec0nue2aX0SwOsD7z4O7IutDX1/Bfug1Vu4GpJG+IN/Pp/fam2CSmz5tIZMSAIe0BG7YYDuMPVTyJjmWsiVE3nDvMezdgvwDiOgP/iyfJKHGUyvg/0GdM/xLEi5wDLkStpVloe0ycSf0vxifNPzENKv+RZSv3JlxcmY9jkmwNvs4mu/vSa2PEoddDUcCWY8eGkdxRe8u1LOLxwwd2i7ZDLUPVMZQKyA9Qj8j5BNhRounhsB2+fK49i48ngDZDkBAQEBAQEBATMW/wHWgMbpfXPWCQAAAABJRU5ErkJggg==>

[image10]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAG0AAAAZCAYAAAA7S6CBAAAEhklEQVR4Xu2YTYgVRxDHZ3kb0ETi52bdz/a93YgaI4EVgwhRVEQRc1g9KAgePARBEAwqQZFcJAfBQBDERZAInjQHUVHQgwdREwRNUMxFiCIKiiyBrAfB3fz/b2pI79/5eOuOkoT+QTEzVdXdNVU9PT0TRYFAIBAIBAKBwLhob2/vUp1HxTnX1tnZ2dHX1/eeGsumt7f3w7R4qtVqKw4VUVe6urracWwSfZ3u7u4NiH0gRfa2trZ+QOG52A7XarXZs0BKuzxZo+NDtxZyHTJi8gJyAXHNYy5x3KNtCmEi0MlByEu1EcS9FLbfIY9t0JeQXW+jeBhrAmQT+n+A449qh/6KjX/DxUm6DPkLN36cbdWfwD6XhYPsx/kwjmd4Df9lMDdTeA7bPsifkBOQ9Zig0+C3Euev2MbGowy7OA83ec04cXxquh/8sWGbSb2NOS+KJ1YTdMth+w3Hc2MqWk9Pz0cMyMWV53FEfVDQRej0ZxwX2PUC+N23AAfUfzygv0NePCM5RePYvhxEgieqr4L76IPvUF6SYO9vaWmZlFzDdx3imCM+QxzX74fjQ3fajxm5gsrdge6b6PXVgQXlU3w/L540Kmg3hUE6S4Y6QHcechMdL0l0aLPaxbPtle87XhgLDhXeBGPJKhr1zmZ9R0fHdPXJIikapF9tCSwSl8vkGmN9Fcmya32waOtE38988dyKeJZ+eSsS+tg81qLVKSjaTxbgkSheSqhrgzxI8y+DoqJpshrFe9Iy26vNyXJnuvq9qy+ua5AzOG2G/TR9IHd9nxSaSy9aFM/8qZE32+A3F/I8w38U8HmC9t/lzTalqGjYdHwJ2+dMKGeq/2Tk8SZFSyOraAncrMH+hxWt/uTlgWX0C9UVUlC010iSCrmnNh/s/t43v0HcyKdqz6KoaJBHsB1F8ebj/Br8H+L6M/VV3lXRknGy7qEUxlI0JL/XxbvIQW5S1K64eNd5oMQn7QTsuyN78hHPxy7eud3D+61T3EfhbFnPSjbJsyX854rm4i32M8hitZVFXtEUP3bIdrX7vMOi1WB/YjGdVHspNFI0PimwD/DbJdFx7fZ9yiKvaC5+l+6LvHes7SaZoCv+dl1x/xQt88UP+07VKeyD42UVjcC+3WIaVJvicnazmRQVjQVDYr7VJObd/HjIKprFyUT8mmz17W8Gn37qj/n+Crfh6Psi/A6ozeBH72FVKq6Botk38B3L6ahPBh/7sVFVfSEFRWtCcLuZwFqt1u3i2dpmH46X1FmBzw203RblBK5kFY24+JtxRXKNzc4M6O5ChuG/2vdNA3798Psl7fsO/X7C/lWvuAaKRvjOh98gNkyr1GbUc8ujGgqxAtxiILphgO5r6jNkyPdV7Cmg3zP+x1N7GkjoBNzI99bulNqhu8rNUHLNmzbfAY09DVvm+WPgkP8XpRr/6bkNWe/7K9a+/suKkzFvOSbwW+7i325bJT5+Su1wDXwS/C/ABJjM2YukbeHyovZGYALRx0L0sRGyjJNFfcqE/fPJQ6E2MHbeg/oEAoFAIBAI/Gv5G/zWrncfmD6iAAAAAElFTkSuQmCC>

[image11]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIcAAAAWCAYAAADq3Y/sAAADVklEQVR4Xu1aP2gTURhPCIKiqCgxTS7JyyVRKC5CRBFEBHES0cFB6eDg4pBJB1cXBwepOpZC6dDFQtGhKDhYRRAsKBRBkDpUXBw0dFAQkfr7cu/px8fdpU3uLol9P/h4ed/3vX+/+927d9emUhYWFhYWFtHDdd2cUipPZaPR2CLjFpsY5XL5A2yqUqncg1Vk3GITA8J4mM1md0i/AeJVFGnp56jX6zsLhUJJ+iNE2nGcvWaHk0EO6Ht3sVjc3+9dEHPYNiDcdY8gcRC5iJ3CBVnwixvgYlxCzgrKaRmLCuh7CWMswiZg71C/TeSLnBHE5mBfMO9HKL/CmghleF4SIO4w9tsw7jDfrUlw1xOkOOi3OX8gdjZogXSH1mq1fci5gZy1uBaIvq/BfsKOMd+avvijVMfYF7VvzOQQ+ajPwz4bX9zg3On5BHKHIhM3dz1DioMjTBwGcS8QfV9RHcShRfALczn+r2Xbf59yuS8p6Dn2lbueMejiADJ4hNRZPU3jYdwn5tGC+grsO3wNlvd3btyXFKw4Ut0tkMZE/hLskIx1AtoexHgtbN9HjI+EESYOesRwfxKIQxylUukw8pdhM9VqdZeMR45+iINy0WZxveLADrEHuefQZkx5h84mfxvpJI6w+ceFOMRBfGnepv9bcfSI9mMFNmsI6kEcGTpUIye/HtvIDqTnOGjcbQxDKA4i/oce86qudyUOx3GKyHkO+9TJ0M9H2BnZRxCsOFLxL5AOo/ShiPuUdwAl8ufpbtb1QHFwX1Kw4kh1t0C0GUebp3TnyhgHckaV98raFgHzm53jpq439cXw+87RMr4koecTKXd4jB5A/jPYrUS+AAeJgwanbRsTeRV2EfWFJiJm/frxg84nuyNjHHoOD8TnZXPmeEPnBXLQ/FB/j9wX5hyC30eVt5vcZW0TAfsIFsgdiZdzJ+N+QN6kzv+N9idlPHJIcejdgibgZwssr616PzM5QUDOS9gq+jgtYxL0poLcb7AZ2HXl3TlzIGeE51W8k/wyytfK+6raQv9TuVxuO8+LE2HcCY59ueu0gxBfyFtVHn95GY8cUhyDCNo5QNx52GUqZdyA7ljXdU9gTRcG9o9Zw4RhEIdFn2DFYREIPLse0+ui/U8wC4M/OLOA/ZxZokgAAAAASUVORK5CYII=>

[image12]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIcAAAAWCAYAAADq3Y/sAAADtklEQVR4Xu1ZPWsUURTdkAiKn4hxMdnd2WwWF8FPViy0UTQ2wUJCEIk/QFAsFLQQbMRSxEYkCJLCykILUTCCEQUFC0XUQrQw+IGKhIgpTNB4Tua+8Lh5M5PAZmaTzIHLTO69896dM2fe3H3JZFKkSJEiRYrao62tLet53joeq9XqIh1PsYBRKBTewa4Xi8XLsKKOp1jAgDBuNzc3L9N+A8RLODRov41yubyipaUlr/2zBax0Z1XNTZh/TUbVyZWQq6Ltiwu5XG5JGHesP5/Pb6ThnVyl43WBIHGQWMT2gtwBV9wAN3YYOR9x7NOx2UCpVFrJ+eyHznPx/YY9gPXCnsH+4B7O2dfHARHliyDustnsUsSGUNug1DyO+1qv8xKHFgfPTf+B2IGgG6Ta29vb1yLnDG8uDnFgrg7M9V2EoMXxVkTRi7xuPgD72jhgc0dOXNyhtn3wj9j1cZWR/FvgcbGdnyi0OGyEicMgLnG0trbmMM9j2DHPLY6XqKVqX5MkgsQB30nGyK3yM/+rfIrqA3NBHLKKXcU8pyiAuSwOWTlGYdtsv+T/wsqzxfYniiTEwTmR/wq2VcdcwPhdsDusI0wcIHYHjp2wK6w9yZ/m8rCd3Ll8kv9GGmsn0LxuR8572A32XjpecyQhDubimufTEYesGkfM3y5xVCqV5fi7H9ZlfDjfAxvDHPeNL07Iww7lTtCAvPOw3igxky/hrW/eimMmwLiHbNJc4nCBccn7p2MWGtlUS26kFWfQLJITL4I7wvNXxTE2pTqWOOpZHCCszPlt33TFIasJG9hxHTNgk4vxHsEGowzjfIB16jGCMB1xIL4T9gPjn9axukA9i0PGHlUPiT9lSfwX9i0Q0CbPX5Z/wnrMtayZtTPXHjMuSI2B3El/9An31J3xN8qacL4L97Na5yaGJMSBay7hmn6+uToWBalJN6Tc+LoLwjdbvg0imCHjixNh4kCdCE00zpOfLIqE/ZEr34AbZch9CLsQ1Z/UBEHi4OQo9igKeRr2EOVBk4ibrnFckHzaRR2LQCOu6YF9BsEV4/T87/Y989bJJhQ3xLifEPuSbW2CTeFOhPHa4mDSol4w5FyT3L/I3a3jNYcWh7yZUwoXG7DyJlYMl5mcICDnCWwYY3ToWBBInJ4HNlLw9zbY8R+HfZM8ks/P0QnEGvVYs4Uw7gzHYbwxpse0Qb6QN+z5/IX2XDWBFsdcBreuQdrBfD6/P5afevMd80kcKWqMVBwpAuH5jVzZ/DdRx1MsPPwHA8OCq4DblacAAAAASUVORK5CYII=>

[image13]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIcAAAAWCAYAAADq3Y/sAAADwUlEQVR4Xu2Zy2sTURTGU1pBUVDEGpsmuUmqrgQfEQUVEdRVcaWC0H/ARVddKLgV6UrUrqQUShdufSyKogvrA4S6EEQRpC5aCiIipWI3isTvNOe2h9OZiZ25mbb0/uCQ9Jwvd+58c+bmZprJeDwej8fjnnK5nDXGdNBrtVrdoOuedUyxWPyMGC6VSncQJV33rGPQGA/b29u36LwF9QpeWnTeUigU9lGgr7bpmktofKxwh/L5/B5dk5CONCu9CmIOm6K8I8/T8i42Yc1B5qJ2GhdkLKiezWY3ozYAzRRefyFqOMnxSqWyV2uTgrHvI75h/BEc7xHe9yLdKjWo7bI61vwI0qUBeYdjv2vg3Yz0rhm+JUY3B723+w/UzgWdIPJnkJ/Da7/N8Z3yhJtko9QnAWNdwpg9Moe/RxHTiLLQ1KSO5mB1i59sLtI7nk+od9QgNkfesf6BS+8So5tDEtYcyPXxydRU/hrleDlNjL3AGO+EzCM3wMefbwbSIP6E6WQuLXh+od6RtypP+q+uvHNCnObg7v+NmFH5q3SSuHv2y3xcMFYHYhLjVmXeHgcxxLpJU1/JAnUylxY8vyjvDso863+68s4JcZqDoJxeAg3fqblcbofMa+iY+Ox7xAFdk9DFjrroiFFeXeaidHqeacDzC/VO51j/Mco7bF4PQzOBuIc9ylZdd07c5lC0QHedT3BQFzW4WCPQvXXQHPNzI02U7j/m7xw5P11TWO8GG/3CIr/Yt5E10xzQnDf17/y7tLnS9bik0BytXV1dO03966thLGcFkvPTNYlh71z65oykzYH6McR3aK9kHP9sbHZzdHZ25qF5gZhqFBjnC6JbjxGGnJ+uWZR3q49i8uaYhu5iZvFhTxvugu1SExfTYENKyyvr1syG1IKN5xHlXRveH3flnRPiNgdODiXzii/gQtDJBukl0NyC9hndubqmga7XBD/nmKGni0JTkzr7M5h0i59MD55PlHfdRvmGOT8N0lvoQRm0zxE3Gu1PnBDWHHRwTPYyJvJGX0Q+uQ9swJKQ2iCE9qauaejYmMdLuQEz9VXidoZXK9Ig90nq8P6o0KWKeAi2LO/sShgGNEOs/QvtKV13jm4OXi2WTJxjjDX2Oz8wFgYPAZrXiFmMc1bXgoB2AmaM47UH0YfPDcsnjATv5K2OHjTR4+klumYS5Z31OMo7qukxJeQXdLOm7l+HrjtHN8dqhO5E3HEnYUgP5ntB1y1WR5pcLlfQdc8yWQvN4VkhfHN4QsFS/Rg/n3bb/ybqumf98Q+qsq1CuymhdwAAAABJRU5ErkJggg==>

[image14]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADMAAAAWCAYAAABtwKSvAAABpElEQVR4Xu2VMUvDUBSFG0RQEFSkgqRN2mYSB4eAg6CTgg4Ouij0B/gPWlwEB0f9B1IUXJwcinUScRLchOKq7g6KXVz0u/KUy6NqhtZmeAcOyTv3lJyTl6SZjIODg4OgUCiMhGE4WyqVAnvWDnjLcNnWew6KnBDsHh7AepKQeFpBEFRtvaegyBLc1BpBmwQ9z+Vyg1o38PBv4XlPWxmPQDW4oEWCXsInOKl1QbFYnEE/S10ZwowS6oZjrHXu/KEJu6J13qdhtNN8Pj+XujIEmoAPv5TRYWUXK8x25LzNvC2y2ewQ3iN+d2vPOgopYV7kP8uwrrNeVOvEZfDV5AmwZx0Fz/80F3lJWGafg6fWicr8G5I+Zhynoiga157UlQl++ACgHUtYuGZ8Vfioaeav5lx2rfdgFzYIU9Ya6ya8lq+X1jWS7kwcx/34tvE37FnH4fv+GIWudHAu/Ia2rn0azAbMzuxJWHuuIbuOryV+e9YVcKE7eCE7BHcJUEHus33mMyt/qFLkm/KO2d4vyE3C04DP9qwrkLvLl23elFm15w4ODp/4ADpSgTcUPURmAAAAAElFTkSuQmCC>

[image15]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADMAAAAWCAYAAABtwKSvAAABhUlEQVR4Xu2VsUvDQBTGG6iDqIhCCNUklwQ16BpwUXDp4KCL/4R/gLt/gZM4uYjOLk4VdHB3cxSHCi4KCg6dhNbvkYs8HyWpYLgO94OPcu/7Lr2XSy6NhsVisTAc3/eXZLEgy7IJ+MthGG5i6Eh/XHCwwDXoSinVlSYBbwfeK/QCfUBPURRtyZxR6G67rjuNxWZYYA96lhnsxiTqnSRJVooaxifQAPOuyed545Q1g1qLFo6dOGe1PapB79AqzxunrBm9M7Twg6KG/K6u9WguzxunrBkiTdMZPsYu7etmumh2kXsceoSRuUD+QXq1UdWMBLk+dIv3aFZ6HP0+niF7L73a+EszcRyvq/xAKG3EGKM2g0YUso+e501Jb2wYpRnaCfg30JEuNTFvA+/M/K+gaaqaQf2UmgiCYEHlR3ULc9rUHH7nZL6AvmPwD+mxlF5dODhttvGHX9AbjaWv8pNrmC7hN0X+B3aTBtL7d5T+IA7RHZ1EFRnSsbwmRz+aHehTehaLxRzfOZp7dPksSM0AAAAASUVORK5CYII=>

[image16]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADoAAAAZCAYAAABggz2wAAAChUlEQVR4Xu2WO2hUQRSG7yWxEHygsIjuY3aX1QVBUFbSKAREREGtrNRO8AF2gmBtpaRMlc5KBBGChUJSBGwEbQQrSRFBFC20igii8Tt7z5XZk/vazUoQ7g+H2fuff2bOvzN37gRBiRIlSpTYXIS1Wq1jyRi9Xm8L+f2NRuM4j6HNjxlxLRM2IXW0Wq09lu90OjssZxFS/EFi3jm3YpNBlD9L7jPxgfhKLDebzWkrHBNkvn4txF6bFI54z/yPaOdoH6j2iNX+Bf/aIQS/iO/EmgxgNfV6/Tz8G2+1Q+3zjX92akC8AWgtb3Xsfi0uw6hq4li2ugHINqhUKtv4B3uIV2UAqyH3HP5Zu90+EHM8z8oEkqPArb5+VMRbUuqJaxFTVicc8YqYI+4TJ6Sv1SUiyyjcUzFF3Io59OeUW5W+vn4ciGsRUwk5Mbpk+ULIMgomut3udp/gvbimRldY0aqfs2Dsq+hvBEMcYEWMEhedrqqcMVaXiByj66DbWYzeDTIM6DaUopbkt82nIc8o87+jvcJWp3E3iR+Ftu+wRtH9JhZ5b3fanMU/WtHXHhUy/j3muexxyRjGqJy0Ljqcck2OiiyjSdAz42VuTUWMyiDkF4gZpSbpd4x3dPeAcAxIMyrb00Un/kefj+vPPRjzjMonxEUf5zuB3lboswvuSbVarRn5hpFmVJ6VX/N5XdFPtG2fX4cso/ovyuk2w+Vhn04mB8JJ2gUxbPv4oM8pdGcsn4U0o7qrXhAPfV6/AsJN+ryFvMynEf4kvsizn8TIbTd4C/HjcZAx+Iinrty8+rVQ12F59pNw151nlDtuxUUXiPQr4P8MFuAC5i6xY44W+rSUKFGixGbiD6Rf1o3TTdcVAAAAAElFTkSuQmCC>

[image17]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAmwAAAA8CAYAAADbhOb7AAAFO0lEQVR4Xu3dy4uXVRgHcCUDo6SrDTkzv4suBmlRYNBtEUGBQUZ0ocJNuyKiXQW2qAj/gWgVRrWKwCjoYljQdSG4qBYRSEG2KMhFEClkmD3PzHn1zHHGpl+M44yfDxze8z7nvL+XmdWX93LeVasAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWwfr16y9qaws1GAzWtjUAABYgg1S/3395nvZkN29ycvK6+rher/dEtJ+ydfPjt66v57Ri7oG2NqpRzg8AsGxNTU2ti8BzvK6Nj49fHrVd3X4Go3o8xfjHUX+62n8h2r56Tm3jxo0Xx2ZNWx/Vfz0/AMCyFSFne7Qfu/0NGzZcUer35HZycvKuCEa3deOdDHkTExPj1f7OaL/Xc1qDweC5tjaqUc4PALAsRcjZ312pikC1tQts9fjY2NiFdS2fZ8vA1O1v2bLl/BKgLqvntWLOL21tFKOeHwBgWcqgE0Ht4WgPRv/YHOOH21pedYv6of7M82PvRfuknTOXOmT9Hws8/5oIoq/F2I3tAADAspFX0+oQFf13c1vfuozan12/qu2POY9U+4cjHG2p58xlrsA2Pj4+0b1A0LaY/0M7Py3k/Dmez+fVNQCAZSdvhWb4acqro/ZSt5NhqB4steNx7KX1fgav7Ed9W+zvi+07sX3x5FFzB7ZRnO78KcLa3VE7EnM+62oAAMtOhpx52t/1vLzaFrXN5Zhd9dxuTvQPR3sm2ttl//2ynXV1rl8FwVEt5Pyl9m3XBwDOEfngfYSAo9F+7vV6z0aQ2Zv1cuvuaDt/pZiYmLgg/sYP2/p88kpX/D+2b9q06crY3lsNrS5Leyy6wcz6cjvbOgCwwkUA+Kvrl7cST9wqrK/2rEQR2J5qa/OJ/8WOfHYs/0d1PX7j1Xp/MQ2Hw2vifBvbOgCwgpVlJE4EthT7X1b9FR3YUgSgO9taqyy4eyzm3l/XB4PBDe3SIIul3MLd09YBgHNABpEMZnmrrb16lPUICg+V26PfV/U90V6J9l09N9rBmHsgtofKg/9Zezzar9GOxW/dUs1/sT+zdMWsB/gBADhVvj2ZwSnDVbYPuoHcz2e9Sv+LvCVX+odym0tMdIGrXvQ16s+X7ev98mWBctzxfAYs6o/2y4P6sd0fbdjNSXnVKgLfffO1mH9TPb8T9a/Ptdb+DwCAlWd1tPO6nW5l/VXl25ilPy36n/bKmmDlRYUjEbw+z1CWtRLYZi2VkWNxzLZuv/xGXnk7GGN7+yc/cH5tfRwAAEWGrFxdv65l6IoAtbb0Twls5S3J6SUyMoyVUHbzAgPbj2U1//czuNVzazF2dZ77NO299hgAgBWpu43ZLc6a36zsl+fSuqtt3XNt0f8q2q11YIvtN9F2R3tjOByOxfbIqpmrdtNKYDtQ5m6O9lv129O/EXMebp+dAwDgpDUZlvKKWnk+7F8/w9TJNydz26tW5m91V9hybvQvaccjtF3V1gAAOIPaW6IAAJxF8hZouWp3X95qbccBAGBRRSB9LNof+ZxftuFwONXOAQBgieTLE4NQ+rPejAUAYIlFTtvaL4v+puh/W48DALDEIrC92X3xIeXt0HocAIAl1uv1bo/Q9kD2I6y9FeGtX+r5yawduZ+LAudSKbOPBADgjMm163IB4bYege2Hst2dn+9qxwEAWGIR1PaX7UftGAAASyw/7xVB7Y65vugAAMBZYmpqal1bAwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACm/QOejKJ0FojJEwAAAABJRU5ErkJggg==>

[image18]: <data:image/png;base64,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>

[image19]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAZCAYAAABQDyyRAAABuElEQVR4Xu2UvUoDQRRGs6igKCpKiGaTbBJiEQsLIwqC2AkiiuALiAg+gWLhM1gpVtrYi40ExSKFEAQbLSxEm3QW8Q2Cnktm4+YSsvnRbg98LDP3m5k7M3c2FAoICPhHkslkfywWm3IcZ5ampeM1wuHwUDQajev+bmDRfVROJBIlvl/onYSWtc/FwviI6QEt0u7RhjaxmOcyk8kMm3YP7YrRVp3Tg5VKpWYw5NEHRzegDa3C+Cy6YMcTnr4T9I2ebdse9/obIibMR6iMTnW8GSaBSjwe33D7OOF1k4Bo1etvipwEA3bQFZNMh5oVkwepK2+b09gzi8uGst5YSzBoDT2hIjub03E/GFeQBNjEGc1eHfdF6oNd3DHBGwms6LgfZvf36XR6RMf8kAqW3RedDl8Iyc+T+C3XOaZjDTEF+ImO0aSOtwoLM9x5ZfEDt49TXCAR2+urgVlGnMvPIxKJDOp4O8gTlCtD2yFTuFKYzH2NcvXu6o8jj/kFbeZyuT5taBfmu0G7coKuqJ0lp1rI9afKoqOd3m8jpNCc3zevVdBPNMAtjlKr4soO9RzdIkVYKxY/BXf4l/wAslpyJWwMYQIAAAAASUVORK5CYII=>

[image20]: <data:image/png;base64,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>