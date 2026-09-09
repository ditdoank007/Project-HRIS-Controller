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


def read_device_fingerprint_data(ip, port=4370):
    """
    Read-only fingerprint/user snapshot from a ZK device.

    This function does not modify the device and does not write
    anything to the HRIS or BDIP database.
    """
    log("=" * 70)
    log(f"ATTENDANCE PREVIEW : {ip}:{port}")

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
        log("[1] Connecting to device...")
        conn = zk.connect()
        log("    CONNECTED")

        log("[2] Reading users...")
        users = conn.get_users()
        log(f"    USERS : {len(users)}")

        log("[3] Reading fingerprint templates...")
        templates = conn.get_templates()
        log(f"    TEMPLATES : {len(templates)}")

        user_data = []

        for user in users:
            user_data.append(
                {
                    "uid": getattr(user, "uid", None),
                    "name": getattr(user, "name", ""),
                    "userId": getattr(user, "user_id", ""),
                    "privilege": getattr(user, "privilege", 0),
                    "groupId": getattr(user, "group_id", ""),
                    "card": getattr(user, "card", 0),
                }
            )

        template_data = []

        for finger in templates:
            template = getattr(finger, "template", b"")

            template_data.append(
                {
                    "uid": getattr(finger, "uid", None),
                    "fid": getattr(finger, "fid", None),
                    "valid": getattr(finger, "valid", 0),
                    "size": len(template),
                    "template": template.hex(),
                }
            )

        return {
            "success": True,
            "ip": ip,
            "port": port,
            "users": user_data,
            "templates": template_data,
            "userCount": len(user_data),
            "templateCount": len(template_data),
        }

    except Exception as exc:
        log()
        log(f"ATTENDANCE PREVIEW ERROR : {repr(exc)}")

        return {
            "success": False,
            "ip": ip,
            "port": port,
            "users": [],
            "templates": [],
            "userCount": 0,
            "templateCount": 0,
            "error": str(exc),
        }

    finally:
        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass



def read_device_user_with_templates(ip, port, uid):
    """
    Read one device user together with all fingerprint templates.

    Read-only:
    - tidak membuat user
    - tidak mengubah user
    - tidak menghapus template
    """
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
        conn = zk.connect()

        users = conn.get_users()
        matching_users = [u for u in users if int(u.uid) == int(uid)]

        if len(matching_users) == 0:
            return {
                "success": False,
                "found": False,
                "uid": int(uid),
                "message": f"UID {uid} tidak ditemukan pada device.",
                "user": None,
                "fingers": [],
            }

        if len(matching_users) > 1:
            return {
                "success": False,
                "found": False,
                "uid": int(uid),
                "message": f"UID {uid} ditemukan lebih dari satu kali.",
                "user": None,
                "fingers": [],
            }

        user = matching_users[0]

        all_templates = conn.get_templates()
        fingers = [
            finger
            for finger in all_templates
            if int(finger.uid) == int(uid)
        ]

        fingers.sort(key=lambda finger: int(finger.fid))

        return {
            "success": True,
            "found": True,
            "uid": int(user.uid),
            "message": "User dan fingerprint berhasil dibaca.",
            "user": user,
            "fingers": fingers,
        }

    except Exception as exc:
        return {
            "success": False,
            "found": False,
            "uid": int(uid),
            "message": str(exc),
            "user": None,
            "fingers": [],
        }

    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass

def delete_device_user(ip, port=4370, uid=0):
    """
    Delete one user from a ZKTeco finger machine by device UID.

    Safety:
    - Read current users first.
    - Verify the requested UID exists.
    - Delete exactly that UID.
    - Read users again and verify the UID is gone.
    - Does not touch BDIP database.
    """
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
        conn = zk.connect()

        users_before = conn.get_users()
        target = next(
            (user for user in users_before if int(user.uid) == int(uid)),
            None,
        )

        if target is None:
            return {
                "success": False,
                "uid": int(uid),
                "userId": "",
                "name": "",
                "deleted": False,
                "verified": False,
                "error": f"UID {uid} tidak ditemukan pada mesin.",
            }

        target_user_id = str(getattr(target, "user_id", "") or "")
        target_name = str(getattr(target, "name", "") or "")

        conn.delete_user(uid=int(uid))

        users_after = conn.get_users()
        still_exists = any(
            int(user.uid) == int(uid)
            for user in users_after
        )

        return {
            "success": not still_exists,
            "uid": int(uid),
            "userId": target_user_id,
            "name": target_name,
            "deleted": not still_exists,
            "verified": not still_exists,
        }

    except Exception as exc:
        return {
            "success": False,
            "uid": int(uid),
            "userId": "",
            "name": "",
            "deleted": False,
            "verified": False,
            "error": repr(exc),
        }

    finally:
        if conn:
            try:
                conn.disconnect()
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

def set_device_user_enabled(ip, port, uid, enabled):
    """
    Enable/disable satu user ZKTeco tanpa menghapus user atau fingerprint.

    Pada packet user ZKTeco TFT:
      bit 0 pada permission byte = enable flag.
        0 = enabled
        1 = disabled

    Parameter uid adalah UID internal device, bukan FingerID/UserID.
    """
    import struct
    from zk import ZK, const

    uid = int(uid)

    zk = ZK(
        ip,
        port=int(port),
        timeout=15,
        password=0,
        force_udp=False,
        ommit_ping=False,
    )

    conn = None

    try:
        conn = zk.connect()

        conn.read_sizes()

        if not conn.users:
            raise RuntimeError("Mesin tidak memiliki data user.")

        data, size = conn.read_with_buffer(
            const.CMD_USERTEMP_RRQ,
            const.FCT_USER,
        )

        if size < 4:
            raise RuntimeError("Data user dari mesin tidak valid.")

        total_size = struct.unpack("<I", data[:4])[0]

        if total_size <= 0 or total_size % conn.users != 0:
            raise RuntimeError(
                "Ukuran packet user tidak valid: "
                f"total={total_size}, users={conn.users}"
            )

        packet_size = total_size // conn.users

        if packet_size not in (28, 72):
            raise RuntimeError(
                f"Ukuran packet user tidak didukung: {packet_size}"
            )

        payload = data[4:4 + total_size]

        target = None

        for offset in range(0, len(payload), packet_size):
            entry = payload[offset:offset + packet_size]

            if len(entry) < packet_size:
                continue

            entry_uid = struct.unpack_from("<H", entry, 0)[0]

            if entry_uid == uid:
                target = bytearray(entry)
                break

        if target is None:
            return {
                "success": False,
                "found": False,
                "uid": uid,
                "enabled": None,
                "message": f"UID {uid} tidak ditemukan di mesin.",
            }

        old_permission = target[2]
        old_enabled = (old_permission & 0x01) == 0

        # Hanya ubah bit E0.
        if enabled:
            target[2] = target[2] & 0xFE
        else:
            target[2] = target[2] | 0x01

        new_permission = target[2]
        new_enabled = (new_permission & 0x01) == 0

        # Tidak perlu menulis jika kondisi sudah sesuai.
        if old_enabled == bool(enabled):
            return {
                "success": True,
                "found": True,
                "changed": False,
                "uid": uid,
                "enabled": old_enabled,
                "previous_enabled": old_enabled,
                "message": "Status user sudah sesuai.",
            }

        # Device harus dikunci selama update user record.
        conn.disable_device()

        try:
            response = conn._ZK__send_command(
                const.CMD_USER_WRQ,
                bytes(target),
                1024,
            )

            if not response.get("status"):
                raise RuntimeError("CMD_USER_WRQ gagal.")

            response = conn._ZK__send_command(
                const.CMD_REFRESHDATA,
                b"",
                1024,
            )

            if not response.get("status"):
                raise RuntimeError("CMD_REFRESHDATA gagal.")

        finally:
            conn.enable_device()

        # Verifikasi ulang dari mesin.
        conn.read_sizes()

        verify_data, verify_size = conn.read_with_buffer(
            const.CMD_USERTEMP_RRQ,
            const.FCT_USER,
        )

        verify_total = struct.unpack("<I", verify_data[:4])[0]
        verify_packet_size = verify_total // conn.users
        verify_payload = verify_data[4:4 + verify_total]

        verified_enabled = None

        for offset in range(0, len(verify_payload), verify_packet_size):
            entry = verify_payload[offset:offset + verify_packet_size]

            if len(entry) < verify_packet_size:
                continue

            entry_uid = struct.unpack_from("<H", entry, 0)[0]

            if entry_uid == uid:
                verify_permission = entry[2]
                verified_enabled = (verify_permission & 0x01) == 0
                break

        if verified_enabled is None:
            raise RuntimeError(
                f"UID {uid} hilang saat verifikasi setelah update."
            )

        if verified_enabled != bool(enabled):
            raise RuntimeError(
                "Status user tidak sesuai setelah update: "
                f"expected={bool(enabled)}, actual={verified_enabled}"
            )

        return {
            "success": True,
            "found": True,
            "changed": True,
            "uid": uid,
            "enabled": verified_enabled,
            "previous_enabled": old_enabled,
            "message": (
                "User berhasil diaktifkan."
                if verified_enabled
                else "User berhasil dinonaktifkan."
            ),
        }

    finally:
        if conn:
            try:
                conn.enable_device()
            except Exception:
                pass

            try:
                conn.disconnect()
            except Exception:
                pass

def read_device_users_with_templates(ip, port):
    """
    Read all device users together with all fingerprint templates.

    Read-only:
    - tidak membuat user
    - tidak mengubah user
    - tidak menghapus user
    - tidak mengubah template
    - menggunakan satu koneksi device
    """

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
        conn = zk.connect()

        users = conn.get_users()
        all_templates = conn.get_templates()

        templates_by_uid = {}

        for finger in all_templates:
            uid = int(finger.uid)

            templates_by_uid.setdefault(uid, []).append(
                {
                    "fid": int(finger.fid),
                    "valid": int(getattr(finger, "valid", 0)),
                    "size": len(finger.template),
                    "template": finger.template.hex(),
                }
            )

        for uid in templates_by_uid:
            templates_by_uid[uid].sort(
                key=lambda item: item["fid"]
            )

        user_data = []

        for user in users:
            uid = int(user.uid)

            user_data.append(
                {
                    "uid": uid,
                    "name": getattr(user, "name", "") or "",
                    "privilege": int(
                        getattr(user, "privilege", 0)
                    ),
                    "password": getattr(user, "password", "") or "",
                    "groupId": getattr(user, "group_id", "") or "",
                    "userId": getattr(user, "user_id", "") or "",
                    "card": getattr(user, "card", 0) or 0,
                    "fingers": templates_by_uid.get(uid, []),
                }
            )

        user_data.sort(
            key=lambda item: (
                str(item["userId"]).strip().lower(),
                item["uid"],
            )
        )

        template_count = sum(
            len(item["fingers"])
            for item in user_data
        )

        return {
            "success": True,
            "ip": ip,
            "port": port,
            "users": user_data,
            "userCount": len(user_data),
            "templateCount": template_count,
        }

    except Exception as exc:
        log()
        log(
            f"ATTENDANCE READ ALL USERS/TEMPLATES ERROR : {repr(exc)}"
        )

        return {
            "success": False,
            "ip": ip,
            "port": port,
            "users": [],
            "userCount": 0,
            "templateCount": 0,
            "error": str(exc),
        }

    finally:
        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass



def sync_device_user(
    ip,
    port=4370,
    user_id="",
    name="",
    templates=None,
    enabled=True,
):
    """
    Create/update one BDIP user on a ZKTeco device.

    user_id = FingerID / ZKTeco UserID.
    uid     = internal device UID.

    Existing users:
      - keep existing device UID
      - update identity
      - compare templates
      - write only missing/different templates

    New users:
      - allocate a free device UID
      - create user
      - write all supplied templates

    The operation is verified by reading the user and templates back.
    """
    from zk import ZK
    from zk.user import User
    from zk.finger import Finger

    user_id = str(user_id or "").strip()
    name = str(name or "").strip()

    if not user_id:
        raise ValueError("user_id/FingerID wajib diisi.")

    if templates is None:
        templates = []

    if not isinstance(templates, list):
        raise ValueError("templates harus berupa list.")

    zk = ZK(
        ip,
        port=int(port),
        timeout=15,
        password=0,
        force_udp=False,
        ommit_ping=False,
    )

    conn = None

    try:
        conn = zk.connect()

        users = conn.get_users()

        target = next(
            (
                user
                for user in users
                if str(getattr(user, "user_id", "") or "") == user_id
            ),
            None,
        )

        is_new_user = target is None

        if target is not None:
            uid = int(target.uid)
        else:
            used_uids = {
                int(getattr(user, "uid", 0))
                for user in users
            }

            uid = max(1, int(getattr(conn, "next_uid", 1)))

            while uid in used_uids:
                uid += 1

            if uid > 65535:
                raise RuntimeError(
                    "Tidak tersedia UID kosong pada mesin."
                )

        # Normalisasi template dari BDIP.
        desired_fingers = {}

        for item in templates:
            fid = int(item.get("fid", -1))

            if fid < 0 or fid > 9:
                raise ValueError(
                    f"FID {fid} tidak valid. FID harus 0..9."
                )

            template_hex = str(
                item.get("template", "") or ""
            ).strip()

            if not template_hex:
                continue

            try:
                template = bytes.fromhex(template_hex)
            except ValueError as exc:
                raise ValueError(
                    f"Template FID {fid} bukan HEX valid."
                ) from exc

            valid = int(item.get("valid", 1))

            desired_fingers[fid] = Finger(
                uid=uid,
                fid=fid,
                valid=valid,
                template=template,
            )

        # Update/create user identity.
        conn.set_user(
            uid=uid,
            name=name,
            privilege=0,
            password="",
            group_id="",
            user_id=user_id,
            card=0,
        )

        # Baca template yang sudah ada pada mesin.
        existing_fingers = {}

        for fid in desired_fingers:
            existing = conn.get_user_template(
                uid,
                fid,
            )

            if existing is not None:
                existing_fingers[fid] = existing

        # Hanya tulis template yang memang berbeda atau belum ada.
        fingers_to_write = []

        for fid, desired in desired_fingers.items():
            existing = existing_fingers.get(fid)

            if (
                existing is None
                or existing.template != desired.template
            ):
                fingers_to_write.append(desired)

        if fingers_to_write:
            conn.save_user_template(
                User(
                    uid=uid,
                    name=name,
                    privilege=0,
                    password="",
                    group_id="",
                    user_id=user_id,
                    card=0,
                ),
                fingers=fingers_to_write,
            )

        # Terapkan status enabled/disabled.
        set_enabled_result = set_device_user_enabled(
            ip,
            port,
            uid,
            bool(enabled),
        )

        if not set_enabled_result.get("success"):
            raise RuntimeError(
                "Status enabled gagal diterapkan: "
                + str(set_enabled_result)
            )

        # READ-BACK VERIFICATION
        verified_users = conn.get_users()

        verified_user = next(
            (
                user
                for user in verified_users
                if int(user.uid) == uid
            ),
            None,
        )

        if verified_user is None:
            raise RuntimeError(
                f"Verifikasi gagal: UID {uid} tidak ditemukan."
            )

        verified_fids = []

        for fid, desired in desired_fingers.items():
            result = conn.get_user_template(
                uid,
                fid,
            )

            if result is None:
                raise RuntimeError(
                    f"Verifikasi gagal: template FID {fid} "
                    "tidak ditemukan."
                )

            if result.template != desired.template:
                raise RuntimeError(
                    f"Verifikasi gagal: template FID {fid} "
                    "berbeda setelah write."
                )

            verified_fids.append(fid)

        return {
            "success": True,
            "uid": uid,
            "userId": user_id,
            "name": name,
            "enabled": bool(enabled),
            "created": is_new_user,
            "updated": True,
            "templatesRequested": len(desired_fingers),
            "templatesWritten": len(fingers_to_write),
            "templateFidsWritten": [
                finger.fid
                for finger in fingers_to_write
            ],
            "templateFidsVerified": verified_fids,
            "verified": True,
            "message": (
                "User dan fingerprint berhasil "
                "disinkronkan dan diverifikasi."
            ),
        }

    except Exception as exc:
        return {
            "success": False,
            "uid": None,
            "userId": user_id,
            "name": name,
            "enabled": bool(enabled),
            "created": False,
            "updated": False,
            "templatesRequested": 0,
            "templatesWritten": 0,
            "templateFidsWritten": [],
            "templateFidsVerified": [],
            "verified": False,
            "error": repr(exc),
        }

    finally:
        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass
