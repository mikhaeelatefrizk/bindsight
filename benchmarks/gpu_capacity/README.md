# Measured GPU capacity on a free Kaggle T4

The VRAM figures in `designer_benchmark/RUN_FREE_GPU.md` were estimates until
this run. `t4-ca9-377aa.log` is the unedited Kaggle kernel log behind them.

## What was measured

| | |
|---|---|
| Card | Tesla T4, 15,360 MiB, compute capability 7.5, driver 580.159.04 |
| Stack | RFdiffusion -> ProteinMPNN -> Boltz-2, the free arm |
| Target | CA9 (Q16790), UniProt-topology extracellular range 38-414 — **377 residues** |
| Job | 10 RFdiffusion trajectories, 2 ProteinMPNN sequences each, 20 designs validated |
| Environment build | 5.9 minutes for both micromamba environments |
| Design + validation | 189.2 minutes |
| Total kernel time | 195.2 minutes |
| **Peak VRAM** | **14,859 MiB of 15,360 — 97% of the card** |

## Why it is a measurement and not a reading

`gpu_report` is called at stage boundaries, which is precisely when no
subprocess is holding GPU memory: RFdiffusion and Boltz-2 run under separate
micromamba environments that have already exited. Sampled that way, a 3h49m
design run reported 0 MiB at every stage while plainly using the card.

A background thread now samples device-wide usage every five seconds and
reports the high-water mark. Device-wide is deliberate — torch's own counter
lives inside whichever environment allocated the memory, and that is never the
process doing the reporting.

## What it implies

The free arm fits a 16 GB card with roughly 500 MiB to spare on a 377-residue
target. That is not comfortable headroom. A larger extracellular domain, more
simultaneous trajectories, or a validator with a bigger footprint should be
expected to exhaust the card rather than merely slow down.

The 377-residue figure is the only size measured so far. Do not read it as a
constant: attention memory grows with sequence length, so a smaller target
leaves more room and a larger one may leave none.
