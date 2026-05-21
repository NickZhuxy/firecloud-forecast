# Research — 火烧云研究板块

研究板块的产出是知识，最终目的是反哺 `predictor/rules.py`。

## 目录

- `theory/` — 原理笔记，每篇一个主题
- `notebooks/` — 探索性 Jupyter notebook，验证假设、看数据
- `observations/log.md` — 自己的火烧云观察日志，将来用作 ML 训练集
- `data/` — 原始/中间数据，大文件 gitignore

## 工作流

```
读资料 / 观察一次火烧云
    ↓
theory/ 新增/更新一篇笔记
    ↓
predictor/rules.py 新增 ScoringRule 或调权重
    ↓
predictor/tests/ 加单测
    ↓
apps/notebook/forecast-map.ipynb 重跑看效果
    ↓
对照 observations/log.md 验证
```
