"""Render offline v0.6A supervisor/recovery contract evidence."""
from ibae.canonical import canonical_json
from ibae.supervisor_conformance import v0_6a_reference_fixture

if __name__ == "__main__":
    print(canonical_json(v0_6a_reference_fixture()))
