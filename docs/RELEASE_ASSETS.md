# Release assets

The repository tracks compact re-encodes of the host clips (`samples/infinitetalk/`, H.264 CRF 23-26,
audio stream copied untouched, so A/V timing is identical) to stay small. The original renders are
kept out of git in `release-assets/` and are meant to be uploaded as assets of a GitHub release.
All files were remuxed without re-encoding and with container metadata stripped.

| file | size | content | audio |
|---|---|---|---|
| `lena-9s-original.mp4` | 4.5 MB | one host, 640x640, calm-presenter prompt | voice kept |
| `artem-12s-original.mp4` | 6.5 MB | one host, 640x640, calm-presenter prompt | voice kept |
| `two-hosts-17s-original.mp4` | 8.1 MB | both hosts in one 832x480 shot, multi-speaker model with masks | dialogue kept |
| `lena-30s-audio-as-rendered-original.mp4` | 16.0 MB | one host, first-night prompt, 31.7 s | voice kept |
| `lena-30s-audio-80ms-earlier-original.mp4` | 16.1 MB | the same video, audio moved 80 ms earlier | voice kept |
| `artem-30s-muted-original.mp4` | 15.7 MB | one host, first-night prompt, 31.5 s | **muted** (see below) |

## Copyright check on every spoken line

The hosts read the opening of a history lesson written for the platform. Before any audio was
published, every clip's full text went through `tools/overlap_check.py`: normalised (lower case,
the Russian yo folded into ye, punctuation stripped), then compared against the local textbook
corpora (the textbook PDFs, the textbook page and block dumps, the verbatim "show" texts of the
cartoon scenes and the source extracts of this lesson) for any shared run of **8 or more
consecutive words**.

| clip text | result |
|---|---|
| Lena 9 s, Artem 12 s, both hosts 17 s, Lena 30 s, `prerender/beats.example.json` | **PASS**: no shared 8-word run |
| Artem 30 s | **FAIL**: one line shares a 10-word run with the textbook, so this clip is published **muted** |

The corpora are read locally and are not part of this repository.

## Credits for the media

- Host portraits: AI-generated portraits (fictional characters), made for the lesson.
- Microphone markings in the host videos are AI-generated artefacts, no brand intended.
- Host videos: rendered locally with Wan2.1 InfiniteTalk (see `local/`).
- Voices: ElevenLabs.
