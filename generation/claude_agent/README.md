# Agent 2 — Claude BPMN Generator (ICAART research)

This is the Claude counterpart to OpenAI Agent 1 Version 2. It uses the **same system prompt text**, the same leave-request input, the same BPMN XML diagnostics, and the same independent layout adapter.

## Windows instructions (step by step)

1. Extract ZIP on Desktop, for example `Desktop\ICAART27\claude_bpmn_agent_2`.
2. Open the folder that **contains `agent.py`, `layout.py`, and `requirements.txt`**.
3. Click the File Explorer **address bar**, type `powershell`, and press Enter.
4. Copy and run these commands one at a time:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

5. Get a separate Anthropic Claude API key at https://console.anthropic.com/settings/keys and ensure your Anthropic API account has billing credits. Your OpenAI key and ChatGPT subscription cannot be used as an Anthropic API key.
6. **Copy** `.env.example` to `.env` (do not just rename the original). Right-click `.env` > Open with Notepad; insert your real key after `ANTHROPIC_API_KEY=` and save. Do not share your key or commit `.env`.
7. Execute:

   ```powershell
   .\.venv\Scripts\python.exe agent.py --input examples/leave_request.txt
   ```

8. Import `outputs\leave_request\claude\visualization.bpmn` in Bizagi using **Export/Import > Import BPMN**, not File > Open. If `visualization.bpmn` was not created, inspect `metadata.json` and `initial.bpmn`.

**If you already keep the new Agent 2 folder nested inside another directory containing `.venv`, adjust the Python path. The instructions above assume `.venv` is created directly beside `agent.py`.**

## What files are generated?

- `initial.bpmn`: exact text returned by Claude, even if invalid (research baseline).
- `initial_raw.txt`: unmodified text returned by Claude.
- `visualization.bpmn`: optional layout-adjusted copy for Bizagi; never use this as evidence of raw generation quality.
- `metadata.json`: model ID, usage, stop reason, time, XML diagnostics, layout status.
- `prompt_system.txt` / `input_description.txt`: records of inputs for reproducibility.
- `api_error.json`: generated on an API failure.

## Offline tests (no API key, no billing)

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Research notes

- Do not run with PMo reference BPMN files as part of the prompt. Input only the process descriptions.
- The current agent does *not* perform corrections. Agent 3 and iterative evaluation are separate subsequent research steps.
- Claude Messages API requires `max_tokens`; a truncation `stop_reason=max_tokens` is logged, not repaired.
- These basic XML checks are **not** a full BPMN 2.0 schema check, semantic assessment, or soundness test.
- If you change a model ID, record it consistently across the study. Do not claim model versions are identical in size, training, or behavior merely because prompts match.
- Agent 1's model `gpt-5-mini` and Claude Sonnet differ in model capability and pricing. The comparison is two selected systems, not a controlled test of model-family superiority.
