# Actual supported GPU smoke evidence — 2026-11-01

Candidate `38fb37ae748e5a7c6430012dc4610c1a7d7abe2a`; tested Bindsight wheel SHA256 `3e0ee56bcadb88e852ec20243b81b3a8a1226d857886872b4007da52517edea2`.
All eight source/protocol/runtime/weight/geometry/sequence/prediction checks passed. The installed CLI imported the actual archive twice, preserving original metrics and archive bytes.

The bounded smoke used one HER2 target fragment (142 residues), one RFdiffusion trajectory, two ProteinMPNN sequences (60-residue binders), and one Boltz draw per sequence with hosted MSA. Both predicted 202-residue complexes, confidence JSON and complete PAE/pLDDT arrays are retained byte-for-byte, alongside the original target, RF backbone, both RF trajectories and original MPNN FASTA.

- P04626_binder_42_seq0: ipTM 0.138935; independently calculated interchain PAE 25.852463.
- P04626_binder_42_seq1: ipTM 0.637975; independently calculated interchain PAE 14.255961.

These measurements establish successful exercised software paths. They are not binding hits, biological efficacy, numerical equivalence with the old runtime, or a larger screening campaign. In particular, the first ipTM is low. Historical scientific results were not rerun. Live Colab and Modal remain untested. Sampled device-memory usage does not establish a true peak or larger-workload capacity.

`manifest.json` describes this selected public subset. `job/original-manifest.json` is the complete original job inventory and therefore also describes omitted files. Model weights, environments, TRB/pickle payloads and the original transport archive are not redistributed here; the latter's hash and size are retained. Original scientific file bytes and all numeric/hash receipt fields are unchanged. Each text-only private-path substitution records the original hash, byte count and transformation; public repository identities remain intact.

`methods/` contains immutable snapshots of the actual extraction, scientific verification and installed-import methods. They were copied without execution. This selected public subset omits the full archive and serialized metadata, so it is not a standalone replay kit.

The initial verification used a Windows-built Boltz wheel reference and reported an identity mismatch. `history/verification-reference-v1.json` retains that record. Changing only the ZIP host-platform header from Windows to Unix exactly reproduced the observed Linux wheel SHA, with all112 decompressed members identical. `wheel-reference/` retains the proof; the unchanged verifier then passed all eight checks. No scientific output or installed package was changed to obtain that pass.

`security/` compares the actual final freezes with the audited versions and preserves original dated reports; it does not claim a new advisory query. DGL's distributed-RPC advisory remains unpatched and RPC is unsupported. Package database and source-package exclusions remain explicit. `interpretation-review.json` records a focused Claude review of supplied evidence, not independent execution.

This bundle records candidate scientific and CI-related evidence. Final release publication and website identity are separately attested in the release record.
