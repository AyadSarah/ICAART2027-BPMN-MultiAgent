# Online appendix: PMo 05 case for the OpenAI-generated model (GPT-5 mini)

| File | Run | Usable | Note |
|---|---|---|---|
| `openai_original.bpmn` | original generation | yes | single lane, 8 activities, site-visit and agreement gateways |
| `pilot_v1_self_refined.bpmn` | pilot, neutral prompt, self-refinement | yes | same structure as the original |
| `pilot_v1_same_refined.bpmn` | pilot, neutral prompt, GPT-4.1 feedback | no | diagram shapes reuse element IDs (26 duplicate IDs) |
| `pilot_v1_cross_refined.bpmn` | pilot, neutral prompt, Claude feedback | no | diagram shapes reuse element IDs (25 duplicate IDs) |
| `v2_self_refined.bpmn` | extended prompt, self-refinement | yes | evaluation sub-process (cost, quality, delivery time), supplier pool with activities, data objects |
| `v2_cross_refined_raw_INVALID_XML.txt` | extended prompt, Claude feedback | no | malformed XML: unescaped `&` in the label "Review & Agree Terms" |
| `v4_same_refined_INVALID_refs.bpmn` | extended prompt (rerun), GPT-4.1 feedback | no | four elements typed as `bpmn:flowElement`, six unresolved sequence-flow references |

The full run folders, with prompts, raw responses and metadata, are in `results/refinement/`.
A first attempt of the extended-prompt same-LLM run (`refinement_results_v3`) failed before any API call because of
missing credentials, so it is not included.
