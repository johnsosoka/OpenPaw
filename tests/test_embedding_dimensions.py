"""Tests for embedding provider dimension detection."""

from openpaw.stores.vector.embeddings import LocalEmbeddingProvider, OpenAIEmbeddingProvider


class TestOpenAIEmbeddingDimensions:
    """Tests for OpenAIEmbeddingProvider.KNOWN_DIMENSIONS class attribute."""

    def test_known_dimensions_is_a_dict(self):
        """KNOWN_DIMENSIONS exists and is a dict."""
        assert isinstance(OpenAIEmbeddingProvider.KNOWN_DIMENSIONS, dict)

    def test_text_embedding_3_small_dimensions(self):
        """text-embedding-3-small maps to 1536 dimensions."""
        assert OpenAIEmbeddingProvider.KNOWN_DIMENSIONS["text-embedding-3-small"] == 1536

    def test_text_embedding_3_large_dimensions(self):
        """text-embedding-3-large maps to 3072 dimensions."""
        assert OpenAIEmbeddingProvider.KNOWN_DIMENSIONS["text-embedding-3-large"] == 3072

    def test_text_embedding_ada_002_dimensions(self):
        """text-embedding-ada-002 maps to 1536 dimensions."""
        assert OpenAIEmbeddingProvider.KNOWN_DIMENSIONS["text-embedding-ada-002"] == 1536

    def test_unknown_model_not_in_dict(self):
        """Unknown model names are absent from KNOWN_DIMENSIONS (use .get() for fallback)."""
        assert "unknown-model" not in OpenAIEmbeddingProvider.KNOWN_DIMENSIONS
        assert "text-embedding-999" not in OpenAIEmbeddingProvider.KNOWN_DIMENSIONS

    def test_all_known_dimension_values_are_positive_ints(self):
        """Every value in KNOWN_DIMENSIONS is a positive integer."""
        for model_name, dims in OpenAIEmbeddingProvider.KNOWN_DIMENSIONS.items():
            assert isinstance(dims, int), f"{model_name} has non-int dimensions"
            assert dims > 0, f"{model_name} has non-positive dimensions"

    def test_known_dimensions_covers_at_least_three_models(self):
        """KNOWN_DIMENSIONS covers the three currently documented OpenAI models."""
        assert len(OpenAIEmbeddingProvider.KNOWN_DIMENSIONS) >= 3


class TestLocalEmbeddingDimensions:
    """Tests for LocalEmbeddingProvider.KNOWN_DIMENSIONS class attribute."""

    def test_known_dimensions_is_a_dict(self):
        """KNOWN_DIMENSIONS exists and is a dict."""
        assert isinstance(LocalEmbeddingProvider.KNOWN_DIMENSIONS, dict)

    def test_all_minilm_l6_v2_dimensions(self):
        """all-MiniLM-L6-v2 maps to 384 dimensions."""
        assert LocalEmbeddingProvider.KNOWN_DIMENSIONS["all-MiniLM-L6-v2"] == 384

    def test_all_mpnet_base_v2_dimensions(self):
        """all-mpnet-base-v2 maps to 768 dimensions."""
        assert LocalEmbeddingProvider.KNOWN_DIMENSIONS["all-mpnet-base-v2"] == 768

    def test_all_minilm_l12_v2_dimensions(self):
        """all-MiniLM-L12-v2 maps to 384 dimensions."""
        assert LocalEmbeddingProvider.KNOWN_DIMENSIONS["all-MiniLM-L12-v2"] == 384

    def test_unknown_model_not_in_dict(self):
        """Unknown model names are absent from KNOWN_DIMENSIONS (use .get() for fallback)."""
        assert "unknown-model" not in LocalEmbeddingProvider.KNOWN_DIMENSIONS
        assert "gpt-4" not in LocalEmbeddingProvider.KNOWN_DIMENSIONS

    def test_all_known_dimension_values_are_positive_ints(self):
        """Every value in KNOWN_DIMENSIONS is a positive integer."""
        for model_name, dims in LocalEmbeddingProvider.KNOWN_DIMENSIONS.items():
            assert isinstance(dims, int), f"{model_name} has non-int dimensions"
            assert dims > 0, f"{model_name} has non-positive dimensions"
