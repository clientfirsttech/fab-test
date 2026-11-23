# Data Agent tests

`fab-test data-agent` runs a promptfoo suite of questions against a deployed Fabric Data Agent and checks each
answer. `fab-test data-agent tests init` writes or edits the suite; `tests lint` checks it before a run.
Walkthrough: `docs/DATA-AGENT-TESTS-WALKTHROUGH.md`. Flags: [flags.md](flags.md#data-agent).
Credentials: [credentials.md](credentials.md).

```
DataAgentTests {
  (FAB_TEST_ENABLE_DATA_AGENT=0) => data-agent | agent exits 2; absent from help and list; on by default
  (enabled) => service only; workspace resolves --workspace → FABRIC_WORKSPACE_ID → workspace in config
  (an item has a suite in fab-tests/data-agent/ or under --artifact-dir) => pair *.DataAgent.promptfoo.yaml by fabTestDataAgent == .platform config.logicalId
  (authored test files) => fab-tests/<flow>/ at the repository root, outside the Git-connected folder; --tests-dir | FAB_TEST_TESTS_DIR | tests_dir moves it
  (an item is selected locally) => resolve the deployed agent by .platform metadata.displayName
  (no paired suite) => skipped; (two suites claim one logicalId) => exit 2 naming both
  (a service target has no local item) => require --tests FILE
  (dry-run) => list local denominators without tokens or service calls; workspace inventory remains unresolved
  (workspace enumeration exceeds 5 agents) => require --all
  (a test uses conversation) => maxConcurrency = 1; provider workers = 1
  (running promptfoo) => use fab-test's Python; no cache, database writes, or sharing
  (persisting results) => redact native.json, effective.promptfoo.yaml, envelope.json; attach the standard report
  (all with a workspace configured and the flag enabled) => include data_agent; (local) => never include it
  (tests init, a person present) => ask each question, its expected answer (Enter = decline), one match key n|c|x|s|e|p|r (Enter = default), follow-ups in the same conversation; ? lists suggestions
  (tests init, CI | --format json | an agent) => --answers FILE {tests: [{query, expect, match, follow_ups, replace?}]}; --questions prints suggestions and the shape; never invent an expected answer
  (match keys) => n number: expect is only the figure (1,204 or 12.5, never $4.2M), matched with or without separators and never inside a bigger one; c contains, any case; x exact: the whole answer equals expect; s starts with | e ends with, any case, end punctuation ignored; p pattern: expect is a regex; r refuses: the first sentence declines, no expect. Default: n for a figure, c for words, r with no expect
  (suggestions) => figure measures and selected tables as questions; a table the source has but the agent leaves out, then a generic out-of-scope question, as `decline`; the agent's aiInstructions and dataSourceInstructions as `instructions`
  (a provider failure) => 401 after one refresh | 403 | "isRetriable": false | CapacityNotActive | a poll timeout are final and name the fix; a conversation turn is never retried once posted, nor its POST after a timeout, reset or 5xx (only a 429, which the service refused, is asked again); a 2xx without what the call needs is final, naming the host; still blocked after waiting once, the agent is asked no more that run
  (who asks the agent) => the chain every service command uses: a full service principal, else az login; --auth az uses az login even when a principal is set; --auth service-principal never falls back; see references/credentials.md
  (running for a person signed in with az login, and the principal is blocked (RequestBlocked), rejected (401/403) or not set up for this agent) => rerun with --auth az; never loop the principal
  (CI or another remote runner) => a service principal from secrets, or the pipeline's own az login (azure/login with OIDC, AzureCLI@2) then --auth az, which needs no client secret
  (the identity) => Member or Contributor in the agent's workspace, read on every data source; a service principal also needs the tenant setting "Service principals can use Fabric APIs"
  (a walkthrough or pipeline is wanted) => docs/DATA-AGENT-TESTS-WALKTHROUGH.md; docs/examples/{github-actions,azure-devops}/data-agent-tests.yml (lint, then the run; weekly)
  (tests init, a suite exists) => list its path and tests, then ask [a]dd (Enter) | [e]dit | [r]eplace all; "replace_all": true in --answers; replacing with no new questions writes nothing
  (editing) => tests by number until Enter, each [c]hange its answer (Enter: only its check changes, id and conversation stay) | [d]elete (with the later turns of its conversation); then new questions; "remove": [ids] at the top of --answers ("tests" may then be left out)
  (adding, a question it already has) => ask [k]eep (Enter) | [r]eplace; "replace": true in --answers; otherwise kept
  (changing a conversation's answers in --answers) => send its first turn with "replace": true and its follow_ups in order, each with query, expect and match; every turn sent is replaced, matched to the conversation's turns by position whatever their ids, turns not sent stay, and a replaced turn stays in its conversation (a follow-up stays a follow-up); never a follow-up as its own top-level test
  (a changed answer sent without "replace") => kept, not applied: -q says kept=N and the suite is unchanged; resend with "replace": true
  (tests lint) => offline checks first, then promptfoo validate (installed on first use, as the run does); run it before the run
  (a suite base_url | fabric_urls on a Fabric host) => works; lint warns (w=1) that fab-test can resolve the agent
  (a suite) => code: run it only from trusted branches; never pull_request_target or fork PRs with secrets
  (a suite base_url | fabric_urls host is not Fabric or Power BI) => a lint finding and a refusal before promptfoo starts; an exact extra host comes only from the caller's FAB_TEST_DATA_AGENT_ALLOWED_HOSTS
  (a suite env sets FAB_TEST_* | FABRIC_* | AZURE_* | PROMPTFOO_* | PLAYWRIGHT_ENV_FILE) => refused; remove it from the suite
  (promptfoo runs) => no service principal in its environment; the provider reads a private temp file, deleted after the run
  (telemetry) => carries redacted answers like every envelope; its readers should match the agent's data-source audience
}
```
