# First stock failure and stop observations

PERF-01's fc554 trial ended with `motion_stop_unknown`. The final adapter
receipt retained only `RuntimeError`; later empty movement lists could not
recover the missing reason. This diagnostic addition does not repair that
failure or change controller authority, RPC order, freshness, waits or retries.

`Hub` records one immutable `first_failure` after the existing unknown latch.
Its stage distinguishes dispatch POST/response, stop preflight, stop POST and
stop observation; its cause distinguishes request failure, expired observation,
invalid observation and absence timeout. Only fixed error classes, numeric HTTP
status, canonical owned UUID, Hub boot and Hub-monotonic timestamps survive.
Exception text, URLs and payloads do not. A failed dispatch without a validated
UUID explicitly has no owned UUID or stop receipt.

A separate `stop_receipt` records at most two existing preflight observations,
the single existing POST attempt and independently observed UUID absence.
`completed=false` and `finished_at=null` mean the operation has not finalized;
unknown observation stays null. A later absence does not clear the old latch or
overwrite the first failure. The stop containing that first failure is retained
and finalized even if a subsequent explicit operation observes absence.

The stock lane's private thread-local operation token binds these records to the
actual adapter request. Failure before a new `stock_begin` cannot inherit an old
UUID or request's diagnostic. Tokens are neither exported nor kept in a growing
map. Published views are fresh whitelisted copies. Diagnostic failures are
best effort and cannot replace the original exception or control result. A
standalone Hub without the autonomous package retains its existing control
behavior with diagnostic data unavailable.

The ordinary follow/expression receipt, adapter status, `run_session`'s
`motion_after`, production log summary and standalone production-status probe
carry `stock_diagnostics`. A snapshot is available after its owner publishes;
this is not a deadlock detector or physical stop certificate. Receipts do not
prove pose arrival, motor hard-stop timing or the cause of an earlier trial.

Reproduce offline from the checkout (fixture children/loopback only):

```sh
PYTHONPATH=src:tests python -m unittest test_stock_diagnostics test_stock_motion_routing test_stock_stop_reconciliation test_stock_motion_adapter test_person_follow test_response_performance test_production_operations
```

These checks cover actual Hub/Adapter/session/public consumers, normal absence,
404/500/transport/read failure, stale/malformed preflight, invalid dispatch UUID,
retained failed-stop observations, immutable projection and diagnostic-failure
parity of actual IO order, old flags and exceptions. Hardware acceptance remains
open in Issue30; a new candidate and measurement window require the lead.
