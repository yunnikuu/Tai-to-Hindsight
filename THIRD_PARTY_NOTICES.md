# 上游来源说明

本项目的数据格式适配与 SQL 测试样本参考了以下本地保存的上游源码：

- Tai：`Planshit/Tai`，MIT License，Copyright (c) 2022 Plan shit。许可全文见 `licenses/LICENSE-Tai.txt`。
- Hindsight：`Tomotsugu-dev/Hindsight`，MIT License，Copyright (c) 2026 Tomotsugu。许可全文见 `licenses/LICENSE-Hindsight.txt`。

`migrator/fixtures/` 与 `tests/fixtures/` 中的 SQL 结构用于迁移兼容性验证；Tai 示例应用记录为合成测试数据。本目录不包含上游完整代码仓库。

运行依赖见 `requirements.txt`，构建依赖见 `requirements-build.txt`；各依赖保留其自身的许可。本项目源码的发布许可尚未指定，这些上游许可并不代替项目作者选择源码许可。
