/**
 * 顶部导航（Day 18）
 * 各页面调用 renderNav("tasks" | "datasets" | "new-run") 自动插入，避免复制粘贴。
 */
const NAV_ITEMS = [
  { key: "datasets", href: "/pages/datasets.html", label: "数据集" },
  { key: "new-run", href: "/pages/new-run.html", label: "发起评测" },
  { key: "tasks", href: "/pages/tasks.html", label: "任务列表" },
];

export function renderNav(activeKey) {
  const links = NAV_ITEMS.map((item) => (
    `<a href="${item.href}"${item.key === activeKey ? ' class="active"' : ""}>${item.label}</a>`
  )).join("");
  document.body.insertAdjacentHTML("afterbegin", `
    <header class="topbar">
      <div class="topbar-inner">
        <a class="brand" href="/pages/tasks.html">AI 评测<span>平台</span></a>
        <nav class="nav">${links}</nav>
      </div>
    </header>
  `);
}
