from datetime import datetime
from pathlib import Path
import json
import os
from urllib.request import Request, urlopen

from zk import ZK


LOG_DIR = Path("/opt/hris-finger-collector/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "time-sync.log"

STATE_FILE = (
    Path("/opt/hris-finger-collector/data")
    / "clear_state.json"
)


BDIP_API_URL = "http://192.168.100.124/api"

DEVICE_PORT = 4370


def get_bdip_machines():
    url = f"{BDIP_API_URL}/finger-machines"

    request = Request(
        url,
        headers={
            "Accept": "application/json",
        },
        method="GET",
    )

    with urlopen(
        request,
        timeout=15,
    ) as response:
        payload = json.load(response)

    if not payload.get("success"):
        raise RuntimeError(
            "BDIP returned unsuccessful response."
        )

    machines = payload.get("data", [])

    return [
        machine
        for machine in machines
        if machine.get("isActive") is True
    ]


def get_bdip_policy(code):
    url = (
        f"{BDIP_API_URL}/finger-machines/"
        f"{code}/policy"
    )

    request = Request(
        url,
        headers={
            "Accept": "application/json",
        },
        method="GET",
    )

    with urlopen(
        request,
        timeout=15,
    ) as response:
        payload = json.load(response)

    if not payload.get("success"):
        raise RuntimeError(
            f"BDIP policy request failed for {code}."
        )

    return payload.get("data", {})


def get_bdip_global_policy():

    url = (
        f"{BDIP_API_URL}/finger-machines/global-policy"
    )

    request = Request(
        url,
        headers={
            "Accept": "application/json",
        },
        method="GET",
    )

    with urlopen(
        request,
        timeout=15,
    ) as response:
        payload = json.load(response)

    if not payload.get("success"):
        raise RuntimeError(
            "BDIP global policy request failed."
        )

    return payload.get("data", {})




def load_clear_state():

    if not STATE_FILE.exists():
        return {}

    try:
        with STATE_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(file)

    except Exception:
        return {}



def save_clear_state(data):

    STATE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with STATE_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            indent=2,
        )



def should_run_clear():

    if os.getenv("CLEAR_TEST") == "true":
        return True


    policy = get_bdip_global_policy()

    if policy.get("clearEnabled") is not True:
        return False


    now = datetime.now()

    clear_time = (
        policy.get("clearTime", "")
        [:5]
    )

    current_time = (
        now.strftime("%H:%M")
    )

    if current_time != clear_time:
        return False


    state = load_clear_state()

    if (
        state.get("lastClearDate")
        == now.strftime("%Y-%m-%d")
    ):
        return False


    return True




def report_bdip_sync(
    machine_code,
    device_before,
    server_time,
    device_after,
    success,
):
    url = (
        f"{BDIP_API_URL}/finger-machines/"
        f"{machine_code}/runtime/sync"
    )

    payload = {
        "deviceTimeBefore": (
            device_before.isoformat()
            if device_before
            else None
        ),
        "serverTime": (
            server_time.isoformat()
            if server_time
            else None
        ),
        "deviceTimeAfter": (
            device_after.isoformat()
            if device_after
            else None
        ),
        "success": success,
        "executedAt": datetime.now().isoformat(),
    }

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urlopen(
        request,
        timeout=15,
    ) as response:
        response.read()


def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"

    print(line)

    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def sync_device(ip, port=DEVICE_PORT):
    zk = ZK(
        ip,
        port=port,
        timeout=15,
        password=0,
        force_udp=False,
        ommit_ping=False,
    )

    conn = None

    try:
        log(f"{ip} CONNECTING")

        conn = zk.connect()

        server_time = datetime.now()
        device_before = conn.get_time()

        conn.set_time(server_time)

        device_after = conn.get_time()

        log(
            f"{ip} OK | "
            f"BEFORE={device_before} | "
            f"SERVER={server_time} | "
            f"AFTER={device_after}"
        )

        return {
            "success": True,
            "deviceTimeBefore": device_before,
            "serverTime": server_time,
            "deviceTimeAfter": device_after,
        }

    except Exception as exc:
        log(f"{ip} ERROR | {repr(exc)}")

        return {
            "success": False,
            "deviceTimeBefore": None,
            "serverTime": None,
            "deviceTimeAfter": None,
            "error": str(exc),
        }

    finally:
        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass


def clear_device(ip, port=DEVICE_PORT):

    zk = ZK(
        ip,
        port=port,
        timeout=15,
        password=0,
        force_udp=False,
        ommit_ping=False,
    )

    conn = None

    try:
        log(f"{ip} CLEAR CONNECTING")

        conn = zk.connect()

        if os.getenv("CLEAR_TEST") == "true":

            log(
                f"{ip} CLEAR TEST MODE - SKIP DELETE"
            )

        else:

            conn.clear_attendance()

            log(
                f"{ip} CLEAR ATTENDANCE SUCCESS"
            )

        return True

    except Exception as exc:

        log(
            f"{ip} CLEAR ERROR | {repr(exc)}"
        )

        return False

    finally:

        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass




def run_global_clear():

    if not should_run_clear():
        return


    log(
        "GLOBAL CLEAR START"
    )


    machines = get_bdip_machines()

    success = 0
    failed = 0


    for machine in machines:

        ip = machine.get("ipAddress")
        port = machine.get("port") or DEVICE_PORT

        result = clear_device(
            ip,
            port,
        )

        if result:
            success += 1
        else:
            failed += 1


    if failed == 0:

        save_clear_state(
            {
                "lastClearDate":
                    datetime.now()
                    .strftime("%Y-%m-%d")
            }
        )

        log(
            "CLEAR STATE SAVED"
        )

    else:

        log(
            "CLEAR STATE NOT SAVED "
            "BECAUSE SOME DEVICES FAILED"
        )


    log(
        f"GLOBAL CLEAR FINISHED "
        f"SUCCESS={success} "
        f"FAILED={failed}"
    )




def main():
    log("=" * 70)
    log("HRIS FINGER TIME SYNCHRONIZATION")
    log("=" * 70)

    run_global_clear()

    machines = get_bdip_machines()

    log(
        f"BDIP MACHINES : {len(machines)}"
    )

    success = 0
    failed = 0

    for machine in machines:
        code = machine.get("code")
        name = machine.get("name")
        ip = machine.get("ipAddress")
        port = machine.get("port") or DEVICE_PORT

        try:
            policy = get_bdip_policy(code)
        except Exception as exc:
            log(
                f"{code} POLICY ERROR : {repr(exc)}"
            )
            failed += 1
            continue

        sync_enabled = (
            policy.get("timeSyncEnabled")
            is True
        )

        log(
            f"BDIP MACHINE : "
            f"{code} | {name} | {ip}:{port}"
        )

        log(
            f"BDIP POLICY : "
            f"TIME_SYNC="
            f"{'ON' if sync_enabled else 'OFF'}"
        )

        if not sync_enabled:
            log(
                f"{code} : TIME SYNC DISABLED "
                f"BY BDIP POLICY"
            )
            continue

        result = sync_device(ip, port)

        try:
            report_bdip_sync(
                code,
                result.get("deviceTimeBefore"),
                result.get("serverTime"),
                result.get("deviceTimeAfter"),
                result.get("success", False),
            )

            log(
                f"{code} : SYNC RESULT REPORTED TO BDIP"
            )

        except Exception as exc:
            log(
                f"{code} : BDIP SYNC REPORT ERROR : "
                f"{repr(exc)}"
            )

        if result.get("success") is True:
            success += 1
        else:
            failed += 1

    log("-" * 70)
    log(f"SUCCESS : {success}")
    log(f"FAILED  : {failed}")
    log("=" * 70)


if __name__ == "__main__":
    main()
