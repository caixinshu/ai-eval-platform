/**
 * 趋势折线图：同一数据集最近 5 次评测的总分（Day 19）
 * 及格线 80 用红色虚线标注，颜色语义与报告徽章一致。
 */
export function renderTrend(element, trend) {
  const chart = echarts.init(element);
  const scores = trend.map((item) => item.score);
  const lowest = Math.min(...scores, 80);
  const yMin = Math.max(0, Math.floor((lowest - 10) / 10) * 10);

  chart.setOption({
    tooltip: {
      trigger: "axis",
      formatter: (items) => {
        const point = trend[items[0].dataIndex];
        return `${point.label}<br/>${point.finished_at ? point.finished_at.replace("T", " ") : ""}` +
               `<br/>综合得分 <b>${point.score}</b>`;
      },
    },
    grid: { left: 46, right: 24, top: 30, bottom: 34 },
    xAxis: {
      type: "category",
      data: trend.map((item) => item.label),
      boundaryGap: false,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: "#e6e8eb" } },
      axisLabel: { color: "#6b7280" },
    },
    yAxis: {
      type: "value",
      min: yMin,
      max: 100,
      name: "综合得分",
      nameTextStyle: { color: "#6b7280" },
      splitLine: { lineStyle: { color: "#eef1f4" } },
      axisLabel: { color: "#6b7280" },
    },
    series: [{
      type: "line",
      smooth: true,
      symbolSize: 7,
      data: scores,
      lineStyle: { width: 3, color: "#2563eb" },
      itemStyle: { color: "#2563eb" },
      areaStyle: {
        color: {
          type: "linear", x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: "rgba(37,99,235,0.18)" },
            { offset: 1, color: "rgba(37,99,235,0.01)" },
          ],
        },
      },
      markLine: {
        silent: true,
        symbol: "none",
        label: { formatter: "及格线 80", color: "#ef4444", position: "insideEndTop" },
        lineStyle: { color: "#ef4444", type: "dashed" },
        data: [{ yAxis: 80 }],
      },
    }],
  });
  return chart;
}
