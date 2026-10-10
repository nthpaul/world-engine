# Historical hardened receipt integrity note

The adjacent JSON, Markdown and JSONL remain unchanged execution evidence at source `4bc73fe6fd92df242900f08b6844fab4f3ff83be`, published with follow-up evidence commit `0cf41c7`. They record CRM `1.1.0`, refund `1.1.1`, 64 unique tasks and 128 scripted attempts. All replayed at that source. The label `hardened` refers to the earlier approval-history correction, not complete resistance to trusted-state corruption.

Subsequent independent review reproduced six completed-state grader gaps: CRM/refund role replacement; CRM marker-only audit or wrong canonical completion ID; refund missing audit or missing new payment ID/idempotency key. Each could retain full credit. No ordinary tool exploit was demonstrated, and fabricated transitions would not replay. CRM `1.1.1` and refund `1.1.2` now validate whole initial-anchored state and exact authorized change certificates. CRM additionally credits legitimate transfer-before-void ownership. See [the correction contract](../../../docs/workflow-grader-integrity.md).

This sidecar does not regrade or overwrite the collected outcomes. Replay old records in their recorded source checkout. New source needs a distinct committed protocol and immutable receipt directory before claiming current corrected coverage; no new collector result is implied here.
