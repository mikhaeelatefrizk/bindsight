# Production checkpoint loader CPU acceptance — 2026-11-01

Both authenticated Boltz checkpoints constructed real `boltz.model.models.boltz2.Boltz2`
models through `verified_checkpoint_loading` and the actual Lightning loader.
The helper is the exact LF source from `38fb37ae748e5a7c6430012dc4610c1a7d7abe2a`, SHA256 `23367a3e5c4cb083472d450d390077d48d43061357377318c0e5265a4801aff3`.
It was supplied as an explicitly authenticated overlay on the previously tested
`493938376ffbbd554998c6b559a7c265827ffb73` candidate wheel, SHA256 `a2cf2d8b8d726a66b802114f1799a9bc9888a93e05a3c9fe40a2e577f608c53d`. This is a focused production-loader
test, not execution of the entire new wheel. The kernel used no GPU and ran no
predictions; no full scientific workflow completion or equivalence is claimed.

The probe tested the production source and class-loader guards, the expected
10/7 checkpoint-global inventories after clearing the ambient user registry,
`weights_only=True` loading through the production helper, upstream model
constructor arguments, CPU tensor state, eval mode, and restoration of the
original class descriptor, ambient object identities, and global `torch.load`.
Confidence construction used the GPU CLI's `use_trifast=True` constructor flag
and full-PAE output setting; no forward pass or Triton computation occurred.

Checkpoint SHA256 and byte counts match the fixed publisher assets before and
after loading. Confidence has 5,102 float32 state tensors / 521,047,871 elements;
affinity has 5,539 / 529,378,245. The original model files were not changed.
The complete baseline safe-global inventories are retained; Torch's registry is
not assumed empty. Identity-set restoration is verified rather than list order.

`base-runtime-receipt.json` describes the preceding CPU provisioning check, so its
`models_downloaded=false` remains unchanged and is correct for that stage. The
subsequent authenticated downloads and real model construction are recorded in
`checkpoint-result.json`. `bootstrap-result.json` confirms owned runtime/model
data were removed before export. The installed package inventory, recipe and
source wheel match the actual failed GPU run, apart from normalized local URLs.

The manifest hashes public files and their original inputs. JSON is reformatted
and CPU/candidate filesystem paths become `/CPU_RUNTIME`, `/CPU_PROBE`, or
`/CANDIDATE_SOURCE`. The loader source retains exact Git bytes and its licence
header. Full logs, credentials, temporary signed URLs, private dataset paths,
model bytes and runtime environments are omitted. Previous v1/v2 evidence is
preserved outside this package; v1's ordering-sensitive diagnostic assertion is
not relabeled as a successful production check. Actual GPU acceptance remains
a separate requirement.
