# Choosing the video teacher by measurement

The AI teacher of the platform speaks with a Russian TTS voice. In July-August 2026 it needed a
face: a talking-head video avatar that lip-syncs to that voice in real time. This is how the
vendor was chosen, in four rounds, and why the last word went to a metric instead of to taste.

All numbers below come from the project's working notes of that period. No vendor media is
published in this repository: their stock faces are real actors licensed to the vendors.
Research rounds were run by AI research agents under my direction; the reachability probes and
the face measurements were run by me.

## Round 1 (15 July): which axis matters

- "2D or 3D" turned out to be the wrong question. The real split is **photoreal = cloud 2D
  neural rendering billed per minute (or your own GPU)** vs **cheap at scale = a 3D avatar
  rendered in the student's browser for ~0 per minute**.
- **Audio-driven engines only.** Text or phoneme-driven visemes are English-centric; one major
  cloud TTS returns ready visemes only for en-US. Audio-driven engines read the acoustic signal,
  so Russian simply works and the existing voice stack stays.

## Round 2 (18 July) and round 3 (17 August): gates and a wrong assumption

- 26 research agents compared 9 providers against two gates: reachable from Russia, and
  "bring your own audio" (our Russian voice goes through untouched).
- Round 3 found the structural reason the then-current vendor (bitHuman Essence 1) looked dead:
  its own documentation describes the pipeline as **a base frame plus an alpha-blended mouth
  patch**, picked from 183 precomputed mouth clusters per avatar. Eyes, brows and head come
  from a looped video and are not connected to the audio at all. No warm-up and no sync fix can
  change that: it is the class of the model, not its settings.

> Rule adopted: only consider engines that compute the **whole face from the audio, every frame**.
> Everything else is the same disease under a different name.

## Round 4 (19 August): 69 candidates, 5 gates, 14 alive

The customer's five criteria became hard gates:

1. connects to our speech (the Yandex TTS stream, PCM16 16 kHz mono);
2. realistic;
3. works **without a VPN** from Russia;
4. in sync;
5. **at most 400 RUB per 40-minute lesson**.

69 candidates were checked in five search directions, cloud services and self-hosted open
models alike. 14 stayed "alive".

### Gate 3 measured, not guessed

The first finding of the day was methodological: every research agent, and my own shell,
reached the internet through a Netherlands exit, so all their "reachable / not reachable"
verdicts described the route Netherlands -> vendor, which has nothing to do with the question.

So reachability was measured from a **Russian datacenter address, without VPN or proxy**, with
a **control**: an endpoint known to be blocked from Russia (the OpenAI API answered **421**).
A probe that cannot see the known block cannot be trusted to report an open route; this one
could. 54 domains were checked, plus TCP/TLS latency to eight providers.

| open (a live production API answered) | closed |
|---|---|
| Simli 200 (in 0.36 s), Protoface 200, Spatius 200, AvatarTalk 200, LemonSlice 200, Anam 307, Beyond Presence and HeyGen (live 404s), D-ID 403 "Missing Authentication Token", fal.ai 200, Replicate 401, Hugging Face 200, Docker Hub / ghcr / PyPI | OpenAI 421 (the control), Tavus 403 from nginx, Trulience (DNS does not resolve), DUIX/GuiJi (TLS breaks), api.vast.ai (DNS) |

TLS handshake from the Russian address: Beyond Presence 0.062 s (fastest), Simli 0.110 s, Anam
0.110 s, HeyGen 0.274-0.385 s. The July verdict "Simli does not answer from a Russian IP" was
stale: the cheapest candidate had been dropped for a reason that no longer existed.

Caveat kept in the memo: a datacenter address is not a home ISP, and in the browser-direct
design the student's browser talks to the vendor itself. Home connections were to be checked
separately. `tools/reachability_probe.py` in this repository is a clean re-implementation of the
control-check pattern (no addresses, no accounts).

### The 14 alive candidates

"Alive" is the memo's word: several rows below do not meet all five gates (price, realism).

| engine | whole face from audio? | reachable without VPN | RUB per 40 min (estimate) | memo verdict |
|---|---|---|---|---|
| SoulX-FlashHead Lite (self-hosted, Apache-2.0) | yes, generates the frame | no external service | 50 (110-180 with warm-up and idle) | try first |
| Ditto (self-hosted) | yes, plus pose, gaze, emotion | yes | 50 (110-180) | backup on latency |
| Spatius | 3D Gaussian splats | measured 200 | 25-32 + plan | cheapest cloud |
| Protoface | claimed, unverified | measured 200 | 36 + plan | check by eye |
| Simli Trinity-1 | 3D Gaussian splats | measured 200 in 0.36 s | price not published | check by eye |
| Beyond Presence | yes, photoreal | yes, fastest TLS; EU jurisdiction risk | 420 | free reference, not a supplier |
| AvatarTalk | unconfirmed | 200; offers on-prem install | 378 | one email |
| NVIDIA Audio2Face-3D | yes, but geometry, not pixels | all local | 0 + GPU rent | insurance |
| **Anam** | **yes, the quality reference** | 307; the browser connects directly | **396-576** | reference for comparison |
| HeyGen LiveAvatar | yes | yes, via a third-party media server | 360 + a monthly plan for 40-min sessions | out on subscription |
| Tencent Cloud IVH | unconfirmed | international page times out | about 45 | email |
| OpenAvatarChat (Apache-2.0) | a streaming wrapper, not an engine | yes | 0 | ready server for SoulX |
| TalkingHead.js + TTS word timings | no, stylised 3D | yes, all in the browser | 0 | emergency path for weak tablets |
| Live2D Cubism | no, a drawing | yes | 0 | a change of genre |

### Why the other 55 fell out (selection)

- **Same disease as the patch engine** (mouth re-pasting): MuseTalk, LiteAvatar,
  Ultralight-Digital-Human, LiveTalking (and its default Wav2Lip weights forbid commercial use), D-ID.
- **License mines:** LAM weights are Attribution-NonCommercial; Sonic, FLOAT and JoyVASA ship
  InsightFace models (non-commercial research only); the INRIA Gaussian-avatar line is research-only;
  the same InsightFace issue sits inside Ditto's weights (a face detector, replaceable).
- **Hardware out of reach:** 80 GB VRAM per stream, 6 fps on a top consumer card where 25 are
  needed, eight datacenter GPUs, 0.81 fps (and a crash of our 16 GB RAM machine), 44 s of
  compute per second of video.
- **Price:** from 590 to 26,000 RUB per lesson; one vendor also capped calls at 30 minutes.
- **Access and jurisdiction:** a sanctions clause in the contract, account resellers, and one
  vendor that had **shut down on 15 April 2026** while its pricing pages still topped search results.
- **Not the product:** a "digital avatar" that turned out to be a live actor in a motion-capture
  suit (lesson learned: ask first whether motion comes from audio or from a human), text-only
  inputs that cannot take our voice, and a TTS vendor with no avatar service at all.

## The final pick: liveness, not the memo's ranking

The memo recommended the self-hosted SoulX-FlashHead first. The decision made the same day went
to **Anam**: it already worked in the lesson prototype, and a metric written for this decision
showed why it looked alive while the incumbent did not.

`avatar_metrics.liveness` splits the face into an upper zone (brows, eyes) and a lower zone
(mouth), measures frame-to-frame motion in each and the correlation between the two series:

| clip (August 2026, numbers only) | mouth | upper | upper/mouth | coupling |
|---|---|---|---|---|
| local lip-sync on a still photo | 1.06 | 0.01 | 0.01 | 0.25 |
| bitHuman Essence 1, take 1 | 2.12 | 1.14 | **0.54** | 0.61 |
| bitHuman Essence 1, take 2 | 2.35 | 1.25 | **0.53** | 0.38 |
| **Anam, stock avatar, cara-4** | 4.66 | **5.06** | **1.09** | **0.89** |
| Wan 2.7 cloud render of our own portrait | 5.98 | 8.06 | 1.35 | 0.91 |

**Anam's upper face moved about four times more than bitHuman's (5.06 vs 1.14 and 1.25), and
in step with the speech.** That is the "dead face with a talking mouth" made into a number.

Honest note: Anam broke gate 5 on paper (396-576 RUB per lesson against a 400 ceiling). That is
precisely why the next step was the prerender cost design in [COST_MODEL.md](COST_MODEL.md).

## The one-engine rule (from the identity seam)

A lesson can mix prerecorded clips with a live avatar. Measured on 5 August with
`avatar_metrics.identity` (insightface ArcFace embeddings, cosine between clips):

| switch between | seam |
|---|---|
| the same engine | **0.942** (invisible) |
| a cloud engine and a local engine | **0.815-0.855** (a visible cut) |

The cut lands in the worst moment: the child has just asked a question and is looking at the
face. Hence the rule: **prerender and live must run on the same engine, face and model.** Anam
satisfies it because the same avatar can be driven in passthrough mode to record files
(`prerender/anam_render.py`) and live for answers.

## What this repository re-measures today

The vendor clips are not redistributable, so the method is re-validated on material that is:
synthetic faces with known ground truth (`tests/`) and the project's own AI-generated lesson
hosts rendered locally with InfiniteTalk ([results/MEASURED.md](../results/MEASURED.md)). The
hosts land where Anam landed (upper/mouth 0.98-1.21, coupling 0.88-0.94), and a still portrait
with audio lands at zero.
