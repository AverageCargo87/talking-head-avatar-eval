# The metrics, how they work and where they break

Four numbers, each born from one argument that could not be settled by eye. All of them are
cheap (OpenCV + NumPy + ffmpeg, seconds per clip on a CPU) and deliberately crude: they are
instruments for comparing engines and variants, not lab-grade measures.

## 1. Face liveness: `avatar-metrics liveness`

**Question:** does the engine animate the whole face, or paste a mouth onto a still or looped base?

1. Find the face (OpenCV Haar cascade, largest face on the first frames that have one; or pass
   `--face-box x,y,w,h`). Upper zone = 15-50 % of the face height (brows, eyes), lower zone =
   60-100 % (mouth, jaw).
2. For each pair of consecutive frames: mean absolute grey-level difference inside each zone.
3. `mouth` and `upper` are the means of the two series, `ratio = upper / mouth`, and
   **`coupling` is the Pearson correlation of the two series**.

Coupling is the discriminator. In a generative engine the brows and eyes move in the rhythm of
the speech; in a patch engine the upper face comes from an unrelated idle loop.

| what you see | ratio | coupling |
|---|---|---|
| mouth patch on a still photo | ~0 | low (noise) |
| mouth patch on a looped base | moderate | low |
| whole face driven by speech | ~0.5-1.3 | high (0.85+) |

Guards added in this repository: when both zones are below 0.05 (a still frame), ratio and
coupling are reported as 0 instead of a ratio of two codec noise floors. Without that guard the
"still portrait + audio" control showed a "coupling" of 0.59, produced purely by key-frame pulses.

**Limits.** Motion energies depend on resolution, face size and compression: compare `mouth` and
`upper` within a clip, compare `ratio` and `coupling` across clips. Global motion (a zoom, a camera
shake) moves both zones together and passes as perfect coupling: the "breathing zoom" control in
[results/MEASURED.md](../results/MEASURED.md) reads ratio 0.94, coupling 1.00. That is why
liveness is never read alone.

## 2. Lip-sync offset: `avatar-metrics offset`

**Question:** is the picture ahead of or behind the sound, and by how much?

1. Mouth region = 55-100 % of the face height, middle 60 % of its width.
2. Mouth "openness" per frame = grey-level standard deviation in that region (an open mouth puts
   a dark cavity next to lips and teeth).
3. Audio envelope per frame = mean absolute amplitude of the 16 kHz track in that frame's window.
4. Correlate `mouth[t + lag]` with `envelope[t]` for lag in -20..+20 frames and take the best.
   `+N` = picture LATE by N frames, `-N` = picture EARLY.

Verdicts and their guards:

- **mouth does not move**: openness spread below 0.25 grey levels. Without it the z-scored codec
  noise of a still frame correlated with the audio by chance (r = 0.16 at a random lag).
- **no link**: best correlation below 0.10. Shifting the track will not help: the lips do not
  follow the speech.
- **no clear peak** (added here): the best lag beats every lag at least 3 frames away by less
  than 0.03. On the bearded host the curve is a plateau (0.20-0.22 from +3 to +9 frames) and the
  "best" lag is noise.
- otherwise: in sync (within one frame) or LATE/EARLY by N ms.

**The threshold is relative.** On a clip known to be in sync (lip-sync over a still portrait)
the best correlation in August was only 0.24, and the lesson hosts measured here peak at
0.28-0.36. A first version used 0.2 as "no link" and declared a good clip broken.

**Cross-check against SyncNet.** On the 30-second host clip the two tools agree on the change and
disagree on the zero point by one frame:

| clip | this metric | SyncNet (project notes) |
|---|---|---|
| audio as rendered | -1 frame | -2 frames |
| audio moved 80 ms earlier | +1 frame | 0 frames |
| difference | **2 frames = 80 ms** | **2 frames = 80 ms** |

**Limits.** Grey-level spread is a proxy: beards, teeth visibility and lighting change it. Small
faces (about 150 px in the 832x480 two-host shot) and dialogue audio (the listener's mouth is
shut while the other host talks) give "no link". Use SyncNet (`local/syncnet_offset.sh`) for a
second opinion, and your eyes for the verdict: a second lip-sync pass once raised the SyncNet
confidence to 7.3-7.5, yet the result was rejected on sight ("uncanny valley, the lips miss").

## 3. Identity seam: `avatar-metrics identity`

**Question:** when the lesson switches from a prerecorded clip to a live engine, is it visibly a
different face?

- Face embeddings on 12 evenly spaced frames per clip (default backend: insightface `buffalo_l`).
- Similarity to a reference portrait: mean, spread across frames, worst frame.
- **Seam between two clips = cosine of their mean embeddings.** Not the difference of their
  similarities to the reference: two different faces can be equally far from a third one (a
  mistake made once and fixed; `tests/test_identity.py` pins it).

Thresholds used: 0.90+ the switch is invisible, below 0.85 a visible cut. Measured in August:
same engine 0.942, cloud vs local 0.815-0.855; the cloud engine also drifted inside its own clip
(0.775 to the source portrait, worst frame 0.729).

**Licensing note.** insightface's pretrained models are for non-commercial research. The backend
is optional (`pip install .[identity]`); the `pixels` backend exists only to test the seam
arithmetic on synthetic faces and knows nothing about identity. No identity numbers were
re-measured for this repository: that would need those weights.

## 4. Frame motion: `avatar-metrics motion`

Mean absolute difference of consecutive frames at 64x64 grey over the first 9 seconds. At that
size the head and the mouth produce nearly all of it, so it tracks "how jumpy does the host look".
It settled a prompt argument on the InfiniteTalk hosts: the "lively expressions" prompt measured
2.25, the "calm TV presenter" prompt 1.74 (project notes); re-measured here on the committed clips:
2.21 and 1.71.

## How the metrics are verified offline

`avatar_metrics.synth` draws a flat cartoon head with OpenCV and drives it with a synthetic
syllable envelope, then muxes it with matching synthetic audio through ffmpeg. Because each part
of the face is driven on purpose, the expected answers are known:

| synthetic clip | liveness must say | offset must say |
|---|---|---|
| still face + audio | 0 / 0 | mouth does not move |
| mouth patch, static base | ratio ~0 | in sync |
| mouth patch, looped base (blinks, brows, sway from an idle loop) | coupling low | in sync |
| whole face driven by speech | coupling high | in sync |
| whole face, picture 3 frames late / 2 frames early | unchanged | +3 / -2 frames |

`python -m pytest` checks all of it (43 tests, about 10 s). No face of any real person is involved.
