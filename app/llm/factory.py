from app.config import Settings, get_settings
from app.llm.base import LLMClient, LLMConfigError

PROVIDERS = ("mock", "openai", "anthropic", "gemini")


def get_llm_client(provider: str | None = None, settings: Settings | None = None,
                   api_key: str | None = None, model: str | None = None) -> LLMClient:
    """api_key / model (optional) override the .env values for this one client - used by the web UI."""
    s = settings or get_settings()
    name = (provider or s.llm_provider).lower().strip()
    key = (api_key or "").strip() or None
    model = (model or "").strip() or None
    if name == "mock":
        from app.llm.mock_client import MockLLMClient

        return MockLLMClient(currency=s.currency)
    if name == "openai":
        if not (key or s.openai_api_key):
            raise LLMConfigError("OpenAI API key missing: enter it in the UI or set OPENAI_API_KEY.")
        from app.llm.openai_client import OpenAIClient

        return OpenAIClient(key or s.openai_api_key, model or s.openai_model)
    if name == "anthropic":
        if not (key or s.anthropic_api_key):
            raise LLMConfigError("Anthropic API key missing: enter it in the UI or set ANTHROPIC_API_KEY.")
        from app.llm.anthropic_client import AnthropicClient

        return AnthropicClient(key or s.anthropic_api_key, model or s.anthropic_model)
    if name == "gemini":
        if not (key or s.gemini_api_key):
            raise LLMConfigError("Gemini API key missing: enter it in the UI or set GEMINI_API_KEY.")
        from app.llm.gemini_client import GeminiClient

        return GeminiClient(key or s.gemini_api_key, model or s.gemini_model)
    raise LLMConfigError(f"Unknown provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}")
