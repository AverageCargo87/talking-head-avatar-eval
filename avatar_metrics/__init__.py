"""avatar_metrics: measure talking-head video quality as numbers, not by eye.

Four measurements, each answering one question that cost real time to answer by eye:

* ``liveness``  Does the engine animate the WHOLE face, or paste a mouth patch onto a
  static or looped base? (upper vs lower face motion energy and their coupling)
* ``offset``    Is the picture ahead of or behind the audio, and by how many ms?
  (mouth openness vs audio envelope cross-correlation)
* ``identity``  Is it still the same person when the lesson switches between two
  rendering engines? (face-embedding cosine, the "seam")
* ``motion``    How jumpy is the frame overall? (mean absolute frame difference)

Everything except the insightface identity backend runs offline on OpenCV + NumPy + ffmpeg.
"""

from .liveness import LivenessResult, measure_liveness
from .motion import MotionResult, measure_motion
from .offset import OffsetResult, measure_offset

__all__ = [
    "LivenessResult",
    "MotionResult",
    "OffsetResult",
    "measure_liveness",
    "measure_motion",
    "measure_offset",
]

__version__ = "0.1.0"
