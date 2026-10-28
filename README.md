# dsh-iphone-use

用 **DeepSeek Harness** 通过 USB 操作真实 iPhone —— [iPhone Use](https://github.com/zhongerxin/iPhone-use) 的 Harness 适配包。

助手能打开 App、读页面、点击、滚动、输入、采集列表；模型自己看图判断界面，右侧栏还能显示实时手机画面。
底层仍是同一个 Python MCP 服务（20 个 `pua_*` 工具）、同一套技能、同一个 WebDriverAgent 通道；
本仓库只补 Harness 需要的那一层，并把上游运行时固定快照在 `vendor/iphone-use`，安装不依赖上游改动。

## 安装

```sh
dsh plugin --profile <profile> add https://github.com/dday55/dsh-iphone-use.git
```

`<profile>` 换成你在用的（headless / web / tui …）。桌面端在应用内 **Plugins** 页安装同一地址
（`desktop` profile 由应用独占，CLI 不能写）。

升级是卸载后重装（git 依赖锁在安装时的 commit，插件页没有更新按钮）：

```sh
dsh plugin --profile <profile> remove dsh-iphone-use
dsh plugin --profile <profile> add https://github.com/dday55/dsh-iphone-use.git
```

装好后得到：

| | 内容 |
| --- | --- |
| MCP 工具 | 20 个 `mcp__iphone_use__pua_*`：观察、查找、点击、滑动、输入、按键、启动 App、批量、列表采集、会话状态 |
| 预览工具 | `iphone_preview`：为当前会话启用预览并返回地址，不碰手机 |
| 技能 | `iphone-use`、`iphone-use-setup`、`iphone-use-harness` |
| 实时画面 | 用过 iPhone Use 的会话会在右侧栏自动出现 Browser 标签 |
| 超时 | 单次工具调用 180s（默认 60s 对手机动作太短） |

## 实时画面

预览服务随 bundle 启动在 `http://127.0.0.1:18760`，但**只有用过 iPhone Use 的会话**才会在右侧栏
自动出现 Browser 标签：模型在手机 READY 后调用 `iphone_preview` 时标记当前会话，客户端每 3 秒问一次
宿主"这个会话用过吗"，用过才放标签。没碰过手机的会话不会出现预览。

同一个会话里手动关掉后不会再自动重开（按会话 id 记住，刷新保持）；关掉浏览器窗口或重启应用后
记忆清空。画面带机型、Live 状态、刷新/主屏幕/截图按钮、点击光标、认证暂停遮罩。

- **桌面端装完/更新插件要完全退出应用再打开**（⌘Q；窗口红叉只是隐藏窗口，页面不会重新加载，而打包版没有「刷新页面」菜单）。
- 端口被占用会自动顺延（18761…），`iphone_preview` 返回实际地址。
- Web profile 默认关闭 Browser 标签，需要时在 profile patch 加 `- id: ui-sidebar-browser` / `disabled: false`；Desktop 默认开启。
- 关掉预览：`- id: iphone-use` → `config: { preview: false }`；换首选端口用 `previewPort`。
- 手工单跑：`node dsh/preview/server.mjs`。

模型侧不受影响：它始终用 `pua_observe(mode="screenshot")` 自己看图；预览页和它共用
`screen-state.json`，所以模型认证接管暂停时，预览会同步盖上遮罩。

## 首次配置

第一次使用按 `iphone-use-setup` 技能，用**你自己的** Apple 账号和开发团队签名、编译并启动手机端
WebDriverAgent。已装过 Codex 版 iPhone Use 的机器会复用 `~/.local/share/iphone-use` 的配置与构建，
不重复编译；两边共用操作锁，不会同时操作手机。

依赖：macOS + DeepSeek Harness、完整 Xcode（仅 Command Line Tools 不够）、可用的 Apple 开发团队、
USB 连接的 iPhone（信任此 Mac、开发者模式、安装期间解锁）、Python 3.9+、Node 20.19+/22.12+/24+。

## 技能

`iphone-use`（操作策略：乐观执行、观察预算、截图兜底、认证接管）、`iphone-use-setup`（WDA 安装与恢复）、
`iphone-use-harness`（**宿主差异层**：没有 `functions.exec`、没有侧栏 widget 协议、提问用
`ask_user_question`）。前两个直接来自上游，所以上游更新技能时不需要 fork 整份内容。

## 结构

```
package.json                 # DSH bundle 清单：dsh.bundle.patch -> dsh/cordis.patch.yml
dsh/lib/index.js             # 入口插件：挂 MCP 客户端 + 技能提供者 + 自动预览
dsh/client.js                # 浏览器半：把预览标签放进右侧栏
dsh/preview/                 # MCP App 补位宿主（iframe + ui/initialize + tools/call）
dsh/skills/iphone-use-harness/SKILL.md
vendor/iphone-use/           # 上游快照 + UPSTREAM.json（commit / 版本）
tools/sync-upstream.py       # 更新快照或 --check
```

细节、实测记录与踩坑见 [dsh/HARNESS.md](dsh/HARNESS.md)。更新上游：

```sh
python3 tools/sync-upstream.py --ref v0.3.17   # 或 --source <本地克隆>；--check 校验
```

## 已知限制

- 预览是「本地页面 + 右侧栏 Browser 标签」，不是会话内原生面板。
- 运行中禁用 bundle 不会立刻回收 MCP 连接，重启后生效。
- `iphone-use-harness` 是薄适配；上游若强化 widget 描述，可能需要补一句硬覆盖。

## 许可

适配层 MIT。`vendor/iphone-use` 来自 [iPhone Use](https://github.com/zhongerxin/iPhone-use)
（© ZHONG XIN，MIT），见 [LICENSE](LICENSE) 与 [NOTICE.md](NOTICE.md)。WDA 在首次使用时用你自己的
Apple 账号在本机构建签名，本仓库不分发任何 WDA 二进制。
