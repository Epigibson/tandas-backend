"""Imita los endpoints de Supabase Storage que usa el backend (subir y firmar en lote)."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

KEY = "sb_secret_prueba"
stored = {}
broadcasts = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/_broadcasts":
            return self._reply(200, broadcasts)
        self._reply(404, {})

    def do_POST(self):
        if self.headers.get("apikey") != KEY or self.headers.get("Authorization") != f"Bearer {KEY}":
            return self._reply(401, {"error": "bad key"})
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        prefix_sign = "/storage/v1/object/sign/comprobantes"
        prefix_obj = "/storage/v1/object/comprobantes/"
        if self.path == "/realtime/v1/api/broadcast":
            broadcasts.extend(json.loads(body)["messages"])
            return self._reply(202, {})
        if self.path == prefix_sign:
            paths = json.loads(body)["paths"]
            return self._reply(200, [
                {"path": p, "signedURL": f"/object/sign/comprobantes/{p}?token=tok", "error": None}
                if p in stored else {"path": p, "signedURL": None, "error": "not found"}
                for p in paths
            ])
        if self.path.startswith(prefix_obj):
            name = self.path[len(prefix_obj):]
            if name in stored:
                return self._reply(409, {"error": "Duplicate"})
            stored[name] = self.headers.get("Content-Type")
            return self._reply(200, {"Key": f"comprobantes/{name}"})
        self._reply(404, {"error": "unknown path"})


HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
