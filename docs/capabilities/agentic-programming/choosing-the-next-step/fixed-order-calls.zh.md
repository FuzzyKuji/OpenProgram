# 固定顺序调用

在按 Python 中硬编码的顺序调用多个子函数的同时，（可选地）调用 LLM。

## 适用场景

- 研究流水线：调研 → 找差距 → 生成想法
- 论文流水线：起草 → 评审 → 修改
- 数据流水线：采集 → 清洗 → 分析
- 任何步骤顺序事先已知的多步任务

## 设计要点

- 编排函数写成普通的 `Agent` method
- 按固定顺序调用多个子 `Agent` method
- `llm()` 是可选的：可以跳过它（纯链式调用），也可以多次调用它
  （每次调用都会创建一个 `llm` 子节点）
- 数据通过普通 Python 变量在子函数之间流动
- 子 method 沿用调用方的 Runtime，步骤之间不传 `runtime` 参数
- 一个函数既可以多次调用 `llm()`，也可以调用任意多个其他
  `Agent` method

## 示例：不调用 LLM，纯链式调用

```python
from openprogram import Agent
from openprogram.runtime.agent import llm

class ExampleAgent(Agent):
    method_options = {
        'survey_pipeline': {'tool': True, 'input': {'task': {'description': 'Research topic.'}}},
    }

    def survey_pipeline(self, task: str) -> dict:
        """Run the full research pipeline: survey, find gaps, generate ideas."""
        survey = survey_topic(topic=task)
        gaps = identify_gaps(survey=survey)
        ideas = generate_ideas(gaps=gaps)

        return {"survey": survey, "gaps": gaps, "ideas": ideas}

_example_agent = ExampleAgent()
survey_pipeline = _example_agent.survey_pipeline
```

## 示例：用一次 `llm()` 调用做汇总

```python
from openprogram import Agent
from openprogram.runtime.agent import llm

class ExampleAgent(Agent):
    method_options = {
        'survey_pipeline': {'tool': True, 'input': {'task': {'description': 'Research topic.'}}},
    }

    def survey_pipeline(self, task: str) -> str:
        """Run the full research pipeline and summarise the results."""
        survey = survey_topic(topic=task)
        gaps = identify_gaps(survey=survey)
        ideas = generate_ideas(gaps=gaps)

        return llm([
            {"type": "text", "text": (
                f"Survey:\n{survey}\n\n"
                f"Gaps:\n{gaps}\n\n"
                f"Ideas:\n{ideas}"
            )},
        ])

_example_agent = ExampleAgent()
survey_pipeline = _example_agent.survey_pipeline
```

## 会话 DAG

每次调用是一个节点；`caller` 边指向编排函数：

```
survey_pipeline
├── survey_topic       ← step 1
├── identify_gaps      ← step 2
└── generate_ideas     ← step 3
```

## 在步骤之间传递数据

子函数通过 Python 变量彼此交接数据 —— 不涉及任何 LLM：

```python
survey = survey_topic(topic=task)
gaps = identify_gaps(survey=survey)
```

`survey_topic` 的返回值直接作为 `identify_gaps` 的输入参数传入。

## 在步骤之间插入 Python 处理逻辑

```python
survey = survey_topic(topic=task)

# 中间穿插普通的 Python 处理
key_points = extract_key_points(survey)
filtered = [p for p in key_points if p["relevance"] > 0.5]

gaps = identify_gaps(survey="\n".join(filtered))
```

## 错误处理

主要机制是异常传播：当子函数抛出异常时，其 DAG 节点会以
`status='error'` 记录，异常重新抛回到编排器中。在那里用普通的
`try/except` 捕获它：

```python
try:
    survey = survey_topic(topic=task)
except Exception as e:
    return {"error": f"Survey failed: {e}"}

gaps = identify_gaps(survey=survey)
```

或者，如果子函数以带内方式上报失败（返回错误字符串而非抛出异常），
则检查其返回值：

```python
survey = survey_topic(topic=task)
if not survey or "error" in survey.lower():
    return {"error": "Survey failed", "survey": survey}

gaps = identify_gaps(survey=survey)
```

## 与“由 LLM 选择调用”的对比

| | 固定顺序调用 | [工具调用](tool-calling.zh.md) / [下一步决策](next-step-decision.zh.md) |
|---|-----------|-------------|
| 由谁决定调用顺序 | Python 代码 | LLM |
| 运行多少个子函数 | 若干个，全部运行 | 工具循环：跨多轮运行多个；决策菜单：仅一个 |
| 灵活性 | 固定流水线 | 随任务而变 |
