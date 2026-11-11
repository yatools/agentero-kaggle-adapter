# Agentero Kaggle Adapter

Reproducible Windows portable adaptation of Agentero v0.15.4, pinned to
`fdacc2bc9da8a4e5569cf986acf2ef09e62d396b`.

Smart highlights retain 32 sentences and five rubric dimensions per batch. The
desktop client submits one batch at a time, with a 300-second total HTTP deadline.
Cancellation drops the active request. Invalid scores fail the job rather than
appearing as completed work. The official updater is disabled in this portable build.

This repository contains adaptation source, tests and build instructions only.
It contains no model weights, papers, Kaggle credentials, user settings or vendor
built-in gateway credentials. Compile-time vendor services are unavailable in
this contributor build; existing user-configured services can still be used.

## Build

Run **Build Windows portable adapter** manually in GitHub Actions. The standard
Windows runner fetches the exact upstream commit, applies `patches/agentero.patch`,
runs transport/highlight tests, and builds the app using the upstream lockfiles.
The draft release `adapter-v1` receives the ZIP, SHA256SUMS and BUILD-MANIFEST.
No GPU is used for building. No updater or vendor signing secret is required.

Only the final ZIP needs downloading. Keep the original Agentero installation;
exit it before opening the portable build because both use the existing app data.
Back up local settings before first use. The companion deployment workspace supplies
the launcher and the separately authenticated local-to-Kaggle relay.

## Runtime

The existing model is mounted from a private Kaggle dataset and never downloaded
to the Windows PC. The decision endpoint remains:

`http://127.0.0.1:8080/v1/systemone` (model `elephant-1`).

The llama.cpp internal slots remain separate from client request concurrency.
Whole-paper processing may take several minutes; each HTTP request starts its own
deadline only when dispatched. Start and stop GPU sessions with the existing controls.

Upstream source: https://github.com/poco-ai/Agentero

Original license and third-party notices are retained in the portable package.
This is an independently adapted build, not an official Agentero release.

## Companion KIS patch

`patches/kis-cloud-support.patch` applies to KaggleInferenceServer commit
`0d6fd399b6bfa075e96f69371f090159744d127d`. It adds mounted-dataset model access,
the pinned Elephant metadata compatibility copy, and authenticated cancellation.

Each forwarded decision attempt receives a fresh `X-KIS-Request-ID`. The internal
`POST /admin/cancel?session=...&request_id=...` route is protected by the existing
server key, rejects a different session, and is idempotent. Cancelled ids are held
briefly to reject inference requests that arrive late through a buffering tunnel.
An attempt is cleaned up before retrying; an unconfirmed cancellation blocks a
duplicate retry. Decision audit records contain counts and timings only.

`scripts/install_portable.py` verifies the archive, source/patch fingerprints and
every resource before extracting into a versioned application directory.
`scripts/launch_portable.py` backs up local settings privately and refuses to start
while another Agentero instance is running. These scripts never upload settings.

The installer exposes the verified executable as `Agentero-Kaggle.exe` so desktop
launchers can distinguish it from an installed official copy. Both executable
names contain identical bytes. The launcher detects either process name.
