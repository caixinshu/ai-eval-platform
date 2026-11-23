/**
 * 评测任务轮询（Day 17）
 *
 * 后端评测是后台任务，前端只做「定时问进度」，不要自己估算时间：
 *   const task = pollRunStatus(runId, {
 *     onProgress: (s) => render(s.progress),
 *     onFinish: (s) => renderResult(s.status),
 *   });
 *   // 用户点「取消」
 *   await cancelRun(runId);
 *   // 页面卸载时务必停掉，否则定时器泄漏
 *   task.stop();
 */

const TERMINAL_STATUS = new Set(["done", "failed", "cancelled"]);

/**
 * 每 2 秒轮询一次任务状态，直到 done / failed / cancelled
 * @param {string} runId 任务 ID
 * @returns {{stop: () => void}} 控制器，stop() 停止轮询
 */
export function pollRunStatus(runId, options = {}) {
  const interval = options.interval ?? 2000;
  const baseUrl = options.baseUrl ?? "";      // 与后端同源时留空
  let timer = null;
  let stopped = false;

  const stop = () => {
    stopped = true;
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  };

  async function tick() {
    if (stopped) return;
    try {
      const resp = await fetch(`${baseUrl}/api/runs/${encodeURIComponent(runId)}/status`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const status = await resp.json();

      options.onProgress?.(status);
      if (TERMINAL_STATUS.has(status.status)) {
        stop();
        options.onFinish?.(status);
        return;
      }
    } catch (err) {
      // 单次网络抖动不终止轮询，交给下一轮自愈
      options.onError?.(err);
    }
    if (!stopped) timer = setTimeout(tick, interval);
  }

  tick();
  return { stop };
}

/**
 * 请求取消任务：后端只置标记，下一条用例处理前中止
 * @returns {Promise<object>} { run_id, status, cancel_requested }
 */
export async function cancelRun(runId, baseUrl = "") {
  const resp = await fetch(`${baseUrl}/api/runs/${encodeURIComponent(runId)}/cancel`,
                           { method: "POST" });
  const body = await resp.json();
  if (!resp.ok) throw new Error(body.message || `HTTP ${resp.status}`);
  return body;
}
