# Specialist Reviewer Workflow

A resilient, production-grade software-release review workflow. A release board assigns a configured specialist agent to inspect a proposed software change and return a typed, schema-validated decision with trusted identity enforcement and deterministic failure handling.

---

## 📌 Problem Overview

In modern AI-assisted CI/CD and release governance pipelines, delegating reviews to LLM specialist agents introduces several operational challenges:

1. **State Mutation & Context Leakage:** Injected agents may inadvertently mutate caller-owned context configurations or expose sensitive private parameters across invocations.
2. **Schema Inconsistency & Hallucination:** Raw language model responses can produce unexpected fields, unknown decision states, blank summaries, or invalid combinations of approvals and corrections.
3. **Identity Spoofing:** Models prompted to produce decisions may hallucinate, forge, or alter their own identifier (`specialist_id`), undermining auditability and attribution.
4. **Fragile Runtime Failures:** Parsing errors or schema violations can trigger uncaught exceptions rather than clean, structured failure representations for automated release boards.

### Design Goals

- **Strict Immutability:** Isolates caller-owned configurations by deeply copying private context dictionaries prior to agent construction.
- **Contract Enforcement:** Enforces exact decision rules using Pydantic v2 validation (`approve` strictly forbids corrections; `request_changes` requires nonblank corrections).
- **Code-Owned Trusted Identity:** Guarantees audit integrity by programmatically overwriting any model-provided `specialist_id` with the code-owned, trusted `config.id`.
- **Deterministic Error Normalization:** Catches `ValidationError`, `TypeError`, and `ValueError` to return a typed `ReviewFailure(config.id, "malformed_output")`.
- **Decoupled Runner Compatibility:** Seamlessly executes tasks via callable runners (such as `GroqTaskRunner`) or LangGraph-compatible single-node shells without network dependencies during unit testing.

---

## 🏗️ Architecture & Component Overview

```
                        +----------------------+
                        |   SpecialistConfig   |
                        +----------+-----------+
                                   | (Deep Copy)
                                   v
+------------------+    +----------------------+
|   ReviewInput    |--->|   build_specialist   |---> Specialist Agent
+------------------+    +----------------------+            |
         |                                                  |
         +------------------------+                         |
                                  |                         |
                                  v                         v
                       +---------------------------------------+
                       |           build_review_task           |
                       +-------------------+-------------------+
                                           |
                                           v
                       +---------------------------------------+
                       |     run_review_task (Runner / LLM)    |
                       +-------------------+-------------------+
                                           | Raw Output
                                           v
                       +---------------------------------------+
                       |        ReviewDecision Validator       |
                       +-------------------+-------------------+
                                           |
                       +-------------------+-------------------+
                       |                                       |
                   [Valid]                                 [Invalid]
                       |                                       |
                       v                                       v
         +---------------------------+           +---------------------------+
         | Overwrite specialist_id   |           |       ReviewFailure       |
         |  with trusted config.id   |           |    ("malformed_output")   |
         +---------------------------+           +---------------------------+
                       |
                       v
                 ReviewDecision
```

### Data Models (`utils/models.py`)

| Component | Type | Description |
|---|---|---|
| `SpecialistConfig` | Frozen Dataclass | Holds code-owned specialist identity (`id`), role, goal, and private context dictionary. |
| `ReviewInput` | Frozen Dataclass | Encapsulates the release target (`release_id`) and proposed change summary (`change_summary`). |
| `Decision` | String Enum | Enumerates allowed review outcomes: `approve` and `request_changes`. |
| `ReviewDecision` | Pydantic v2 Model | Enforces typed output with forbidden extra fields, nonblank summary, and decision contract rules. |
| `ReviewFailure` | Frozen Dataclass | Typed failure record containing `specialist_id` and normalized error code (`"malformed_output"`). |
| `Factories` | Frozen Dataclass | Injected callable dependency bundle: `agent_factory` and `task_factory`. |
| `EXPECTED_OUTPUT` | String Constant | Standard prompt directive: `"A typed decision, concise summary, and required corrections."` |

---

## ⚙️ Core Functions (`main.py`)

### 1. `build_specialist(config, agent_factory)`
- Creates a `copy.deepcopy` of `config.private_context` to guarantee the caller-owned dictionary cannot be mutated by the factory.
- Inspects the injected `agent_factory` signature. If keyword-only, supplies named parameters; otherwise invokes with exact positional arguments: `(config.role, config.goal, copied_context)`.
- Invokes `agent_factory` **exactly once** and returns the resulting specialist instance.

### 2. `build_review_task(review_input, specialist, task_factory)`
- Formats the review description to the exact template: `"Review release {release_id}: {change_summary}"`.
- Invokes `task_factory` with the required fields:
  - `description`: The formatted release description string.
  - `expected_output`: The supplied `EXPECTED_OUTPUT` constant.
  - `output_schema`: The supplied `ReviewDecision` Pydantic model.
  - `agent`: The specialist agent instance created for this review.

### 3. `run_review_task(task, runner)`
- Executes the review task through the runner shell.
- Dynamically accommodates standard callables (e.g., `runner(task)`) and LangGraph / LangChain runnable objects (e.g., `runner.invoke(task)`).

### 4. `run_specialist(config, review_input, factories, runner)`
- Coordinates end-to-end execution:
  1. Instantiates the specialist via `build_specialist()`.
  2. Constructs the review task via `build_review_task()`.
  3. Executes the task through `run_review_task(task, runner)` exactly once.
  4. Validates raw output using `ReviewDecision.model_validate(raw_output)`.
  5. Enforces trusted identity by replacing any model-provided `specialist_id` with `config.id`.
  6. Catches `(ValidationError, TypeError, ValueError)` to return `ReviewFailure(config.id, "malformed_output")`.

---

## 📋 Decision Contract Specification

Output validation strictly adheres to the following matrix:

| Field | Validation Rule | Malformed If |
|---|---|---|
| `decision` | Must be either `"approve"` or `"request_changes"`. | Any other value (`"reject"`, `"pass"`, uppercase, or numbers). |
| `summary` | Non-empty string after stripping whitespace. | Empty string, whitespace-only, `None`, or missing. |
| `corrections` | Tuple of non-empty strings. Defaults to `()`. | Contains blank strings, whitespace-only strings, or non-string items. |
| `approve` contract | Requires nonblank `summary` and **zero** corrections (`()`). | Any correction is present. |
| `request_changes` contract | Requires nonblank `summary` and **at least one** nonblank correction. | `corrections` is empty or omitted. |
| Additional Fields | `extra="forbid"` on model configuration. | Any unexpected or unauthorized keys present in raw output. |

### Valid Examples

#### 1. Approved Release
```json
{
  "specialist_id": "sec-reviewer-01",
  "decision": "approve",
  "summary": "Cryptographic migration follows security best practices and test suites pass.",
  "corrections": []
}
```

#### 2. Changes Requested
```json
{
  "specialist_id": "sec-reviewer-01",
  "decision": "request_changes",
  "summary": "Token expiry is not checked prior to issuing credentials.",
  "corrections": [
    "Validate token expiry before refresh.",
    "Add integration test verifying expired token rejection."
  ]
}
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+ (tested on Python 3.14)
- Git

### Installation

Clone the repository:
```bash
git clone https://github.com/Shubhankart101/SpecialistReviewer.git
cd SpecialistReviewer
```

Install dependencies:
```bash
pip install -r requirements.txt
```

---

## 🧪 Testing & Verification

The suite includes 22 unit and regression tests covering all edge cases, mutation defenses, contract boundaries, and identity overrides.

Run the test suite with pytest:
```bash
pytest -v
```

### Test Coverage Highlights

- **`TestBuildSpecialist`**:
  - Validates `agent_factory` is called exactly once.
  - Verifies exact forwarding of `role` and `goal`.
  - Asserts private context immutability (modifying factory-received dict or nested dicts leaves `config.private_context` untouched).
  - Verifies compatibility with keyword-only factory signatures.
- **`TestBuildReviewTask`**:
  - Verifies description template formatting against `release_id` and `change_summary`.
  - Verifies exact binding of `EXPECTED_OUTPUT`, `ReviewDecision`, and `specialist`.
  - Tests positional-only fallback compatibility.
- **`TestRunReviewTask`**:
  - Verifies execution with standard callable runners and invokable runnable shells.
- **`TestRunSpecialist`**:
  - Validates end-to-end `approve` and `request_changes` decisions.
  - Verifies model-provided `specialist_id` replacement with code-owned `config.id`.
  - Verifies rejection and normalization to `ReviewFailure(config.id, "malformed_output")` for:
    - Approve decisions containing corrections.
    - Request changes decisions with empty corrections.
    - Blank or whitespace-only summaries.
    - Blank or whitespace-only correction entries.
    - Unknown or unexpected decisions.
    - Extra unauthorized fields in model output.
    - Non-dict or malformed raw outputs (`None`, strings, integers, arrays).

---

## 📂 Project Structure

```
SpecialistReviewer/
├── .gitignore               # Ignored build, cache, and virtual environment files
├── LICENSE                  # MIT License
├── README.md                # Project documentation and specifications
├── main.py                  # Core implementation of the 3 TODO reviewer functions
├── requirements.txt         # Project dependencies (pytest, groq, pydantic)
├── test_specialist.py       # Comprehensive pytest test suite (22 unit tests)
└── utils/
    ├── __init__.py          # Package initializer
    ├── groq_runner.py       # Groq-compatible structured task runner
    └── models.py            # Pydantic decision models, dataclasses, and constants
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
