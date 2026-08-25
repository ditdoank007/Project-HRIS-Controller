import subprocess
import sys
from datetime import datetime


PYTHON = "/opt/hris-finger-collector/.venv/bin/python"

COLLECTOR = "/opt/hris-finger-collector/collector.py"
NORMALIZER = "/opt/hris-finger-collector/normalizer.py"


def run_step(name, script):

    print()
    print("=" * 70)
    print(f"PIPELINE : {name}")
    print("=" * 70)
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"START"
    )

    result = subprocess.run(
        [PYTHON, script],
        cwd="/opt/hris-finger-collector",
    )

    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"{name} EXIT CODE = {result.returncode}"
    )

    return result.returncode


def main():

    print()
    print("=" * 70)
    print("HRIS FINGER COLLECTOR PIPELINE")
    print("=" * 70)

    # ----------------------------------------------------------
    # STEP 1
    # Collector
    # ----------------------------------------------------------

    result = run_step(
        "COLLECTOR",
        COLLECTOR,
    )

    if result != 0:

        print()
        print("=" * 70)
        print("PIPELINE FAILED")
        print("NORMALIZER NOT EXECUTED")
        print("=" * 70)

        sys.exit(result)

    # ----------------------------------------------------------
    # STEP 2
    # Normalizer
    # ----------------------------------------------------------

    result = run_step(
        "NORMALIZER",
        NORMALIZER,
    )

    if result != 0:

        print()
        print("=" * 70)
        print("PIPELINE FAILED")
        print("NORMALIZER FAILED")
        print("=" * 70)

        sys.exit(result)

    # ----------------------------------------------------------
    # SUCCESS
    # ----------------------------------------------------------

    print()
    print("=" * 70)
    print("PIPELINE SUCCESS")
    print("COLLECTOR : PASS")
    print("NORMALIZER: PASS")
    print("=" * 70)

    sys.exit(0)


if __name__ == "__main__":
    main()
