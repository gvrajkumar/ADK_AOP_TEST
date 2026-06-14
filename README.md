# Decoupled Agentic SOP Search & Execution Platform

An enterprise-ready orchestration platform built on **Google Agent Development Kit (ADK) 2.x** and **OpenAI GPT-5.5**. It introduces a **decoupled architecture** separating business logic (SOPs) from technical backend services (LOB integrations), backed by declarative **telemetry**, **cost budgeting**, and **explainability guardrails**.

---

## 🏛️ Architecture Overview

The platform is divided into three completely decoupled components:

1. **Knowledge Management (KM) Team**:
   * Authors procedural workflows in human-readable YAML graphs ([`workflow.yaml`](lost-card-replacement/assets/workflow.yaml)) and standard markdown files ([`SKILL.md`](lost-card-replacement/SKILL.md)).
   * References abstract capabilities (e.g., `freeze_card`) without knowing concrete technical parameter names or code functions.

2. **Line of Business (LOB) Engineering Team**:
   * Builds concrete API functions and database handlers ([`tools_registry.py`](tools_registry.py)).
   * Maps abstract capabilities to concrete functions via the `CAPABILITY_BINDINGS` registry on-the-fly, allowing backend upgrades without changing the SOP YAML files.

3. **Harness Platform (Core Orchestrator)**:
   * **Semantic Search Store** ([`sop_store.py`](sop_store.py)): Performs capability-aware searches, ensuring returned SOPs only require tools that the calling agent supports.
   * **Stateful Run Controller** ([`harness.py`](harness.py)): Validates preconditions, executes graph steps, delegates cognitive diagnostics to an ADK Agent, handles human override approvals, and guarantees transaction-level rollback on failures.

---

## 🛡️ Guardrails & Telemetry Engine

To ensure safe deployment in corporate environments, the Harness implements three runtime guardrails:

* **Global Cost Budget Gating**: Enforces a `max_workflow_cost_usd` cap. Accumulates LLM token costs across steps and aborts execution immediately if the budget is breached.
* **Step Latency Gating**: Monitors the duration of each step and issues alerts if execution times exceed `alert_on_latency_ms`.
* **Explainability Audit Trails**: Captures the ADK Agent’s cognitive reasoning paths (thought streams) during diagnostic steps, logging justifications and automatically injecting them into the Human-In-The-Loop review context.

---

## 📁 Repository Structure

```text
ADK_AOP_TEST/
├── lost-card-replacement/
│   ├── SKILL.md                 # Declarative skill metadata & allowed tools
│   └── assets/
│       └── workflow.yaml        # Executable SOP step graph & guardrails
├── harness.py                   # Stateful Harness Orchestrator
├── tools_registry.py            # LOB concrete services & parameter bindings
├── sop_store.py                 # Keyword/Capability search store
├── models.py                    # Pydantic schemas for step configuration
├── main.py                      # Interactive CLI verification driver
├── technical_design.html        # Interactive, premium HTML design document
├── requirements.txt             # Project dependencies
└── README.md                    # Project documentation
```

---

## 🚀 Setup & Execution

### Prerequisites
* Python 3.10 or higher
* Active OpenAI API Key (configured for the `gpt-5.5` model routing or falling back to local mocks if omitted)

### 1. Installation
Clone the repository and install the dependencies inside a virtual environment:

```bash
# Navigate to project folder
cd ADK_AOP_TEST

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration
Create a `.env` file in the root directory:

```env
OPENAI_API_KEY=your-api-key-here
OPENAI_MODEL=gpt-5.5
```
*(Note: If `OPENAI_API_KEY` is omitted, the Harness automatically activates a high-fidelity local `MockLlm` simulating the ADK agent's planning and transaction tool calls.)*

### 3. Running the Verification CLI
Execute the runner to simulate scenario tests:

```bash
python main.py
```

#### What the driver will verify:
* **Test 1**: Searches the SOP store for `"replace lost card"` matching agent capabilities.
* **Test 2 (Jane Doe)**: Runs a successful card replacement workflow. An ADK Agent performs transaction analysis, detects no anomalies, bypasses gates, freezes the card, and orders the replacement.
* **Test 3 (John Smith)**: Analyzes suspicious transactions (ATM withdrawal in Paris, foreign transfer, Russian IP access). The Harness halts at the **Human-In-The-Loop Gate**, displaying the agent's explanation and prompting the manager for approval. Upon order placement connection failure, the Harness executes transaction-level **Rollback**, restoring the card back to `ACTIVE`.
* **Test 4 (LOB Migration)**: Simulates upgrading a backend endpoint from version v1 to v3 (renaming parameter `card_num` to `technical_card_no`). Executes the card replacement successfully using dynamic parameter bindings while keeping the KM YAML file 100% unchanged.

---

## 📊 Interactive Design Document

For a premium visual walkthrough, open [`technical_design.html`](technical_design.html) in your browser. This custom design document features:
* Sleek dark mode styling and Outfit typography.
* Three interactive SVG diagrams (System Flow, Binding Registry, and Guardrails Flowchart).
* Code tabs for file inspections.
* Chronological execution timelines with real token costs and audit trails.

```bash
# Open in your browser (Mac)
open technical_design.html
```
