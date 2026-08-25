import pymysql
from datetime import datetime, timedelta


DB_HOST = "192.168.100.128"
DB_USER = "hris_app"
DB_PASSWORD = "HRIS_DB_TEMP_2026"
DB_NAME = "HRIS"


# ID yang digunakan sebagai administrator/operator mesin.
# Tidak diproses sebagai absensi.
IGNORE_FINGER_IDS = {
    "1",
    "2",
    "4",
    "5",
}


# Tanggal minimum yang masih dianggap masuk akal
# untuk data historis HRIS.
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


def is_valid_device_time(waktu):
    if waktu is None:
        return False

    # Data masa depan yang terlalu jauh biasanya berasal
    # dari CMOS mesin finger yang kehilangan tanggal/waktu.
    max_valid = datetime.now() + timedelta(days=1)

    return (
        waktu >= MIN_VALID_DATETIME
        and waktu <= max_valid
    )


def normalize_to_time_recorder():
    db = get_db_connection()

    try:
        with db.cursor() as cursor:

            cursor.execute("""
                SELECT
                    ID,
                    DEVICE_IP,
                    DEVICE_SERIAL,
                    DEVICE_NAME,
                    USER_ID,
                    WAKTU,
                    STATUS,
                    PUNCH
                FROM FINGER_HARVEST_RAW
                ORDER BY ID
            """)

            rows = cursor.fetchall()

            inserted = 0
            skipped = 0
            ignored = 0
            invalid = 0
            errors = 0

            print("=" * 100)
            print("HRIS FINGER NORMALIZER V6")
            print("RAW -> TIME_RECORDER")
            print("=" * 100)
            print(f"RAW RECORDS : {len(rows)}")
            print()

            for row in rows:

                finger_id = str(
                    row["USER_ID"]
                ).strip()

                waktu = row["WAKTU"]
                status = str(
                    row["STATUS"] or ""
                ).strip()

                mesin = str(
                    row["DEVICE_IP"] or ""
                ).strip()

                punch = row["PUNCH"]

                # --------------------------------------------------
                # Ignore administrator/operator machine
                # --------------------------------------------------

                if finger_id in IGNORE_FINGER_IDS:
                    ignored += 1
                    continue

                # --------------------------------------------------
                # Validate device timestamp
                # --------------------------------------------------

                if not is_valid_device_time(waktu):
                    invalid += 1

                    print(
                        f"INVALID TIME | "
                        f"FINGER={finger_id} | "
                        f"WAKTU={waktu} | "
                        f"STATUS={status} | "
                        f"DEVICE={mesin}"
                    )

                    continue

                # --------------------------------------------------
                # Check exact attendance transaction
                #
                # TIME_RECORDER primary key:
                # FingerID + Waktu + Status + Mesin
                # --------------------------------------------------

                cursor.execute("""
                    SELECT 1
                    FROM TIME_RECORDER
                    WHERE FingerID = %s
                      AND Waktu = %s
                      AND Status = %s
                      AND Mesin = %s
                    LIMIT 1
                """, (
                    finger_id,
                    waktu,
                    status,
                    mesin,
                ))

                existing = cursor.fetchone()

                if existing:
                    skipped += 1
                    continue

                # --------------------------------------------------
                # INSERT ONLY
                #
                # Tidak pernah UPDATE record absensi lama.
                # --------------------------------------------------

                try:
                    cursor.execute("""
                        INSERT INTO TIME_RECORDER
                        (
                            FingerID,
                            Waktu,
                            Status,
                            Mesin,
                            Ket,
                            Transaksi,
                            KetInject,
                            ReffInject,
                            trx,
                            UpdateBy,
                            UpdateDate
                        )
                        VALUES
                        (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            NULL,
                            NULL,
                            NULL,
                            %s,
                            NOW()
                        )
                    """, (
                        finger_id,
                        waktu,
                        status,
                        mesin,
                        f"PUNCH={punch}",
                        "LogFP",
                        "HRIS_FINGER_COLLECTOR",
                    ))

                    inserted += 1

                except pymysql.err.IntegrityError:
                    # Race condition / duplicate PK.
                    # Tidak dianggap sebagai kegagalan batch.
                    skipped += 1

                except Exception as exc:
                    errors += 1

                    print(
                        f"INSERT ERROR | "
                        f"FINGER={finger_id} | "
                        f"WAKTU={waktu} | "
                        f"STATUS={status} | "
                        f"DEVICE={mesin} | "
                        f"ERROR={repr(exc)}"
                    )

            db.commit()

            print()
            print("=" * 100)
            print("NORMALIZER RESULT")
            print("=" * 100)
            print(f"RAW RECORDS : {len(rows)}")
            print(f"INSERT      : {inserted}")
            print(f"SKIPPED     : {skipped}")
            print(f"IGNORED     : {ignored}")
            print(f"INVALID TIME: {invalid}")
            print(f"ERROR       : {errors}")
            print("=" * 100)

            if errors > 0:
                print("WARNING: terdapat record yang gagal INSERT.")
            else:
                print("NORMALIZER : SUCCESS")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    normalize_to_time_recorder()
