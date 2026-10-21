# Case study: PMo 05 (supplier selection), Claude-generated model

| Paper figure | Model | Figure file | BPMN file |
|---|---|---|---|
| Figure 2 | PMo reference model | `figures/fig2_reference.png` | `data/PMo_ready/references_bpmn/05.bpmn` (downloaded) |
| Figure 3 | Claude original model | `figures/fig3_claude_original.png` | `models/claude_original.bpmn` |
| Figure 4 | Self-refinement | `figures/fig4_claude_self_refinement.png` | `models/claude_self_refined.bpmn` |
| Figure 5 | Same-LLM refinement (Claude feedback) | `figures/fig5_claude_same_llm.png` | `models/claude_same_refined.bpmn` |
| Figure 6 | Cross-LLM refinement (GPT-4.1 feedback) | `figures/fig6_claude_cross_llm.png` | `models/claude_cross_refined.bpmn` |

- **Where the refined models come from.** They are copies of
  `results/refinement/pmo05_v2_extended_prompt/pmo_05/claude/{self,same,cross}/refined.bpmn`.
  These runs used the extended refinement prompt (`prompts/refinement_system_prompt_v2_extended.txt`).
- **How the figures were drawn.** The figures are simplified redrawings of the BPMN XML, not exports of its
  diagram layout. Red circles mark selected changed elements. Artifacts are shown as found in the XML; the
  data associations are not drawn.
- **Evaluator feedback.** The feedback given to each refinement is in
  `results/evaluation/agent3_batch_reports/agent3_side_by_side_all.csv` (PMo 05, generator `claude`). The exact
  refinement prompts, including this feedback, are in the `prompt.json` file of each run.
- **Traceability.** `PMo05_Evaluator_Comments_Refinement_Traceability.docx` maps each evaluator comment to the
  change observed in the refined XML.
- **Quality measures.** Recompute the case-study table with `python analysis/06_case_study_pmo05.py`.
