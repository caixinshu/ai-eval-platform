/**
 * 雷达图：六项能力 vs 目标基线（Day 19）
 * 数值缺失（未采集该指标）时传 null，ECharts 会留空档，不伪造数据。
 */
export function renderRadar(element, indicators) {
  const chart = echarts.init(element);
  chart.setOption({
    color: ["#2563eb", "#94a3b8"],
    tooltip: {
      trigger: "item",
      formatter: (params) => {
        const values = (params.value || [])
          .map((v) => (v === null || v === undefined ? "暂无" : Number(v).toFixed(4)));
        return `${params.name}<br/>${indicators
          .map((item, i) => `${item.label}：${values[i]}`).join("<br/>")}`;
      },
    },
    legend: { bottom: 0, itemWidth: 14, itemHeight: 8 },
    radar: {
      indicator: indicators.map((item) => ({ name: item.label, max: 1 })),
      radius: "64%",
      splitNumber: 4,
      axisName: { color: "#6b7280", fontSize: 12 },
      splitLine: { lineStyle: { color: "#e6e8eb" } },
      splitArea: { areaStyle: { color: ["#fff", "#fafbfc"] } },
    },
    series: [{
      type: "radar",
      symbolSize: 4,
      data: [
        {
          name: "当前版本",
          value: indicators.map((item) => (item.value === null ? null : Number(item.value))),
          areaStyle: { opacity: 0.22 },
          lineStyle: { width: 2 },
        },
        {
          name: "目标基线",
          value: indicators.map((item) => item.target),
          lineStyle: { type: "dashed", width: 1.5 },
          areaStyle: { opacity: 0 },
        },
      ],
    }],
  });
  return chart;
}
