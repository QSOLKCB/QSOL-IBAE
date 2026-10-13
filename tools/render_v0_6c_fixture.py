"""Render offline OpenAI wire/read-only conformance; no live API operation."""
from ibae.canonical import canonical_json
from ibae.transport_conformance import v0_6c_reference_fixture

if __name__ == "__main__":
    print(canonical_json(v0_6c_reference_fixture()))
