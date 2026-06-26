---
name: adapter-mvp-workflow-guard
description: Enforce Adapter MVP workflow guardrails for DingTalk requirement documents, Yunxiao demand/task creation, pipeline webhook binding, Apifox sync, and Yunxiao close/writeback. Use when Codex changes or tests adapter-mvp behavior involving Alidocs/DingTalk parsing, Yunxiao workitems, sprint/version mapping, commit ID parsing, pipeline callbacks, Apifox imports, or closing workitems.
---

# Adapter Mvp Workflow Guard

## Workflow

1. Read the current Adapter MVP code and tests before editing.
2. Before parsing a DingTalk requirement document or creating Yunxiao workitems, align the document with `delivery/templates/钉钉需求文档标准模版.md`. If the product document has a new shape, document that shape first, then continue.
3. Preserve this business model:
   - DingTalk document -> Yunxiao demand workitem (`category=Req`).
   - Every parsed task -> Yunxiao task workitem (`category=Task`).
   - Every task must carry the parent demand identifier (`parentIdentifier` in Adapter context, `parentId` for personal token API).
   - A demand heading is a hard scope boundary: description, owner, main content, and task rows under it belong only to that current demand.
   - `demandIndex` and `itemIndex` are ordering hints only; never infer or overwrite a demand title from indexes, document title, requirement key, the first demand, or another demand.
   - If the demand title or task ownership is ambiguous, fail explicitly or ask the user. Do not silently guess.
   - Document version maps to Yunxiao sprint; missing or ambiguous sprint must fail explicitly.
   - Close/writeback closes only real child task IDs explicitly listed in the commit message `云效任务` field or manual `closeTaskRefs`; never close any demand.
   - If there are no explicit Yunxiao task IDs, skip close/writeback. Do not close all tasks by default.
4. Reject silent fallbacks for missing project, Apifox project, sprint, assignee, task type, token, or close status config.
5. Keep commit parsing user-friendly: support Chinese labels such as `云效ID`、`云效任务`、`任务编号`, not only one English key, and support multiple IDs such as `云效任务: AYRR-4062、 AYRR-4063`.
6. After changes, run focused tests first, then the full unit test suite and compile check.

## Guard Commands

Use these checks before claiming Adapter MVP workflow changes are complete:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m compileall app scripts
.venv/bin/python scripts/validate_yunxiao_workflow_guard.py --file <workflow.json> --mode all
```

For real integration runs, verify Yunxiao with GET/readback evidence after create or close:

- demand category is `Req`
- task category is `Task`
- task `parentId` equals the parent demand ID
- demand and tasks have the expected sprint
- close result contains child task IDs only

Never print secrets, tokens, AK/SK, Authorization headers, cookies, or private keys.
