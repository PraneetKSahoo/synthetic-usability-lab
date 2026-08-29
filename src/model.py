import os
import logging
import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForMultimodalLM, BitsAndBytesConfig

logger = logging.getLogger(__name__)

try:
    from google.colab import userdata
    COLAB_ENV = True
except ImportError:
    COLAB_ENV = False

class Gemma4VisionClient:
    def __init__(self, model_id: str = "google/gemma-4-E4B-it"):
        self.model_id = model_id
        self.hf_token = self._get_token()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        if self.hf_token is None:
            # Not fatal: the weights may already be cached locally, or auth may be
            # configured another way. If it really is needed, the load below fails
            # with actionable guidance rather than blocking a valid setup here.
            logger.warning(
                "No Hugging Face token found (checked Colab Secrets, HF_TOKEN, and saved "
                "login). Gemma 4 is gated, so the download will fail unless the weights "
                "are already cached. Run huggingface_hub.login(), set HF_TOKEN, or see .env.example."
            )

        if self.device == "cpu":
            raise RuntimeError(
                "No CUDA device available. This project loads a 4-bit quantized "
                "multimodal model via bitsandbytes, which requires a CUDA GPU. "
                "Run it on a GPU machine or use the provided colab.ipynb."
            )

        logger.info("Loading multimodal %s in 4-bit...", model_id)
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16
        )

        try:
            self.processor = AutoProcessor.from_pretrained(
                self.model_id,
                token=self.hf_token
            )
            self.model = AutoModelForMultimodalLM.from_pretrained(
                self.model_id,
                quantization_config=bnb_config,
                device_map="auto",
                token=self.hf_token
            )
        except Exception as ex:
            raise RuntimeError(
                f"Failed to load {self.model_id}: {ex}\n"
                "Common causes: no valid HF token (run huggingface_hub.login() or set "
                "HF_TOKEN), the token lacks access to this gated model (accept the "
                "licence on the model page first), insufficient GPU memory, or a "
                "transformers version that predates Gemma 4 support."
            ) from ex

        logger.info("Gemma 4 multimodal loaded with vision enabled.")

    def _get_token(self):
        """Resolves an HF token from Colab Secrets, the environment, or a prior login().

        Note the last case: `huggingface_hub.login()` (what colab.ipynb calls)
        persists the token to the HF cache on disk and does NOT set HF_TOKEN, so
        checking only Secrets/env would reject a valid, already-logged-in session.
        """
        if COLAB_ENV:
            try:
                token = userdata.get('HF_TOKEN')
                if token:
                    return token
            except Exception:
                # Expected when running as a subprocess (`!python app.py`), where
                # userdata cannot reach the Colab kernel bridge.
                logger.debug("Colab userdata lookup for HF_TOKEN unavailable; trying env/cache.")

        env_token = os.getenv("HF_TOKEN")
        if env_token:
            return env_token

        try:
            from huggingface_hub import get_token
            return get_token()
        except ImportError:
            try:  # older huggingface_hub
                from huggingface_hub import HfFolder
                return HfFolder.get_token()
            except Exception:
                return None
        except Exception:
            return None

    def generate_with_vision(self, prompt: str, image: Image.Image = None, max_new_tokens: int = 500, temperature: float = 0.2) -> str:
        """Generates reasoning and action directly from a web screenshot and prompt."""
        messages = [
            {"role": "system", "content": "You are a human usability tester with native vision. You look directly at screenshots, reason about UI elements, and take actions using visual coordinates."}
        ]
        
        content = []
        if image is not None:
            content.append({"type": "image", "image": image})
        content.append({"type": "text", "text": prompt})
        messages.append({"role": "user", "content": content})

        # Apply multimodal chat template
        prompt_text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        
        if image is not None:
            inputs = self.processor(text=prompt_text, images=image, return_tensors="pt").to(self.device)
        else:
            inputs = self.processor(text=prompt_text, return_tensors="pt").to(self.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                do_sample=True if temperature > 0.0 else False,
                top_p=0.9
            )

        generated_tokens = outputs[0][inputs.input_ids.shape[1]:]
        # skip_special_tokens=True: template/control tokens are noise that the
        # JSON extraction downstream would otherwise have to regex around.
        return self.processor.decode(generated_tokens, skip_special_tokens=True).strip()