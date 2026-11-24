/**
 * 对比条形图：最近两次评测的指标差异（Day 19）
 * 只画两次都采集到的指标，避免用 0 冒充缺失值。
 */
import { metricLabel } from "../assets/api.js";

export function renderCompare(element, compare) {
  const keys = Object.keys(compare.metrics || {}).filter((key) => {
    const item = compare.metrics[key];
    return item && item.current !== null && item.baseline !== null;
  });
  if (!keys.length) return null;

  const chart = echarts.init(element);
  chart.setOption({
    color: ["#2563eb", "#cbd5e1"],
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { bottom: 0, data: ["本次", "基线"] },
    grid: { left: 96, right: 28, top: 20, bottom: 36 },
    xAxis: {
      type: "value",
      min: 0,
      max: 1,
      splitLine: { lineStyle: { color: "#eef1f4" } },
      axisLabel: { color: "#6b7280" },
    },
    yAxis: {
      type: "category",
      data: keys.map(metricLabel),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: "#e6e8eb" } },
      axisLabel: { color: "#4b5563" },
    },
    series: [
      {
        name: "本次",
        type: "bar",
        barMaxWidth: 16,
        data: keys.map((key) => compare.metrics[key].current),
        label: { show: true, position: "right", formatter: (p) => Number(p.value).toFixed(4), color: "#2563eb" },
      },
      {
        name: "基线",
        type: "bar",
        barMaxWidth: 16,
        data: keys.map((key) => compare.metrics[key].baseline),
        label: { show: true, position: "right", formatter: (p) => Number(p.value).toFixed(4), color: "#94a3b8" },
      },
    ],
  });
  return chart;
}
