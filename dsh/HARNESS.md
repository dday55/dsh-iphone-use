# Harness 适配记录与实测

版本：本包独立递增（当前 `0.1.0`）；上游运行时固定在 `vendor/iphone-use/UPSTREAM.json`，
由 `tools/sync-upstream.py` 同步。

这个仓库把 iPhone Use 接到 DeepSeek Harness 上。iPhone Use 本身已经是标准 MCP stdio 服务、
技能是标准 `SKILL.md`，所以没有「移植」工作，只有三件事要做：把它们包成 DSH bundle、
补上 Codex 独有的宿主行为、给出可验证的证据。

实测环境：一台 iOS 真机（已签名 WDA）、DeepSeek Harness 0.2.1-rc.3。本文只记录宿主差异
与可复现的方法，不含设备标识、Apple 团队与签名信息、账户、模型、本地路径或界面内容。

## 1. 实测结果

### 1.1 协议层（不经模型，直接 stdio）

```sh
cd vendor/iphone-use
IPHONE_USE_STATE_DIR=$(mktemp -d) IPHONE_USE_ANALYTICS=0 python3 scripts/smoke_mcp.py --ready
```

```json
{"server": {"name": "iphone-use", "version": "0.3.16"}, "tools": 20, "protocol_ok": true,
 "ready": true,
 "proof": {"status_ready": true, "phone_unlocked": true, "session_usable": true,
           "foreground_resolved": true, "source_readable": true,
           "viewport_readable": true, "screenshot_readable": true},
 "image_content_returned": true}
```

`initialize` 0.057s，`tools/call pua_ready` 0.417s；服务端协商 `2025-06-18`，Harness 的 MCP
SDK 支持。

### 1.2 模型层（`dsh headless` 真跑）

装好 bundle 的 profile 里：

- 工具名：`mcp__iphone_use__pua_setup` / `pua_ready` / `pua_observe`（与 Codex 同名同前缀）
- `pua_setup(status)`：`ok=true, service.ready=true`
- `pua_ready`：`ready=true, state="ready"`，`phone_unlocked`、`session_usable` 均 true
- `pua_observe(mode="tree")`：41 个可见节点（含 tab bar 与列表项）
- 技能目录：`iphone-use`、`iphone-use-setup`、`iphone-use-harness`

### 1.3 截图（模型真看到了图）

`pua_observe(mode="screenshot")` 返回 `image` 内容块（带 `pixel_to_point` 换算比例），模型能
准确复述状态栏、导航标签和底部 tab，说明图像通道正常，没有退化成 base64 文本。

### 1.4 git 安装本身

在全新 profile 里 `dsh plugin add <repo>`（本地路径与 `git+file://` 都试过）：

- `iphone-use` 进入 `dsh.profile.bundles`
- `node_modules/` 里的副本包含 `vendor/iphone-use/server`、`skills`、`assets`、`tooling`
- 启动后工具可调、技能可加载，**没有任何路径需要手工修改**

## 2. Codex 专属 vs Harness 对等物

| 项目 | Codex | Harness | 结论 |
| --- | --- | --- | --- |
| MCP 传输 | `codex mcp add ...` | `@deepseek-ai/dsh-mcp-client` | 一致，前缀都是 `mcp__iphone_use__` |
| 插件清单 | `plugin.json` / `.mcp.json` | bundle：`package.json` + `cordis.patch.yml` | 已翻译 |
| 技能 | `skills/<name>/SKILL.md` | 同一套，额外挂一个 provider | 直接复用 |
| 用户提问 | `functions.request_user_input_async` | `ask_user_question` | 适配技能覆盖 |
| 图片转发 | `functions.exec` + `image(block)` | 直接调 MCP，图片自动进对话 | 适配技能覆盖 |
| 实时面板 | MCP App（`ui://` + widget session） | 无 MCP App 宿主，用 `dsh/preview/` 补位 | 能用，非原生 |
| 工具超时 | Codex 自带上限 | 默认 60s，需调大 | 已设 180s |
| app-only 工具 | `_meta.ui.visibility` 隐藏 | Harness 忽略该字段 | 会出现在工具表，适配技能写明不要调 |

## 3. 实时画面：默认随 bundle 启动

入口插件在激活时就在宿主进程里起一个 loopback HTTP 服务（默认 `127.0.0.1:18760`），
并注册 `iphone_preview` 工具把地址报给模型。实测 bundle 激活 1s 内 `/health` 就返回 200，
Web 构建下客户端插件会自动探测并打开右侧栏标签（`dsh/client.js`，手写为
`window.__ModuleLoader__.load` 的 factory 格式，不需要构建步骤）。

自动打开的规则（0.1.0 起：**用过 iPhone Use 的会话才打开**）：

- 触发点在宿主侧：`iphone_preview` 工具执行时用 `exec.agent.session.id` 把当前会话标记到预览
  服务（与侧边栏的 `data-row-key="session:<id>"` 是同一串）。没调用过这个工具的会话不会被标记。
- 浏览器半每 3s 问一次 `GET /health?session=<id>`；`used: true` 才放置 Browser 标签。标签已
  存在时只读 DOM（不请求）；会话没有用过就保持安静。
- 「已打开」只认 DOM：Browser 标签是真实的 `iframe`/`webview` 节点，按 URL 命中即视为该会话
  已有预览。不用「已打开」的 sessionStorage 标记，也不用 `frame_seq`（历史帧可能来自任何一次查看）。
- **关闭判定要求会话未变**：只有「标签消失」且当前会话 id 等于标签挂载时的会话 id，才记为用户
  关闭（写 `sessionStorage` 的 `dsh-iphone-use.preview-closed:<sessionId>`，本会话不再自动放，
  刷新保留，关窗口清空）。切换会话导致面板卸载时 id 已变，不会被误记成关闭。
- 会话 id 优先读侧边栏选中行的 `data-row-key="session:<id>"`，读不到才退回
  `sidebarRight.commandTarget()`——后者在切换瞬间可能仍返回旧会话。
- `openTab` 抛错（没有已 adopt 的 Session、或 Browser 类型不可用）按 1.2s 重试；放置成功但
  DOM 里没出现时按 1.2s → 2.4s → 4.8s … 30s 退避。
- **可自证**：浏览器半把 `loaded` / `placed` / `openTab-failed` / `mounted` /
  `closed-in-session` 事件 POST 到 `preview` 的 `/client-report`，`/health` 里回显为
  `client`、`client_reports`。`client === null` 就是「当前页面根本没加载 `dsh/client.js`」，
  此时预览不可能自己打开，刷新窗口才会加载。

实测（Web 构建 + 手动启用 Browser 标签、headless Chrome）：打开一个已有会话后，右侧栏自动
出现 `http://127.0.0.1:18760/` 的 Browser 标签，`/health` 从 `frame_seq=0` 变为
`frame_seq=2, frame_bytes=109100`，即预览页真的在轮询手机画面。

它背后仍是「MCP App 补位宿主」：

Codex 的预览是一个 MCP App：`assets/phone-screen.html` 用 postMessage 向宿主发
`ui/initialize`，之后轮询 `pua_screen_frame`，按钮走 `pua_screen_action`。Harness 没有
这个宿主，但协议本身是公开的，`dsh/preview/` 就实现了最小宿主：

- `host.html`：iframe 装载原版页面，回答 `ui/initialize`，把 `tools/call` 转给 HTTP
- `server.mjs`：一条 MCP stdio 连接（`pua_screen` 起流），`/rpc` 转发工具调用，`/health` 自检

实测：页面自己轮询，`frame_seq` 递增，单帧 JPEG 45–50 KB；在无头 Chrome 里验证过。

与模型的观察互不干扰；`pua_screen(action="pause")` 写的是同一份 `screen-state.json`，
所以认证接管时预览页也会暂停（前提是两边共用 `IPHONE_USE_STATE_DIR`，默认就是这样）。

预览默认开启，`config.preview: false` 可关、`config.previewPort` 可改首选端口；
端口被占时自动顺延，并只复用真正属于自己的监听（`/health` 里带 `frame_seq` 的那个）。

## 4. 沙箱：只有 CLI 从受限终端启动时才会踩

Desktop 应用不受沙箱限制，MCP 子进程能正常写 `~/.local/share/iphone-use`。

如果 `dsh` 是从 `workspace-write` 沙箱里的终端启动的，整个进程树继承沙箱，MCP 子进程会在
`Runtime.__init__` 的 `chmod ~/.local/share/iphone-use` 处退出，表现为「工具表里没有
`mcp__iphone_use__*`」。解法：把 `IPHONE_USE_STATE_DIR` 指到可写目录（复制一份
`config.json` 即可复用现有 WDA），或让 CLI 以 `danger-full-access` 运行。

## 5. 桌面端手动接入（CLI 拒绝 desktop profile 时）

应用内 Plugins 页装不上时，退回到手工两件事，效果等价：

```sh
mkdir -p ~/.dsh/skills
cp -R vendor/iphone-use/skills/iphone-use vendor/iphone-use/skills/iphone-use-setup \
      dsh/skills/iphone-use-harness ~/.dsh/skills/
```

然后在 `~/.dsh/profiles/desktop/cordis.patch.yml` 末尾追加（路径换成你的实际目录）：

```yaml
- insert:
    - id: mcp-iphone-use
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: iphone_use
        transport: stdio
        command: python3
        args: ['/ABS/dsh-iphone-use/vendor/iphone-use/server/iphone_use.py']
        cwd: '/ABS/dsh-iphone-use/vendor/iphone-use'
        toolCallTimeoutMs: 180000
```

技能走 `~/.dsh/skills` 就不用动 `skill-filesystem` 的配置——那条补丁会整段替换配置，
容易把别的技能根（比如 office）一起顶掉。

重启应用后确认工具表里有 `mcp__iphone_use__pua_setup`。

## 6. 已知限制

1. **非原生面板**：预览是本地页面 + 右侧栏 Browser 标签，不是 `sidebarRightTabs` 里的
   原生 tab。要原生需要写 DSH 客户端插件（node 半管 MCP，浏览器半管渲染）；协议已通，
   剩的是前端工程。
2. **禁用要重启**：入口插件把子插件挂在 `ctx.root`，运行中禁用 bundle 不会立刻回收
   MCP 连接。
3. **GUI 路径未在本机实测**：上面的端到端验证在 `headless` profile（没有 agent preset 层）。
   Desktop 是 `dsh-web-app` + preset；MCP 客户端按设计属于宿主层（同 `mcp-resources` 的
   共享工具），装完看一眼工具表即可确认，兜底写法见 README。
4. **技能薄适配**：`iphone-use-harness` 只覆盖宿主差异；手机操作策略、观察预算、截图兜底、
   认证接管仍读上游 `iphone-use` / `iphone-use-setup`。上游若强化 widget 描述，这里可能
   需要加一句硬覆盖。
