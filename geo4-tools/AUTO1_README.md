# AUTO1 monthly adapter

Trusted main only for cycle/readiness/publish/status; pull requests run11small contracts +3publication gates without secrets or mutation. Build is read-only; only protected production signing step sees existing key. Separate status writer never touches stable. Source compiler/algorithms remain locked by SOURCE_LOCK.json. Full fallback and compact exact reconstruction are required.

Manual default `rehearse` validates existing signed r1 and a distinct-domain readiness signature, without PBF/components, build or release/stable mutation. `cycle` requires allow_build=true if inputs changed; scheduled cycles allow one natural build. `resume` requires exact current executable SHA, trusted current workflow/main build origin, exact source/compiler/config/manifest/components and current predecessor CAS; no rebuild. Verified bundles21days. No forced overwrite or fake releases.

Initial schedule absent until readiness succeeds. Enable43 17 2 * * only after protection/environment/readback. Useful geo4-status commits are an audit record, not guaranteed prevention of GitHub60day scheduled-workflow inactivity disable. Stale cloud status is informational; Android has no token or remote workflow control. Production changed-source/compact evidence remains due on the first natural cycle, not proven by rehearsal.
