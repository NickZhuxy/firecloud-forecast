# Research — 火烧云研究板块

研究板块的产出是知识，最终目的是反哺 `predictor/rules.py`。

## 目录

- `theory/` — 原理笔记，每篇一个主题
- `notebooks/` — 探索性 Jupyter notebook，验证假设、看数据
- `人工火烧云预报速成.pdf` — 当前人工预报流程与细节规则的主要参考
- `data/` — 原始/中间数据，大文件 gitignore

## 工作流

```
读资料 / 提炼可计算的预报规则
    ↓
theory/ 新增/更新一篇笔记
    ↓
predictor/rules.py 新增 ScoringRule 或调权重
    ↓
predictor/tests/ 加单测
    ↓
apps/notebook/forecast-map.ipynb 重跑看效果
    ↓
用构造情景、历史公开资料与多数据源交叉检查
```

不再规划依靠个人长期观察积累 ML 训练集：单人采样速度和覆盖面不足以形成可用数据量。
