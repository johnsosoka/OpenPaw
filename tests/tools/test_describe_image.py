"""Tests for describe_image workspace tool."""

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def create_test_image(workspace_path: Path):
    """Factory fixture to create test image files."""
    def _create_image(filename: str, size_bytes: int = 100) -> Path:
        """Create a test image file with given size.

        Extension is inferred from filename. Defaults to .png if none provided.
        """
        path = Path(filename)
        if not path.suffix:
            filename = filename + ".png"

        image_path = workspace_path / filename
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_data = b"\x89PNG\r\n\x1a\n" + (b"x" * max(0, size_bytes - 8))
        image_path.write_bytes(image_data)
        return image_path

    return _create_image


@pytest.fixture
def mock_api_keys(monkeypatch):
    """Mock all API keys as available."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")


@pytest.fixture
def mock_no_api_keys(monkeypatch):
    """Clear all API keys."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# Test _resolve_image_path


def test_resolve_image_path_valid_relative(workspace_path: Path):
    """Test valid relative path resolves correctly."""
    from agent_workspaces.krieger.tools import describe_image

    test_file = workspace_path / "test.jpg"
    test_file.write_text("test")

    with patch.object(describe_image, "_WORKSPACE_ROOT", workspace_path):
        result = describe_image._resolve_image_path("test.jpg")
        assert result == test_file
        assert result.exists()


def test_resolve_image_path_absolute_rejected():
    """Test absolute paths are rejected."""
    from agent_workspaces.krieger.tools import describe_image

    with pytest.raises(ValueError, match="Absolute paths not allowed"):
        describe_image._resolve_image_path("/etc/passwd")


def test_resolve_image_path_traversal_rejected():
    """Test path traversal with .. is rejected."""
    from agent_workspaces.krieger.tools import describe_image

    with pytest.raises(ValueError, match="Path traversal.*not allowed"):
        describe_image._resolve_image_path("../etc/passwd")


def test_resolve_image_path_escaping_workspace_rejected():
    """Test paths resolving outside workspace are rejected."""
    from agent_workspaces.krieger.tools import describe_image

    with pytest.raises(ValueError, match="Path traversal.*not allowed"):
        describe_image._resolve_image_path("subdir/../../etc/passwd")


def test_resolve_image_path_file_not_found(workspace_path: Path):
    """Test non-existent file raises FileNotFoundError."""
    from agent_workspaces.krieger.tools import describe_image

    with patch.object(describe_image, "_WORKSPACE_ROOT", workspace_path):
        with pytest.raises(FileNotFoundError, match="Image not found"):
            describe_image._resolve_image_path("nonexistent.jpg")


def test_resolve_image_path_nested_directory(workspace_path: Path):
    """Test nested directory paths work correctly."""
    from agent_workspaces.krieger.tools import describe_image

    nested_dir = workspace_path / "uploads" / "2026-02-07"
    nested_dir.mkdir(parents=True)
    test_file = nested_dir / "photo.jpg"
    test_file.write_text("test")

    with patch.object(describe_image, "_WORKSPACE_ROOT", workspace_path):
        result = describe_image._resolve_image_path("uploads/2026-02-07/photo.jpg")
        assert result == test_file


# Test _load_and_encode_image


def test_load_and_encode_image_png(create_test_image):
    """Test loading and encoding a PNG image."""
    from agent_workspaces.krieger.tools import describe_image

    test_file = create_test_image("test.png")

    b64_data, mime_type, size = describe_image._load_and_encode_image(test_file)

    assert isinstance(b64_data, str)
    assert mime_type == "image/png"
    assert size == test_file.stat().st_size
    # Verify it's valid base64
    decoded = base64.b64decode(b64_data)
    assert decoded == test_file.read_bytes()


def test_load_and_encode_image_jpeg(workspace_path: Path):
    """Test loading and encoding a JPEG image."""
    from agent_workspaces.krieger.tools import describe_image

    test_file = workspace_path / "test.jpg"
    test_data = b"\xFF\xD8\xFF\xE0" + (b"x" * 100)  # JPEG header
    test_file.write_bytes(test_data)

    b64_data, mime_type, size = describe_image._load_and_encode_image(test_file)

    assert mime_type == "image/jpeg"
    assert base64.b64decode(b64_data) == test_data


def test_load_and_encode_image_gif(workspace_path: Path):
    """Test loading and encoding a GIF image."""
    from agent_workspaces.krieger.tools import describe_image

    test_file = workspace_path / "animated.gif"
    test_data = b"GIF89a" + (b"x" * 100)
    test_file.write_bytes(test_data)

    b64_data, mime_type, size = describe_image._load_and_encode_image(test_file)

    assert mime_type == "image/gif"


def test_load_and_encode_image_webp(workspace_path: Path):
    """Test loading and encoding a WebP image."""
    from agent_workspaces.krieger.tools import describe_image

    test_file = workspace_path / "modern.webp"
    test_data = b"RIFF" + (b"x" * 100)
    test_file.write_bytes(test_data)

    b64_data, mime_type, size = describe_image._load_and_encode_image(test_file)

    assert mime_type == "image/webp"


def test_load_and_encode_image_unsupported_format(workspace_path: Path):
    """Test unsupported image format raises ValueError."""
    from agent_workspaces.krieger.tools import describe_image

    test_file = workspace_path / "document.bmp"
    test_file.write_bytes(b"BMP data")

    with pytest.raises(ValueError, match="Unsupported image format '.bmp'"):
        describe_image._load_and_encode_image(test_file)


def test_load_and_encode_image_too_large(workspace_path: Path):
    """Test file exceeding size limit raises ValueError."""
    from agent_workspaces.krieger.tools import describe_image

    test_file = workspace_path / "huge.png"
    # Create a file just over 20MB
    large_data = b"x" * (21 * 1024 * 1024)
    test_file.write_bytes(large_data)

    with pytest.raises(ValueError, match="Image too large"):
        describe_image._load_and_encode_image(test_file)


def test_load_and_encode_image_file_not_found(workspace_path: Path):
    """Test non-existent file raises FileNotFoundError."""
    from agent_workspaces.krieger.tools import describe_image

    test_file = workspace_path / "missing.png"

    with pytest.raises(FileNotFoundError, match="Image not found"):
        describe_image._load_and_encode_image(test_file)


def test_load_and_encode_image_case_insensitive_extension(workspace_path: Path):
    """Test extension matching is case-insensitive."""
    from agent_workspaces.krieger.tools import describe_image

    test_file = workspace_path / "test.PNG"
    test_data = b"\x89PNG\r\n\x1a\n" + (b"x" * 100)
    test_file.write_bytes(test_data)

    b64_data, mime_type, size = describe_image._load_and_encode_image(test_file)

    assert mime_type == "image/png"


# Test _build_vision_message


def test_build_vision_message_structure():
    """Test vision message has correct structure."""
    from agent_workspaces.krieger.tools import describe_image

    b64_data = "dGVzdGRhdGE="
    mime_type = "image/jpeg"
    prompt = "Describe this image"

    blocks = describe_image._build_vision_message(b64_data, mime_type, prompt)

    assert len(blocks) == 2
    assert blocks[0]["type"] == "image_url"
    assert blocks[1]["type"] == "text"


def test_build_vision_message_image_first():
    """Test image block comes before text prompt."""
    from agent_workspaces.krieger.tools import describe_image

    b64_data = "abc123"
    mime_type = "image/png"
    prompt = "What's in this image?"

    blocks = describe_image._build_vision_message(b64_data, mime_type, prompt)

    # Image must be first
    assert blocks[0]["type"] == "image_url"
    assert blocks[1]["type"] == "text"


def test_build_vision_message_data_url_format():
    """Test image uses correct data URL format."""
    from agent_workspaces.krieger.tools import describe_image

    b64_data = "iVBORw0KGgo="
    mime_type = "image/png"
    prompt = "Analyze"

    blocks = describe_image._build_vision_message(b64_data, mime_type, prompt)

    image_url = blocks[0]["image_url"]["url"]
    assert image_url == f"data:{mime_type};base64,{b64_data}"
    assert image_url.startswith("data:image/png;base64,")


def test_build_vision_message_text_content():
    """Test text block contains the prompt."""
    from agent_workspaces.krieger.tools import describe_image

    b64_data = "xyz"
    mime_type = "image/jpeg"
    prompt = "What objects are visible?"

    blocks = describe_image._build_vision_message(b64_data, mime_type, prompt)

    assert blocks[1]["text"] == prompt


# Test _get_available_models


def test_get_available_models_all_keys_present(mock_api_keys):
    """Test all models are available when API keys are set."""
    from agent_workspaces.krieger.tools import describe_image

    available = describe_image._get_available_models()

    aliases = [m["alias"] for m in available]
    # Should include claude, gpt, gpt5, bedrock-nova
    assert "claude" in aliases
    assert "gpt" in aliases
    assert "gpt5" in aliases
    assert "bedrock-nova" in aliases
    assert len(available) == 4


def test_get_available_models_no_keys(mock_no_api_keys):
    """Test only Bedrock is available when no API keys are set."""
    from agent_workspaces.krieger.tools import describe_image

    available = describe_image._get_available_models()

    aliases = [m["alias"] for m in available]
    # Only bedrock-nova should be available (no env_key requirement)
    assert "bedrock-nova" in aliases
    assert "claude" not in aliases
    assert "gpt" not in aliases
    assert len(available) == 1


def test_get_available_models_partial_keys(monkeypatch):
    """Test only models with available keys are returned."""
    from agent_workspaces.krieger.tools import describe_image

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    available = describe_image._get_available_models()

    aliases = [m["alias"] for m in available]
    assert "claude" in aliases
    assert "bedrock-nova" in aliases
    assert "gpt" not in aliases
    assert "gpt5" not in aliases


def test_get_available_models_includes_metadata():
    """Test each available model includes all metadata fields."""
    from agent_workspaces.krieger.tools import describe_image

    available = describe_image._get_available_models()

    for model in available:
        assert "alias" in model
        assert "provider" in model
        assert "model_id" in model
        assert "display_name" in model
        assert "env_key" in model


# Test describe_image tool


@patch("agent_workspaces.krieger.tools.describe_image._create_vision_model")
def test_describe_image_auto_selects_claude(
    mock_create_model,
    workspace_path: Path,
    create_test_image,
    mock_api_keys,
):
    """Test auto-selection picks Claude first when available."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("test.jpg")

    # Mock the model and its response
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "A beautiful sunset over mountains"
    mock_model.invoke.return_value = mock_response
    mock_create_model.return_value = mock_model

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.describe_image.invoke({
            "image_path": "test.jpg",
            "prompt": "What do you see?",
        })

    result = json.loads(result_json)

    assert result["status"] == "success"
    assert result["model"] == "claude-sonnet-4-5-20250929"
    assert result["provider"] == "anthropic"
    assert result["analysis"] == "A beautiful sunset over mountains"
    assert result["image_path"] == "test.jpg"


@patch("agent_workspaces.krieger.tools.describe_image._create_vision_model")
def test_describe_image_explicit_model_selection(
    mock_create_model,
    workspace_path: Path,
    create_test_image,
    mock_api_keys,
):
    """Test explicit model selection works."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("chart.png")

    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "A bar chart showing quarterly revenue"
    mock_model.invoke.return_value = mock_response
    mock_create_model.return_value = mock_model

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.describe_image.invoke({
            "image_path": "chart.png",
            "model": "gpt",
        })

    result = json.loads(result_json)

    assert result["status"] == "success"
    assert result["model"] == "gpt-4.1"
    assert result["provider"] == "openai"


@patch("agent_workspaces.krieger.tools.describe_image._create_vision_model")
def test_describe_image_bedrock_model(
    mock_create_model,
    workspace_path: Path,
    create_test_image,
    mock_no_api_keys,
):
    """Test Bedrock model selection when no API keys are available."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("photo.jpg")

    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "A person standing in a park"
    mock_model.invoke.return_value = mock_response
    mock_create_model.return_value = mock_model

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.describe_image.invoke({
            "image_path": "photo.jpg",
            "model": "bedrock-nova",
        })

    result = json.loads(result_json)

    assert result["status"] == "success"
    assert result["model"] == "amazon.nova-pro-v1:0"
    assert result["provider"] == "bedrock"


def test_describe_image_invalid_model_name(workspace_path: Path, create_test_image):
    """Test invalid model name returns error."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("test.jpg")

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.describe_image.invoke({
            "image_path": "test.jpg",
            "model": "invalid-model",
        })

    result = json.loads(result_json)

    assert "error" in result
    assert "Invalid model" in result["error"]
    assert "invalid-model" in result["error"]


def test_describe_image_missing_api_key_for_explicit_model(workspace_path: Path, create_test_image, mock_no_api_keys):
    """Test error when API key is missing for explicitly selected model."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("test.jpg")

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.describe_image.invoke({
            "image_path": "test.jpg",
            "model": "claude",
        })

    result = json.loads(result_json)

    assert "error" in result
    assert "API key not configured" in result["error"]
    assert "ANTHROPIC_API_KEY" in result["error"]


def test_describe_image_no_models_available(workspace_path: Path, create_test_image, mock_no_api_keys):
    """Test error when no models are available for auto-selection."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("test.jpg")

    # Mock _get_available_models to return empty list (simulating no Bedrock access)
    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        with patch.object(dm, "_get_available_models", return_value=[]):
            result_json = dm.describe_image.invoke({
                "image_path": "test.jpg",
                "model": "auto",
            })

    result = json.loads(result_json)

    assert "error" in result
    assert "No vision models available" in result["error"]


def test_describe_image_file_not_found(workspace_path: Path):
    """Test error when image file doesn't exist."""
    from agent_workspaces.krieger.tools import describe_image as dm

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.describe_image.invoke({
            "image_path": "nonexistent.jpg",
        })

    result = json.loads(result_json)

    assert "error" in result
    assert "Image not found" in result["error"]


def test_describe_image_unsupported_format(workspace_path: Path):
    """Test error for unsupported image format."""
    from agent_workspaces.krieger.tools import describe_image as dm

    test_file = workspace_path / "document.bmp"
    test_file.write_bytes(b"BMP data")

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.describe_image.invoke({
            "image_path": "document.bmp",
        })

    result = json.loads(result_json)

    assert "error" in result
    assert "Unsupported image format" in result["error"]


def test_describe_image_path_traversal_blocked(workspace_path: Path):
    """Test path traversal is blocked."""
    from agent_workspaces.krieger.tools import describe_image as dm

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.describe_image.invoke({
            "image_path": "../etc/passwd",
        })

    result = json.loads(result_json)

    assert "error" in result
    assert "not allowed" in result["error"].lower()


@patch("agent_workspaces.krieger.tools.describe_image._create_vision_model")
def test_describe_image_includes_size_metadata(
    mock_create_model,
    workspace_path: Path,
    create_test_image,
    mock_api_keys,
):
    """Test result includes image size metadata."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("test.jpg", size_bytes=2048)

    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "An image"
    mock_model.invoke.return_value = mock_response
    mock_create_model.return_value = mock_model

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.describe_image.invoke({
            "image_path": "test.jpg",
        })

    result = json.loads(result_json)

    assert "image_size_kb" in result
    assert result["image_size_kb"] == 2.0  # 2048 bytes = 2 KB


@patch("agent_workspaces.krieger.tools.describe_image._create_vision_model")
def test_describe_image_model_error_handling(
    mock_create_model,
    workspace_path: Path,
    create_test_image,
    mock_api_keys,
):
    """Test graceful handling of model invocation errors."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("test.jpg")

    # Mock model to raise an error
    mock_model = MagicMock()
    mock_model.invoke.side_effect = RuntimeError("API rate limit exceeded")
    mock_create_model.return_value = mock_model

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.describe_image.invoke({
            "image_path": "test.jpg",
        })

    result = json.loads(result_json)

    assert "error" in result
    assert "API rate limit exceeded" in result["error"]


# Test compare_image_models tool


@patch("agent_workspaces.krieger.tools.describe_image._create_vision_model")
def test_compare_image_models_queries_all_available(
    mock_create_model,
    workspace_path: Path,
    create_test_image,
    mock_api_keys,
):
    """Test compare tool queries all available compare models."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("landscape.jpg")

    # Mock different responses for each model
    responses = {
        "claude-sonnet-4-5-20250929": "Detailed mountains with snow",
        "gpt-4.1": "Mountain landscape at sunset",
        "amazon.nova-pro-v1:0": "Alpine scenery with peaks",
    }

    def mock_invoke(messages):
        # Determine which model based on call args
        model_id = mock_create_model.call_args[0][0]["model_id"]
        response = MagicMock()
        response.content = responses.get(model_id, "Generic description")
        return response

    mock_model = MagicMock()
    mock_model.invoke = mock_invoke
    mock_create_model.return_value = mock_model

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.compare_image_models.invoke({
            "image_path": "landscape.jpg",
            "prompt": "Describe the landscape",
        })

    result = json.loads(result_json)

    assert result["status"] == "success"
    assert result["models_queried"] == 3
    assert result["models_succeeded"] == 3
    assert len(result["results"]) == 3


@patch("agent_workspaces.krieger.tools.describe_image._create_vision_model")
def test_compare_image_models_partial_failure(
    mock_create_model,
    workspace_path: Path,
    create_test_image,
    mock_api_keys,
):
    """Test compare tool handles partial failures gracefully."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("test.jpg")

    call_count = [0]

    def create_model_side_effect(config):
        call_count[0] += 1
        mock_model = MagicMock()

        if call_count[0] == 2:
            # Second model fails
            mock_model.invoke.side_effect = RuntimeError("Model error")
        else:
            # Other models succeed
            mock_response = MagicMock()
            mock_response.content = f"Description from {config['display_name']}"
            mock_model.invoke.return_value = mock_response

        return mock_model

    mock_create_model.side_effect = create_model_side_effect

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.compare_image_models.invoke({
            "image_path": "test.jpg",
        })

    result = json.loads(result_json)

    assert result["status"] == "success"
    assert result["models_queried"] == 3
    assert result["models_succeeded"] == 2

    # Check that failed model has error status
    failed_results = [r for r in result["results"] if r["status"] == "error"]
    assert len(failed_results) == 1
    assert "Model error" in failed_results[0]["error"]


def test_compare_image_models_no_models_available(workspace_path: Path, create_test_image, mock_no_api_keys):
    """Test error when no compare models are available."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("test.jpg")

    # Mock _get_available_models to return empty list
    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        with patch.object(dm, "_get_available_models", return_value=[]):
            result_json = dm.compare_image_models.invoke({
                "image_path": "test.jpg",
            })

    result = json.loads(result_json)

    assert "error" in result
    assert "No vision models available" in result["error"]


def test_compare_image_models_file_not_found(workspace_path: Path):
    """Test error when image file doesn't exist."""
    from agent_workspaces.krieger.tools import describe_image as dm

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.compare_image_models.invoke({
            "image_path": "missing.jpg",
        })

    result = json.loads(result_json)

    assert "error" in result
    assert "Image not found" in result["error"]


@patch("agent_workspaces.krieger.tools.describe_image._create_vision_model")
def test_compare_image_models_includes_metadata(
    mock_create_model,
    workspace_path: Path,
    create_test_image,
    mock_api_keys,
):
    """Test compare result includes expected metadata fields."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("chart.png", size_bytes=4096)

    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "A chart"
    mock_model.invoke.return_value = mock_response
    mock_create_model.return_value = mock_model

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.compare_image_models.invoke({
            "image_path": "chart.png",
        })

    result = json.loads(result_json)

    assert result["image_path"] == "chart.png"
    assert result["image_size_kb"] == 4.0
    assert "models_queried" in result
    assert "models_succeeded" in result
    assert "results" in result


@patch("agent_workspaces.krieger.tools.describe_image._create_vision_model")
def test_compare_image_models_result_format(
    mock_create_model,
    workspace_path: Path,
    create_test_image,
    mock_api_keys,
):
    """Test each result in compare has correct format."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("test.jpg")

    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Test description"
    mock_model.invoke.return_value = mock_response
    mock_create_model.return_value = mock_model

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.compare_image_models.invoke({
            "image_path": "test.jpg",
        })

    result = json.loads(result_json)

    for model_result in result["results"]:
        assert "model" in model_result
        assert "provider" in model_result
        assert "status" in model_result
        # Should have either "analysis" or "error"
        assert "analysis" in model_result or "error" in model_result


def test_compare_image_models_excludes_gpt5(monkeypatch):
    """Test compare tool excludes gpt5 from default set."""
    from agent_workspaces.krieger.tools import describe_image

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    # gpt5 should not be in the compare set (to avoid double-billing OpenAI)
    assert "gpt5" not in describe_image._COMPARE_MODELS
    assert "gpt" in describe_image._COMPARE_MODELS


# Test auto-selection priority


@patch("agent_workspaces.krieger.tools.describe_image._create_vision_model")
def test_auto_selection_priority_claude_first(
    mock_create_model,
    workspace_path: Path,
    create_test_image,
    mock_api_keys,
):
    """Test auto-selection prefers Claude over GPT and Bedrock."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("test.jpg")

    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Description"
    mock_model.invoke.return_value = mock_response
    mock_create_model.return_value = mock_model

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.describe_image.invoke({
            "image_path": "test.jpg",
            "model": "auto",
        })

    result = json.loads(result_json)

    # Should select Claude (first in priority)
    assert result["provider"] == "anthropic"
    assert "claude" in result["model"].lower()


@patch("agent_workspaces.krieger.tools.describe_image._create_vision_model")
def test_auto_selection_fallback_to_gpt(
    mock_create_model,
    workspace_path: Path,
    create_test_image,
    monkeypatch,
):
    """Test auto-selection falls back to GPT when Claude unavailable."""
    from agent_workspaces.krieger.tools import describe_image as dm

    # Only set OpenAI key
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    create_test_image("test.jpg")

    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Description"
    mock_model.invoke.return_value = mock_response
    mock_create_model.return_value = mock_model

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.describe_image.invoke({
            "image_path": "test.jpg",
            "model": "auto",
        })

    result = json.loads(result_json)

    # Should select GPT (Claude not available)
    assert result["provider"] == "openai"
    assert result["model"] == "gpt-4.1"


@patch("agent_workspaces.krieger.tools.describe_image._create_vision_model")
def test_auto_selection_fallback_to_bedrock(
    mock_create_model,
    workspace_path: Path,
    create_test_image,
    mock_no_api_keys,
):
    """Test auto-selection falls back to Bedrock when others unavailable."""
    from agent_workspaces.krieger.tools import describe_image as dm

    create_test_image("test.jpg")

    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Description"
    mock_model.invoke.return_value = mock_response
    mock_create_model.return_value = mock_model

    with patch.object(dm, "_WORKSPACE_ROOT", workspace_path):
        result_json = dm.describe_image.invoke({
            "image_path": "test.jpg",
            "model": "auto",
        })

    result = json.loads(result_json)

    # Should select Bedrock (only one available)
    assert result["provider"] == "bedrock"
    assert "nova" in result["model"].lower()
