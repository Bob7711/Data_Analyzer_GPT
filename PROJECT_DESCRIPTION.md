# Project Description: AutoGen Data Analyzer GPT

## 1. What the project does

Data Analyzer GPT is an AI data analyst. You upload a CSV file and ask a question in plain English, such as *"Which region has the highest revenue and how does it trend by month?"*. A team of AI agents built with **Microsoft AutoGen** then:

1. loads and profiles the data,
2. cleans it,
3. creates useful new columns (features),
4. computes the statistics that answer your question,
5. draws charts, and
6. writes a final Markdown report.

The agents do not guess the numbers. They **write Python code**, a separate **Code Executor** runs it, and they read the real output. If the code fails, the agent sees the error and fixes it.

**Tech stack**

| Part | Technology |
|------|-----------|
| Agent framework | Microsoft AutoGen 0.7 (`autogen-agentchat`, `autogen-ext`) |
| Language model | OpenAI `gpt-4o-mini` (configurable) |
| Code execution | Docker container `amancevice/pandas:2.2.2`, or a local Python subprocess |
| Data and charts | pandas, matplotlib, seaborn |
| User interface | Streamlit (web chat) plus a command-line runner |

---

## 2. How it works end to end

```
 User
  │  uploads CSV + types a question
  ▼
 app.py (Streamlit UI)  ──or──  main.py (terminal)
  │  calls run_analysis()
  ▼
 data_analyzer/pipeline.py
  │  1. creates a run folder  temp/<id>/  and copies the CSV there as data.csv
  │  2. creates the code executor           (executor.py)
  │  3. creates the OpenAI model client
  │  4. builds the agent team               (team.py + prompts.py)
  │  5. streams every agent message back to the UI
  ▼
 AutoGen team
  ┌───────────────────────────────────────────────────────────┐
  │ DataLoader → DataCleaner → FeatureEngineer → DataAnalyzer │
  │          → Visualizer → ReportGenerator                   │
  │     each agent ⇄ CodeExecutor (runs its Python code)      │
  └───────────────────────────────────────────────────────────┘
  │
  ▼
 Final report + PNG charts shown in the chat, with a report download
```

The agents pass work to each other through **files** in the run folder, because every code block runs in a fresh Python process:

```
data.csv ──DataCleaner──▶ cleaned.csv ──FeatureEngineer──▶ features.csv ──Visualizer──▶ plot_*.png
```

---

## 3. Folder structure

```
ai_ChatBot/
├── app.py                    Streamlit web interface
├── main.py                   Command-line runner
├── requirements.txt          Python dependencies
├── .env.example              Template for settings (API key, model, …)
├── .gitignore                Files git should ignore
├── README.md                 Quick start guide
├── PROJECT_DESCRIPTION.md    This document
├── sample_data/
│   └── sales.csv             Deliberately messy demo dataset
├── temp/                     One sub-folder per analysis run (created automatically)
└── data_analyzer/            The core package
    ├── __init__.py
    ├── config.py
    ├── prompts.py
    ├── executor.py
    ├── team.py
    └── pipeline.py
```

---

## 4. The modules, one by one

### 4.1 `data_analyzer/config.py`: settings

**Purpose:** holds every configurable value in one place.

It loads the `.env` file with `python-dotenv` and exposes a `settings` object, built from the `Settings` dataclass, that the other modules import.

| Setting | `.env` variable | Default | Meaning |
|---------|-----------------|---------|---------|
| `openai_api_key` | `OPENAI_API_KEY` | – | Your OpenAI key |
| `model` | `OPENAI_MODEL` | `gpt-4o-mini` | Model used by all agents |
| `executor` | `CODE_EXECUTOR` | `auto` | `auto`, `docker` or `local` |
| `docker_image` | `DOCKER_IMAGE` | `amancevice/pandas:2.2.2` | Image used for Docker execution |
| `code_timeout` | `CODE_TIMEOUT` | `120` | Seconds a single code block may run |
| `work_root` | `WORK_DIR` | `temp` | Where run folders are created |
| `max_messages` | `MAX_MESSAGES` | `80` | Safety limit on messages per run |

---

### 4.2 `data_analyzer/prompts.py`: agent instructions

**Purpose:** contains the **system prompt** (role description) for every agent. Changing an agent's behaviour usually means editing only this file.

- **`CODE_RULES`**: shared rules added to every agent that writes code:
  - use relative paths, because the dataset is `data.csv` in the working directory;
  - put one complete code block per message, since nothing persists between runs except files;
  - `print()` results, because the agent only sees console output;
  - save charts with `plt.savefig()` and never call `plt.show()`;
  - after the executor replies, send corrected code if it failed, or a **plain-text summary with no code** if it succeeded. A message without code tells the system the stage is finished.
- **`DATA_LOADER`**: profile the data (shape, dtypes, head, missing values, duplicates, describe).
- **`DATA_CLEANER`**: remove duplicates, fix types, trim text, handle missing values, flag outliers, save `cleaned.csv`.
- **`FEATURE_ENGINEER`**: add helpful columns (date parts, ratios, bins) and save `features.csv`.
- **`DATA_ANALYZER`**: answer the question with numbers (group-bys, trends, correlations, rankings).
- **`VISUALIZER`**: create 2–4 labelled charts saved as `plot_<n>_<name>.png`.
- **`REPORT_GENERATOR`**: write no code, only the final Markdown report with fixed sections (Answer, Dataset Overview, Data Cleaning, Key Findings, Visualizations, Recommendations).
- **`QUICK_ANALYST`**: a single all-in-one analyst for Quick mode that ends with the word `TERMINATE`.

---

### 4.3 `data_analyzer/executor.py`: where the code runs

**Purpose:** creates the **code executor**, the component that actually runs the Python the agents write.

| Function | What it does |
|----------|--------------|
| `docker_available()` | Pings the Docker daemon and returns `True` or `False`. |
| `resolve_mode(mode)` | Turns `auto` into `docker` (if Docker is running) or `local`, and rejects unknown values. |
| `create_executor(work_dir, mode)` | Returns a `DockerCommandLineCodeExecutor` (sandboxed container) or a `LocalCommandLineCodeExecutor` (subprocess on your PC). Both use the run folder as their working directory. |
| `prepare_executor(executor, mode)` | Starts the executor. In Docker it also runs `pip install matplotlib seaborn`, because the pandas image doesn't include them. |

It also sets `MPLBACKEND=Agg` so charts are drawn without opening windows.

> **Security note:** local mode runs AI-generated code directly on your machine. Docker is safer because the code runs inside an isolated container.

---

### 4.4 `data_analyzer/team.py`: the agent teams

**Purpose:** creates the AutoGen agents and wires them into a team. This is the "orchestration" part of the architecture diagram.

**Key definitions**

- **`PIPELINE`**: the ordered list of the six specialist agents, each with a name, a short description and a prompt from `prompts.py`.
- **`EXECUTOR_NAME = "CodeExecutor"`**: the agent that runs code.
- **`MAX_CODE_ROUNDS = 5`**: how many code/fix attempts a stage gets before the pipeline moves on.

**`pipeline_selector(thread)`: the "traffic controller"**

AutoGen calls this function to decide who speaks next. It follows fixed rules, so no extra LLM call is needed:

| Last message came from… | Next speaker |
|--------------------------|--------------|
| the user (the task) | `DataLoader` |
| a stage agent, and it contains code (and the stage has used fewer than 5 rounds) | `CodeExecutor` |
| `CodeExecutor` | back to the same stage, which fixes the error or summarises |
| a stage agent, with no code | the **next** stage in the pipeline |

**`build_full_team(model_client, executor)`: Full pipeline mode**

- Uses AutoGen's **`SelectorGroupChat`** with the six `AssistantAgent`s, the `CodeExecutorAgent` and `pipeline_selector`.
- Stops when **`ReportGenerator`** has answered (`SourceMatchTermination`) or when the message limit is reached (`MaxMessageTermination`).

**`build_quick_team(model_client, executor)`: Quick mode**

- Uses **`RoundRobinGroupChat`**: `DataAnalyzerGPT` and `CodeExecutor` simply take turns.
- Stops when the analyst writes **`TERMINATE`** (`TextMentionTermination`) or at the message limit.

---

### 4.5 `data_analyzer/pipeline.py`: running one analysis

**Purpose:** the single entry point that both the web UI and the CLI use. It prepares everything, runs the team and streams results.

**Data classes**

- **`AgentMessage(source, content)`**: one message from one agent, sent to the UI as soon as it arrives.
- **`AnalysisResult(work_dir, executor_mode, report, plots, stop_reason)`**: the final outcome of the run.

**Functions**

| Function | What it does |
|----------|--------------|
| `new_work_dir()` | Creates a unique folder such as `temp/3fa9c1d2e0/` for one run. |
| `run_analysis(csv_path, question, mode=…, …)` | An **async generator**. It copies the CSV into the run folder as `data.csv`, creates the executor and the OpenAI client, builds the Full or Quick team, sends the task, yields each `AgentMessage` as agents talk, and finally yields one `AnalysisResult`. A `finally` block always stops the executor and closes the model client, even after an error. |
| `_final_report(messages, mode)` | Picks the final report: the last code-free message from `ReportGenerator` (Full) or `DataAnalyzerGPT` (Quick), with `TERMINATE` removed. |

---

### 4.6 `data_analyzer/__init__.py`: package entry

Makes `data_analyzer` a Python package and re-exports the three names other code needs: `run_analysis`, `AgentMessage` and `AnalysisResult`.

---

### 4.7 `app.py`: Streamlit web interface

**Purpose:** the chat front end shown in the browser.

**Sidebar**
- OpenAI API key (pre-filled from `.env`) and model name.
- **Agent team**: Full pipeline or Quick.
- **Code execution**: docker or local. It shows a notice if Docker isn't running.
- **CSV upload** and a **Clear conversation** button.

**Main area**
- A **preview** of the uploaded CSV (first 20 rows).
- The **chat history** of earlier questions, kept in `st.session_state.turns`.
- A **chat input** for new questions.

**What happens when you ask a question**
1. The app checks that a CSV and an API key are present.
2. It saves the upload into a new run folder.
3. It runs `run_analysis()` with `asyncio.run()`. Each agent message appears live with its own avatar (📥 🧹 ⚙️ 📊 🖼️ 📝 🐍). Code-executor output is collapsed in an expander.
4. It shows the final report, all generated charts and a **Download report (.md)** button.
5. It saves the whole turn in session state so it stays visible after the page reruns.

**Helper functions:** `render_message()` draws one agent message, and `render_result()` draws the report, charts and download button.

---

### 4.8 `main.py`: command-line runner

**Purpose:** runs an analysis without the browser, which is useful for testing and automation.

```powershell
.\.venv\Scripts\python main.py sample_data\sales.csv "Which region grew fastest?" --mode quick
```

| Argument | Meaning |
|----------|---------|
| `csv` | Path to the CSV file |
| `question` | Your question, in quotes |
| `--mode` | `full` (default) or `quick` |
| `--executor` | `auto`, `docker` or `local` (default: value from `.env`) |

It prints every agent message, then the final report, stop reason, run folder and chart paths.

---

### 4.9 Supporting files

| File | Purpose |
|------|---------|
| `requirements.txt` | All Python packages needed (`pip install -r requirements.txt`). |
| `.env.example` | Template for settings. Copy it to `.env` and add your API key. |
| `.gitignore` | Keeps `.venv/`, `.env` (your secret key), `temp/` and caches out of git. |
| `README.md` | Short setup and run guide. |
| `sample_data/sales.csv` | 408 rows of demo sales data with deliberate problems (duplicate rows, missing prices and ratings, `N/A` in the revenue column, inconsistent region names such as `" north "`) so the cleaning stage has real work to do. |
| `temp/<run-id>/` | Created per run. It holds `data.csv`, `cleaned.csv`, `features.csv` and `plot_*.png`. |

---

## 5. Example: a Full pipeline run

Question: *"Which region has the highest revenue?"*

```
user            → task: dataset + question
DataLoader      → python: profile data.csv
CodeExecutor    → (408, 9), dtypes, 8 duplicates, 3 "N/A" in revenue …
DataLoader      → summary (no code)                 ⇒ next stage
DataCleaner     → python: clean, save cleaned.csv
CodeExecutor    → error? → DataCleaner fixes → CodeExecutor → success
DataCleaner     → summary                           ⇒ next stage
FeatureEngineer → python → CodeExecutor → summary   ⇒ next stage
DataAnalyzer    → python → CodeExecutor → summary   ⇒ next stage
Visualizer      → python → CodeExecutor → summary   ⇒ next stage
ReportGenerator → final Markdown report             ⇒ STOP
```

---

## 6. How to extend the project

| Goal | Where to change |
|------|-----------------|
| Change an agent's behaviour | Edit its prompt in `prompts.py` |
| Add a new pipeline stage | Write a prompt in `prompts.py` and add a tuple to `PIPELINE` in `team.py` at the right position |
| Use a different model | Set `OPENAI_MODEL` in `.env` or type it in the sidebar |
| Allow longer-running code | Increase `CODE_TIMEOUT` in `.env` |
| Use a different Docker image | Set `DOCKER_IMAGE` in `.env` |
| Review code before it runs | Pass an `approval_func` to `CodeExecutorAgent` in `team.py` |
