# Peer status: bounded polling inside the existing freshness budget

The [2c17 trial](releases/2026-11-27-2c17c0ff6b7d-combined.md) ended with a
317.809ms peer status age, while the operator and reducer were still fresh.
The saved hardware report does not retain the individual HTTP request timings;
this change does not identify the historical network/server delay.

An actual production `run_session` replay with a loopback HTTP AudioPeer,
PersistentPeer, real workers/lease and SQLite reproduced a controllable gap:
after the old 100ms start cadence, one successful status response taking
237–243ms exceeded the unchanged 300ms receipt guard. Three of three replays
with a 230ms injected response delay withdrew only for `status_fresh`;
the no-delay control did not. No transport error, operator expiry or reducer
expiry was needed.

## Scheduling contract

STARTING retains the 100ms cadence. After a successful ACTIVE receipt, the next
due time is its observation time plus:

`min(100ms, max(25ms, 300ms - client.timeout - 25ms))`.

There is one retained status Job and at least25ms between starts: at most40
starts/s, no catch-up loop, parallel request, cached-success substitution or
retry on failure. Slow calls reduce the rate themselves. Failed/foreign/stale
receipts retain the existing fail-closed behavior. The300ms freshness guard,
HTTP timeout, reducer/operator/UUID guards, authority binding and STOP are
unchanged. A timeout too large to fit the budget still uses the load floor;
this cannot make a late receipt fresh. Positive finite numeric timeout is
required; old substituted clients lacking the attribute use PeerClient's.25s
default, while malformed present values are rejected.

The25ms allowance is a scheduling margin, not a hard runtime guarantee. A
sufficient reducer stall or genuinely late reply still withdraws authority.
The negative replay with a successful350ms reply and configured500ms transport
timeout continues to latch `status_fresh`; the transport succeeding does not
renew a stale receipt.

## Local load and synthetic voice comparison

Serial baseline/head fixtures used the ordinary production scheduler, actual
loopback HTTP peer, synthetic STT/TTS/PCM, one input and one spoken result.
The lease fixture uses the existing production200ms reducer progress policy.
No hardware, production service or real inference was used. Each intended
window was2s; failed baseline cases ended earlier. Rates below include startup;
they are descriptive samples, not hardware capacity guarantees.

| Fixture | Baseline | Updated |
|---|---:|---:|
| Fast status starts/s |9.58|25.13|
| Fast status median client call,ms |1.632|1.925|
| Fast status median server handler,µs |56.1|75.2|
| Fast case max reducer tick gap,ms |52.60|55.83|
| Fast capture→observed speech receipt,s |.15809|.16714|
| Repeated200ms delay |freshness withdrawal|no withdrawal|
| One230ms delay |freshness withdrawal|no withdrawal|

Updated repeated-slow ACTIVE starts were4.06/s; peak actual status jobs stayed1
in every case. All cases completed their one synthetic audio/TTS chain and
cleanup; the old slow cases still lost session authority. Updated repeated-slow
capture→observed speech receipt was.16865s versus.21908s in the shorter failed
baseline; single-late was.17665s versus.20953s. Receipt observation is sampled
by the fixture publisher, not an acoustic timing measurement. These n=1
comparisons do not establish zero overhead or a voice speedup. The additional
fast-peer request load is intentional and must be checked on the next selected
hardware candidate before accepting the whole session.

`PYTHONPATH=src:tests python -m unittest test_peer_status_schedule` exercises
actual loopback delayed success, bounded fast starts, repeated slow replies,
synthetic voice, genuinely late success and timeout validation. Related session,
lease and terminal-drain tests preserve the owner/STOP contracts. The hardware
remains stopped until a separately assigned installation/trial window.

Private numeric evidence and executable reproduction are retained under
`~/reachy-release-backups/20261127-peer-poll-offline`; the baseline was exact
`2c17c0ff6b7d499d9d2e8082651d12ea34cee676`. No private transcripts/configs are
needed for these fixtures.

The exact344c71cd push CI failed the existing three-stream retirement fixture
with `audio_completion_unknown`; its first predicate was not retained. The
same exact PR CI and local full suite passed. This historical cause remains
unknown, rather than being assigned to the polling change or called a flake.
The fixture now retains a bounded first-unknown projection on failure.

Separate local base/head and fallback/PersistentPeer comparisons reproduced
`Local terminal references changed`. A controlled ordinary joined-loop
interleaving establishes its cause: after the remote retirement ACK, a new
operator joint-stop worker can still be returning locally. Stream/generation,
full consumed cursor and stop receipt remain valid, but the old commit treated
this new live reference as an identity error. The loop now checks identity
under the existing playback lock and retains that same ACK/job until the
actual local references return. Admission stays closed; there is no repeated
remote retirement RPC, blocking wait or new deadline. Missing/foreign identity,
unexpected local ownership and invalid final stop/cursor receipts still fail.
STOP continues through the existing immediate withdrawal and bounded drain;
a permanently held reference remains busy and prevents successful cleanup.

`PYTHONPATH=src:tests python -m unittest test_terminal_retirement` checks the
actual ACK→joint-stop→commit sequence, one remote ACK, closed admission, STOP
with a held worker, wrong identity while busy and final receipt validation.
This fixes the independently reproduced retirement race; it does not establish
the cause of the older CI `audio_completion_unknown` or hardware latency.

The subsequent CI projection narrows the failure to remote retirement before
ACK (`withdrawn=true`, phase `RETIRING`), with local cursor/stop flags known and
no lease/reducer expiry. A separate controlled capacity reproduction holds four
real HTTP handlers: HTTP renewal, status, observation and PCM. The fifth
`/retire` connection is rejected (`RemoteDisconnected`), latching unknown with
no retry or new admission. The historical CI's exact transport exception was
not retained, so this controlled result is not a retrospective network claim.

Positive joined-loop fixtures now match the selected production transport set:
real authenticated UDP renewal and PersistentPeer for status/observation.
`deploy/current/hub/systemd/reachy-production.service.template` supplies
`--lease-datagram-port 8782`; `production_start.py` forwards it, and
`companion_session.main` constructs DatagramRenewal, persistent AudioPolling and
persistent status. The fixtures open a real UDP receiver and assert successful
renewals with the exact authority binding. No timeout/capacity/lease guard is
changed. HTTP fallback remains covered by the existing forty-completion
protocol test and an explicit four-handlers/fifth-retirement rejection test.

A second serial n=1 base/head comparison using this complete transport set
reproduced the old slow-response freshness failures and the updated success:

| Fixture metric | Baseline2c17 | Updated runtime346e7a27 |
|---|---:|---:|
| Fast status starts/s |9.48|24.25|
| Fast status median client call,ms |2.037|2.473|
| Fast status median handler,µs |50.7|68.4|
| Fast maximum reducer tick gap,ms |55.98|60.68|
| Fast capture→observed speech receipt,s |.21846|.16609|
| Repeated200ms / single230ms response |freshness withdrawal|no withdrawal|

All six cases completed one synthetic STT/TTS chain and cleanup; peak status
jobs stayed1. Updated repeated-slow starts were4.80/s including startup. The
first comparison above used the older HTTP-renewal fixture; neither comparison
measures acoustic latency or proves zero overhead. Paired JSON and the exact
fixture are retained under `peer-poll-offline/production-transport`.
