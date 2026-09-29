# Unfamiliar-user check

Give a first-time user the [README quickstart](../README.md#install-and-get-a-first-result),
the [demo guide](demo.md), and a fresh machine or environment without this checkout. Ask them to
record whether they can:

1. Explain that the repository builds species-neutral physical Seascape products and that the
   quickstart's pinned revision differs from this development branch.
2. Install the package, run `seascape --help`, and finish the offline demo without credentials,
   source downloads, pytest or Jupyter.
3. Locate its Parquet, manifest, validation report and two figures inside the demo-owned workspace;
   identify synthetic provenance and distinguish missing depth from measured zero.
4. Find the product reference, source requirements, scientific limitations, and the
   release-backed metric-matrix command. Explain why a synthetic PASS is not a regional release.

Record tester identity/experience, revision, platform, exact commands/exits, artifacts, confusing
steps and fixes. No unfamiliar tester was available during scientific hardening; this checklist
is prepared but the human trial remains pending. Automated consumer checks are separate evidence.
