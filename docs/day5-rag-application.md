# Day 5：搭建被测 RAG 应用

> 项目三第 1 周 · 搭建带检索增强的问答应用，作为后续评测的被测对象

## 一、RAG 应用架构

```
用户问题
   ↓
[检索层] chromadb + bge-small-zh 向量检索
   ↓ 返回 top_k 相关文档片段
[生成层] Prompt 模板 + LLM 生成答案
   ↓
答案 + 检索到的上下文
```

**三层职责**：

| 层 | 职责 | 实现 |
|----|------|------|
| 检索层 | 从知识库找到相关文档 | chromadb + bge-small-zh-v1.5 |
| 生成层 | 基于上下文生成答案 | Prompt v1.2.0 + LLM |
| 接口层 | 对外暴露 HTTP 服务 | FastAPI |

---

## 二、核心代码

### 2.1 检索 + 生成链路（`app/rag.py`）

```python
def retrieve(question: str, top_k: int = 3) -> list:
    """检索相关文档片段"""
    result = collection.query(query_texts=[question], n_results=top_k)
    return result.get("documents", [[]])[0]

def generate(question: str, contexts: list) -> str:
    """基于上下文生成答案。有 API Key 调真实 LLM，否则用 mock。"""
    context_text = "\n\n---\n\n".join(contexts) if contexts else "（无相关资料）"
    messages = build_messages(context_text, question)
    # 调用 LLM 或降级到 mock

def ask(question: str) -> dict:
    """完整问答链路：检索 -> 生成"""
    contexts = retrieve(question)
    answer = generate(question, contexts)
    return {"question": question, "answer": answer,
            "contexts": contexts, "context_count": len(contexts)}
```

### 2.2 Embedding 工厂（`app/embedding.py`）

```python
def get_embedding_function():
    """优先 bge-small-zh，失败降级到本地字符 n-gram"""
    try:
        return SentenceTransformerEmbeddingFunction(model_name="BAAI/bge-small-zh-v1.5")
    except Exception:
        return LocalEmbeddingFunction()  # 字符 n-gram + 哈希
```

**降级策略**：无网络/模型加载失败时，用本地字符 n-gram embedding 保证流程可跑。

### 2.3 LLM 降级策略

```python
if _llm_client is not None:
    # 调用真实 LLM API
    resp = client.chat.completions.create(...)
else:
    # 无 API Key 时用 mock：基于检索上下文拼接答案
    return mock_llm_answer(question, contexts)
```

### 2.4 HTTP 接口（`app/main.py`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/stats` | 知识库统计（片段数、embedding 模型、LLM 模式） |
| POST | `/ask` | 问答接口，body: `{"question": "..."}` |

### 2.5 知识库入库（`scripts/ingest.py`）

- 扫描 `knowledge/` 下的 `.md`/`.txt` 文件
- 滑动窗口切分（chunk_size=500, overlap=50）
- 向量化后存入 chromadb

---

## 三、知识库

共 **13 篇文档**，覆盖 6 个业务类别：

| 类别 | 文档 |
|------|------|
| 退款政策 | refund_policy.md, refund_process.md |
| 物流配送 | logistics_query.md, shipping_time.md |
| 产品咨询 | product_x1_spec.md, product_x1_pro_spec.md, product_warranty.md |
| 账户安全 | account_password.md, account_security.md |
| 功能使用 | feature_favorites_invoice.md, feature_coupon.md |
| 售后服务 | aftersale_exchange.md, aftersale_repair.md |

入库后共 **13 个向量片段**（每篇文档较短，未触发切分）。

---

## 四、端到端验证结果

### 4.1 检索准确性

| 问题 | 检索到的上下文[0] | 相关性 |
|------|-------------------|--------|
| 你们的退款政策是什么？ | 退款流程与到账 | ✅ 相关 |
| 退款多久能到账？ | 退款流程与到账 | ✅ 相关 |
| 这款手机的电池容量是多少？ | X1 手机参数 | ✅ 相关 |
| 怎么修改密码？ | 密码管理 | ✅ 相关 |

### 4.2 接口测试

```
GET /health -> 200: {"status": "ok"}
GET /stats  -> 200: {"count": 13, "embedding_model": "BAAI/bge-small-zh-v1.5", ...}
POST /ask   -> 200: {"answer": "...", "contexts": [...], "context_count": 3}
```

### 4.3 幻觉验证

| 问题（知识库外） | 行为 | 结果 |
|-----------------|------|------|
| 你们公司 2025 年营收是多少？ | 检索到不相关上下文，mock 回答未编造具体数字 | ✅ 未编造 |

---

## 五、环境配置

### 依赖

```
chromadb==0.5.20        # 向量数据库
sentence-transformers   # bge-small-zh embedding
openai                  # LLM 调用
fastapi + uvicorn       # HTTP 服务
numpy<2.0               # chromadb 0.5.x 兼容
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | 无 | 不设则用 mock LLM |
| `LLM_BASE_URL` | OpenAI 官方 | 可指向兼容接口 |
| `LLM_MODEL` | gpt-4o-mini | 模型名称 |
| `EMBEDDING_MODEL` | BAAI/bge-small-zh-v1.5 | embedding 模型 |
| `CHROMA_PATH` | ./chroma_db | 向量库存储路径 |
| `TOP_K` | 3 | 检索返回片段数 |
| `USE_LOCAL_EMBEDDING` | 空 | 设为 1 强制用本地 embedding |

### 启动命令

```powershell
# 入库
python scripts/ingest.py

# 启动服务
python -m uvicorn app.main:app --reload
```

---

## 六、踩坑记录

### 坑 1：chromadb 1.5.9 在 Python 3.9 上崩溃

**现象**：`collection.add()` 时进程段错误（0xC0000005），无任何输出。

**根因**：chromadb 1.5.x 与 Python 3.9 不兼容（可能需要 3.10+）。

**解决**：降级到 `chromadb==0.5.20`，完全兼容 Python 3.9。

### 坑 2：numpy 2.0 与 chromadb 不兼容

**现象**：chromadb 操作时崩溃。

**解决**：降级 numpy 到 1.26.4（`numpy<2`）。

### 坑 3：HuggingFace 连接超时

**现象**：下载 bge-small-zh 模型时连接超时。

**解决**：设置 `HF_ENDPOINT=https://hf-mirror.com` 使用国内镜像。

### 坑 4：embedding function 冲突

**现象**：`ValueError: Embedding function conflict: new: sentence_transformer vs persisted: default`

**根因**：之前降级时用 default embedding 创建了空 collection，后用 sentence_transformer 时冲突。

**解决**：删除 chroma_db 目录重新入库。

---

## 七、文件清单

| 文件 | 说明 |
|------|------|
| `app/__init__.py` | 包初始化 |
| `app/rag.py` | RAG 核心：检索 + 生成 |
| `app/embedding.py` | Embedding 工厂 + 本地降级 |
| `app/main.py` | FastAPI HTTP 接口 |
| `scripts/ingest.py` | 知识库入库脚本 |
| `knowledge/*.md` | 13 篇知识库文档 |
| `requirements.txt` | 依赖清单 |

---

## 八、下一步

- **Day 6-7**：接入 Ragas 评测框架，用规则评测 + 语义评测跑出首轮基线
- 有 LLM API Key 时，配置 `LLM_API_KEY` 即可切换到真实模型，无需改代码
