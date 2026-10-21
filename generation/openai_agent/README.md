# Agent 1 — OpenAI text-to-BPMN generator (Option A)

This research prototype uses the **OpenAI API** to convert one natural-language process description directly into **BPMN 2.0 XML**. It does not use a reference model, quality evaluator, JSON intermediate representation, or automatic repair. It is intended to measure initial-generation behavior fairly.

## Requirements
- Windows, macOS or Linux computer with Python 3.10+ installed
- An OpenAI **API key** created at https://platform.openai.com/api-keys
- OpenAI API billing/credits as required for your account (ChatGPT subscriptions and API billing are separate)
- Internet connection

## Windows quick start (PowerShell)
1. Extract the ZIP to a folder, e.g. `C:\BPMNResearch\openai_bpmn_agent_1`.
2. Open PowerShell in that folder (File Explorer address bar: type `powershell` and press Enter).
3. Check Python: `py --version`.
4. Create a virtual environment: `py -m venv .venv`.
5. Activate it: `.\.venv\Scripts\Activate.ps1`. If PowerShell blocks activation, use `cmd.exe` and `.venv\Scripts\activate.bat`, or call `.venv\Scripts\python.exe` directly.
6. Install: `python -m pip install -r requirements.txt`.
7. Copy `.env.example` to `.env` (`Copy-Item .env.example .env`) and replace `replace_with_your_openai_api_key` with your private API key.
8. Run: `python agent.py --input examples/leave_request.txt`.
9. Check `outputs/leave_request/openai/initial.bpmn`, `initial_raw.txt` and `metadata.json`.

**Short way without activation** (after creating .venv):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# edit .env and put your key
.\.venv\Scripts\python.exe agent.py --input examples/leave_request.txt
```

## macOS/Linux quick start
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# Edit .env and replace the placeholder with your API key.
python agent.py --input examples/leave_request.txt
```

## Use a different input
Create a UTF-8 `.txt` file with one process description, for example `examples/my_process.txt`.
```bash
python agent.py --input examples/my_process.txt --model gpt-5-mini
```
Set your own model ID with `--model` or `OPENAI_MODEL` in `.env`, after checking access to that model in your API account. For a rigorous paper, record a stable dated model ID when available.

## Run tests without an API key
```bash
python -m unittest discover -s tests -v
```
Tests use a mock API client and do not contact OpenAI.

## Output structure
```text
outputs/
  leave_request/
    openai/
      input_description.txt   # Exact input used
      prompt_system.txt       # Exact system prompt
      initial_raw.txt         # Raw LLM response, even when malformed
      initial.bpmn            # Raw response saved as BPMN XML, without auto-repair
      metadata.json           # Model, API response ID, token usage, elapsed time, diagnostics
```

`initial.bpmn` may be invalid or not importable in Bizagi. That is an **experimental observation**, not something to hide or silently fix. The included parser checks XML well-formedness and some basic references; it does not validate against the complete BPMN 2.0 specification or measure semantic/pragmatic quality. That is the later evaluator's job.

## Security and reproducibility
- Keep `.env` private and do not commit it to GitHub, share screenshots of it, or put keys in prompts.
- The ZIP includes only `.env.example`; no secret or real key is bundled.
- API calls incur usage charges depending on the model and consumption; begin with one process.
- Each run to the **same input path** overwrites that process's `initial.*` files. Save/copy results into versioned folders for replicates, or choose a separate `--output` folder (e.g., `--output outputs_run02`).
- The script saves actual outputs even if malformed; no agent feedback or auto-correction is performed at this stage.
- The prompt is minimal by design; output quality is being measured, not guaranteed.
