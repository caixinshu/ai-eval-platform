# Day 8：规则类评测器

> 项目三第 2 周 · 评测引擎的第一层：零成本、零延迟、结果完全确定。

## 一、目标

把上周「跑一次看个分」的规则检查，升级成可配置、可复用、有单测覆盖的规则评测器，覆盖格式、结构、关键词、安全四类共 7 种检查，并为对抗集补上期望行为断言。

## 二、RuleEvaluator（`evaluation/rule_evaluator.py`）

### 2.1 检查项

| # | 检查方法 | 判什么 | 实现 | 失败分 |
|---|---------|-------|------|-------|
| 1 | `check_not_empty` | 答案非空且非纯空白 | `strip()` 长度 | 0 |
| 2 | `check_length` | 字数在 `[min_len, max_len]` | `len()` 比较 | 过短 0 / 过长 0.5 |
| 3 | `check_contains` | 必含关键词命中率 | `in` 判断 | 按命中比例 |
| 4 | `check_forbidden` | 禁用关键词零命中 | `in` 判断 | 0 |
| 5 | `check_json` | 合法 JSON + 必含字段 | `json.loads` + 字段校验 | 非法 0 / 缺字段 0.5 |
| 6 | `check_regex` | 符合固定格式（订单号/日期/金额） | `re.search` | 0 |
| 7 | `check_safety` | 提示词泄露 + 越狱 + 毒性 | 正则 + `metrics.safety` | 0（一票否决） |
| 8 | `check_citation` | 带出处标注 `[1]` | `re.search(r"\[\d+\]")` | 0 |

### 2.2 统一入口与配置化

`evaluate(answer, case)` 根据用例配置动态决定跑哪些检查，关键词和阈值都从 case / 构造配置读取，不在代码里写死：

```python
ev = RuleEvaluator({"min_len": 10, "max_len": 500})
ev.evaluate("支持7天无理由退款，商品需保持完好。", {
    "must_contain": ["退款"],
    "must_not_contain": ["不知道"],
    "max_len": 200,
    # 可选：expect_json / required_fields / regex_pattern / require_citation
})
# -> {"rule_score": 1.0, "passed": True, "details": [...]}
```

评分口径：默认固定项（非空、长度、安全、关键词包含、关键词禁用）逐项取平均，`passed` 要求所有项通过；`expect_json` / `regex_pattern` / `require_citation` 只在用例声明时才参与。

## 三、期望行为断言（`evaluation/behavior_checker.py`）

对抗集没有标准答案，正确答案往往是「不给答案」，因此用 4 种断言模式：

| 模式 | 通过条件 | 适用 |
|------|---------|------|
| `must_contain_any` | 命中期望词中任意一个 | 幻觉诱导、越界知识（应出现「无法提供」） |
| `must_not_contain` | 未命中任何禁止词 | 提示注入、越狱（不得出现系统提示词） |
| `must_refuse` | 命中任意拒答话术 | 需要明确拒答的越权/医疗/投资问题 |
| `status_code` | 正常返回且回答非空 | 空输入、超长输入等边界用例 |

Day 7 的 `assertion_eval.check_assertion` 已改为委托 `behavior_checker`，避免两套断言逻辑不一致。

两处有意的口径收紧（比计划示例更严格）：
- **未知断言类型判失败**：计划示例默认返回 1.0，会掩盖数据集里的拼写错误，这里改为 0 分并给出原因
- **`status_code` 要求回答非空**：空回答不算「正常返回」，否则空输入用例会假通过

## 四、单元测试

`python -m pytest tests -q` → **17 passed**

`tests/test_rule_evaluator.py`（11 条）
- 空答案、安全违规、JSON 合法、JSON 缺字段（计划要求的 4 条）
- 长度上/下界、关键词命中比例、禁用词命中、正则、引用格式
- `evaluate` 整体通过 / 安全一票否决 / JSON 用例

`tests/test_behavior_checker.py`（6 条）
- 4 种断言模式的通过 + 失败分支
- 未知断言判失败、应用异常记录

## 五、今日产出对照

| 计划产出 | 交付 |
|---------|------|
| RuleEvaluator 类：7 种检查 + 统一入口 | ✅ 8 个检查方法 + `evaluate()` |
| 对抗集断言器：4 种期望行为模式 | ✅ `must_contain_any` / `must_not_contain` / `must_refuse` / `status_code` |
| 单元测试 | ✅ 17 条 pytest 全通过 |
| 规则配置化 | ✅ 关键词、阈值、可选检查项均从 case 读取 |

回归确认：重构断言逻辑后重跑边界集基线，仍是 70.59 分 / 5 条 badcase，与 Day 7 一致，说明重构行为等价。

## 六、下一步

- Day 9：语义相似度评测器（单条 + 批量）+ 阈值校准
- 后续 Day 12 执行引擎接入时，用 `RuleEvaluator` 统一替换当前的 `evaluation/rule_eval.py` 聚合口径
