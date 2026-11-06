# 纯 Python

## 何时使用

任务是纯确定性逻辑，不需要 LLM 推理。例如：
- 字数统计
- 文件读取 / 写入
- 数据格式转换
- 数学运算

## 设计要点

- **不要**使用 `Agent` method 装饰器
- **不要**调用 `llm()`
- 不需要 `runtime` 参数
- 使用标准的 Google 风格 docstring

## 示例

```python
def word_count(text: str) -> int:
    """Count the number of words in a text.

    Args:
        text: Input text.

    Returns:
        The word count.
    """
    return len(text.split())
```

```python
def extract_emails(text: str) -> list[str]:
    """Extract every email address from a text.

    Args:
        text: Input text.

    Returns:
        List of email addresses.
    """
    import re
    return re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)
```

## Session DAG

受管 Program 源码内的普通帮助函数与普通 Agent 方法自动具有调用作用域。任意宿主函数不自动采集源码。是否确定性不决定该调用是否出现在 DAG 中。

确定性帮助函数属于已记录 workflow 时，使用普通 Agent 方法，无需模型请求或工具登记。只有允许模型调用时才设置 `tool=True`。

```python
from openprogram import Agent

class TextAgent(Agent):
    def word_count(self, text: str) -> int:
        """Count words."""
        return len(text.split())
```

## 确定性操作与模型操作

| 操作 | 实现 |
|---|---|
| 固定算法、格式转换、计数 | 普通 Python 帮助函数或 Agent 方法 |
| 自然语言生成、分类、推理 | 显式 `agent()` 或 `self(...)` 模型请求 |
