# Forcing Boltz-2 to fp32: what the patch touches

Every confidence number this project publishes comes out of Boltz-2, and on the
only hardware the free tier offers, Boltz-2 does not run as shipped. The kernel
patches one line of it before every run. This is the audit of that line.

## The patch

`bindsight/runners/kaggle_kernel.py` rewrites one expression in the installed
`boltz/main.py`:

```python
_txt.replace('precision=32 if model == "boltz1" else "bf16-mixed"', "precision=32")
```

with `assert _patched != _txt` immediately after, so a run whose patch did not
apply dies at that step instead of producing numbers under the wrong precision.

**Why it is needed.** Boltz-2 hardcodes `"bf16-mixed"`. bfloat16 requires compute
capability 8.0 (Ampere); the T4 this kernel pins is 7.5. The patch is required
for as long as the free tier is pre-Ampere, and `bindsight/plugins.py` records
the same threshold as a backend capability.

**Why it is safe** is the part that needed evidence rather than assertion, since
"it only changes a trainer flag" is exactly the kind of claim that is easy to
make and easy to be wrong about.

## Scope of this audit

`boltz 2.0.3`, the pinned version — wheel sha256
`5851dd10c7819d4c011534a4e5c9cc495d95e42e0e1336617a1e9e78d6c4cf12`. The audit is
a claim about this version and no other; `BOLTZ_PIP` is pinned exactly so the
claim stays attached to the artifact it was made about, and a test fails if the
pin and this document disagree.

## Findings

**1. There is exactly one trainer, and the patched line is one of its arguments.**
`Trainer(` is constructed once in the whole package, at `main.py:1112`.
`precision=` reaches it once, at `main.py:1118`. Nothing anywhere reads
`trainer.precision` or otherwise consults the trainer's precision setting.

**2. fp32 is a value upstream already ships on this exact argument.** The
expression replaced is `precision=32 if model == "boltz1" else "bf16-mixed"` —
one parameter, two values. The patch does not introduce an untried setting; it
selects the arm upstream already uses for boltz1.

**3. The dtype-conditional code is not on the boltz2 path at all.** Every
`d is torch.bfloat16` branch in the package lives in
`model/layers/triangular_attention/primitives.py`, reached only through
`model/modules/trunk.py`, which only `boltz1.py` and the v1 `confidence.py`
import. `boltz2.py` imports `trunkv2.py`, and `trunkv2.py` imports none of it.
The model bindsight runs never executes those branches.

**4. Were they reached, each is a bf16 compensation whose other arm is the fp32
behaviour it exists to emulate.** They are not alternative algorithms:

| site | bf16 arm | other arm |
|---|---|---|
| `softmax_no_cast` | `softmax(t, dim)` under `autocast(enabled=False)` | `softmax(t, dim)` |
| `LayerNorm.forward` | `layer_norm(...)` with weight/bias cast to `d` | `layer_norm(...)` |
| `Linear.forward` | `linear(...)` with weight cast to `d` | `linear(...)` |

Same operation on both sides. The casts are no-ops when `d` is already fp32, and
the `autocast(enabled=False)` wrapper is a no-op when autocast was never enabled.
`softmax_no_cast`'s own docstring states the intent — "Softmax, but without
automatic casting to fp32 when the input is of type bfloat16" — which is to say
the branch exists to reach, under bf16, the behaviour fp32 gives directly.

**5. The two genuinely different kernels are unreachable.** The DeepSpeed
Evoformer path casts to bf16 explicitly, and `_flash_attn` calls `.half()`. Both
are dead here:

- `deepspeed` is not a declared dependency of boltz 2.0.3, so
  `deepspeed_is_installed` is `False`, the `DS4Sci_EvoformerAttention` import
  never runs, and every `deepspeed_is_initialized` in the file is `False`.
- `use_deepspeed_evo_attention` defaults to `False` and is never set `True`
  anywhere in the package.
- `_flash_attn` is gated on `is_fp16_enabled()`, which requires autocast to be
  **enabled** *and* its dtype to be `float16`. Under the patch autocast is off;
  under stock `bf16-mixed` the dtype is bfloat16. It is `False` either way, so
  the patch does not change this gate — it was already closed.

**6. The one other precision-related call is untouched and points the same way.**
`main.py:977` runs `torch.set_float32_matmul_precision("highest")`, independent
of the patched line. "highest" means full fp32 matmuls with no TF32 substitution
— upstream's own stance that these numerics are worth paying for.

## Conclusion

The patch changes one PyTorch Lightning trainer argument to a value upstream
already ships for its other model, on a code path where no algorithm branches on
precision. The direction is toward more precision, not less. **It does not put
an asterisk on the ipTM numbers.**

What it does affect is speed and memory: fp32 activations are roughly twice the
size of bf16 and the T4 has no bf16 tensor cores to lose. Measured cost is in the
run logs — about 2.2 minutes per ~230-token complex.

## What the audit turned up on the way

Asking "which Boltz-2 is this an audit of?" found that nothing in the project
knew. `BOLTZ_PIP` was the range `boltz>=2.0,<3.0`, the kernel's install was
quiet, and `validator_version` — the one field in every metrics row that looks
like the answer — was a hardcoded `"2.0.1"` written regardless of what ran. It
sat beside real measurements in the same line, so it read as one.

All three are fixed: the pin is exact, the kernel logs what it resolved, and the
field is read from the environment (reporting `"unrecorded"`, never a
plausible-looking version, where Boltz is not importable).

**This leaves the committed designer-benchmark figures with no recoverable
validator version.** The ipTM values themselves are unaffected — they are what
Boltz-2 returned, and the `"2.0.1"` label never touched them — but which release
produced them cannot now be established. The first calibration job inherits the
same gap, having been submitted before the fix; its own design-versus-scramble
comparison is unharmed, because both arms were folded by the same installed
version in the same job. That is why the two arms are folded together and not
compared across runs.

## Known remaining gap

`CHAI_PIP` is still a range (`chai_lab>=0.6`). It is left alone deliberately:
no shipped backend can execute Chai-1r (it needs sm_80+, recorded in
`bindsight/plugins.py`), so it has produced no published number, and pinning it
to a version nothing has ever run would be a pin taken on faith rather than on
evidence. It should be pinned by the first run that executes it, to the version
that run used.

## Reproducing this audit

```bash
pip download 'boltz==2.0.3' --no-deps --dest /tmp/boltzsrc
cd /tmp/boltzsrc && python -c "import zipfile; zipfile.ZipFile('boltz-2.0.3-py3-none-any.whl').extractall('x')"
grep -rn "Trainer(" x/boltz --include=*.py                  # finding 1
grep -rn "precision" x/boltz --include=*.py                 # findings 1, 6
grep -rn "trunkv2\|triangular_attention" x/boltz --include=*.py   # finding 3
grep -rn "autocast\|bfloat16\|\.half()" x/boltz --include=*.py    # findings 4, 5
grep -i "deepspeed" x/boltz-2.0.3.dist-info/METADATA        # finding 5
```
