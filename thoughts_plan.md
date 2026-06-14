# Agentic SOP Search & Execution Platform Architecture

Let me break this down into the core problem: **converting SOPs into machine-executable knowledge, making them discoverable, and enabling agents to consume them reliably.**

---

## 1. What is an "Agentic SOP"?

First, let's define the transformation target. A traditional SOP is prose written for humans. An Agentic SOP is a **structured, executable artifact**.

```yaml
agentic_sop:
  id: "sop-incident-db-failover-v3"
  title: "Database Failover Recovery"
  version: 3.2
  
  metadata:
    domain: ["infrastructure", "incident-response"]
    capabilities_required: ["kubectl", "datadog_read", "pagerduty"]
    risk_level: "high"
    requires_approval: true
    
  triggers:
    - intent: "database is down / failover / DB unreachable"
    - signals: ["datadog.alert.db_connection_failure"]
    
  preconditions:
    - "incident severity >= SEV2"
    - "primary DB health check failing for > 2min"
    
  steps:
    - id: step_1
      action: "diagnose"
      instruction: "Check replica lag via kubectl"
      tool: "kubectl"
      params_schema: {...}
      success_criteria: "replica_lag < 30s"
      on_failure: goto step_escalate
      
    - id: step_2
      action: "decision"
      condition: "replica_lag < 30s"
      human_approval: required   # guardrail
      
  rollback:
    - "..."
  
  embeddings_text: "natural language summary for semantic search"
```

The key insight: **the SOP carries both semantic content (for search) AND execution structure (for agents).**

---

## 2. SOP → Agentic SOP Conversion Pipeline

```
Raw SOP (PDF/Confluence/Word/Wiki)
        │
        ▼
┌─────────────────────┐
│  Ingestion & Parse  │  (OCR, doc parsing, chunking)
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│  LLM Extraction     │  Extract: steps, triggers, tools,
│  (structured)       │  decision points, preconditions
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│  Schema Mapping     │  Map tools → real capabilities
│  + Tool Binding     │  in the Harness registry
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│  Human-in-Loop      │  SME validates/approves
│  Review & Approve   │  (critical for trust)
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│  Compile & Index    │  Generate embeddings, store
└─────────────────────┘
```

**Design notes:**
- Keep conversion **semi-automated** — high-risk SOPs MUST have human review before becoming executable.
- Maintain **traceability**: link each agentic step back to the source SOP paragraph (auditability).
- **Version everything** — SOPs change; agents may be mid-execution on an old version.

---

## 3. Agentic SOP Search — The Core Design

This is the heart of your ask. I recommend a **hybrid retrieval architecture**, because pure vector search fails badly for procedural/operational content.

### 3.1 Multi-Index Strategy

```
                    ┌──────────────────────────────┐
   Agent Query ───▶ │      Query Understanding      │
                    │  (intent + entities + context)│
                    └──────────────┬───────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          ▼                        ▼                         ▼
  ┌───────────────┐       ┌────────────────┐       ┌─────────────────┐
  │ Vector Search │       │ Keyword/BM25   │       │ Metadata Filter │
  │ (semantic)    │       │ (exact terms,  │       │ (domain, tools, │
  │               │       │  error codes)  │       │  risk, version) │
  └───────┬───────┘       └───────┬────────┘       └────────┬────────┘
          └────────────────────────┼─────────────────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │   Reciprocal Rank Fusion      │
                    │   + Reranker (cross-encoder)  │
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │  Capability & Permission      │
                    │  Filtering (can agent run it?)│
                    └──────────────┬───────────────┘
                                   ▼
                            Ranked SOPs
```

### 3.2 Why Hybrid (not just vector)?

| Query Type | Best Retriever |
|------------|---------------|
| "DB is slow and timing out" | Vector (semantic intent) |
| "Error code PG-5043" | Keyword (exact match) |
| "high-risk infra SOPs needing approval" | Metadata filter |
| "failover but for read replicas only" | Reranker (nuance) |

### 3.3 What to Embed

Don't embed the whole executable JSON. Embed a **purpose-built search document**:
- Title + summary
- Trigger conditions / symptoms in natural language
- "When to use this" / "When NOT to use this"
- Keywords, synonyms, error codes

Store the executable body separately, retrieved by ID.

### 3.4 Critical: Capability-Aware Search

A key differentiator from normal RAG: **search must be filtered by what the requesting agent can actually do.**

```python
def search_agentic_sop(query, agent_context):
    candidates = hybrid_retrieve(query)
    
    # Filter to what THIS agent can execute
    executable = [
        sop for sop in candidates
        if agent_context.capabilities.satisfies(sop.required_capabilities)
        and agent_context.permissions.allows(sop.risk_level)
        and sop.status == "approved"
        and sop.version_is_current()
    ]
    return rerank(executable, query)
```

There's no point returning an SOP the agent has no tools or permissions to execute.

---

## 4. How AI Agents & Agent Harness Use Agentic SOPs

### 4.1 Two Consumer Types

**AI Agent (reasoning/planning):** Uses SOPs as *guidance* — flexible, can adapt, handles ambiguity.

**Harness Agent (deterministic execution):** Uses SOPs as *contracts* — runs steps in order, enforces guardrails, predictable.

### 4.2 Execution Flow

```
┌──────────────────────────────────────────────────────────┐
│  1. PLAN     Agent receives task/incident                 │
│              → searches Agentic SOP store                 │
│              → retrieves best-match SOP(s)                 │
├──────────────────────────────────────────────────────────┤
│  2. BIND     Resolve SOP's abstract tools → concrete      │
│              tool instances in Harness                    │
│              Check preconditions                          │
├──────────────────────────────────────────────────────────┤
│  3. EXECUTE  Harness runs steps:                          │
│              - deterministic steps → direct tool calls    │
│              - reasoning steps → LLM agent decides         │
│              - decision points → branch or human approval │
├──────────────────────────────────────────────────────────┤
│  4. GUARD    At each step, enforce:                       │
│              success_criteria, approvals, risk gates      │
├──────────────────────────────────────────────────────────┤
│  5. RECOVER  on_failure → rollback / escalate / re-plan   │
├──────────────────────────────────────────────────────────┤
│  6. RECORD   Full trace, link back to SOP version         │
└──────────────────────────────────────────────────────────┘
```

### 4.3 The SOP as a State Machine

The Harness should treat the Agentic SOP as a **stateful workflow graph**, not a flat script:

```
        ┌──────────┐
        │ Diagnose │
        └────┬─────┘
             │
        ┌────▼─────┐     fail
        │ Decision │──────────▶ Escalate
        └────┬─────┘
   pass      │
        ┌────▼─────────┐
        │ Approval     │ ◀── human-in-loop gate
        │ (if high-risk)│
        └────┬─────────┘
             ▼
        ┌──────────┐  fail  ┌──────────┐
        │ Failover │───────▶│ Rollback │
        └────┬─────┘        └──────────┘
             ▼
          Verify
```

This makes execution **resumable, auditable, and interruptible.**

### 4.4 Division of Responsibility

| Concern | AI Agent | Harness |
|---------|----------|---------|
| Find the right SOP | ✅ semantic reasoning | — |
| Decide step order | guidance | ✅ enforces graph |
| Handle ambiguity in a step | ✅ | — |
| Call tools safely | requests | ✅ executes + sandboxes |
| Enforce approvals/guardrails | — | ✅ |
| Logging & audit | — | ✅ |
| Re-plan on failure | ✅ | triggers it |

**Principle:** *The AI Agent provides intelligence and adaptability; the Harness provides safety, determinism, and control.*

---

## 5. Key Design Decisions & Trade-offs

| Decision | Recommendation | Why |
|----------|---------------|-----|
| Search approach | Hybrid + rerank + capability filter | Operational content needs precision |
| SOP format | Structured (YAML/JSON) + embedded NL | Serves both search & execution |
| Conversion | Semi-automated + HITL for high-risk | Trust & safety |
| Versioning | Immutable, versioned, current-pointer | Mid-execution consistency |
| Agent flexibility | Guidance vs. contract by risk level | Balance autonomy & control |
| Guardrails | Enforced by Harness, not LLM | LLMs can't be trusted to self-gate |

---

## 6. Things People Get Wrong (Watch Outs)

1. **Pure vector search for SOPs fails** — error codes, exact tool names, and version filters need keyword + metadata.
2. **Letting the LLM enforce its own guardrails** — approval gates and risk checks must live in the deterministic Harness.
3. **Stale SOP execution** — pin the SOP version at plan time; warn if a newer version exists.
4. **No capability binding** — returning SOPs an agent can't execute wastes cycles and erodes trust.
5. **Skipping human review on conversion** — auto-generated executable steps for high-risk ops is dangerous.
6. **No execution feedback loop** — capture which SOPs succeed/fail to improve search ranking and SOP quality.

---

## 7. Suggested Tech Stack

- **Vector store:** Elasticsearch/OpenSearch (hybrid native) or Qdrant + BM25
- **Reranker:** Cohere Rerank or cross-encoder
- **Embeddings:** domain-tuned text-embedding model
- **Orchestration/Harness:** LangGraph / Temporal (durable workflows) for the state machine
- **SOP store:** versioned object store + relational metadata DB
- **Conversion:** LLM with structured output (function calling / JSON schema)

---

Would you like me to go deeper on any piece — for example, the **conversion pipeline prompts**, the **hybrid search ranking details**, or the **Harness execution state machine design**?

I'd also recommend we discuss your **feedback loop** (execution outcomes → search quality), since that's what makes this platform improve over time rather than degrade.