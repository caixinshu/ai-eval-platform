# Day 20-21：联调与部署

> 项目三第 3 周 · 从「能跑」到「别人也能一键跑」：7 项联调检查、容器化、初始化脚本、README 与量化验收。

## 一、联调检查清单（7/7 通过）

| 检查项 | 验证方法 | 结果与证据 |
|--------|---------|-----------|
| 接口连通 | 四个页面逐个访问，看网络请求 | 通过：浏览器实测任务列表、详情、看板，`/api/*` 无 404/500 |
| 数据一致 | 页面数值与数据库/种子数据抽查 3 条 | 通过：看板 82.5 分、详情 82.5、任务列表 82.50 与库中 `total_score` 一致；Badcase 数 1 与 `passed=false` 条数一致 |
| 分页正确 | 120 条结果翻 3 页，比对去重后的 ID 数 | 通过：`test_long_run_progress_and_pagination`，3 页共 120 条、去重仍 120 |
| 异常提示 | 传不存在的 ID、重复版本、已结束任务取消 | 通过：统一 `{code, message}`，404 / 409 / 400 均有中文提示（既有 6 条异常测试） |
| 长任务 | 120 条用例一次评测 | 通过：终态 done、`progress=100`、`processed=120`，无超时 |
| 并发场景 | 两个任务同时跑 | 通过：`test_concurrent_runs_do_not_interfere`，6+6 条并发，结果各归各任务、无串数据 |
| 页面刷新 | 评测中刷新详情页 | 通过：详情页检测到 pending/running 后继续 2 秒轮询；服务重启残留任务由 `recover_stale_runs` 置 failed，不会永远转圈 |

## 二、容器化部署

新增文件：

```
Dockerfile            # python:3.11-slim + 健康检查
docker-compose.yml    # db(PostgreSQL) + api + web(Nginx)
nginx.conf            # 静态页 + /api 反代
.env.example          # LLM Key / 模型镜像地址
.dockerignore
```

### 关键决策

| 决策 | 原因 |
|------|------|
| 构建上下文用仓库根目录（`build: .`） | 项目不是纯后端目录，`backend/`、`app/`、`evaluation/` 都要进镜像；计划的 `build: ./backend` 对应单目录布局，这里必须调整 |
| 同时安装 `requirements.txt` 与 `backend/requirements.txt` | 根依赖是被测应用（chromadb / sentence-transformers / openai），后端依赖是 Web 框架与 ORM，缺一不可 |
| 新增 `psycopg2-binary` | compose 默认 PostgreSQL；SQLite 本地零配置不受影响 |
| `model-cache` / `chroma-data` 命名卷 | embedding 模型与向量库持久化，`docker compose up --build` 重建容器不必重复下载 |
| Nginx `client_max_body_size 10m` | 默认 1m，上传几百条用例的 JSON 会 413 |
| Nginx `proxy_read_timeout 300s` | 默认 60s，报告生成/大结果集接口容易 504 |
| api 健康检查 + db healthy 依赖 | 避免 api 先于 PostgreSQL 启动导致首启建表失败 |

### 一键启动（3 条命令）

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec api python scripts/import_dataset.py eval_datasets/golden_set.json
```

访问 `http://localhost`，API 文档 `http://localhost:8000/docs`。

> 环境说明：当前开发机未安装 Docker CLI，`docker-compose.yml` 已用 YAML 解析校验（services: api/db/web，volumes: pg-data/model-cache/chroma-data），镜像构建需在装有 Docker 的机器执行。README 已写明首次构建会下载依赖与模型。

## 三、演示数据导入

`scripts/import_dataset.py` 把 `eval_datasets/*.json` 直接灌进平台：

```bash
python scripts/import_dataset.py eval_datasets/golden_set.json
python scripts/import_dataset.py eval_datasets/edge_set.json --name 边界集 --type edge
python scripts/import_dataset.py eval_datasets/golden_set.json --force   # 清空后重导
```

- 幂等：数据集按「名称 + 类型」复用，用例按 id 去重
- 自动建 Prompt 版本：库里没有 Prompt 时创建「客服问答 v1.0.0」，保证导入完就能发起评测
- 实测：首次导入 55 条 → `导入 55，跳过 0`；重复执行 → `导入 0，跳过 55`，总数仍 55

## 四、README

补齐为可交付文档：项目简介、能力概览、两种快速开始（Docker / 本地）、五个页面功能、架构图、目录、文档索引、8 条常见问题（数据库未就绪、413、504、任务残留、无 Key 降级、模型下载慢、端口冲突等）。

## 五、量化验收自评

| 维度 | 分值 | 自评 | 说明 |
|------|------|------|------|
| 架构设计 | 15 | 15 | 6 实体、14 个接口、6 表 + 约束 + 6 个索引 |
| 后端 API | 25 | 23 | 数据集缺删除/编辑接口（-2）；其余增查、上传、异常处理完整 |
| 异步任务 | 20 | 20 | 后台执行、进度、失败隔离、取消 + 超时兜底 |
| 前端页面 | 20 | 20 | 四页 + 看板，loading / error / 二次确认齐全 |
| 可视化 | 10 | 10 | 雷达 / 趋势 / 分类 / 对比 + 阈值语义色，缺失值不伪造 |
| 部署文档 | 10 | 9 | 容器化文件齐全，本机无 Docker 未实机构建（-1）；README 可复现 |
| **合计** | **100** | **97** | 优秀（≥95） |

## 六、计划里的 8 个坑，我们怎么处理

| 坑 | 处理 |
|----|------|
| 后台任务卡在 running | `execute_eval` 整体 try/except/finally，异常写 failed；启动时 `recover_stale_runs` 清理残留 |
| BackgroundTasks 阻塞响应 | 任务函数是 `async def`，同步问答用 `asyncio.to_thread`，接口立即返回 |
| 连接数耗尽 | 后台任务自建 `SessionLocal`，`finally` 必关；长事务拆成每 5 条一次提交 |
| CORS 报错 | 生产 Nginx 同源反代；本地仅放行开发端口 |
| 大文件上传超时 | Nginx 10m + 后端批量解析入库 |
| 重启后 running 残留 | 启动清理并写「服务重启导致任务中断，请重新发起」 |
| 图表 null 白屏 | 雷达缺失返回空档 + 文案提示；分类为空显示占位；四图独立渲染互不阻塞 |
| 只有自己会用 | 看板首页给下一步引导，各页空状态都有「先做什么」文案，一键导入示例数据 |
