from datetime import datetime
from pathlib import Path
import sys

from urllib.request import Request, urlopen
import pymysql
from zk import ZK


LOG_DIR = Path("/opt/hris-finger-collector/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "collector.log"


def log(message=""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"

    print(line)

    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


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
        payload = __import__("json").load(response)

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
        payload = __import__("json").load(response)

    if not payload.get("success"):
        raise RuntimeError(
            f"BDIP policy request failed for {code}."
        )

    return payload.get("data", {})


def get_bdip_pull_schedule():

    url = (
        f"{BDIP_API_URL}/finger-machines/pull-schedule"
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
        payload = __import__("json").load(response)

    if not payload.get("success"):
        raise RuntimeError(
            "BDIP pull schedule request failed."
        )

    return payload.get("data", [])



def is_pull_allowed():

    now = datetime.now().strftime("%H:%M")

    schedule = get_bdip_pull_schedule()

    for item in schedule:

        if (
            item.get("pullTime") == now
            and item.get("isActive") is True
        ):
            return True

    return False



def report_bdip_pull(machine_code, result):
    url = (
        f"{BDIP_API_URL}/finger-machines/"
        f"{machine_code}/runtime/pull"
    )

    payload = {
        "readCount": result.get("read", 0),
        "insertedCount": result.get("inserted", 0),
        "skippedCount": result.get("skipped", 0),
        "success": result.get("success", False),
        "errorMessage": result.get("error"),
        "executedAt": datetime.utcnow().isoformat() + "Z",
    }

    request = Request(
        url,
        data=__import__("json").dumps(payload).encode("utf-8"),
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


DB_HOST = "192.168.100.128"
DB_USER = "hris_app"
DB_PASSWORD = "HRIS_DB_TEMP_2026"
DB_NAME = "HRIS"


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        autocommit=True,
    )


def harvest_device(ip, port=4370):
    log("=" * 70)
    log(f"DEVICE : {ip}:{port}")

    zk = ZK(
        ip,
        port=port,
        timeout=15,
        password=0,
        force_udp=False,
        ommit_ping=False,
    )

    conn = None
    db = None

    try:
        log("[1] Connecting to device...")
        conn = zk.connect()

        serial = None
        device_name = None

        try:
            serial = conn.get_serialnumber()
        except Exception:
            pass

        try:
            device_name = conn.get_device_name()
        except Exception:
            pass

        log("    CONNECTED")
        log(f"    SERIAL : {serial}")
        log(f"    NAME   : {device_name}")

        log("[2] Reading attendance...")
        attendance = conn.get_attendance()
        log(f"    RECORDS : {len(attendance)}")

        log("[3] Connecting to HRIS-DB...")
        db = get_db_connection()
        log("    DATABASE CONNECTED")

        inserted = 0
        skipped = 0

        log("[4] Inserting attendance...")

        with db.cursor() as cursor:

            for record in attendance:

                user_id = str(record.user_id)
                waktu = record.timestamp

                cursor.execute(
                    """
                    SELECT ID
                    FROM FINGER_HARVEST_RAW
                    WHERE DEVICE_IP = %s
                      AND USER_ID = %s
                      AND WAKTU = %s
                    LIMIT 1
                    """,
                    (
                        ip,
                        user_id,
                        waktu,
                    ),
                )

                existing = cursor.fetchone()

                if existing:
                    skipped += 1
                    continue

                cursor.execute(
                    """
                    INSERT INTO FINGER_HARVEST_RAW
                    (
                        HARVEST_DATE,
                        DEVICE_IP,
                        DEVICE_SERIAL,
                        DEVICE_NAME,
                        FINGER_ID,
                        UID_DEVICE,
                        USER_ID,
                        WAKTU,
                        STATUS,
                        PUNCH
                    )
                    VALUES
                    (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        waktu.date(),
                        ip,
                        serial,
                        device_name,
                        getattr(record, "uid", None),
                        getattr(record, "uid", None),
                        user_id,
                        waktu,
                        str(getattr(record, "status", "")),
                        getattr(record, "punch", None),
                    ),
                )

                inserted += 1

        log()
        log("HARVEST RESULT")
        log(f"READ    : {len(attendance)}")
        log(f"INSERT  : {inserted}")
        log(f"SKIPPED : {skipped}")

        return {
            "ip": ip,
            "read": len(attendance),
            "inserted": inserted,
            "skipped": skipped,
            "success": True,
        }

    except Exception as exc:
        log()
        log(f"ERROR : {repr(exc)}")

        return {
            "ip": ip,
            "read": 0,
            "inserted": 0,
            "skipped": 0,
            "success": False,
            "error": str(exc),
        }

    finally:
        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass

        if db:
            try:
                db.close()
            except Exception:
                pass


def main():
    log()
    log("=" * 70)
    log("HRIS FINGER COLLECTOR - MULTI DEVICE")
    log("=" * 70)
    try:
        if not is_pull_allowed():

            log(
                "GLOBAL PULL SCHEDULE : DISABLED"
            )

            return 0

    except Exception as exc:

        log(
            "GLOBAL PULL SCHEDULE CHECK ERROR : "
            f"{repr(exc)}"
        )

        return 1


    machines = get_bdip_machines()

    log(f"BDIP MACHINES : {len(machines)}")
    log()

    results = []

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
            continue

        collection_enabled = (
            policy.get("collectionEnabled")
            is True
        )

        log(
            f"BDIP MACHINE : "
            f"{code} | {name} | {ip}:{port}"
        )

        log(
            f"BDIP POLICY : "
            f"COLLECTION="
            f"{'ON' if collection_enabled else 'OFF'}"
        )

        if not collection_enabled:
            log(
                f"{code} : COLLECTION DISABLED "
                f"BY BDIP POLICY"
            )
            continue

        result = harvest_device(ip, port)

        try:
            report_bdip_pull(code, result)
            log(
                f"{code} : PULL RESULT REPORTED TO BDIP"
            )
        except Exception as exc:
            log(
                f"{code} : BDIP PULL REPORT ERROR : "
                f"{repr(exc)}"
            )

        results.append(result)

    log()
    log("=" * 70)
    log("TOTAL HARVEST SUMMARY")
    log("=" * 70)

    total_read = 0
    total_inserted = 0
    total_skipped = 0

    for result in results:
        total_read += result["read"]
        total_inserted += result["inserted"]
        total_skipped += result["skipped"]

        if result["success"]:
            log(
                f"{result['ip']:16} "
                f"READ={result['read']:4} "
                f"INSERT={result['inserted']:4} "
                f"SKIP={result['skipped']:4}"
            )
        else:
            log(
                f"{result['ip']:16} ERROR={result.get('error')}"
            )

    log("-" * 70)
    log(f"TOTAL READ    : {total_read}")
    log(f"TOTAL INSERT  : {total_inserted}")
    log(f"TOTAL SKIPPED : {total_skipped}")
    log("=" * 70)

    failed = [
        result for result in results
        if not result["success"]
    ]

    if failed:
        log(f"FAILED DEVICES : {len(failed)}")
        return 1

    log("ALL DEVICES : SUCCESS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
