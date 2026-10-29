# Optional free-tier LLM research commentary

This is an **isolated research-only adapter**, not a trading agent. It does not call eToro,
access portfolio balances, generate order approvals, or connect to execution modules.
The open-free-llm-api project is a **directory**, not a free inference endpoint.
This implementation uses the official Groq OpenAI-compatible API directly, with the
existing pinned httpx dependency. Verify Groq's current free-tier terms, available
model IDs, data-handling policy and quotas yourself before opting in.

Configuration (never commit credentials):

- `FREE_LLM_MODEL`: exact currently available free-tier Groq model ID.
- `FREE_LLM_API_KEY`: private Groq API key.
- `FREE_LLM_NETWORK_ENABLED=1`: required opt-in to any network request.

Python example:

```python
from etoro_demo_bot.free_llm import analyze_research

# Supply ONLY sanitized, non-sensitive, public research. Never pass
# broker balances, account identifiers, API keys or customer data.
result = analyze_research("Public market-research summary without account data")
print(result.text)  # Untrusted commentary, not an order recommendation.
```

No automatic fallback to paid models or providers. Calls may be rate-limited or
rejected. The adapter does not prove a model is free, and no free-tier catalog
listing guarantees that usage is cost-free. Keep network disabled until verified.
AI output must never be routed into risk approval, order execution, or automated
strategy decisions. Offline tests use mock HTTP transport.
