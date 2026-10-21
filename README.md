# A Multi-Agent Framework for Quality-Driven Refinement of BPMN Models Using Large Language Models

Code, prompts, generated models, evaluation results and analysis scripts for the ICAART 2027 paper

> Sarah Ayad (Arab Open University, Saudi Arabia) and Humam Kourani (Fraunhofer FIT, Germany).
> *A Multi-Agent Framework for Quality-Driven Iterative Refinement of BPMN Models Using Large Language Models.* ICAART 2027.

The framework has three stages:

1. **Generation.** Two independent LLM agents generate BPMN 2.0 XML directly from the same natural-language process description.
2. **Evaluation.** Each usable model is evaluated independently by two LLM evaluators, using the same rubric. The rubric covers semantic and pragmatic quality. Syntactic quality is checked automatically.
3. **Refinement.** The generator revises its model by self-refinement, with feedback from the same LLM provider, or with feedback from the other provider.

All experiments use the 55 descriptions of the **PMo benchmark** (Brissard, Cuppens & Zouaq, 2025).

---

## Models and settings

| Role | Model | Settings |
|---|---|---|
| OpenAI generator and refiner | `gpt-5-mini` (returned as `gpt-5-mini-2025-08-07`) | API default temperature, no output limit |
| Claude generator and refiner | `claude-sonnet-4-5-20250929` | API default temperature, `max_tokens` 8,192 (16,000 for 17 recovery runs) |
| OpenAI evaluator | `gpt-4.1` | temperature 0 |
| Claude evaluator | `claude-sonnet-4-5-20250929` | temperature 0, `max_tokens` 3,500 |

Generation ran on 12 October 2026, the Claude recovery runs with 16,000 tokens on 13 October 2026, and the refinement runs on 17 October 2026. Each description was generated once per generator. Refinement used the runner's default output limit of 12,000 tokens.

---

## Repository structure

```
data/prepare_pmo.py        Downloads PMo v1.0.0 from Zenodo and checks its MD5 checksum
prompts/                   Generation prompt, evaluator rubric, refinement prompts (v1 and v2)
src/generation/            OpenAI and Claude generation agents, batch runner, Claude recovery script
src/evaluation/            Evaluator (agent3.py) and its batch runner
src/refinement/            Refinement runners: v1 (neutral prompt) and v2-v4 (extended prompt)
src/validation/            XML/BPMN checks and lexical comparison with the reference models
analysis/                  Scripts that recompute every table and number in the paper
results/generation/        Generated models, raw outputs, metadata and provenance manifest
results/evaluation/        All 176 evaluator reports and the combined evaluation table
results/refinement/        Refinement runs (prompts, raw outputs, refined XML, run metadata)
results/tables/            CSV output of the analysis scripts
case_study/                PMo 05 case study: models, figures and comment traceability
appendix/openai_pmo05/     PMo 05 case for the OpenAI-generated model (online appendix)
```

---

## Reproducing the analysis (no API key needed)

```bash
pip install -r requirements.txt
python data/prepare_pmo.py --out data/PMo_ready      # downloads PMo from Zenodo
for s in analysis/0*.py; do python "$s"; done         # writes results/tables/*.csv
```

If the automatic download is blocked, download `pmo-dataset.zip` from
https://doi.org/10.5281/zenodo.15857589 and run
`python data/prepare_pmo.py --zip pmo-dataset.zip --out data/PMo_ready`.

| Script | Paper content | Output in `results/tables/` |
|---|---|---|
| `01_generation.py` | Generation outcomes, causes of unusable output (Table 1), size of failed descriptions | `generation_outcomes.csv`, `failure_causes.csv`, `failed_descriptions_size.csv` |
| `02_scores_agreement.py` | Evaluator scores (Table 2), agreement, paired comparison | `scores_by_evaluator.csv`, `evaluator_agreement.csv`, `paired_comparison.csv` |
| `03_comments.py` | Comment themes (Table 3), abstraction level, comment style | `comment_themes.csv`, `abstraction_level.csv`, `comment_style.csv` |
| `04_structural_checks.py` | Structural checks (Table 4) | `structural_checks.csv` |
| `05_reference_correspondence.py` | Correspondence with the reference models | `reference_correspondence.csv` |
| `06_case_study_pmo05.py` | Case-study quality measures | `case_study_pmo05_quality.csv` |
| `07_refinement_pilot.py` | Usability and activity changes of all refinement runs | `refinement_runs.csv`, `refinement_pilot_usability.csv` |

The comments on abstraction level were coded by hand. The coding is in `analysis/abstraction_manual_coding.csv`, where each comment is coded as `too_general`, `too_specific`, `appropriate` or `not_granularity`.

---

## Re-running the experiments (paid API calls)

Set `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` in your environment (see `.env.example`). Never commit a real `.env` file.

```bash
# 1. Generation (both agents, all 55 descriptions)
python src/generation/batch_generate.py --dataset data/PMo_ready --agent both \
       --openai-dir src/generation/openai_agent --claude-dir src/generation/claude_agent --end 55

# 2. Claude recovery of truncated outputs with a 16,000-token limit
python src/generation/recover_claude_pmo.py --dataset data/PMo_ready --claude-dir src/generation/claude_agent --max-tokens 16000

# 3. Evaluation (both evaluators, all usable models)
cp -r data/PMo_ready/descriptions results/generation/PMo_combined_analysis/
python src/evaluation/run_agent3_batch.py --dataset results/generation/PMo_combined_analysis \
       --agent3 src/evaluation/agent3.py --openai-model gpt-4.1 --claude-model claude-sonnet-4-5-20250929 --ids all

# 4. Refinement (one round, three strategies)
python src/refinement/refinement_runner_v1.py --dataset results/generation/PMo_combined_analysis \
       --feedback results/evaluation/agent3_batch_reports/agent3_side_by_side_all.csv \
       --ids 01,02,03,04,05 --openai-model gpt-5-mini --claude-model claude-sonnet-4-5-20250929
```

Each run first asks for a `--dry-run` check, which makes no API calls. LLM outputs are not deterministic, so a re-run produces different models. The files in `results/` are the outputs used in the paper.

---

## Notes on the data

- **Usable model.** The XML parses, has a BPMN `definitions` root, unique identifiers and resolved sequence-flow references. No automatic repair was applied. This is not full BPMN 2.0 schema validation and not a soundness check.
- **Mixed token limits for Claude.** 38 Claude models were generated with 8,192 tokens and 16 with 16,000 tokens. PMo 18 failed in both runs. See `results/generation/PMo_combined_analysis/analysis_manifest.csv`, column `selection`.
- **Reference models are never given to the agents.** They are used only by the scripts in `src/validation/` and `analysis/`.
- **Refinement prompts.** `results/refinement/pilot_v1_neutral_prompt` (PMo 01–05, 30 runs) used the neutral prompt in `prompts/refinement_system_prompt_v1_neutral.txt`. The PMo 05 runs in `pmo05_v2_extended_prompt` and `pmo05_v4_openai_same_rerun`, which are used in the case study, used the extended prompt in `prompts/refinement_system_prompt_v2_extended.txt`. That prompt adds explicit quality criteria on participants, artifacts, abstraction level and control flow.
- **Lexical matching.** Activity precision and recall match labels with a similarity of at least 0.6. They approximate semantic correspondence and are not a proof of it.

---

## Data source and licences

- **PMo dataset:** Brissard, A., Cuppens, F. and Zouaq, A. (2025). *PMo Dataset* (v1.0.0). Zenodo. https://doi.org/10.5281/zenodo.15857589. Licensed under CC BY 4.0. The prompt and metadata files in `results/` contain the PMo process descriptions, which are reproduced under this licence. The reference models are not included and are downloaded by `data/prepare_pmo.py`.
- **Code** in this repository: MIT licence (see `LICENSE`).
- **Generated models, evaluations and analysis results:** CC BY 4.0.

## Citation

See `CITATION.cff`.
