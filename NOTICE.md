# Attribution and third-party notices

This repository is a DeepSeek Harness adapter for **iPhone Use**
(<https://github.com/zhongerxin/iPhone-use>), redistributed here as a vendored
snapshot under `vendor/iphone-use`.

- Upstream project: iPhone Use, © ZHONG XIN, MIT License (`LICENSE`).
- The snapshot is pinned in `vendor/iphone-use/UPSTREAM.json` (repository, ref,
  commit, upstream version, sync time). Run `python3 tools/sync-upstream.py
  --check` to inspect it.
- Everything outside `vendor/` is the adapter layer written for DeepSeek
  Harness: the bundle manifest, the entry plugin, the skill-provider mount, the
  preview host, and the host-difference skill.

iPhone Use itself controls a real iPhone through
[WebDriverAgent](https://github.com/appium/WebDriverAgent), which is built and
signed locally on first use with the user's own Apple developer account. No WDA
binaries are redistributed here.

Upstream also ships its own third-party notices for the widget and tooling
dependencies; see the upstream repository's `THIRD_PARTY_NOTICES.md` when you
need the full list.
