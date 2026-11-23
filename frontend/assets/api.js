/**
 * 前端公共工具（Day 18）
 *
 * 统一三件事：请求与错误提示、转义与格式化、loading/toast/确认交互。
 * 页面用 <script type="module"> 导入。
 */

export class ApiError extends Error {
  constructor(message, code, status) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

/** 统一请求：非 2xx 时把后端 {code,message} 转成可展示的错误 */
export async function api(path, options = {}) {
  const resp = await fetch(path, options);
  const text = await resp.text();
  let body = null;
  if (text) {
    try { body = JSON.parse(text); } catch { body = null; }
  }
  if (!resp.ok) {
    const message = body && body.message
      ? humanize(body)
      : `请求失败（HTTP ${resp.status}），请稍后重试`;
    throw new ApiError(message, body && body.code, resp.status);
  }
  return body;
}

/** 错误码说人话：后端信息已经可读，只对高频冲突补一句行动建议 */
function humanize(body) {
  if (body.code === "RUNNING_CONFLICT") {
    return body.message + "，可前往任务列表查看进度";
  }
  if (body.code === "VERSION_CONFLICT") {
    return body.message + "，请换一个版本号";
  }
  return body.message;
}

/** JSON 请求快捷方式 */
export function postJson(path, payload) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function esc(value) {
  return String(value === null || value === undefined ? "" : value)
    .replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
}

export function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("zh-CN", { hour12: false });
}

/** 耗时：只给「秒」和「分秒」两档，够用且不啰嗦 */
export function fmtDuration(start, end) {
  if (!start || !end) return "—";
  const seconds = Math.max(0, Math.round((new Date(end) - new Date(start)) / 1000));
  if (seconds < 60) return `${seconds} 秒`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s ? `${m} 分 ${s} 秒` : `${m} 分`;
}

const STATUS_META = {
  pending: { label: "排队中", cls: "pending" },
  running: { label: "运行中", cls: "running" },
  done: { label: "已完成", cls: "done" },
  failed: { label: "失败", cls: "failed" },
  cancelled: { label: "已取消", cls: "cancelled" },
};

export function statusLabel(status) {
  return STATUS_META[status] ? STATUS_META[status].label : status || "未知";
}

export function statusBadge(status) {
  const meta = STATUS_META[status] || { label: status || "未知", cls: "" };
  return `<span class="badge ${meta.cls}">${esc(meta.label)}</span>`;
}

export function typeLabel(type) {
  return { golden: "黄金集", edge: "边界集", adversarial: "对抗集" }[type] || type;
}

export const METRIC_LABELS = {
  rule_score: "规则得分",
  correctness: "答案正确性",
  faithfulness: "忠实度",
  answer_relevance: "答案相关性",
  context_precision: "上下文精度",
  context_recall: "上下文召回",
};

export function metricLabel(key) {
  return METRIC_LABELS[key] || key;
}

/** 底部轻提示，4 秒自动消失 */
export function toast(message, type = "info") {
  let stack = document.querySelector(".toast-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.className = "toast-stack";
    document.body.appendChild(stack);
  }
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  stack.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

/** 按钮 loading 态：禁用 + 换文案，结束后恢复 */
export function setLoading(button, loading, text = "处理中…") {
  if (!button) return;
  if (loading) {
    button.dataset.originalText = button.textContent;
    button.textContent = text;
    button.disabled = true;
  } else {
    if (button.dataset.originalText) button.textContent = button.dataset.originalText;
    button.disabled = false;
  }
}

/** 关键操作二次确认：原生 confirm 已足够，避免自造弹窗 */
export function confirmAction(message) {
  return window.confirm(message);
}
