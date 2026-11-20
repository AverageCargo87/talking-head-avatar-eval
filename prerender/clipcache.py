"""Python twin of prerender/clip-cache.mjs (the parts the Python renderers need).

The hash MUST equal the JavaScript one bit for bit: the lesson page finds a prerendered
clip by it. tests/test_clip_hash.py checks the two implementations against each other.
"""


def hash_text(text: str) -> str:
    """djb2 variant over Unicode code points: h = (h * 33) XOR cp, unsigned 32-bit."""
    h = 5381
    for ch in str(text):
        h = ((h * 33) ^ ord(ch)) & 0xFFFFFFFF
    return f"{h:08x}"


def hash_bytes(data: bytes) -> str:
    h = 5381
    for b in data:
        h = ((h * 33) ^ b) & 0xFFFFFFFF
    return f"{h:08x}"


def video_name(text_hash: str, signature: str) -> str:
    return f"clip-{text_hash}-{signature}.mp4"
