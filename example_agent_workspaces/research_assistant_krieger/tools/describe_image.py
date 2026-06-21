"""Image analysis tools using vision-capable LLMs.

Provides vision analysis via Anthropic Claude, OpenAI GPT, and AWS Bedrock models.
Supports single-model analysis and multi-model comparison for uploaded images.
Uses LangChain provider packages already in project dependencies.
"""
import base64
import json
import logging
import os
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Capture workspace root at module import
_WORKSPACE_ROOT = Path(os.getenv("OPENPAW_WORKSPACE_PATH", ".")).resolve()

# Image format support
_SUPPORTED_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB limit

# Model registry
_MODEL_REGISTRY = {
    "claude": {
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-5-20250929",
        "display_name": "Claude Sonnet 4.5",
        "env_key": "ANTHROPIC_API_KEY",
    },
    "gpt": {
        "provider": "openai",
        "model_id": "gpt-4.1",
        "display_name": "GPT-4.1",
        "env_key": "OPENAI_API_KEY",
    },
    "gpt5": {
        "provider": "openai",
        "model_id": "gpt-5.2",
        "display_name": "GPT-5.2",
        "env_key": "OPENAI_API_KEY",
    },
    "bedrock-nova": {
        "provider": "bedrock",
        "model_id": "amazon.nova-pro-v1:0",
        "display_name": "Amazon Nova Pro",
        "env_key": None,  # Uses AWS credential chain
    },
}

# Auto-selection priority (excludes gpt5 — opt-in only)
_AUTO_PRIORITY = ["claude", "gpt", "bedrock-nova"]

# Compare tool default set (one per provider, excludes gpt5 to avoid double-billing OpenAI)
_COMPARE_MODELS = ["claude", "gpt", "bedrock-nova"]


def _resolve_image_path(image_path: str) -> Path:
    """Resolve image path relative to workspace root.

    Performs basic safety checks without importing framework internals.
    Workspace tools run inside the agent sandbox already, so this is
    defense-in-depth rather than the primary security boundary.

    Args:
        image_path: Workspace-relative image path

    Returns:
        Resolved absolute path

    Raises:
        ValueError: For path traversal attempts or absolute paths
        FileNotFoundError: If image does not exist
    """
    if os.path.isabs(image_path):
        raise ValueError(
            f"Absolute paths not allowed. Use workspace-relative paths. Got: {image_path}"
        )

    if ".." in Path(image_path).parts:
        raise ValueError(f"Path traversal (..) not allowed. Got: {image_path}")

    full_path = (_WORKSPACE_ROOT / image_path).resolve()

    # Verify it stays within workspace
    try:
        full_path.relative_to(_WORKSPACE_ROOT)
    except ValueError:
        raise ValueError(f"Path resolves outside workspace: {image_path}") from None

    if not full_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    return full_path


def _load_and_encode_image(abs_path: Path) -> tuple[str, str, int]:
    """Read image from disk and base64 encode it.

    Args:
        abs_path: Absolute path to image file

    Returns:
        Tuple of (base64_encoded_string, mime_type, file_size_bytes)

    Raises:
        ValueError: If file extension is unsupported or file is too large
        FileNotFoundError: If file does not exist
    """
    if not abs_path.exists():
        raise FileNotFoundError(f"Image not found: {abs_path}")

    ext = abs_path.suffix.lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported image format '{ext}'. "
            f"Supported: {', '.join(_SUPPORTED_EXTENSIONS.keys())}"
        )

    size = abs_path.stat().st_size
    if size > _MAX_IMAGE_SIZE:
        raise ValueError(
            f"Image too large: {size / (1024*1024):.1f} MB "
            f"(max: {_MAX_IMAGE_SIZE / (1024*1024):.0f} MB)"
        )

    raw = abs_path.read_bytes()
    b64 = base64.b64encode(raw).decode("utf-8")
    mime = _SUPPORTED_EXTENSIONS[ext]

    return b64, mime, size


def _build_vision_message(base64_data: str, mime_type: str, prompt: str) -> list[dict]:
    """Build multimodal content blocks for LangChain HumanMessage.

    Args:
        base64_data: Base64-encoded image data
        mime_type: MIME type of the image
        prompt: Text prompt for analysis

    Returns:
        List of content blocks (image_url + text dicts)
    """
    blocks: list[dict] = []

    # Image first
    blocks.append({
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{base64_data}"},
    })

    # Prompt last
    blocks.append({"type": "text", "text": prompt})

    return blocks


def _get_available_models() -> list[dict]:
    """Check which vision models are available based on API keys.

    Returns:
        List of model config dicts for available models
    """
    available = []

    for alias, config in _MODEL_REGISTRY.items():
        env_key = config["env_key"]

        # Bedrock uses AWS credential chain (no specific env var check)
        if env_key is None:
            available.append({"alias": alias, **config})
            continue

        # Check if API key is set
        if os.getenv(env_key):
            available.append({"alias": alias, **config})

    return available


def _create_vision_model(model_config: dict):
    """Instantiate a LangChain chat model for vision analysis.

    Uses direct provider instantiation (same pattern as AgentRunner._create_model).
    Temperature is set to 0.3 for deterministic descriptions.
    Max tokens is set to 4096 to allow detailed analysis.

    Args:
        model_config: Model configuration dict from registry

    Returns:
        LangChain BaseChatModel instance

    Raises:
        ValueError: If provider is unknown
    """
    provider = model_config["provider"]
    model_id = model_config["model_id"]

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model_id,
            temperature=0.3,
            max_tokens=4096,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_id,
            temperature=0.3,
            max_tokens=4096,
        )

    if provider == "bedrock":
        from langchain_aws import ChatBedrockConverse
        return ChatBedrockConverse(
            model=model_id,
            temperature=0.3,
            max_tokens=4096,
        )

    raise ValueError(f"Unknown provider: {provider}")


def _query_model(model_config: dict, content_blocks: list[dict]) -> dict:
    """Query a single vision model and return the result.

    Args:
        model_config: Model configuration dict
        content_blocks: LangChain message content blocks (image + text)

    Returns:
        Result dict with keys: model, provider, status, analysis/error
        Never raises — catches all exceptions and returns error dict
    """
    try:
        model = _create_vision_model(model_config)
        message = HumanMessage(content=content_blocks)
        response = model.invoke([message])

        return {
            "model": model_config["model_id"],
            "provider": model_config["provider"],
            "status": "success",
            "analysis": response.content,
        }
    except Exception as e:
        logger.warning(
            f"Vision model {model_config['display_name']} failed: {e}"
        )
        return {
            "model": model_config["model_id"],
            "provider": model_config["provider"],
            "status": "error",
            "error": str(e),
        }


@tool
def describe_image(
    image_path: str,
    prompt: str = "Describe this image in detail.",
    model: str = "auto",
) -> str:
    """Analyze an image using a vision-capable AI model.

    Reads an image from the workspace, sends it to the specified vision model,
    and returns the model's analysis. Supports JPEG, PNG, GIF, and WebP.

    Available models:
    - "auto" (default): picks the best available model (Claude Sonnet 4.5 > GPT-4.1 > Bedrock Nova)
    - "claude": Anthropic Claude Sonnet 4.5 (excellent detail, reasoning)
    - "gpt": OpenAI GPT-4.1 (strong general vision, 1M context)
    - "gpt5": OpenAI GPT-5.2 (flagship, best OpenAI vision — higher cost)
    - "bedrock-nova": AWS Bedrock Nova Pro (cost-effective, good quality)

    Args:
        image_path: Path to image file relative to workspace root
            (e.g., "uploads/2026-02-07/photo.jpg")
        prompt: Analysis prompt describing what to look for
            (default: "Describe this image in detail.")
        model: Which vision model to use (default: "auto")

    Returns:
        JSON with model name, analysis text, and metadata.
    """
    logger.info(f"describe_image called with image_path='{image_path}', model='{model}'")

    try:
        # Resolve and load image
        abs_path = _resolve_image_path(image_path)
        b64_data, mime_type, size_bytes = _load_and_encode_image(abs_path)

        # Build vision message
        content_blocks = _build_vision_message(b64_data, mime_type, prompt)

        # Determine which model to use
        if model == "auto":
            # Auto-select first available from priority list
            available = _get_available_models()
            available_aliases = {m["alias"] for m in available}

            selected_alias = None
            for priority_alias in _AUTO_PRIORITY:
                if priority_alias in available_aliases:
                    selected_alias = priority_alias
                    break

            if selected_alias is None:
                error_msg = (
                    "No vision models available. Ensure API keys are configured: "
                    "ANTHROPIC_API_KEY, OPENAI_API_KEY, or AWS credentials for Bedrock."
                )
                logger.error(error_msg)
                return json.dumps({"error": error_msg})

            model_config = _MODEL_REGISTRY[selected_alias].copy()
            model_config["alias"] = selected_alias
        else:
            # Use specified model
            if model not in _MODEL_REGISTRY:
                valid_models = ", ".join(_MODEL_REGISTRY.keys())
                error_msg = f"Invalid model '{model}'. Valid options: auto, {valid_models}"
                logger.error(error_msg)
                return json.dumps({"error": error_msg})

            model_config = _MODEL_REGISTRY[model].copy()
            model_config["alias"] = model

            # Check if API key is available for this model
            env_key = model_config["env_key"]
            if env_key and not os.getenv(env_key):
                error_msg = (
                    f"API key not configured for {model_config['display_name']}. "
                    f"Set {env_key} in workspace .env file."
                )
                logger.error(error_msg)
                return json.dumps({"error": error_msg})

        # Query the model
        logger.info(f"Querying {model_config['display_name']}...")
        result = _query_model(model_config, content_blocks)

        # Check if query failed
        if result["status"] == "error":
            return json.dumps({"error": result["error"]})

        # Success — build response
        response = {
            "status": "success",
            "model": result["model"],
            "provider": result["provider"],
            "analysis": result["analysis"],
            "image_path": image_path,
            "image_size_kb": round(size_bytes / 1024, 2),
        }

        return json.dumps(response, indent=2)

    except (ValueError, FileNotFoundError) as e:
        # Image loading errors
        error_msg = str(e)
        logger.error(error_msg)
        return json.dumps({"error": error_msg})
    except Exception as e:
        # Unexpected errors
        error_msg = f"Image analysis failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({"error": error_msg})


@tool
def compare_image_models(
    image_path: str,
    prompt: str = "Describe this image in detail.",
) -> str:
    """Analyze an image with multiple vision models for comparison.

    Sends the same image and prompt to all available vision models and
    returns each model's analysis side by side. Useful for getting diverse
    perspectives or cross-referencing observations.

    Only models whose API keys are available will be queried. If a model
    fails, results from other models are still returned.

    Default model set: Claude Sonnet 4.5, GPT-4.1, Bedrock Nova Pro
    (one per provider, excludes GPT-5.2 to avoid double-billing OpenAI)

    Args:
        image_path: Path to image file relative to workspace root
        prompt: Analysis prompt describing what to look for

    Returns:
        JSON with results from each model and summary metadata.
    """
    logger.info(f"compare_image_models called with image_path='{image_path}'")

    try:
        # Resolve and load image
        abs_path = _resolve_image_path(image_path)
        b64_data, mime_type, size_bytes = _load_and_encode_image(abs_path)

        # Build vision message
        content_blocks = _build_vision_message(b64_data, mime_type, prompt)

        # Get available models from compare set
        available = _get_available_models()

        # Filter to compare set
        models_to_query = [
            m for m in available if m["alias"] in _COMPARE_MODELS
        ]

        if not models_to_query:
            error_msg = (
                "No vision models available for comparison. Ensure API keys are configured: "
                "ANTHROPIC_API_KEY, OPENAI_API_KEY, or AWS credentials for Bedrock."
            )
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

        # Query each model sequentially
        results = []
        succeeded_count = 0

        for model_config in models_to_query:
            logger.info(f"Querying {model_config['display_name']}...")
            result = _query_model(model_config, content_blocks)
            results.append(result)

            if result["status"] == "success":
                succeeded_count += 1

        # Build response
        response = {
            "status": "success",
            "image_path": image_path,
            "image_size_kb": round(size_bytes / 1024, 2),
            "models_queried": len(results),
            "models_succeeded": succeeded_count,
            "results": results,
        }

        return json.dumps(response, indent=2)

    except (ValueError, FileNotFoundError) as e:
        # Image loading errors
        error_msg = str(e)
        logger.error(error_msg)
        return json.dumps({"error": error_msg})
    except Exception as e:
        # Unexpected errors
        error_msg = f"Image comparison failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({"error": error_msg})
