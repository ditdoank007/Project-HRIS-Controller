from http.server import BaseHTTPRequestHandler, HTTPServer
import json

from collector import harvest_device


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
