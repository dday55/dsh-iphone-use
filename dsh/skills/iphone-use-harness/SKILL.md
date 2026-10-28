---
name: iphone-use-harness
description: DeepSeek Harness（DSH）里使用 iPhone Use 的宿主适配层：覆盖 iphone-use 技能中 Codex 专属的 widget/侧边栏、functions.exec 图片转发和 request_user_input_async 提问方式；手机操作流程仍以 iphone-use 技能为准。涉及 pua_* 工具、看图、用户接管或 MCP 启动失败时先读本技能。
whenToUse: 任务涉及用 pua_* MCP 工具操作真实 iPhone，或需要判断 Harness 下如何看手机画面、如何请用户接管、MCP 服务起不来时。
---

# iPhone Use 在 Harness 下的宿主差异

本文件只写 Codex 与 Harness 不同、且会改变做法的地方。手机任务的目标、乐观执行、观察预算、截图兜底、认证接管等内容仍按 `iphone-use` 与 `iphone-use-setup` 技能执行，本文件优先于其中与宿主有关的说法。

## 1. 工具直接可调，没有 functions.exec

工具名固定为 `mcp__iphone_use__pua_*`，例如 `mcp__iphone_use__pua_setup`、`mcp__iphone_use__pua_ready`、`mcp__iphone_use__pua_observe`。直接调用即可，不需要也不存在 `functions.exec` 或 `tools.mcp__iphone_use__*` 这层包装。

截图的图片块由 Harness 直接转给模型：MCP 返回的 `image` 内容会按序进入对话。不要自己把结果转成 base64 文本，也不要为了“转发图片”写脚本。

## 2. 没有 MCP App 侧边栏，屏幕用截图看

Harness 不渲染 MCP App（`ui://` 资源）面板，因此：

- 不要调用 `pua_screen_frame`、`pua_screen_action`。它们是给前端预览页面内部轮询与触控用的，模型不需要也不应直接调用它们。
- 需要看手机画面时用 `pua_observe(mode="screenshot")`（或 `mode="both"`）；需要判断界面异常时同样先看这张图。
- `pua_ready` 返回里的 `preview` 字段是预览状态，不是模型观察；不要因为 `preview` 为空或 `paused` 去恢复通道。
- 实时画面服务随 bundle 启动（默认 `http://127.0.0.1:18760`），**只要这个会话调用过任意 `pua_*` 工具**，右侧栏就会自动出现 Browser 标签（宿主在 `tools/execute` 里按会话标记，不依赖模型记得额外调用）。`iphone_preview` 只是取地址与自检用的辅助工具，不是触发开关；用户说没看到时调用一次确认即可。那是给人看的，不改变模型的观察方式；两边共用 `screen-state.json`，所以 `pua_screen(action="pause")` 会让预览同时盖上暂停遮罩。
- `iphone_preview` 只报告地址和运行状态，不碰手机。它返回 `running=false` 时，把 `note` 里的原因告诉用户；确实需要手工兜底时才用 `node dsh/preview/server.mjs`。
- READY 可能仍会在后台启动 MJPEG 预览流（无人消费）。这不影响操作；若与 Codex 的预览抢流，按下一步实际观察到的截图为准，不必反复重开。

## 3. 请用户接管用 ask_user_question

App 密码或 Face ID 等安全场景需要用户接管时：
1. 先调用一次 `pua_screen(action="pause")`，使右侧栏的实时预览同步盖上隐私遮罩，避免敏感信息外露；
2. 用 `ask_user_question` 提问：一次一个问题，选项写进 `options`，首个选项固定「已完成继续」，第二个可为「暂时无法完成」；
3. 暂停所有手机操作与截图，等待用户在真机上操作；异步返回、预选或超时都不是用户答复；
4. 收到用户实际选择「已完成继续」后，调用一次 `pua_screen(action="resume")` 恢复预览，再取新观察（`pua_observe`）继续任务。

## 4. MCP 起不来时先看是不是沙箱

如果工具列表里没有 `mcp__iphone_use__*`，或工具报 `server is disconnected`，先看宿主是怎么启动的：

- Desktop 应用本身不受沙箱限制，MCP 子进程可直接写 `~/.local/share/iphone-use`，与 Codex 共用同一份配置、构建和操作锁。
- 若 Harness 是 CLI 且运行在 `workspace-write` 沙箱里（例如从受限终端启动），MCP 子进程也会被同一沙箱约束，表现为启动即退出、stderr 有 `PermissionError: … ~/.local/share/iphone-use`。此时给 MCP 行设置 `IPHONE_USE_STATE_DIR` 指向可写目录，或以 `danger-full-access` 启动。

同一部手机被 Codex 与 Harness 同时使用时，按 `device_busy` 提示等待，不要重试抢占。

## 5. 本会话 READY 仍然必须

以上差异不改变 PUA 的会话语义：本对话首次操作手机前仍先 `pua_setup(action="status")`，再 `pua_ready(recover=true, screenshot=false)`，只有 `ready=true, state="ready"` 才继续任务，并复用 READY 返回的 `observation`。
