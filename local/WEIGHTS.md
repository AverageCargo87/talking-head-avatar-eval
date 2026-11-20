# Weights (links only)

Nothing below is redistributed by this repository. Download with
`python local/download_weights.py local/weights.txt --root /path/to/ComfyUI` or by hand, and check
each model card for its license before any commercial use.

| file | ComfyUI folder | source |
|---|---|---|
| `wan2.1-i2v-14b-480p-Q4_K_M.gguf` | `models/diffusion_models` | [city96/Wan2.1-I2V-14B-480P-gguf](https://huggingface.co/city96/Wan2.1-I2V-14B-480P-gguf) |
| `Wan2_1-InfiniteTalk_Single_Q8.gguf` | `models/diffusion_models` | [Kijai/WanVideo_comfy_GGUF](https://huggingface.co/Kijai/WanVideo_comfy_GGUF) (InfiniteTalk/) |
| `Wan2_1-InfiniteTalk_Multi_Q8.gguf` | `models/diffusion_models` | [Kijai/WanVideo_comfy_GGUF](https://huggingface.co/Kijai/WanVideo_comfy_GGUF) (InfiniteTalk/) |
| `lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors` | `models/loras` | [Kijai/WanVideo_comfy](https://huggingface.co/Kijai/WanVideo_comfy) (Lightx2v/) |
| `umt5-xxl-enc-fp8_e4m3fn.safetensors` | `models/text_encoders` | [Kijai/WanVideo_comfy](https://huggingface.co/Kijai/WanVideo_comfy) |
| `open-clip-xlm-roberta-large-vit-huge-14_visual_fp16.safetensors` | `models/clip_vision` | [Kijai/WanVideo_comfy](https://huggingface.co/Kijai/WanVideo_comfy) |
| `Wan2_1_VAE_bf16.safetensors` | `models/vae` | [Kijai/WanVideo_comfy](https://huggingface.co/Kijai/WanVideo_comfy) |
| `wav2vec2-chinese-base_fp16.safetensors` | `models/wav2vec2` | [Kijai/wav2vec2_safetensors](https://huggingface.co/Kijai/wav2vec2_safetensors) |

Software (installed separately, not vendored): [ComfyUI](https://github.com/comfyanonymous/ComfyUI),
[ComfyUI-WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper),
[ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes),
[ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite),
[SageAttention](https://github.com/thu-ml/SageAttention) (optional, faster),
[InfiniteTalk](https://github.com/MeiGen-AI/InfiniteTalk) (the method, Apache-2.0).
For `syncnet_offset.sh` and the prerender lip-sync: [LatentSync](https://github.com/bytedance/LatentSync).
