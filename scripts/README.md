# scripts/ —— 项目工具目录

> ⚠️ **工具索引已统一到 [`docs/TOOLS.md`](../docs/TOOLS.md)**（覆盖 `quant/` · `wb_analysis/` · `scripts/` 三个目录）。
> 这里**不再重复维护**一份 —— 同一份清单写两处必然漂移。

## 这个目录放什么

项目维护类工具：清理 / 重排 / 索引 / 封存 / 健康检查 / 各类核验探针。

## 两条约定

1. **每个 `.py` 头部必须声明 `# lifecycle: reusable | maintenance | oneoff`**
   （门禁：`_tidy_scripts.py --check`；新探针用 `_tidy_scripts.py --new <名字> --serves <标的> <日期>` 生成）。
2. `oneoff` 一次性探针移入 `_oneoff/`（**保留作审计线索，不删**）；
   它服务的那一轮封存后，探针会随案卷进 `reports/<标的>/<时间戳>/_source.zip` ⇒ `_oneoff/` 回到空是正常的。

## 先跑这个

```bash
./.venv/Scripts/python.exe scripts/_health.py      # 一条命令看整个项目状态
```
