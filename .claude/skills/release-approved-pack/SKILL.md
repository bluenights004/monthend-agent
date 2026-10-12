---
name: release-approved-pack
description: Deliver a month-end pack that a person has already approved (Outlook draft or send, SharePoint upload).
disable-model-invocation: true
argument-hint: <run_id>
---

# Release an approved pack

Only a person can start this skill. Model invocation is disabled.

1. Call `mcp__datastore__get_review_history` for the run. Confirm the latest decision is `approved` and state who approved it and when.
2. Call `mcp__m365__deliver_approved_pack` with the run id. The guard hook verifies the approval again and asks the user to confirm. The review gate checks again that every file still matches the approved bundle.
3. Report what happened: an Outlook draft id or sent message, and the SharePoint upload. For draft mode, remind the user that the email is waiting in the firm mailbox's Drafts folder for them to send.

If the gate refuses, report its reason word for word. Do not retry with different inputs.
