# DataV 基础地图组件

这是从 `zhfy_dump` 中剥离出的第一版独立地图组件，仅负责基础地图展示。

当前支持：

- XYZ 瓦片底图；
- 右下角矢量 / 影像底图切换；
- WMS 图层；
- 地图中心点、缩放级别和投影；
- 图层显隐与透明度；
- 地图点击事件。
- 高德地名地址搜索（GCJ-02 自动转换为 WGS84 后定位）。
- 配置图层的 WFS 属性检索，结果按“地名地址 / 图层”分 Tab 展示，并以临时矢量要素定位。
- 地图界面整体截图 PNG 下载。
- 测距、测面积绘制，支持实时结果和双击结束。
- 基础标绘：点、线、面、圆、矩形，支持连续绘制和清除。
- 缓冲查询：可绘制查询范围或点选源要素，按米设置缓冲距离，并查询指定 WFS 图层。

## 数据格式

组件通过 `data` 接收地图数据：

```json
{
  "center": [116.397, 39.916],
  "zoom": 10,
  "projection": "EPSG:4326",
  "baseLayers": [
    {
      "id": "base",
      "type": "XYZ",
      "url": "https://example.com/{z}/{x}/{y}.png",
      "visible": true
    }
  ],
  "layers": [
    {
      "id": "规划图层",
      "type": "WMS",
      "url": "https://example.com/geoserver/wms",
      "params": { "LAYERS": "workspace:layer", "TILED": true },
      "searchFields": ["地址", "标题"],
      "opacity": 0.8,
      "visible": true
    }
  ]
}
```

## 本地验证

```bash
npm install
npm run dev
```

局域网访问：

```bash
npm run dev:lan
```

启动后，本机访问 `http://localhost:8081/`；局域网其他电脑使用本机 IPv4 地址访问，例如 `http://192.168.1.100:8081/`。如果 Windows 防火墙首次询问 Node.js 网络权限，请允许专用网络访问。

## Windows x64 离线运行

项目附带的 `datav-map-basic-windows-x64-node_modules.zip` 是按 Windows x64 重新准备的依赖包，包含 `esbuild.exe` 和 Rollup 的 Windows 原生模块。不要把 macOS/Linux 机器上的 `node_modules` 压缩包直接用于 Windows。

Windows 电脑安装 Node.js 20.19+（或 22.12+）后，在项目根目录用 PowerShell 执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install-windows.ps1
npm run dev
```

脚本会将已有的 `node_modules` 改名备份为带时间戳的目录，再解压 Windows 依赖；因此可随时删除新目录并恢复旧目录。若 Windows 电脑可以访问 npm，也可以跳过压缩包，直接执行 `npm ci`，`package-lock.json` 会按当前平台安装正确的可选原生依赖。

局域网访问时，默认开发服务端口为 `8081`。如需让同一局域网其他电脑访问，应使用：

```powershell
npm run dev:lan
```

依赖包 SHA-256：`eb4a8e6dd2bfa0e8153b1d1dc11062c2faf1908c2e401467b8a3af1bccb9eac0`。

同级 `frontend` 项目的 Windows x64 依赖包为 `frontend-windows-x64-node_modules.zip`，SHA-256：`0ee2779bc760dd99a610fa9e25542d2742ab0bb459503502b74160aeedc15c36`。若目录结构保持为 `datav-map-basic` 与 `frontend` 同级，可在本目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\install-frontend-windows.ps1
Set-Location ..\frontend
npm run dev
```

地图瓦片、GeoServer 和高德服务仍需填写 Windows 电脑可访问的地址；`127.0.0.1` 只表示当前 Windows 电脑自身。项目中的 Vite 代理默认将 `/geoserver` 转发到 `127.0.0.1:8080`，如果 GeoServer 在另一台局域网电脑上，需要修改 `vite.config.ts` 中的代理目标。

生产构建：

```bash
npm run build
```

## 与 frontend 自动同步

`vite.datav.config.ts` 已配置构建钩子：每次 DataV 组件构建完成后，会自动把最新的 `widget.js` 和 `widget.css` 写入 `../frontend/public/datav-map/`。开发联调时，在 frontend 目录执行：

```bash
npm run dev:with-datav
```

该命令会同时启动 DataV 组件监听构建和 frontend 开发服务。修改 `datav-map-basic/src` 后，组件会自动重建并同步到 frontend；浏览器刷新即可看到最新版本。

注意：示例使用 OpenStreetMap 公共瓦片，仅用于验证组件是否能运行。生产环境应替换为有授权、支持 CORS 的地图服务地址。

天地图 TK 配置在项目根目录的 `.env.local`：将 `VITE_TIANDITU_KEY=请填写你的天地图tk` 改为自己的密钥，保存并重启 `npm run dev`。示例地图右下角的“矢量 / 影像”按钮会切换天地图底图和对应注记：矢量模式叠加 `cva_w`，影像模式叠加 `cia_w`。

地名搜索需要配置高德 Web 服务 API Key：

```bash
VITE_AMAP_KEY=你的高德Web服务Key npm run dev
```

WMS 图层如需参与属性搜索，在配置中增加 `searchFields`，字段名必须与 GeoServer WFS 返回的属性名一致；组件会根据 `params.LAYERS` 自动查询对应的 WFS 图层。当前示例中的民生信息、轨道线路和轨道站点已配置该能力。本地开发服务将 `/geoserver` 代理到 `127.0.0.1:8080`，避免 GeoServer 未配置 CORS 时无法查询。

点击“截图”会将当前地图界面整体保存为 PNG，包括地图、搜索栏、图层列表、工具栏和底图切换控件。

## DataV 组件交付

DataV 组件包位于 `datav-package/`，包含 DataV protocol 2 入口、配置面板定义和编译后的地图引擎。完整的配置、服务、坐标系、导入、验收和回滚说明见：[基础地图组件 DataV 开发与交付说明](../docs/基础地图组件DataV开发与交付说明.md)。
