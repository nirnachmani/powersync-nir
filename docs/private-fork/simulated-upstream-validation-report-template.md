# Simulated upstream-maintainer validation report

Use this template only for deterministic local-fixture validation. It is not an upstream fetch, integration authorization, deployment record, or release report.

```text
Scope: local temporary Git repositories; <collector/classifier/candidate scripts exercised>
Fixtures: <documentation-only, test-only, compatible external-session, redundant, incompatible ownership/config>
Source checkout/deploy state: <starting SHA/status and deploy sentinel unchanged>
Classification results:
- no-overlap: <candidate merged locally / source untouched>
- compatible: <requires resolution; no source mutation>
- redundant: <recorded and no candidate promoted>
- incompatible: <held; no candidate promoted>
Gate result: <passed/failed; failed candidate reset and not promoted>
Interrupted/resumed: <state unchanged on interruption; explicit retry result>
Focused runner: <command and result>
Deployment/publish/network: not attempted
Blockers / follow-up: <none or factual item>
```
