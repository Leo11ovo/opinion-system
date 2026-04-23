# Strategy Matrix

Use these presets unless the user explicitly asks for a different retrieval mode.

## `fact`

Best for:

- what happened
- who participated
- which platform was most active
- what values or findings were observed

Recommended preset:

- `mode = normalrag`
- `topk_normalrag = 8`
- `topk_tagrag = 2`
- `enable_expert_overlay = false`
- `enable_llm_summary = true`
- `llm_summary_mode = strict`
- `return_format = both`

Reason:

- factual questions should emphasize evidence recall and avoid over-weighting theory overlay

## `explain`

Best for:

- why did this happen
- why is this judged as a certain stage
- which theory or frame explains the event

Recommended preset:

- `mode = mixed`
- `topk_graphrag = 4`
- `topk_normalrag = 8`
- `topk_tagrag = 3`
- `enable_expert_overlay = true`
- `enable_expert_rewrite = true`
- `enable_expert_hints = true`
- `enable_expert_answer_structure = true`
- `enable_llm_summary = true`
- `llm_summary_mode = supplement`
- `return_format = both`

Reason:

- explanation needs evidence plus expert graph guidance

## `compare`

Best for:

- similar cases
- comparison with historical events
- what is different from another case

Recommended preset:

- `mode = mixed`
- `topk_graphrag = 5`
- `topk_normalrag = 10`
- `topk_tagrag = 4`
- `enable_expert_overlay = true`
- `enable_expert_rewrite = true`
- `enable_expert_hints = true`
- `enable_expert_answer_structure = true`
- `enable_llm_summary = true`
- `llm_summary_mode = supplement`
- `return_format = both`

Reason:

- comparison benefits from broad retrieval and stronger graph/context overlay

## `decision`

Best for:

- what should we do next
- how should the actor respond
- what strategy is suitable

Recommended preset:

- `mode = mixed`
- `topk_graphrag = 6`
- `topk_normalrag = 10`
- `topk_tagrag = 5`
- `enable_expert_overlay = true`
- `enable_expert_rewrite = true`
- `enable_expert_hints = true`
- `enable_expert_answer_structure = true`
- `enable_llm_summary = true`
- `llm_summary_mode = supplement`
- `return_format = both`

Reason:

- decision questions need the widest bridge from evidence to strategy

## `explore`

Best for:

- open-ended investigation
- broad topic discovery
- initial scoping before narrowing down

Recommended preset:

- `mode = mixed`
- `topk_graphrag = 3`
- `topk_normalrag = 8`
- `topk_tagrag = 3`
- `enable_expert_overlay = true`
- `enable_expert_rewrite = true`
- `enable_expert_hints = true`
- `enable_expert_answer_structure = true`
- `enable_llm_summary = true`
- `llm_summary_mode = strict`
- `return_format = both`

Reason:

- exploratory questions need balanced retrieval without overcommitting to a single path
