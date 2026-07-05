"""
DEPRECATED — do not run this script.

Standalone velocity calibration was superseded in v0.2.0 by the calibration
integrated into `scripts/run_full_pipeline.py` (`calibrate_velocity_field()`),
and the legacy workflow became actively dangerous in v0.3.0.

Why it was removed (review finding 1.1):

  The old script calibrated `data/processed/fused/velocity_aligned.tif` and
  instructed the user to copy the result back into `data/raw/insar/` and rerun
  the pipeline. But as of v0.3.0, M1 projects line-of-sight velocity to
  vertical (factor ~1/cos(39 deg) ~= 1.29). Feeding an already-vertical,
  already-calibrated file back through M1 would apply that factor a SECOND
  time, inflating every velocity by ~29% and silently corrupting all
  downstream results. The script also predated the v0.3.0 calibration sanity
  checks (max-shift bound, candidate-spread sensitivity) and wrote into the
  raw-data directory.

What to use instead:

  Calibration now runs automatically inside the pipeline, between clustering
  (M4) and the InSAR overlay (M4B). It identifies the most stable cluster as
  the reference, applies the shift, and runs the sanity checks — no manual
  file shuffling.

      python scripts/run_full_pipeline.py                 # calibration runs automatically
      python scripts/run_full_pipeline.py --force-from cal # re-run calibration only
      python scripts/run_full_pipeline.py --no-calibration # skip calibration

  The reusable implementation lives in run_full_pipeline.calibrate_velocity_field().
"""

import sys


def main():
    sys.stderr.write(__doc__)
    sys.stderr.write(
        "\nERROR: calibrate_velocity.py is deprecated and will not run. "
        "Use scripts/run_full_pipeline.py (see above).\n"
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
