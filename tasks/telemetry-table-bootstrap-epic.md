# Telemetry Table Bootstrap Epic

**Status**: 📋 PLANNED
**Goal**: Create the telemetry tables and their ingestion mapping when they are absent, and never report a send that cannot land.

## Overview

`fab-test` currently tells you telemetry was delivered when it was not. Queued
ingest accepts a batch aimed at a table that does not exist — the request is
valid, the failure happens later in the ingestion pipeline — so the run prints
`✓ fab-test: telemetry delivered (1 record(s))`, sets `telemetry_error: null`,
and the record is never queryable. Confirmed against a real cluster: ingesting
into `fabric_no_such_table` returned `ok=True, sent=1`.

That is the same defect the [Eventhouse Shipping](archive/2026-08-22-eventhouse-shipping.md)
epic was written to remove, reappearing one layer lower. The placeholder lied
about the network call; this lies about the destination. A first-time user
following the documentation gets a green run and an empty table, with nothing
anywhere telling them why.

This epic makes the tables `fab-test`'s responsibility: check once per run,
create what is missing, and refuse to claim delivery when the destination still
is not there.

**This reverses a non-goal.** Eventhouse Shipping said creating the Eventhouse,
its database, or its tables was out of scope, and the manual `.create-merge` KQL
was documented as a prerequisite. That prerequisite is a trap: it is invisible
until data silently goes missing, and the mapping half of it is easy to skip
because a table without it *also* ingests successfully — into empty rows. The
Eventhouse and the database stay out of scope; the tables come in.

---

## A Missing Table Is Not A Successful Send

Fix the report before fixing the cause, so a failure is loud even where creation
cannot happen.

**Requirements**:
- Given a table that does not exist and cannot be created, should report the flush as failed rather than `ok=True` with a record count
- Given that failure, should name the table and the database, since "not found" without a name sends a reader to the wrong cluster
- Given `run.json`, should carry the reason in `telemetry_error` like every other delivery failure
- Given the run, should keep its own exit code — this is still telemetry, and telemetry never fails a build
- Given a mocked ingest in the test suite, should not have to reach a cluster to prove this: the check is separable from the send

---

## Create The Tables When They Are Absent

**Requirements**:
- Given a configured destination whose table does not exist, should create it with the single `Data: dynamic` column rather than failing
- Given a table that already exists, should not attempt to create or alter it — a run against a healthy cluster does no schema work
- Given a run over many artifacts, should check at most once per table per run, not once per record: this is a management call against the query endpoint, and paying it per artifact repeats the mistake batching was introduced to avoid
- Given both tables are used in one `fab-test all` run, should ensure each independently, since a repository with no semantic model never touches the dynamic table
- Given creation succeeds, should say so once — a schema change is worth one line of narration, and silence would leave a reader unsure whether their data has a home

---

## The Mapping Is Checked Too

A table without the `fab_test_payload` mapping ingests successfully and stores
empty rows, which is worse than an outright failure.

**Requirements**:
- Given a table that exists but has no `fab_test_payload` mapping, should create the mapping rather than assume it
- Given an existing mapping, should leave it alone unless it disagrees with what this version needs
- Given a table created by an older `fab-test` or by hand with a different schema, should not silently ingest into it — the mapping is what makes the `Data` column work, and its absence is undetectable from the ingest side
- Given the mapping name, should stay a fixed constant rather than a config key: a caller who changes it gets empty rows and no error

---

## Creating It Can Fail, And That Is Not Fatal

Ingesting needs Database Ingestor; creating a table needs more. The two failures
must not be reported as one.

**Requirements**:
- Given a credential with Ingestor but not table-creation rights, should report that the table is missing *and* could not be created, with the KQL to run by hand
- Given that case, should not repeat the attempt per artifact or per table — one message per run
- Given any creation failure, should leave the analyzer's exit code untouched
- Given a cluster that is unreachable, should report the connection failure rather than a schema problem: a reader told to check permissions when the cluster is down loses the thread
- Given the credential is valid but the database does not exist, should say so distinctly — `fab-test` creates tables, never databases, and that boundary should be visible in the message

---

## Documentation For All Three Callers

**Requirements**:
- Given the human, should read that the tables are created automatically on first use, with the manual KQL kept as a fallback for a governed cluster rather than as a prerequisite
- Given the pipeline, should not need a setup step before its first telemetry run
- Given the agent, should read what `fab-test` creates, what it never creates (the Eventhouse, the database), and which permission each needs
- Given the Eventhouse Shipping epic's non-goal, should record that this epic reverses it and why, rather than leaving two documents that disagree
- Given a reader of the schema, should find that `Data` is deliberately the only column and downstream functions own the transform
