# Permanent project rules

- This project supports eToro DEMO trading only. Never implement, configure, call or fall back to real-money trading endpoints. Reject unknown account modes and destinations.
- No leverage: allow only explicitly verified unleveraged instruments and orders. Reject margin, shorts, leveraged products and derivatives. An API leverage value alone does not prove that a product is unleveraged.
- No paid services, subscriptions or chargeable API usage. Verify free access and applicable terms before adding an external dependency.
- Never request, print, log, commit or embed credentials. Read secrets from environment variables; never dump the environment. Use placeholders only in examples. Never include secrets in prompts, telemetry, fixtures or exception output.
- No order execution without explicit user authorization for the exact DEMO order. Approval to code, run tests or start the bot is not order authorization. Autonomous analysis may propose trades; it cannot approve them.
- Bind approval to account, instrument, direction, size, order type, price constraints and expiry. A changed or expired proposal requires new approval. Revalidate risk and demo identity immediately before submission.
- Until implementation is explicitly approved, make documentation changes only. Do not implement the bot or place orders.
- Verify authentication, API schemas and demo routes against current official eToro documentation before implementation. Do not invent endpoint paths or infer safety from a URL name.
- Fail closed when authentication, account identity, prices, portfolio state, approval or risk validation is uncertain. No live-mode configuration switch.
- Tests default to offline fixtures and mocked transport. Real DEMO order tests require separate explicit authorization. Preserve TLS verification; never retry an ambiguous order submission blindly.
- Keep all repository changes reviewable. Use the existing checkout; do not create worktrees unless requested.
