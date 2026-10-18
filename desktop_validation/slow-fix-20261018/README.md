# SWE-bench slow 测试修复验证

日期：2026-10-18。执行主机为 `desktop-pc / PC-20230218RALO`，使用独立副本
`D:\cs427-slow-fix-20261018-1410` 与 Linux 验证容器，不覆盖正在运行的实验源码。

## 修复

- SWE-bench 入口将 Typer 元数据移入 `Annotated`，Python 默认值保留为普通的
  `None`、布尔、字符串和路径，防止 `OptionInfo` 流入运行清单；`-c` 仅用于配置，
  模型类使用 `--model-class`。
- 从上游 mini-swe-agent `v1.11.1` 原样恢复 `github_issue.traj.json`，增加 Git 忽略例外和来源说明。
- 跳过/重跑测试先完成一次真实执行，再复用其 manifest；检查跳过时无额外模型调用、
  重跑时输出被更新、两次执行共用相同 manifest。原有无 manifest 旧结果保护保留。
- 增加 Python 与 CLI 两条真实本地 Git 补丁导出回归，并提供独立的 `slow-checks` 命令。

## 结果

执行：

```bash
python -m pytest tests/run/test_swebench.py tests/run/test_experiment.py tests/run/test_patch_export.py \
  -vv --tb=short -p no:cacheprovider
```

**38 passed，97.89 秒，退出码 0**，其中包含全部 **9 项 slow**。测试使用真实 Docker 环境、
公开 dummy 数据集及固定/异常模拟模型，不调用付费模型 API。

完整日志：[targeted-tests.log](targeted-tests.log)。

Ruff 检查覆盖入口、测试和部署脚本，仅报告 `swebench.py` 原有的 `RET504`
（`load_verified_instances()` 中多余的局部变量），本次新增代码没有其他诊断。
该无关风格问题保持原样。记录：[ruff-no-cache.log](ruff-no-cache.log)。

后续在台式机运行：

```powershell
python deployment/desktop_run.py checks
python deployment/desktop_run.py slow-checks
```

本记录修复的是 slow 测试的前置条件和 Python 调用入口，不构成 memory 性能提升证据。
