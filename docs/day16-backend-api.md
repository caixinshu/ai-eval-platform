# Day 16：后端 API 开发

> 项目三第 3 周 · 按 Day 15 的契约实现数据集、Prompt、评测任务三大模块，13 个接口全部落地。

## 一、目录结构

```
backend/
├── main.py               # 入口：CORS、统一错误体、lifespan 建表、挂载路由
├── config.py             # DATABASE_URL / 并发数 / 分页上限
├── database.py           # engine / SessionLocal / Base / get_db / init_db
├── models/               # SQLAlchemy：dataset.py / prompt.py / run.py
├── schemas/              # Pydantic v2：dataset.py / prompt.py / run.py
├── routers/              # datasets.py / prompts.py / runs.py / _common.py
├── services/             # eval_service.py / report_service.py
└── requirements.txt
```

## 二、13 个接口落地情况

| 模块 | 接口 | 实现要点 |
|------|------|---------|
| 数据集 | GET/POST `/api/datasets` | type 过滤、分页；同名同版本返回 409 |
| | GET `/api/datasets/{id}/cases` | category 过滤、数据集不存在 404 |
| | POST `/api/datasets/upload` | JSON 数组或 `{cases: []}`；批内重复 ID 也跳过 |
| Prompt | GET/POST `/api/prompts` | 版本只增不改，重复版本 409 |
| 任务 | POST `/api/runs` | 建任务后**立即返回 201**，评测进后台 |
| | GET `/api/runs` | status 过滤、分页 |
| | GET `/api/runs/{id}` | 单任务详情 |
| | GET `/api/runs/{id}/status` | 轮询专用：status/progress/processed/total/failed |
| | GET `/api/runs/{id}/results` | passed 过滤；列表不返回 contexts 大字段 |
| | GET `/api/runs/{id}/report` | `format=json` 聚合 / `html` 自包含报告 |
| | POST `/api/runs/compare` | 复用 `analysis.comparator`，跨数据集对比返回 400 |

## 三、三个关键实现点

### 1. 长任务必须立即返回

`POST /api/runs` 只做三件事：校验数据集、查重、写 pending 行，然后把 `execute_eval` 丢给 `BackgroundTasks`，响应体只有 `{run_id, status, total_cases}`。前端拿 run_id 轮询 `/status`，进度条只依赖这一个接口。

### 2. 逐条落库，单条失败不炸整批

`services/eval_service.execute_eval`：

- 每条用例：调用问答 → 规则检查（RuleEvaluator）→ 语义正确性（可选）→ 写 `eval_results` → 更新 `progress`
- 单条异常：捕获后 `passed=False`，回答写成 `[应用异常] xxx`，现场保留在报告里
- 任务结束：按指标写入 `metric_snapshots`（供趋势图直查），置 `status=done`、`total_score`
- 任务级异常：`status=failed`，原因写 `error_message`，不吞异常

通过线：规则全过 + 语义正确性 ≥ **0.84**（对齐 Day 9 校准结果），避免「规则过了就算通过」的自欺。

### 3. 统一错误体 + 重复运行保护

- `api_error()` 统一抛 `{code, message}`，`main.py` 的异常处理器原样输出，前端只需一套错误处理
- 同一数据集 + Prompt 已有 `pending/running` 任务时返回 `409 RUNNING_CONFLICT`，避免用户连点五次建五个任务
- 6 个错误码与 Day 15 契约一致（INVALID_PARAM / NOT_FOUND / VERSION_CONFLICT / RUNNING_CONFLICT / DATASET_INVALID / INTERNAL_ERROR）

## 四、与计划的三处偏差（有意为之）

| 偏差 | 原因 |
|------|------|
| 默认 `sqlite:///data/eval_platform.db`，PostgreSQL 走 `DATABASE_URL` | 本机无 PostgreSQL，SQLite 让 API 零配置可跑；models 用 `JSON` 类型，两种库都兼容；`psycopg2` 在 requirements 中注释保留 |
| 上传接口为 `POST /api/datasets/upload?dataset_id=xxx` | Day 15 契约漏了「传到哪个数据集」，显式作为 query 参数补上 |
| 依赖版本取本机已验证版本（fastapi 0.128.8 等） | 计划里的 0.109 与本机环境不一致；API 用法完全兼容 |

## 五、测试（`tests/test_api.py`，10 条全绿）

临时 SQLite + `TestClient`，不依赖 PostgreSQL、不加载 embedding 模型：

- 健康检查、数据集创建/列表/重复冲突
- 用例上传（含批内重复跳过、非法 JSON 422、case_count 回填）
- Prompt 创建与版本冲突
- 任务：数据集不存在 404、运行中重复发起 409
- 端到端：发起 → 后台执行 → 轮询 done/100% → 结果列表 → JSON 报告 → HTML 报告
- 对比：两次评测指标 diff，空回答被识别为 `rule_score` 退化

```
python -m pytest tests\test_api.py -q   →  10 passed（19s）
```

## 六、启动方式

```powershell
python -m uvicorn backend.main:app --reload --port 8000
# Swagger: http://localhost:8000/docs
```

```powershell
# 冒烟
curl.exe http://localhost:8000/api/health
```

首次启动自动建表到 `data/eval_platform.db`（已在 .gitignore 中）。生产切库只需设 `DATABASE_URL=postgresql://...` 并按 `sql/schema.sql` 建表。

## 七、今日产出对照

| 计划产出 | 交付 |
|---------|------|
| 数据集模块接口 | ✅ 4 个（列表/创建/用例/上传） |
| Prompt 模块接口 | ✅ 2 个（列表/创建） |
| 评测任务接口 | ✅ 7 个（创建/列表/详情/状态/结果/报告/对比） |
| SQLAlchemy 模型 + Pydantic 契约 | ✅ 6 模型 + 11 Schema |
| 后台执行 + 进度 | ✅ 逐条落库、progress 更新、失败隔离 |
| 接口测试 | ✅ 10 条通过 |

## 八、下一步

- Day 17：前端页面（数据集管理、发起评测、任务列表轮询、结果可视化）
- 评测任务目前用 `BackgroundTasks`（进程内），多实例部署时需换成任务队列
- 报告 HTML 目前是轻量版（指标 + badcase），Day 18 可与 `templates/report.html` 统一
