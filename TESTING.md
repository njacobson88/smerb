# Running the tests

The project's first automated tests cover the most safety-critical pure logic.
No external test runner is required (stdlib `unittest` + Flutter's bundled
`flutter_test`), so they run anywhere and are CI-friendly.

## Backend (Python) — C-SSRS crisis detection

```bash
cd dashboard/backend
python3 -m unittest discover -s tests -v
```

`tests/test_cssrs_sync.py` locks in the 2026-06-11 fix where the C-SSRS
instrument/field names were all wrong (crisis detection was completely dead).
It guards: the exact REDCap instrument + field names, the crisis trigger firing
on intent/plan/behavior across all three forms (screener/weekly/pediatric),
non-overfiring on low-level ideation, severity computation, and the
`risk_assessment.py`-compat output shapes.

## App (Flutter/Dart) — EMA safety-trigger config

```bash
flutter test                       # all dart tests
flutter test test/ema_safety_config_test.dart
```

`test/ema_safety_config_test.dart` guards the EMA safety-trigger configuration —
the root of the crisis pipeline. It fails if a threshold changes, if the
`inverted` flag is dropped from `ability_safe` (low ability-to-stay-safe = danger),
or if slider values stop parsing as doubles (the type the trigger check requires).

## Notes
- These are pure-logic unit tests (no Firebase/network). Modules coupled to
  FastAPI/Firebase (e.g. `main.py`) need a venv with the full `requirements.txt`
  to import; expanding coverage there is a good next step.
- When you change the C-SSRS field map or the EMA safety thresholds, run the
  relevant suite — a green run confirms crisis detection still fires correctly.
