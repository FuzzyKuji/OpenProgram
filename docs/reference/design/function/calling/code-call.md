# Agent method Calling Sub-Functions in a Fixed Order

Optionally calls the LLM, then invokes multiple sub-functions in the order hard-coded in the source.

## Use Cases

- Research flow: survey → find gap → generate ideas
- Paper flow: write draft → review → revise
- Data flow: collect → clean → analyze
- Any multi-step task with a fixed step order

## Design Points

- Write the flow as an `Agent` method
- Call multiple sub-`Agent` methods in a fixed order
- Calling the model is optional: don't call it (pure chaining), or call `llm()` any number of times (each call creates a child node)
- Data is passed between sub-functions through Python variables
- Sub-methods run on the Runtime of the calling method; nothing passes a Runtime along

## Example: No Model Call, Pure Chaining

```python
from openprogram import Agent

class ExampleAgent(Agent):
    method_options = {
        'survey_pipeline': {'tool': True},
    }

    def survey_pipeline(self, task: str) -> dict:
        """Run the full research flow: survey → find gap → generate ideas.

        Args:
            task: Research topic.

        Returns:
            A result dict containing survey, gaps, and ideas.
        """
        survey = survey_topic(topic=task)
        gaps = identify_gaps(survey=survey)
        ideas = generate_ideas(gaps=gaps)

        return {"survey": survey, "gaps": gaps, "ideas": ideas}

_example_agent = ExampleAgent()
survey_pipeline = _example_agent.survey_pipeline
```

## Example: Calling the Model Once to Summarize

```python
from openprogram import Agent
from openprogram.runtime.agent import llm

class ExampleAgent(Agent):
    method_options = {
        'survey_pipeline': {'tool': True},
    }

    def survey_pipeline(self, task: str) -> str:
        """Run the full research flow and summarize the result.

        Args:
            task: Research topic.

        Returns:
            The consolidated research summary.
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

## Context Tree

```
survey_pipeline
├── survey_topic       ← step 1
├── identify_gaps      ← step 2
└── generate_ideas     ← step 3
```

## Passing Data Between Steps

Data is passed between sub-functions through Python variables, with no LLM involvement:

```python
survey = survey_topic(topic=task)
gaps = identify_gaps(survey=survey)
```

The return value of `survey_topic` is used directly as the input argument to `identify_gaps`.

## Inserting Python Processing Between Steps

```python
survey = survey_topic(topic=task)

# Insert ordinary Python processing in between
key_points = extract_key_points(survey)
filtered = [p for p in key_points if p["relevance"] > 0.5]

gaps = identify_gaps(survey="\n".join(filtered))
```

## Error Handling

```python
survey = survey_topic(topic=task)
if not survey or "error" in survey.lower():
    return {"error": "Survey failed", "survey": survey}

gaps = identify_gaps(survey=survey)
```

## Difference from "LLM-Chosen Calls"

| | Fixed-order calls | LLM-chosen calls |
|---|-----------|-------------|
| Who decides the call order | Python code | The LLM |
| How many sub-functions are called | Multiple, all executed | One, chosen to execute |
| Whether a function registry is required | Not required | Required |
| Flexibility | Fixed flow | Varies with the task |
