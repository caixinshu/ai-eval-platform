# Day 18：前端页面开发

> 项目三第 3 周 · 把 13 个接口串成非技术同学也能用的四个页面：数据集管理、发起评测、任务列表、结果详情。

## 一、页面与路由

静态页由 FastAPI 直接托管（`/` 挂载 `frontend/`），前后端同源，不用配 CORS、不用起两个服务。

| 页面 | 路径 | 核心内容 |
|------|------|---------|
| 入口 | `/` | 自动跳转到任务列表 |
| 数据集管理 | `/pages/datasets.html` | 列表、用例预览、新建数据集、上传 JSON |
| 发起评测 | `/pages/new-run.html` | 数据集 / Prompt / 模型下拉，提交后进度条 + 取消 |
| 任务列表 | `/pages/tasks.html` | 状态、进度、总分、耗时，未完成任务每 3 秒自动刷新 |
| 结果详情 | `/pages/run-detail.html?run_id=xxx` | 总分、指标卡片、基线对比、Badcase、报告导出 |

本地启动：

```powershell
python -m uvicorn backend.main:app --port 8000
# 打开 http://localhost:8000/
```

## 二、目录结构

```
frontend/
├── index.html              # 跳转到任务列表
├── poll.js                 # Day 17：轮询 + 取消（页面复用）
├── assets/
│   ├── app.css             # 全站样式：表格、卡片、徽章、进度条、弹窗、toast
│   ├── api.js              # 请求封装、错误说人话、转义/时间格式化、loading/toast/确认
│   └── layout.js           # 顶部导航，各页一行 renderNav() 复用
└── pages/                  # 四个业务页面，原生 HTML + ES Module
```

选原生 HTML + ES Module 而不是 React+Vite：四个页面、无复杂状态，起构建链的收益小于成本；后端已能托管静态文件，打开即用。Day 19 的可视化看板也用同一套方式引入 ECharts。

## 三、统一交互底线

计划要求的「任何操作都有反馈、错误说人话、关键操作二次确认」，落在公共层：

1. **loading**：按钮统一走 `setLoading(btn, true)`（禁用 + 换文案），列表有「加载中…」占位，不会出现点了没反应
2. **error**：`api()` 把后端 `{code, message}` 转成 `ApiError`，页内 alert 区 / toast 展示；`RUNNING_CONFLICT` 等高频错误自动补一句行动建议，不把堆栈甩给用户
3. **二次确认**：开始评测（带用例数）、上传 JSON（带目标数据集与文件名）、取消评测，都用原生 `confirm`，不自造弹窗

另外所有用户内容（问题、回答、标准答案）统一 `esc()` 转义后再拼 HTML，避免题库里的 `<script>` 被当成代码执行。

## 四、页面实现要点

### 1. 数据集管理

- 列表展示名称、类型、用例数、版本、创建时间（后端补了 `DatasetOut.created_at`）
- 预览弹窗分页拉 `/api/datasets/{id}/cases`，展示 ID / 问题 / 分类 / 难度 / 标准答案
- 上传走 `multipart/form-data`，后端返回「导入 X 条、跳过 Y 条、当前共 Z 条」
- 计划只写了「上传」，但上传必须先有数据集，因此补了「新建数据集」弹窗（复用已有 `POST /api/datasets`），避免新环境无路可走

### 2. 发起评测

- 三个下拉并行加载；数据集提示当前用例数，Prompt 为空时提供「新建 Prompt 版本」弹窗（复用 `POST /api/prompts`）
- 提交后立即拿到 `run_id`，用 Day 17 的 `pollRunStatus` 每 2 秒刷新进度，结束自动跳转结果详情
- 进度区带「取消评测」，调用 Day 17 的取消接口，等任务走到检查点后终态变为已取消

### 3. 任务列表

- 状态筛选 + 分页；耗时由 `started_at / finished_at` 前端计算（后端补了这两个字段）
- 只要当前页存在 `pending/running` 任务，就每 3 秒自动刷新，全部结束自动停表
- 失败任务鼠标悬停显示 `error_message`，点进详情看完整原因

### 4. 结果详情

- 顶部：总分大卡片 + 数据集 / Prompt / 模型 / 用例数 / 耗时 / 开始时间
- 指标区：来自 `/report` 的 `metrics`，低于 0.6 标红；答案正确性提示通过线 0.84
- 对比区：在同数据集的历史任务中找开始时间更早的最近一次 `done` 任务，调 `/api/runs/compare`，展示总分与逐指标 diff，回归/提升指标用提示条标出（±3 个百分点内视为噪声）
- Badcase 区：`/results?passed=false` 分页，`<details>` 展开看问题、回答、标准答案、指标、耗时（后端结果契约补了 `ground_truth`）
- 导出区：下载 JSON、新窗口查看自包含 HTML 报告

## 五、后端配合改动（4 处）

| 改动 | 原因 |
|------|------|
| `main.py` 挂载 `StaticFiles(frontend, html=True)` | 前后端同源，省掉 CORS 与单独静态服务器 |
| `mimetypes.add_type("application/javascript", ".js")` | Windows 注册表可能把 `.js` 映射成 `text/plain`，浏览器会**静默拒绝执行 ES module**，页面永远停在「加载中…」；这个问题在浏览器实测时暴露，已加测试防回归 |
| `DatasetOut.created_at`、`RunOut.started_at/finished_at/error_message` | 列表页要展示创建时间、耗时和失败原因 |
| `ResultOut.ground_truth`（按 case_id 关联用例表补齐） | Badcase 展开需要标准答案对照 |

## 六、验收

- 后端测试：`python -m pytest tests/test_api.py -q` → 17 passed（新增静态页与 `ground_truth` 两条）
- 浏览器实测（临时 SQLite + 演示数据）：任务列表正常显示两条已完成任务的分数与进度；结果详情显示总分 82.5、指标卡片、与基线 75.00 的对比表、Badcase 展开内容；控制台无报错
- 首次实测曾因 `.js` Content-Type 错误导致页面不渲染，修复后复测通过——这也是把「浏览器验收」写进流程的价值

## 七、与计划的偏差

| 偏差 | 原因 |
|------|------|
| 原生 HTML + ES Module，非计划架构图里的 React + Vite | 四个简单页面不值得引入构建链；同源静态托管零配置 |
| 结果详情用 `?run_id=` 查询参数，而非 `/run/{id}` 路径 | 纯静态页无需服务端路由，刷新/分享都稳定 |
| 新增「新建数据集 / 新建 Prompt」两个弹窗 | 否则空库无法上传用例、无法发起评测，页面闭环走不通 |
| 任务列表自动刷新 3 秒，发起评测轮询 2 秒 | 列表是概览、单任务是主操作，频率有意区分 |
