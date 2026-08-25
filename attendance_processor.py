from collections import defaultdict
from datetime import datetime, timedelta
import pymysql


DB_HOST = "192.168.100.128"
DB_USER = "hris_app"
DB_PASSWORD = "HRIS_DB_TEMP_2026"
DB_NAME = "HRIS"


IGNORE_FINGER_IDS = {
    "1",
    "2",
    "4",
    "5",
}

DUPLICATE_WINDOW_SECONDS = 60
MAX_OUT_AFTER_IN_HOURS = 30
MIN_VALID_DATETIME = datetime(1990, 1, 1)


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def is_valid_time(waktu):
    if waktu is None:
        return False

    return (
        waktu >= MIN_VALID_DATETIME
        and waktu <= datetime.now() + timedelta(days=1)
    )


def load_raw(cursor):
    cursor.execute("""
        SELECT
            ID,
            USER_ID,
            WAKTU,
            STATUS,
            PUNCH,
            DEVICE_IP
        FROM FINGER_HARVEST_RAW
        WHERE WAKTU >= '2026-07-01'
          AND WAKTU < '2026-08-01'
        ORDER BY USER_ID, WAKTU, ID
    """)
    return cursor.fetchall()


def collapse_duplicates(records):
    result = []

    for record in records:
        if not result:
            result.append(record)
            continue

        previous = result[-1]

        delta = (
            record["WAKTU"] - previous["WAKTU"]
        ).total_seconds()

        if (
            delta <= DUPLICATE_WINDOW_SECONDS
            and record["PUNCH"] == previous["PUNCH"]
        ):
            continue

        result.append(record)

    return result


def build_pairs(records):
    events = collapse_duplicates(records)

    pairs = []
    open_in = None

    for event in events:
        if not is_valid_time(event["WAKTU"]):
            continue

        punch = event["PUNCH"]

        if punch == 0:
            if open_in is None:
                open_in = event
            continue

        if punch == 1:
            if open_in is None:
                pairs.append({
                    "type": "OUT_ONLY",
                    "in": None,
                    "out": event,
                })
                continue

            delta = (
                event["WAKTU"] - open_in["WAKTU"]
            ).total_seconds()

            if delta < 0:
                continue

            if delta > MAX_OUT_AFTER_IN_HOURS * 3600:
                pairs.append({
                    "type": "IN_ONLY",
                    "in": open_in,
                    "out": None,
                })

                open_in = None

                pairs.append({
                    "type": "OUT_ONLY",
                    "in": None,
                    "out": event,
                })

                continue

            pairs.append({
                "type": "PAIR",
                "in": open_in,
                "out": event,
            })

            open_in = None

    if open_in is not None:
        pairs.append({
            "type": "IN_ONLY",
            "in": open_in,
            "out": None,
        })

    return pairs


def find_employee(cursor, finger_id):
    cursor.execute("""
        SELECT
            FingerID,
            NIP,
            Nama,
            Jabatan,
            UnitKerja,
            isKeluar,
            Tglkeluar
        FROM PEGAWAI
        WHERE FingerID = %s
    """, (finger_id,))

    rows = cursor.fetchall()

    if len(rows) == 1:
        return rows[0]

    if len(rows) == 0:
        return None

    # Jika satu FingerID mempunyai beberapa pegawai,
    # pilih pegawai aktif. Jika masih lebih dari satu,
    # dianggap ambiguous dan tidak diproses.
    active = [
        row for row in rows
        if row["isKeluar"] is None or row["isKeluar"] != "Y"
    ]

    if len(active) == 1:
        return active[0]

    return None


def upsert_absensi(cursor, finger_id, tgl_kerja, jam_in, jam_out):
    cursor.execute("""
        SELECT
            FingerID,
            TglKerja,
            TglJamIn,
            TglJamOut
        FROM ABSENSI
        WHERE FingerID = %s
          AND TglKerja = %s
        FOR UPDATE
    """, (finger_id, tgl_kerja))

    existing = cursor.fetchone()

    if existing:
        new_in = existing["TglJamIn"] or jam_in
        new_out = existing["TglJamOut"] or jam_out

        if (
            new_in != existing["TglJamIn"]
            or new_out != existing["TglJamOut"]
        ):
            cursor.execute("""
                UPDATE ABSENSI
                SET
                    TglJamIn = %s,
                    TglJamOut = %s,
                    TransaksiIn =
                        CASE
                            WHEN %s IS NOT NULL
                             AND TransaksiIn IS NULL
                            THEN 'LogFP'
                            ELSE TransaksiIn
                        END,
                    TransaksiOut =
                        CASE
                            WHEN %s IS NOT NULL
                             AND TransaksiOut IS NULL
                            THEN 'LogFP'
                            ELSE TransaksiOut
                        END,
                    UpdateInBy =
                        CASE
                            WHEN %s IS NOT NULL
                             AND UpdateInBy IS NULL
                            THEN 'HRIS_FINGER_COLLECTOR'
                            ELSE UpdateInBy
                        END,
                    UpdateOutBy =
                        CASE
                            WHEN %s IS NOT NULL
                             AND UpdateOutBy IS NULL
                            THEN 'HRIS_FINGER_COLLECTOR'
                            ELSE UpdateOutBy
                        END,
                    UpdateInDate = NOW(),
                    UpdateOutDate = NOW()
                WHERE FingerID = %s
                  AND TglKerja = %s
            """, (
                new_in,
                new_out,
                jam_in,
                jam_out,
                jam_in,
                jam_out,
                finger_id,
                tgl_kerja,
            ))

            return "UPDATED"

        return "SKIPPED"

    cursor.execute("""
        INSERT INTO ABSENSI
        (
            FingerID,
            TglKerja,
            TglJamIn,
            TglJamOut,
            TransaksiIn,
            TransaksiOut,
            UpdateInBy,
            UpdateOutBy,
            UpdateInDate,
            UpdateOutDate
        )
        VALUES
        (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            NOW(),
            NOW()
        )
    """, (
        finger_id,
        tgl_kerja,
        jam_in,
        jam_out,
        "LogFP" if jam_in else None,
        "LogFP" if jam_out else None,
        "HRIS_FINGER_COLLECTOR" if jam_in else None,
        "HRIS_FINGER_COLLECTOR" if jam_out else None,
    ))

    return "INSERTED"


def process_absensi():
    db = get_db_connection()

    try:
        with db.cursor() as cursor:
            rows = load_raw(cursor)

            grouped = defaultdict(list)

            for row in rows:
                finger_id = str(row["USER_ID"]).strip()

                if finger_id in IGNORE_FINGER_IDS:
                    continue

                if not is_valid_time(row["WAKTU"]):
                    continue

                grouped[finger_id].append(row)

            inserted = 0
            updated = 0
            skipped = 0
            unknown = 0
            ambiguous = 0
            pairs_count = 0
            in_only = 0
            out_only = 0

            print("=" * 110)
            print("HRIS ABSENSI PROCESSOR V4")
            print("RAW -> ABSENSI")
            print("=" * 110)
            print(f"RAW RECORDS : {len(rows)}")
            print(f"FINGER IDS  : {len(grouped)}")
            print()

            for finger_id, records in grouped.items():
                employee = find_employee(cursor, finger_id)

                if employee is None:
                    cursor.execute("""
                        SELECT COUNT(*) AS jumlah
                        FROM PEGAWAI
                        WHERE FingerID = %s
                    """, (finger_id,))

                    count = cursor.fetchone()["jumlah"]

                    if count == 0:
                        unknown += 1
                        print(
                            f"UNKNOWN   | FINGER={finger_id} | "
                            f"RAW={len(records)}"
                        )
                    else:
                        ambiguous += 1
                        print(
                            f"AMBIGUOUS | FINGER={finger_id} | "
                            f"RAW={len(records)}"
                        )

                    continue

                pairs = build_pairs(records)

                for pair in pairs:
                    if pair["type"] == "PAIR":
                        pairs_count += 1
                        event_in = pair["in"]
                        event_out = pair["out"]

                        tgl_kerja = event_in["WAKTU"].replace(
                            hour=0,
                            minute=0,
                            second=0,
                            microsecond=0,
                        )

                        result = upsert_absensi(
                            cursor,
                            finger_id,
                            tgl_kerja,
                            event_in["WAKTU"],
                            event_out["WAKTU"],
                        )

                    elif pair["type"] == "IN_ONLY":
                        in_only += 1
                        event_in = pair["in"]

                        tgl_kerja = event_in["WAKTU"].replace(
                            hour=0,
                            minute=0,
                            second=0,
                            microsecond=0,
                        )

                        result = upsert_absensi(
                            cursor,
                            finger_id,
                            tgl_kerja,
                            event_in["WAKTU"],
                            None,
                        )

                    else:
                        out_only += 1
                        event_out = pair["out"]

                        tgl_kerja = event_out["WAKTU"].replace(
                            hour=0,
                            minute=0,
                            second=0,
                            microsecond=0,
                        )

                        result = upsert_absensi(
                            cursor,
                            finger_id,
                            tgl_kerja,
                            None,
                            event_out["WAKTU"],
                        )

                    if result == "INSERTED":
                        inserted += 1
                    elif result == "UPDATED":
                        updated += 1
                    else:
                        skipped += 1

            db.commit()

            print()
            print("=" * 110)
            print("ABSENSI PROCESS RESULT")
            print("=" * 110)
            print(f"RAW RECORDS       : {len(rows)}")
            print(f"PAIR              : {pairs_count}")
            print(f"IN ONLY           : {in_only}")
            print(f"OUT ONLY          : {out_only}")
            print(f"INSERTED          : {inserted}")
            print(f"UPDATED           : {updated}")
            print(f"SKIPPED           : {skipped}")
            print(f"UNKNOWN FINGER    : {unknown}")
            print(f"AMBIGUOUS FINGER  : {ambiguous}")
            print("=" * 110)
            print("ABSENSI PROCESSOR : SUCCESS")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    process_absensi()
