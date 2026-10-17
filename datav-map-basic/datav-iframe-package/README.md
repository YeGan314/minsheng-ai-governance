# chy-bjgh DataV 原生 iframe 嵌套组件（0.0.2）

这是 `@chy-bjgh/datav-iframe-component` 组件库中的零依赖 DataV protocol 2 组件，不需要 Vue、React 或其他运行时。组件入口采用 DataV 官方模板使用的构造函数导出方式，将 `index.js`、`package.json`、`readme.md` 和 `history.md` 放在同一个组件包中即可导入。

## 配置

- **系统地址**：填写 DataV 运行环境可以访问的完整 URL。
- **显示操作栏**：显示刷新按钮和可选的全屏按钮。
- **自动刷新**：按秒重新加载 iframe，最小间隔为 5 秒。
- **iframe sandbox**：默认留空。

组件也声明了 `source` 数据接口；当数据流提供 `{ "url": "https://example.com" }` 时，会更新 iframe 地址。

## 部署注意事项

DataV 所在浏览器必须能访问系统地址，被嵌套页面也不能通过 `X-Frame-Options: DENY` 或 CSP `frame-ancestors` 禁止 iframe 嵌套。
