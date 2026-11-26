"""Service settings. Durations are strings with a unit, like the ops team writes them."""

STRIPE_GW_URL = "https://stripe-gw.internal/v1/charges"
STRIPE_GW_TIMEOUT = "3s"  # the gateway's SLA is 2s, so 3s leaves headroom
RETRY_DELAY = "250ms"
MAX_ATTEMPTS = 2
