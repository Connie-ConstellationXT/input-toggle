# Imported Mergetriggers sources

Copied from `/home/conneh/actual/development/python/Mergetriggers/` on 2026-09-18.

Included: all top-level Python scripts, local `dpad_util.py` and `trigger_util.py` dependencies, original README, requirements, and shell.nix. The original repository, virtualenv executables, caches, evidence files, and unrelated ML environment under `otherprojectexport/` were not copied.

`vendor/python3.12/` and `vendor/python3.13/` contain the existing evdev 1.9.2 packages and distribution metadata copied from the corresponding site-packages directories. They include Linux x86-64 compiled extensions. Each distribution’s MIT license is in its `*.dist-info/licenses/LICENSE` file. Use the input-toggle root `shell.nix` to obtain evdev for another Python version or architecture.

Integration is in `../runner.py` and `../../remapping.py`. The runner supplies the selected F710 event path, exclusive physical-device grab, virtual output permissions, and systemd readiness notification. It uses each selected script’s original capabilities and event-mapping loop. The two merged-trigger scripts additionally flush D-pad output before their early `continue`, so isolated D-pad changes are delivered immediately.

The legacy hardcoded `DEVICE_PATH`/`TRUDDER_PATH` values remain in the copied originals for reference. Use the input-toggle `r` menu for managed F710 remapping, rather than executing these copies directly without reviewing their paths. Yareli and diagnostic scripts are not F710 remapping profiles.
