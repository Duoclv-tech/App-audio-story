"""
Node-locked offline license enforcement (Ed25519 signed tokens).

Activation flow: the tool calls the storefront once online, receives a
server-signed license token bound to this machine's hardware fingerprint,
stores it, and on every later launch verifies the token OFFLINE against a
public key embedded in this binary. See docs license-token.md /
license-verify-lifecycle.md for the full contract.
"""
