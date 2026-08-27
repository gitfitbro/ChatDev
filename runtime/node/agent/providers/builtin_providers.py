"""Register built-in agent providers."""

from runtime.node.agent.providers.base import ProviderRegistry

from runtime.node.agent.providers.openai_provider import OpenAIProvider

ProviderRegistry.register(
    "openai",
    OpenAIProvider,
    label="OpenAI",
    summary="OpenAI models via the official OpenAI SDK (responses API)",
)

try:
    from runtime.node.agent.providers.gemini_provider import GeminiProvider
except ImportError:
    GeminiProvider = None

if GeminiProvider is not None:
    ProviderRegistry.register(
        "gemini",
        GeminiProvider,
        label="Google Gemini",
        summary="Google Gemini models via google-genai",
    )
else:
    print("Gemini provider not registered: google-genai library not found.")

try:
    from runtime.node.agent.providers.anthropic_provider import AnthropicProvider
except ImportError:
    AnthropicProvider = None

if AnthropicProvider is not None:
    ProviderRegistry.register(
        "anthropic",
        AnthropicProvider,
        label="Anthropic Claude",
        summary="Claude models via the official Anthropic SDK (messages API)",
    )
else:
    print("Anthropic provider not registered: anthropic library not found.")
