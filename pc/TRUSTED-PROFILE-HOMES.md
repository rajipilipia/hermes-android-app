# Trusted profile-home junction repair (source verification)

**Not live acceptance / not full Desktop parity.** The source repair covers
policy, original service calls, history, attachments and picker-worker lifetime.
An inactive 11-profile access-policy candidate has passed real-PC filesystem
preflight. The active policy, profile configurations, service, gateway, login,
upstream source and devices have not been changed by this repair.

## Explicit mapping, unchanged schema

The existing schemaVersion 1 `expectedHome` is the exact canonical declaration.
For a named profile it may name a separate canonical directory only when:

- the manifest's real `root` remains the distinct default home;
- exactly `root/profiles` is a Windows directory junction owned by the process
  user or the built-in Windows Administrators group (mount-point tag only);
- that junction resolves to the declared home's canonical parent;
- the child is an ordinary directory with the exact profile name;
- the declared canonical home and its ancestor chain pass the existing no-link
  checks, and its owner matches the host owner;
- junction identity, owner, link text, target, canonical ancestor identities,
  and manifest fingerprint remain unchanged through validation/admission.

No storage-root-wide grant, alias map, wildcard, permission, profile-name alias,
resolve-before-validation exception, or hardcoded machine path is introduced.
Default `expectedHome` must still equal `root`. Launch home is still explicit.
Workspaces additionally cannot overlap declared canonical profile homes. Generic
`_canonical_path`, workspace and filesystem no-reparse checks are unchanged.

The new external-mapping path pins the bound resolver callables as well as the
existing server/REST resolver binding. Legacy non-junction manifests preserve
existing resolver restoration behavior. Both runtime resolver results must be
either their exact declared canonical home or their one exact verified lexical
`root/profiles/name` path; other spellings/paths are not resolved as authority.

## Implemented service slice

`BoundPolicy.profile_home(owner)` reauthorizes, holds canonical-directory guards
and the exact declared junction through I/O, then reauthorizes at settlement.
Canonical directory guards reuse the existing `.pc-guard-*` held-sentinel and
RW-sharing/no-DELETE mechanism: original atomic child saves work, but directory
replacement and reparse conversion remain blocked. Temporary guard files contain
no user data and are removed at settlement. The junction itself has read-only
sharing and cannot be rewritten/deleted. Canonical homes remain user-owned;
privileged-group ownership is accepted only for the exact declared junction.

`Adapter.invoke` retains this lease through settled original ASGI calls, including
session/config services and cancellation. Original lexical profile paths remain
safe because their exact junction cannot retarget during use; no global resolver
patch is introduced. The model-picker worker owns its own lease until its work
settles, even after the caller's deadline.

Attachments validate a live session's stored home against only the bound canonical
home or its one declared lexical alias, then use canonical storage and a held home
through the actual copy. Foreign or missing named-owner homes cannot fall back to
Default. `pc.history.execute_history` uses the lease for every exact
selected/granted store, opening canonical `home/state.db` and holding the home
through DB close and DTO materialization. Generic lab `Policy` remains compatible.

The regression uses a real synthetic Windows junction and real Windows handles;
it asserts that the finite history service gives its DB constructor the canonical
path and cannot rename the home while the service owns it. The DB constructor and
final list materializer are synthetic spies, not claimed real-runtime acceptance.
The existing broader PC suites independently exercise pinned original DB/history
and authenticated composition behavior in scrubbed homes.

## Verification gates before external-home activation

- Finish fresh final-source full regression and canonical npm gates.
- `pc.production_proof --cli-junction` exercises original authenticated startup,
  separate Default and canonical named homes, profile discovery, exact history,
  no Default-store fallback, and teardown. It uses a synthetic provider and homes;
  it is not real Nous, model, audio or Android acceptance.
- Independently confirm the atomic-save correction and privileged-junction owner
  rule. A prior review correctly rejected read-only directory leases because they
  broke original atomic saves; that reproduction now has a passing regression.
- Activate only after those gates, using the separately approved controlled
  service handoff and rollback. Then recheck every real profile through Android.

## TDD evidence

Run with the read-only lab interpreter through `pc.production_test_runner`.
Logs are in ignored `.cache/port-checkpoints/`:

- `pc-production-source-trusted-homes-red-behavior.log`: exit 1, real junction
  rejected by `expectedHome does not match root/profile` before the repair.
  The earlier `trusted-homes-red.log` was a discarded new-schema experiment,
  not the behavioral RED used for this implementation.
- `pc-production-source-trusted-homes-guard-red.log`: exit 1, missing canonical
  I/O guard and resolver replacement not denied; subsequent guard GREEN passed.
- `pc-production-source-trusted-homes-history-red.log`: exit 1, finite service
  attempted the lexical DB path; canonical-store/held-home GREEN then passed.
- `trusted-homes-full-checkpoint` exposed a legacy callable-restoration
  compatibility failure; the fix scopes identity fencing to external mappings
  without changing the existing assertion.

Final focused/full commands and results are supplied in the handoff; they are
source evidence only, not live managed-runtime, model, audio, Android, or parity
acceptance.
