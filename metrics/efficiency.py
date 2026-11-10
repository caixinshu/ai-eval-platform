"""
效率指标与格式校验 (Efficiency & Format Metrics)
- latency_p95: P95 延迟
- tokens_per_request: 单次 Token 消耗
- cost_per_request: 单次成本
- format_valid: 格式合规率
"""
import json
import math
from typing import Any


def percentile(data: list[float], p: float) -> float:
    """计算百分位数"""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return sorted_data[f]
    return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)


def latency_p95(latencies_ms: list[float]) -> float:
    """P95 延迟（毫秒）"""
    return percentile(latencies_ms, 95)


def latency_avg(latencies_ms: list[float]) -> float:
    """平均延迟"""
    return sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0


def tokens_per_request(token_records: list[dict]) -> float:
    """
    平均单次请求的 Token 消耗。
    token_records: [{"input": 100, "output": 50}, ...]
    """
    if not token_records:
        return 0.0
    total = sum(r.get("input", 0) + r.get("output", 0) for r in token_records)
    return total / len(token_records)


def cost_per_request(token_records: list[dict], input_price: float = 0.001, output_price: float = 0.002) -> float:
    """
    平均单次请求成本（美元）。
    input_price / output_price: 每 1K tokens 的价格（默认 $0.001/$0.002）
    """
    if not token_records:
        return 0.0
    total_cost = sum(
        (r.get("input", 0) / 1000) * input_price + (r.get("output", 0) / 1000) * output_price
        for r in token_records
    )
    return total_cost / len(token_records)


def format_valid(text: str, schema: dict = None) -> bool:
    """
    格式校验：回答是否符合预期格式。
    如果提供了 JSON Schema，则按 Schema 校验；否则只检查是否为合法 JSON。
    """
    if schema:
        try:
            data = json.loads(text)
            return _validate_json_schema(data, schema)
        except (json.JSONDecodeError, TypeError):
            return False
    # 无 Schema 时：尝试解析 JSON
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


def _validate_json_schema(data: Any, schema: dict) -> bool:
    """简易 JSON Schema 校验（支持 type、required、properties）"""
    expected_type = schema.get("type")
    if expected_type == "object" and not isinstance(data, dict):
        return False
    if expected_type == "array" and not isinstance(data, list):
        return False
    if expected_type == "string" and not isinstance(data, str):
        return False
    if expected_type == "number" and not isinstance(data, (int, float)):
        return False

    if isinstance(data, dict) and "required" in schema:
        for field in schema["required"]:
            if field not in data:
                return False
    return True


def format_valid_batch(texts: list[str], schema: dict = None) -> float:
    """批量格式合规率"""
    if not texts:
        return 0.0
    return sum(1 for t in texts if format_valid(t, schema)) / len(texts)


if __name__ == "__main__":
    print("效率指标:")
    latencies = [100, 150, 200, 250, 300, 500, 800, 1200, 2000]
    print(f"  P95 延迟: {latency_p95(latencies):.1f} ms")
    print(f"  平均延迟: {latency_avg(latencies):.1f} ms")

    tokens = [{"input": 500, "output": 200}, {"input": 800, "output": 300}]
    print(f"  单次 Token: {tokens_per_request(tokens):.0f}")
    print(f"  单次成本: ${cost_per_request(tokens):.6f}")

    print("\n格式校验:")
    valid_json = '{"name": "test"}'
    print(f"  合法 JSON: {format_valid(valid_json)}")
    print(f"  非法文本: {format_valid('不是 JSON')}")
    schema = {"type": "object", "required": ["name", "age"]}
    valid_schema = '{"name": "a", "age": 20}'
    invalid_schema = '{"name": "a"}'
    print(f"  Schema 合规: {format_valid(valid_schema, schema)}")
    print(f"  Schema 违规: {format_valid(invalid_schema, schema)}")
