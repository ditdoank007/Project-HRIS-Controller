from http.server import BaseHTTPRequestHandler, HTTPServer
import json

from collector import (
    harvest_device,
    read_device_fingerprint_data,
    read_device_users_with_templates,
    delete_device_user,
    set_device_user_enabled,
    sync_device_user,
)


HOST = "0.0.0.0"
PORT = 8090


class ManualPullHandler(BaseHTTPRequestHandler):

    def send_json(self, data, status=200):

        body = json.dumps(
            data,
            default=str
        ).encode()


        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(body)


    def do_POST(self):
        if self.path == "/attendance/sync-user":

            transfer_encoding = self.headers.get(
                "Transfer-Encoding",
                ""
            ).lower()

            if "chunked" in transfer_encoding:
                chunks = []

                while True:
                    line = self.rfile.readline()

                    if not line:
                        break

                    chunk_size = int(
                        line.strip().split(b";", 1)[0],
                        16
                    )

                    if chunk_size == 0:
                        self.rfile.readline()
                        break

                    chunk = self.rfile.read(chunk_size)
                    chunks.append(chunk)

                    self.rfile.read(2)

                raw_body = b"".join(chunks)

            else:
                length = int(
                    self.headers.get(
                        "Content-Length",
                        0
                    )
                )

                raw_body = self.rfile.read(length)

            if not raw_body:
                self.send_json(
                    {
                        "success": False,
                        "error": "EMPTY BODY RECEIVED"
                    },
                    400
                )
                return

            try:
                payload = json.loads(raw_body)

                ip = payload.get("ip")
                port = payload.get("port", 4370)
                user_id = payload.get("userId")
                name = payload.get("name", "")
                templates = payload.get("templates", [])
                enabled = payload.get("enabled", True)

                if not ip:
                    self.send_json(
                        {
                            "success": False,
                            "error": "IP required"
                        },
                        400
                    )
                    return

                if not user_id:
                    self.send_json(
                        {
                            "success": False,
                            "error": "userId/FingerID required"
                        },
                        400
                    )
                    return

                if not isinstance(templates, list):
                    self.send_json(
                        {
                            "success": False,
                            "error": "templates harus berupa array"
                        },
                        400
                    )
                    return

                result = sync_device_user(
                    ip=ip,
                    port=port,
                    user_id=user_id,
                    name=name,
                    templates=templates,
                    enabled=bool(enabled),
                )

                self.send_json(
                    result,
                    200 if result.get("success") else 500
                )

            except Exception as exc:
                self.send_json(
                    {
                        "success": False,
                        "error": repr(exc)
                    },
                    500
                )

            return


        if self.path == "/attendance/preview":

            transfer_encoding = self.headers.get(
                "Transfer-Encoding",
                ""
            ).lower()

            if "chunked" in transfer_encoding:
                chunks = []

                while True:
                    line = self.rfile.readline()

                    if not line:
                        break

                    chunk_size = int(
                        line.strip().split(b";", 1)[0],
                        16
                    )

                    if chunk_size == 0:
                        self.rfile.readline()
                        break

                    chunk = self.rfile.read(chunk_size)
                    chunks.append(chunk)

                    self.rfile.read(2)

                raw_body = b"".join(chunks)

            else:
                length = int(
                    self.headers.get(
                        "Content-Length",
                        0
                    )
                )

                raw_body = self.rfile.read(length)

            if not raw_body:
                self.send_json(
                    {
                        "success": False,
                        "error": "EMPTY BODY RECEIVED"
                    },
                    400
                )
                return

            try:
                payload = json.loads(raw_body)

                ip = payload.get("ip")
                port = payload.get(
                    "port",
                    4370
                )

                if not ip:
                    self.send_json(
                        {
                            "success": False,
                            "error": "IP required"
                        },
                        400
                    )
                    return

                result = read_device_fingerprint_data(
                    ip,
                    port
                )

                self.send_json(
                    result,
                    200 if result.get("success") else 500
                )

            except Exception as exc:
                self.send_json(
                    {
                        "success": False,
                        "error": str(exc)
                    },
                    500
                )

            return


        if self.path == "/attendance/snapshot":

            transfer_encoding = self.headers.get(
                "Transfer-Encoding",
                ""
            ).lower()

            if "chunked" in transfer_encoding:
                chunks = []

                while True:
                    line = self.rfile.readline()

                    if not line:
                        break

                    chunk_size = int(
                        line.strip().split(b";", 1)[0],
                        16
                    )

                    if chunk_size == 0:
                        self.rfile.readline()
                        break

                    chunk = self.rfile.read(chunk_size)
                    chunks.append(chunk)

                    self.rfile.read(2)

                raw_body = b"".join(chunks)

            else:
                length = int(
                    self.headers.get(
                        "Content-Length",
                        0
                    )
                )

                raw_body = self.rfile.read(length)

            if not raw_body:
                self.send_json(
                    {
                        "success": False,
                        "error": "EMPTY BODY RECEIVED"
                    },
                    400
                )
                return

            try:
                payload = json.loads(raw_body)

                ip = payload.get("ip")
                port = int(payload.get("port", 4370))

                if not ip:
                    self.send_json(
                        {
                            "success": False,
                            "error": "IP required"
                        },
                        400
                    )
                    return

                result = read_device_users_with_templates(
                    ip,
                    port
                )

                self.send_json(
                    result,
                    200 if result.get("success") else 500
                )

            except (TypeError, ValueError) as exc:
                self.send_json(
                    {
                        "success": False,
                        "error": f"INVALID REQUEST: {exc}"
                    },
                    400
                )

            except Exception as exc:
                self.send_json(
                    {
                        "success": False,
                        "error": str(exc)
                    },
                    500
                )

            return


        if self.path == "/attendance/delete-user":

            transfer_encoding = self.headers.get(
                "Transfer-Encoding",
                ""
            ).lower()

            if "chunked" in transfer_encoding:
                chunks = []

                while True:
                    line = self.rfile.readline()

                    if not line:
                        break

                    chunk_size = int(
                        line.strip().split(b";", 1)[0],
                        16
                    )

                    if chunk_size == 0:
                        self.rfile.readline()
                        break

                    chunk = self.rfile.read(chunk_size)
                    chunks.append(chunk)

                    self.rfile.read(2)

                raw_body = b"".join(chunks)

            else:
                length = int(
                    self.headers.get(
                        "Content-Length",
                        0
                    )
                )

                raw_body = self.rfile.read(length)

            if not raw_body:
                self.send_json(
                    {
                        "success": False,
                        "error": "EMPTY BODY RECEIVED"
                    },
                    400
                )
                return

            try:
                payload = json.loads(raw_body)

                ip = payload.get("ip")
                port = int(payload.get("port", 4370))
                uid = payload.get("uid")

                if not ip:
                    self.send_json(
                        {
                            "success": False,
                            "error": "IP required"
                        },
                        400
                    )
                    return

                if uid is None:
                    self.send_json(
                        {
                            "success": False,
                            "error": "UID required"
                        },
                        400
                    )
                    return

                uid = int(uid)

                if uid < 0:
                    self.send_json(
                        {
                            "success": False,
                            "error": "UID must be >= 0"
                        },
                        400
                    )
                    return

                result = delete_device_user(
                    ip,
                    port,
                    uid
                )

                self.send_json(
                    result,
                    200 if result.get("success") else 400
                )

            except (TypeError, ValueError) as exc:
                self.send_json(
                    {
                        "success": False,
                        "error": f"INVALID REQUEST: {exc}"
                    },
                    400
                )

            except Exception as exc:
                self.send_json(
                    {
                        "success": False,
                        "error": str(exc)
                    },
                    500
                )

            return


        if self.path == "/attendance/user-enabled":

            transfer_encoding = self.headers.get(
                "Transfer-Encoding",
                ""
            ).lower()

            if "chunked" in transfer_encoding:
                chunks = []

                while True:
                    line = self.rfile.readline()

                    if not line:
                        break

                    chunk_size = int(
                        line.strip().split(b";", 1)[0],
                        16
                    )

                    if chunk_size == 0:
                        self.rfile.readline()
                        break

                    chunk = self.rfile.read(chunk_size)
                    chunks.append(chunk)

                    self.rfile.read(2)

                raw_body = b"".join(chunks)

            else:
                length = int(
                    self.headers.get(
                        "Content-Length",
                        0
                    )
                )

                raw_body = self.rfile.read(length)

            if not raw_body:
                self.send_json(
                    {
                        "success": False,
                        "error": "EMPTY BODY RECEIVED"
                    },
                    400
                )
                return

            try:
                payload = json.loads(raw_body)

                ip = payload.get("ip")
                port = int(payload.get("port", 4370))
                uid = payload.get("uid")

                if not ip:
                    self.send_json(
                        {
                            "success": False,
                            "error": "IP required"
                        },
                        400
                    )
                    return

                if uid is None:
                    self.send_json(
                        {
                            "success": False,
                            "error": "UID required"
                        },
                        400
                    )
                    return

                if "enabled" not in payload:
                    self.send_json(
                        {
                            "success": False,
                            "error": "enabled required"
                        },
                        400
                    )
                    return

                uid = int(uid)

                if uid < 0:
                    self.send_json(
                        {
                            "success": False,
                            "error": "UID must be >= 0"
                        },
                        400
                    )
                    return

                enabled = payload.get("enabled")

                if not isinstance(enabled, bool):
                    self.send_json(
                        {
                            "success": False,
                            "error": "enabled must be boolean"
                        },
                        400
                    )
                    return

                result = set_device_user_enabled(
                    ip,
                    port,
                    uid,
                    enabled
                )

                self.send_json(
                    result,
                    200 if result.get("success") else 400
                )

            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self.send_json(
                    {
                        "success": False,
                        "error": f"INVALID REQUEST: {exc}"
                    },
                    400
                )

            except Exception as exc:
                self.send_json(
                    {
                        "success": False,
                        "error": str(exc)
                    },
                    500
                )

            return


        if self.path != "/manual-pull":

            self.send_json(
                {
                    "success": False,
                    "error": "Endpoint not found"
                },
                404
            )

            return


        length = int(
            self.headers.get(
                "Content-Length",
                0
            )
        )

        raw_body = self.rfile.read(length)

        print(
            "MANUAL PULL DEBUG",
            "CONTENT_LENGTH=",
            length,
            "BODY=",
            raw_body
        )

        if not raw_body:
            self.send_json(
                {
                    "success": False,
                    "error": "EMPTY BODY RECEIVED"
                },
                400
            )
            return

        payload = json.loads(raw_body)


        ip = payload.get("ip")

        port = payload.get(
            "port",
            4370
        )


        if not ip:

            self.send_json(
                {
                    "success": False,
                    "error": "IP required"
                },
                400
            )

            return


        try:
            result = harvest_device(
                ip,
                port
            )

            self.send_json(
                result
            )

        except Exception as exc:

            self.send_json(
                {
                    "success": False,
                    "error": str(exc)
                },
                500
            )


if __name__ == "__main__":

    server = HTTPServer(
        (
            HOST,
            PORT
        ),
        ManualPullHandler
    )

    print(
        f"Manual Pull API running {HOST}:{PORT}"
    )

    server.serve_forever()
