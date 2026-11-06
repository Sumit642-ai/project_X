"""Demo mode (DEMO_MODE=true only): `make demo` build, a movable frozen clock with scripted
intraday deliveries, and operator toggles that break things on purpose for the 15-minute script
(docs/DEMO.md). Breakage goes through the same paths as real life: feed files are ingested by the
data-layer mock, consents arrive as snapshots, the mock CM platform is told to go down."""
