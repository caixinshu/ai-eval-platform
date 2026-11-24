/**
 * 分组柱状图：各分类通过率（Day 19）
 * 阈值着色：低于 70% 标红，达标标绿，读者不用看刻度就能定位重灾区。
 */
const PASS_LINE = 70;

export function renderCategory(element, categories) {
  const chart = echarts.init(element);
  chart.setOption({
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (items) => {
        const item = categories[items[0].dataIndex];
        return `${item.category}<br/>通过率 <b>${item.pass_rate}%</b>` +
               `<br/>通过 ${item.passed} / ${item.total} 条`;
      },
    },
    grid: { left: 46, right: 24, top: 34, bottom: 40 },
    xAxis: {
      type: "category",
      data: categories.map((item) => item.category),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: "#e6e8eb" } },
      axisLabel: {
        color: "#6b7280",
        interval: 0,
        rotate: categories.length > 6 ? 22 : 0,
      },
    },
    yAxis: {
      type: "value",
      max: 100,
      name: "通过率(%)",
      nameTextStyle: { color: "#6b7280" },
      splitLine: { lineStyle: { color: "#eef1f4" } },
      axisLabel: { color: "#6b7280" },
    },
    series: [{
      type: "bar",
      barMaxWidth: 46,
      data: categories.map((item) => item.pass_rate),
      itemStyle: {
        borderRadius: [4, 4, 0, 0],
        color: (params) => (params.value < PASS_LINE ? "#ef4444" : "#22c55e"),
      },
      label: { show: true, position: "top", formatter: "{c}%", color: "#4b5563" },
      markLine: {
        silent: true,
        symbol: "none",
        label: { formatter: "阈值 70%", color: "#b45309", position: "insideEndTop" },
        lineStyle: { color: "#f59e0b", type: "dashed" },
        data: [{ yAxis: PASS_LINE }],
      },
    }],
  });
  return chart;
}
