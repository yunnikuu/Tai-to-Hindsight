# Tai → Hindsight 数据迁移工具

Windows 中文桌面工具，把 Tai 的应用使用汇总迁移到 Hindsight 本机数据库。当前源码版本为 **v1.1.0**，使用 Python 3.12、CustomTkinter 和 SQLite。

## 功能

- 智能定位：读取常见目录、运行进程、安装登记、启动项、快捷方式及最近访问线索，记住成功选择的数据库路径。
- 文件夹扫描：支持嵌套便携目录，提供取消操作、扫描深度、时间及目录数量上限。
- Hindsight 路径识别：支持 `bootstrap.json`、`HINDSIGHT_DATA_DIR`、`active_user.json` 和多账号数据库选择。
- 可筛选的数据库候选弹窗，显示完整路径、发现来源、文件大小及修改时间。
- 日期范围、时区、应用分类、每日时长补齐和重叠处理。
- 只读来源、迁移预览、重复导入检测、事务取消、自动备份和备份恢复。

## 使用

1. 先运行一次 Hindsight，确保已有初始化的数据库。
2. 打开工具，用“智能定位”或“扫描…”找到 Tai 来源和 Hindsight 目标。也可选择数据库、程序或快捷方式。
3. 定位时可保持软件运行；**预览和迁移前完全退出 Tai、Hindsight 及托盘进程**。
4. 核对目标账号、时区和预览统计，再开始迁移。

备份与报告保存在目标数据库旁的 `tai-migration-backups` 文件夹。恢复时需要备份的同名 `.json` 校验文件；恢复会撤回备份之后整个数据库的全部变化，恢复前会额外创建安全备份。

Tai 只有小时/日汇总，导入的活动时间段是重建值，无法还原精确会话、真实窗口标题、截图或网页记录。每日补齐时长的小时分布也不代表真实发生时间。建议使用同一台电脑和记录时一致的时区。本工具只写本地数据库，不主动加入云同步队列。

## 运行源码

在仓库根目录执行：

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 launcher.py
```

使用合成数据演示（不会访问真实数据库）：

```powershell
py -3.12 launcher.py --demo
```

## 测试

```powershell
py -3.12 -m unittest discover -v
py -3.12 -m migrator --self-test "$env:TEMP\tai-hindsight-self-test.json"
```

SQLite 结构样本和演示记录用于自动验证，不包含真实用户数据。当前测试覆盖定位、小时/日汇总、时区、重复导入、跨小时重叠、事务回滚、WAL 和备份校验。

## 打包 Windows x64 EXE

在 Windows 上安装 Python 3.12，并在仓库根目录运行：

```powershell
py -3.12 -m pip install -r requirements-build.txt
.\build.ps1
```

输出：`dist/Tai-Hindsight-Migrator.exe`。便携版用户无需安装 Python。

EXE 建议作为 GitHub Release 附件发布；本仓库目录只包含源码、测试和文档。`dist/`、`build/`、数据库和缓存已加入 `.gitignore`。

## 已知问题

- v1.1.0 有用户反馈：使用 Win+D 显示桌面后应用窗口可能无法恢复。根因尚未确认，当前源码未修复该问题。
- 新弹窗尚未完成全部实际桌面视觉和窗口恢复测试。
- 结构兼容测试基于保存的 Hindsight v43、旧版 v7 样本；遇到未知必填字段时工具会拒绝写入。

## 目录

```text
migrator/             桌面界面、定位和迁移实现
migrator/fixtures/    打包演示使用的合成 SQL 样本
tests/               单元与回归测试及 SQL 样本
docs/                设计说明
licenses/            相关上游项目的许可证
launcher.py          启动入口
build.ps1            Windows 构建脚本
requirements*.txt    运行与构建依赖
```

上游来源和许可说明见 `THIRD_PARTY_NOTICES.md`。本工具独立开发，与 Tai、Hindsight 官方无隶属关系。
