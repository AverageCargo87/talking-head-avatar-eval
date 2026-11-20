# Measured in this repo

Measured on 2026-11-20 with `python scripts/measure_samples.py` on the clips committed in `samples/`
and on the synthetic set rendered by `avatar_metrics.synth`. Re-run the script to reproduce.

Motion energies (mouth, upper, motion) are mean grey-level differences per frame and depend on
resolution and face size; compare them within a row. upper/mouth and coupling are scale-free.

## Lesson hosts (InfiniteTalk, own AI-generated characters) and controls

| clip | mouth | upper | upper/mouth | coupling | A/V lag (frames, ms) | lag r | motion |
|---|---|---|---|---|---|---|---|
| InfiniteTalk, Lena 9 s | 10.22 | 11.06 | 1.08 | 0.88 | -1 (-40 ms) | 0.36 | 1.71 |
| InfiniteTalk, Artem 12 s | 9.46 | 9.31 | 0.98 | 0.91 | no clear peak | 0.22 | 1.71 |
| InfiniteTalk, two hosts 17 s: Lena (left) | 6.35 | 7.70 | 1.21 | 0.94 | no link | -0.03 | 0.87 |
| InfiniteTalk, two hosts 17 s: Artem (right) | 6.34 | 7.16 | 1.13 | 0.92 | no link | 0.00 | 0.87 |
| InfiniteTalk, Lena 30 s, audio as rendered | 10.96 | 11.55 | 1.05 | 0.91 | -1 (-40 ms) | 0.28 | 2.21 |
| InfiniteTalk, Lena 30 s, audio 80 ms earlier | 10.96 | 11.55 | 1.05 | 0.91 | +1 (+40 ms) | 0.28 | 2.21 |
| Control: still portrait + audio | 0.01 | 0.01 | 0.00 | 0.00 | mouth does not move | 0.00 | 0.00 |
| Control: still portrait + breathing zoom + audio | 0.72 | 0.68 | 0.94 | 1.00 | no link | -0.07 | 0.24 |

Reading the table:

- **Liveness.** Every InfiniteTalk host lands in the whole-face corner (upper/mouth 0.98-1.21,
  coupling 0.88-0.94), where the Anam reference landed in August (1.09 / 0.89). The still
  portrait reads zero.
- **The zoom trap.** A slow breathing zoom over a still portrait moves both face zones together,
  so liveness reads 0.94 / 1.00. Its mouth-zone motion is 14x lower than a real host's, and the
  offset metric finds no lip link at all. No single number is enough.
- **The 80 ms shift.** Moving the audio 80 ms earlier changes the measured lag from -1 to +1
  frame(s): a 2-frame change; SyncNet reported -2 to 0. Where the two tools disagree on the
  zero point, remember this metric is coarse by design.
- **Where the offset proxy gives up.** On the bearded host the correlation curve is flat
  (no clear peak); in the two-host shot the faces are about 150 px and the audio is a
  dialogue, so each host's mouth is shut half the time: no link. SyncNet was also weak there.

## Synthetic ground truth

| clip | mouth | upper | upper/mouth | coupling | A/V lag (frames, ms) | lag r | motion |
|---|---|---|---|---|---|---|---|
| Synthetic: still face + audio | 0.00 | 0.00 | 0.00 | 0.00 | mouth does not move | 0.00 | 0.00 |
| Synthetic: mouth patch on a static base | 3.82 | 0.00 | 0.00 | 0.01 | +0 (+0 ms) | 0.97 | 0.30 |
| Synthetic: mouth patch on a looped base | 3.98 | 0.55 | 0.14 | 0.03 | +0 (+0 ms) | 0.97 | 0.36 |
| Synthetic: whole face driven by speech | 5.41 | 2.69 | 0.50 | 0.87 | +0 (+0 ms) | 0.94 | 0.66 |
| Synthetic: whole face, picture 3 frames late | 5.40 | 2.71 | 0.50 | 0.84 | +3 (+120 ms) | 0.94 | 0.66 |
| Synthetic: whole face, picture 2 frames early | 5.40 | 2.68 | 0.49 | 0.86 | -2 (-80 ms) | 0.94 | 0.66 |
