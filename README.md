# Physical Quantity Engine (Python)

本地物理量表达式求值服务。接收带单位与可选标准不确定度的物理量，
对由这些物理量组成的表达式进行解析、量纲校验、求值、单位换算与
不确定度传播，并提供原子版本化目录与可取消/可超时的批量任务。

## 运行

```bash
uv sync                       # 安装依赖（Python 3.14）
uv run pytest                 # 运行全部测试
uv run uvicorn main:app --reload   # 启动 HTTP 服务（默认 http://127.0.0.1:8000）
```

## 表达式语法

- 标量常量：`1`、`2.5`、`1e-3`、`.5`
- 命名物理量：`x`、`v_1`（来自请求变量或目录版本）
- 四则运算：`+ - * /`，括号 `( )`
- 整数幂：`x^2`、`m^-1`、`a^(1+1)`（指数必须是整型常量表达式，右结合）
- 一元函数：`neg`（一元负号）、`abs`、`sqrt`、`sqr`（平方）、
  `sin`、`cos`、`tan`、`ln`、`log10` 写作 `log`、`exp`

优先级（由低到高）：`+ -` < `* /` < 一元函数/符号 < `^`。
三角函数参数按弧度计，且必须是无量纲量。

## 量纲与运算规则

- 加减：两侧量纲必须完全一致，否则 `DIMENSION_MISMATCH`。
  运算在左侧操作数的单位下进行（会触发前缀/导出单位换算）。
- 乘除：量纲按指数向量相乘/相除；除零（含零分母物理量）返回
  `DIVISION_BY_ZERO`。
- 幂：指数必须为整数，否则 `DIMENSION_MISMATCH`；零底的非正幂返回
  `DIVISION_BY_ZERO`。
- 一元函数（除 `neg/abs` 外）要求无量纲参数，否则
  `DIMENSION_MISMATCH`；`sqrt/ln/log` 对非法定义域返回 `DOMAIN_ERROR`。

## 单位与换算

- 7 个 SI 基本单位：`m kg s A K mol cd`；无量纲单位：`one`（等价 `1`）。
- 全部标准十进制词头：`Q R Y Z E P T G M k h da d c m u/µ n p f a z y r q`。
- 相干导出单位：`Hz N Pa J W C V ohm/Ω S F T Wb H`。
- 接受的非 SI 单位（精确换算）：`min h L/l t bar eV deg/° percent`。
- 复合单位：`m/s`、`kN*m/s^2`、`cm^3` 等，通过线性倍率与量纲指数解析。
- 换算要求量纲匹配，失败时返回 `UNIT_CONVERSION_FAILED`，且不产生任何
  结果值（无部分结果）。
- 求值在 SI 基本单位上进行；显示单位优先选择**相干**单位（如力显示
  `N`），没有相干命名词条时显示 `(compound)`，升/分等非相干单位不会
  遮蔽 `m^3` 这类复合量纲。

## 数值、舍入与不确定度传播（确定性）

- 所有运算使用 `decimal.Decimal`，内部精度 40 位，舍入固定
  `ROUND_HALF_UP`；三角函数用固定 50 位 π、角度归约与幂级数实现，
  不依赖平台浮点数学，保证同一输入在同一规则版本下结果逐位一致。
- 报告值保留 10 位有效数字；标准不确定度保留 2 位有效数字；
  存在不确定度时，报告值对齐到不确定度的末位。
- 不确定度假设输入相互独立，按线性误差传播：
  - 加减：`u = sqrt(u_a² + u_b²)`
  - 乘除：`u = |v| * sqrt((u_a/a)² + (u_b/b)²)`
  - 幂：`u = |n · a^(n-1)| · u_a`
  - 一元函数：`u = |f'(x)| · u_x`
- 非有限值（`inf/-inf/nan`）在构造物理量时即被拒绝
  （`NON_FINITE_VALUE`）；量级超过 1e308 返回 `OVERFLOW`。
- 任何失败路径都返回明确错误码，绝不返回 `null` 或伪成功。

## 目录版本与并发

- `Catalog` 的每次 `commit` 发布一份全新的不可变完整快照，版本号单调
  递增；求值可通过 `version` 固定到任意完整版本。
- 读者始终基于某个快照求值，并发提交时不可能读到混合状态。
- 提交支持乐观并发控制：传入 `expected_version`，不匹配时返回
  `CATALOG_CONFLICT`，且不会创建新版本。

## 批量任务

- 每个任务在独立工作线程中执行，单个任务失败被捕获到自己的结果里，
  不污染其它任务。
- 每个任务可设 `timeout`（秒），超时返回 `TASK_TIMEOUT`；
  批次级取消信号返回 `TASK_CANCELLED`。
- 每个任务恰好产出一个终态结果（成功或失败），不存在中间/悬挂结果。
- 任务 `id` 必须唯一，否则 `INVALID_REQUEST`。

## HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| POST | `/evaluate` | 单表达式求值 |
| GET | `/catalog/versions` | 列出所有版本 |
| GET | `/catalog/versions/{v}` | 读取某版本完整快照 |
| POST | `/catalog/commit` | 原子提交新版本（可带 `expected_version`） |
| POST | `/batch` | 批量求值（隔离/超时） |

物理量规格：`{"value": <number>, "unit": "<string>", "uncertainty": <number >= 0>}`。

错误响应统一为 HTTP 422：

```json
{"error": {"code": "<ERROR_CODE>", "message": "<human readable>"}}
```

## 错误码（稳定）

| 错误码 | 含义 |
| --- | --- |
| `PARSE_ERROR` | 表达式词法/语法错误 |
| `UNKNOWN_QUANTITY` | 引用了未定义的物理量（或该版本中不存在） |
| `UNKNOWN_UNIT` | 未知/非法单位或单位表达式 |
| `DIMENSION_MISMATCH` | 量纲不一致，或幂指数非整数 |
| `UNIT_CONVERSION_FAILED` | 单位换算量纲不匹配 |
| `DOMAIN_ERROR` | 函数定义域错误（如 sqrt(-1)、ln(0)） |
| `DIVISION_BY_ZERO` | 除零或零底非正幂 |
| `NON_FINITE_VALUE` | 出现 inf/-inf/nan |
| `OVERFLOW` | 数值超过 1e308 |
| `UNCERTAINTY_INVALID` | 不确定度为负 |
| `VERSION_NOT_FOUND` | 指定的目录版本不存在 |
| `CATALOG_CONFLICT` | 乐观版本号冲突 |
| `TASK_TIMEOUT` | 批量任务超时 |
| `TASK_CANCELLED` | 批量任务被取消 |
| `TASK_FAILED` | 任务内未预期的内部失败（已隔离） |
| `INVALID_REQUEST` | 请求结构不合法 / 任务 id 重复 |

## 项目结构

```
pqengine/
  errors.py      # 稳定错误码与 EngineError
  dimensions.py  # 7 维量纲指数向量
  units.py       # 单位、词头、导出单位、复合单位解析与换算
  quantity.py    # 物理量、有限性校验、单位换算（不确定度同步）
  parser.py      # 词法/递归下降/AST
  evaluator.py   # 量纲校验、Decimal 求值、不确定度传播、舍入
  catalog.py     # 原子不可变版本快照与乐观并发
  batch.py       # 隔离/超时/取消的批量任务
  service.py     # FastAPI 端点与统一错误响应
tests/           # 覆盖以上全部能力的自动化测试
```
