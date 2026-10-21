# GEO4 Stage 5: reviewed manual first-install publication

Only `workflow_dispatch` on the protected `geo4-publication` branch is permitted.
The read-only build job has no signing key. The publication job requires the existing
`geo4-production` Environment and owner approval. No PR, push or schedule trigger exists.

The 32 compiler/source files are byte-for-byte copies of accepted ref
`a49142154f1166f8d7af014c646acbc3e2fc0182`; `SOURCE_LOCK.json` enforces this.
No private TaxiHelper repository checkout or cross-repository token is needed.
The approved public geographic input capsules retain original provenance and NOTICE.

One full first-install closure is produced. There is no published predecessor and
no compact route is advertised. Existing compact transport is preserved unchanged.
Exact reconstruction, source-to-phone proof, immutable payload SHA, independent
Ed25519 verification and unauthenticated public payload readback gate the signed
`geo4-channel` commit. The legacy release and latest alias are never written.

Resources: accepted SDK-only cleanup, unchanged 14 GiB prebuild admission,
dynamic worst-case full packaging/reconstruction admission plus 2 GiB reserve,
sequential compiler/packing/reconstruction, independent publication runner.
Resource sampling includes setup and phase RSS/free-space observations; sampled
RSS includes shared pages and may miss short peaks. Limits stop rather than retry.
Seven-day verified build artifact retention allows inspection/recovery without an
automatic rebuild. No automated retry is enabled. First-install channel expectation
is ABSENT: after publication a fresh build is intentionally rejected.

Local targeted tests: `python -m unittest discover -s geo4-tools -p test_stage5.py -v`.
They use only tiny synthetic databases, a known test key, mocked publication APIs;
production key and large geographic compiler are never accessed by these tests.

Preparation is not hosted execution evidence. Actual resource headroom, package
sizes, hosted signing access and successful production readback remain to be
established by one separately authorized full manual run and owner Environment approval.
