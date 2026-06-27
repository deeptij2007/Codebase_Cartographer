"""Model selection driven by environment variables, so the project runs no
matter which provider you have access to.

Env vars:
    CARTOGRAPHER_MODEL_TYPE   inference | litellm | openai | transformers   (default: inference)
    CARTOGRAPHER_MODEL_ID     model id for the chosen backend (optional)
    CARTOGRAPHER_PROVIDER     HF inference provider, e.g. together, novita    (inference only)
    CARTOGRAPHER_API_BASE     base URL for an OpenAI-compatible server         (openai only)

Plus the usual provider keys: HF_TOKEN, ANTHROPIC_API_KEY, OPENAI_API_KEY, ...
"""

from __future__ import annotations

import os


def get_model():
    """Return a smolagents model instance based on environment configuration."""
    model_type = os.getenv("CARTOGRAPHER_MODEL_TYPE", "inference").lower()
    model_id = os.getenv("CARTOGRAPHER_MODEL_ID")

    if model_type == "inference":
        from smolagents import InferenceClientModel
        kwargs = {}
        if model_id:
            kwargs["model_id"] = model_id
        if os.getenv("CARTOGRAPHER_PROVIDER"):
            kwargs["provider"] = os.getenv("CARTOGRAPHER_PROVIDER")
        return InferenceClientModel(**kwargs)

    if model_type == "litellm":
        from smolagents import LiteLLMModel
        return LiteLLMModel(model_id=model_id or "anthropic/claude-sonnet-4-5")

    if model_type == "openai":
        from smolagents import OpenAIServerModel
        return OpenAIServerModel(
            model_id=model_id or "gpt-4o",
            api_base=os.getenv("CARTOGRAPHER_API_BASE"),
            api_key=os.getenv("OPENAI_API_KEY"),
        )

    if model_type == "transformers":
        from smolagents import TransformersModel
        return TransformersModel(model_id=model_id or "Qwen/Qwen2.5-Coder-7B-Instruct")

    raise ValueError(
        f"Unknown CARTOGRAPHER_MODEL_TYPE={model_type!r}. "
        "Use one of: inference, litellm, openai, transformers."
    )
