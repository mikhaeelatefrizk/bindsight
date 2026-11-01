# Canceled full GPU attempt — candidate 0.3.8

This record describes the first attempted RFdiffusion → ProteinMPNN → Boltz
workflow on 2026-11-01. It is **incomplete execution evidence, not a successful
full-pipeline or numerical-validation result**. The candidate is identified by
its wheel checksum in `observations.json`; it must not be confused with the
later corrected release candidate.

The persisted logs show runtime setup and CUDA checks, followed by RFdiffusion,
ProteinMPNN, the executor message `designer produced 2 designs`, and the first
Boltz prediction command. That command included `--use_msa_server` and seed
`2498828884`. The saved input and source review indicate the automatic hosted-MSA
protocol; this was not an empty-MSA run. A launch command does not prove that a
remote MSA request or a model prediction actually finished.

The progression and executor message record completion of the design stages in
the executor flow. The output download contains no raw generated backbones,
ProteinMPNN sequences, prediction structures, confidence records, or completed
result archive. Those scientific artifacts therefore could not be independently
checked. The saved strict verifier recorded eight incomplete checks, zero passed
checks, and zero failed checks; absence of a recorded failure is not a pass.

The requested session budget was 7200 seconds. The coordinator recorded the final
backend status as `CANCEL_ACKNOWLEDGED`. No raw backend status response or exact
cancellation timestamp is included in this evidence. Outer-log times are elapsed
log times, not a measured duration of each scientific stage. In particular, the
nested tool output was buffered, so the precise state of the first Boltz process
at cancellation is unknown.

Static source review identified unbounded retry/polling behavior in the then-used
MSA client. Waiting for hosted MSA was a plausible explanation, not a confirmed
cause. Slow prediction, preprocessing, or another child-process stall cannot be
excluded by the retained logs. This record does not assign an MSA outage, GPU
failure, or scientific error as the cause.

`manifest.json` hashes the retained originals using logical source roles. Private
account/kernel identifiers, local home paths, and unrelated coordinator fields
are omitted. Source roles are deliberate aliases, not original filenames. The
original artifacts remain untouched; model weights, input structure bytes and
complete logs are not copied into this compact supplement. Selected observations
and short log excerpts are transcribed; they are not a substitute for missing
raw scientific outputs. No credentials or private mail are included.
