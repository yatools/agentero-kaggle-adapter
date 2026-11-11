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
