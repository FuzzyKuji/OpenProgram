# Agent method 按固定顺序调用子函数

调用大模型（可选），按代码写死的顺序调用多个子函数。

## 适用场景

- 研究流程：调研 → 找 gap → 生成想法
- 论文流程：写初稿 → 审稿 → 修改
- 数据流程：采集 → 清洗 → 分析
- 任何步骤顺序固定的多步任务

## 设计要点

- 把流程写成一个 `Agent` method
- 按固定顺序调用多个子 `Agent` method
- 调用模型可选：不调（纯串联），或调任意多次 `llm()`（每次创建一个子节点）
- 子函数之间通过 Python 变量传递数据
- 子 method 跑在调用它的 method 的 Runtime 上，不需要逐层传 Runtime

## 示例：不调模型，纯串联

```python
from openprogram import Agent

class ExampleAgent(Agent):
    method_options = {
        'survey_pipeline': {'tool': True},
    }

    def survey_pipeline(self, task: str) -> dict:
        """执行完整研究流程：调研 → 找 gap → 生成想法。

        Args:
            task: 研究主题。

        Returns:
            包含 survey、gaps、ideas 的结果字典。
        """
        survey = survey_topic(topic=task)
        gaps = identify_gaps(survey=survey)
        ideas = generate_ideas(gaps=gaps)

        return {"survey": survey, "gaps": gaps, "ideas": ideas}

_example_agent = ExampleAgent()
survey_pipeline = _example_agent.survey_pipeline
```

## 示例：调一次模型做总结

```python
from openprogram import Agent
from openprogram.runtime.agent import llm

class ExampleAgent(Agent):
    method_options = {
        'survey_pipeline': {'tool': True},
    }

    def survey_pipeline(self, task: str) -> str:
        """执行完整研究流程并总结结果。

        Args:
            task: 研究主题。

        Returns:
            整合后的研究总结。
        """
        survey = survey_topic(topic=task)
        gaps = identify_gaps(survey=survey)
        ideas = generate_ideas(gaps=gaps)

        return llm(
            f"Survey:\n{survey}\n\n"
            f"Gaps:\n{gaps}\n\n"
            f"Ideas:\n{ideas}"
        )

_example_agent = ExampleAgent()
survey_pipeline = _example_agent.survey_pipeline
```

<div id="context-tree"></div>

## 上下文树

```
survey_pipeline
├── survey_topic       ← 第1步
├── identify_gaps      ← 第2步
└── generate_ideas     ← 第3步
```

## 步骤之间的数据传递

子函数之间通过 Python 变量传递，不需要大模型参与：

```python
survey = survey_topic(topic=task)
gaps = identify_gaps(survey=survey)
```

`survey_topic` 的返回值直接作为 `identify_gaps` 的输入参数。

## 步骤之间插入 Python 处理

```python
survey = survey_topic(topic=task)

# 中间插入普通 Python 处理
key_points = extract_key_points(survey)
filtered = [p for p in key_points if p["relevance"] > 0.5]

gaps = identify_gaps(survey="\n".join(filtered))
```

## 错误处理

```python
survey = survey_topic(topic=task)
if not survey or "error" in survey.lower():
    return {"error": "Survey failed", "survey": survey}

gaps = identify_gaps(survey=survey)
```

## 与"大模型选择调用"的区别

| | 固定顺序调用 | 大模型选择调用 |
|---|-----------|-------------|
| 谁决定调用顺序 | Python 代码 | 大模型 |
| 调用几个子函数 | 多个，全部执行 | 1个，选择执行 |
| 是否需要函数注册表 | 不需要 | 需要 |
| 灵活性 | 固定流程 | 根据任务变化 |
