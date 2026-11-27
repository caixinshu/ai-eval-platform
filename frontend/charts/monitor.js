/**
 * 线上监控图表（Day 24）
 * 三张图共用一套视觉：质量分 0-100，空桶留空，不把「没有数据」画成 0 分。
 */
const AXIS_COLOR = "#6b7280";
const LINE_COLOR = "#2f6feb";

function baseGrid(extra = {}) {
  return { left: 46, right: 24, top: 34, bottom: 42, ...extra };
}

export function renderHourly(element, hourly) {
  const chart = echarts.init(element);
  chart.setOption({
    tooltip: {
      trigger: "axis",
      formatter: (items) => {
        const item = hourly[items[0].dataIndex];
        const score = item.avg_score === null ? "无抽样" : `${item.avg_score} 分`;
        return `${item.hour}<br/>抽样均分 <b>${score}</b>` +
               `<br/>抽样 ${item.sample_count} 条 / 反馈 ${item.feedback_count} 条` +
               `<br/>差评率 ${item.bad_rate === null ? "—" : `${(item.bad_rate * 100).toFixed(1)}%`}`;
      },
    },
    grid: baseGrid(),
    xAxis: {
      type: "category",
      data: hourly.map((item) => item.hour.slice(5)),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: "#e6e8eb" } },
      axisLabel: { color: AXIS_COLOR, interval: 3 },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 100,
      name: "抽样均分",
      nameTextStyle: { color: AXIS_COLOR },
      splitLine: { lineStyle: { color: "#eef1f4" } },
      axisLabel: { color: AXIS_COLOR },
    },
    series: [{
      type: "line",
      data: hourly.map((item) => item.avg_score),
      smooth: true,
      connectNulls: false,
      symbolSize: 6,
      lineStyle: { width: 2.5, color: LINE_COLOR },
      itemStyle: { color: LINE_COLOR },
      areaStyle: { color: "rgba(47,111,235,0.08)" },
    }],
  });
  return chart;
}

export function renderIssues(element, issues) {
  const chart = echarts.init(element);
  const items = issues.items || [];
  if (!items.length) {
    return null;
  }
  chart.setOption({
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (points) => {
        const item = items[points[0].dataIndex];
        return `${item.category}<br/>${item.count} 条（${(item.share * 100).toFixed(1)}%）`;
      },
    },
    grid: baseGrid({ left: 96 }),
    xAxis: {
      type: "value",
      minInterval: 1,
      splitLine: { lineStyle: { color: "#eef1f4" } },
      axisLabel: { color: AXIS_COLOR },
    },
    yAxis: {
      type: "category",
      inverse: true,
      data: items.map((item) => item.category),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: "#e6e8eb" } },
      axisLabel: { color: AXIS_COLOR },
    },
    series: [{
      type: "bar",
      barMaxWidth: 26,
      data: items.map((item) => item.count),
      itemStyle: { color: "#f59e0b", borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: "right", color: "#4b5563" },
    }],
  });
  return chart;
}

export function renderTrend(element, trend) {
  const chart = echarts.init(element);
  chart.setOption({
    tooltip: {
      trigger: "axis",
      formatter: (items) => {
        const item = trend[items[0].dataIndex];
        const score = item.avg_score === null ? "无抽样" : `${item.avg_score} 分`;
        return `${item.date}<br/>抽样均分 <b>${score}</b><br/>抽样 ${item.sample_count} 条`;
      },
    },
    grid: baseGrid(),
    xAxis: {
      type: "category",
      data: trend.map((item) => item.date.slice(5)),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: "#e6e8eb" } },
      axisLabel: { color: AXIS_COLOR, interval: Math.max(0, Math.floor(trend.length / 8) - 1) },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 100,
      name: "抽样均分",
      nameTextStyle: { color: AXIS_COLOR },
      splitLine: { lineStyle: { color: "#eef1f4" } },
      axisLabel: { color: AXIS_COLOR },
    },
    series: [{
      type: "line",
      data: trend.map((item) => item.avg_score),
      smooth: true,
      connectNulls: false,
      symbolSize: 5,
      lineStyle: { width: 2.5, color: "#0f9d58" },
      itemStyle: { color: "#0f9d58" },
      markLine: {
        silent: true,
        symbol: "none",
        label: { formatter: "及格线 80", color: "#b45309", position: "insideEndTop" },
        lineStyle: { color: "#f59e0b", type: "dashed" },
        data: [{ yAxis: 80 }],
      },
    }],
  });
  return chart;
}
