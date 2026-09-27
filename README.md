# AutoGen Data Analyzer GPT

A team of AI agents built with Microsoft AutoGen. Upload a CSV and ask a question in plain English. The agents write Python, run it, fix their own errors and return a Markdown report with charts.

```
User ─ upload CSV + question ─▶ Streamlit
                                   │
            ┌──────────── AutoGen orchestration ────────────┐
            │ DataLoader → DataCleaner → FeatureEngineer →   │
            │ DataAnalyzer → Visualizer → ReportGenerator    │
            │        ▲  code  │                             │
            │        └─ CodeExecutor (Docker or local) ◀────┘
            └───────────────────────────────────────────────┘
                                   │
                  final report + charts (temp/<run>/plot_*.png)
```

## Two agent teams

| Mode | Team | When to use |
|------|------|-------------|
| **Full pipeline** | `SelectorGroupChat` with 6 specialist agents and a `CodeExecutorAgent`. A deterministic `selector_func` sends each stage's code to the executor, returns the output to that stage so it can fix or summarise, and then moves to the next stage. The run stops when `ReportGenerator` answers. | Thorough reports |
| **Quick** | `RoundRobinGroupChat` with `DataAnalyzerGPT` and `CodeExecutor`. The run stops when the analyst says `TERMINATE`. | Fast, single questions |

Stages pass their work to each other through files: `data.csv` → `cleaned.csv` → `features.csv` → `plot_*.png`.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # then put your OPENAI_API_KEY in .env
```

### Code execution
- **Docker (recommended, sandboxed):** install Docker Desktop and start it. Code then runs in `amancevice/pandas:2.2.2`, and matplotlib and seaborn are installed in the container automatically.
- **Local:** used when Docker is not running. Agent-written code runs as a subprocess of this Python environment, so use it only with data and questions you trust.

Set `CODE_EXECUTOR=auto|docker|local` in `.env`, or pick the option in the UI.

## Run

```powershell
streamlit run app.py
# or from the terminal:
python main.py sample_data/sales.csv "Which region grew revenue fastest, and what drives it?" --mode quick
```

`sample_data/sales.csv` is a deliberately messy sales file (duplicates, missing values, `N/A` in a numeric column, inconsistent region names), so the cleaning stage has real work to do.

## Project layout

```
app.py                     Streamlit chat UI
main.py                    CLI runner
data_analyzer/
  config.py                settings from .env
  prompts.py               system prompts for every agent
  team.py                  agent definitions, pipeline selector, both teams
  executor.py              Docker/local executor factory
  pipeline.py              run_analysis(): streams messages, returns report + plots
```
