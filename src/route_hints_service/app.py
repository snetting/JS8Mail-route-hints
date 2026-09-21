"""Small dependency-free HTTP service for expiring JS8Mail route evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

PROTOCOL = "j8rh/1"
MAX_CLAIMS = 100
MAX_RESPONSE = 200
CALLSIGN = re.compile(r"^[A-Z0-9/@]{1,16}$", re.IGNORECASE)
KINDS = {"heard": 60 * 60_000, "observed_traffic": 6 * 60 * 60_000, "observed_path": 6 * 60 * 60_000}


def now_ms() -> int:
    return int(time.time() * 1000)


def clean_call(value: Any, *, allow_group: bool = False) -> str:
    text = str(value or "").strip().upper()
    if allow_group and text.startswith("@"):
        return text if CALLSIGN.fullmatch(text) else ""
    return text if CALLSIGN.fullmatch(text) and not text.startswith("@") else ""


class Store:
    def __init__(self, filename: str) -> None:
        self.connection = sqlite3.connect(filename, check_same_thread=False)
        self.lock = threading.Lock()
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS evidence (
                id INTEGER PRIMARY KEY,
                claim_hash TEXT NOT NULL UNIQUE,
                observer TEXT NOT NULL,
                kind TEXT NOT NULL,
                source TEXT NOT NULL,
                destination TEXT NOT NULL DEFAULT '',
                via TEXT NOT NULL DEFAULT '',
                band TEXT NOT NULL,
                dial_frequency INTEGER,
                snr REAL,
                observed_at_ms INTEGER NOT NULL,
                expires_at_ms INTEGER NOT NULL,
                created_at_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS evidence_target_idx
                ON evidence(destination, band, expires_at_ms, observed_at_ms);
            CREATE INDEX IF NOT EXISTS evidence_source_idx
                ON evidence(source, band, expires_at_ms, observed_at_ms);
            CREATE INDEX IF NOT EXISTS evidence_expiry_idx
                ON evidence(expires_at_ms);
            """
        )
        self.connection.commit()

    def prune(self, current_ms: int | None = None) -> None:
        with self.lock:
            self.connection.execute("DELETE FROM evidence WHERE expires_at_ms <= ?", (current_ms or now_ms(),))
            self.connection.commit()

    def put_batch(self, observer: str, claims: list[dict[str, Any]]) -> int:
        accepted = 0
        current = now_ms()
        with self.lock:
            for claim in claims[:MAX_CLAIMS]:
                kind = str(claim.get("kind", "")).strip().lower()
                ttl = KINDS.get(kind)
                source = clean_call(claim.get("source"))
                destination = clean_call(claim.get("destination"))
                via = clean_call(claim.get("via"))
                band = str(claim.get("band", "")).strip().lower()[:32]
                if not ttl or not source or not band or source == observer:
                    continue
                if kind == "heard":
                    destination = ""
                elif not destination or destination.startswith("@"):
                    continue
                try:
                    observed = int(claim.get("observed_at_ms", current))
                except (TypeError, ValueError):
                    continue
                if observed < current - 24 * 60 * 60_000 or observed > current + 5 * 60_000:
                    continue
                expiry = min(current + ttl, observed + ttl)
                try:
                    dial = int(claim["dial_frequency"]) if claim.get("dial_frequency") else None
                except (TypeError, ValueError):
                    dial = None
                try:
                    snr = float(claim["snr"]) if claim.get("snr") is not None else None
                except (TypeError, ValueError):
                    snr = None
                canonical = json.dumps(
                    [observer, kind, source, destination, via, band, dial, observed],
                    separators=(",", ":"),
                )
                digest = hashlib.sha256(canonical.encode()).hexdigest()
                cursor = self.connection.execute(
                    """INSERT OR IGNORE INTO evidence
                    (claim_hash, observer, kind, source, destination, via, band,
                     dial_frequency, snr, observed_at_ms, expires_at_ms, created_at_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (digest, observer, kind, source, destination, via, band, dial, snr, observed, expiry, current),
                )
                accepted += int(cursor.rowcount or 0)
            self.connection.commit()
        return accepted

    def query(self, target: str, band: str, limit: int) -> list[dict[str, Any]]:
        current = now_ms()
        self.prune(current)
        with self.lock:
            rows = self.connection.execute(
                """SELECT observer, kind, source, destination, via, band,
                   dial_frequency, snr, observed_at_ms, expires_at_ms
                   FROM evidence
                   WHERE band = ? AND expires_at_ms > ?
                     AND (? = '' OR source = ? OR destination = ?)
                   ORDER BY observed_at_ms DESC LIMIT ?""",
                (band, current, target, target, target, max(1, min(limit, MAX_RESPONSE))),
            ).fetchall()
        return [dict(row) for row in rows]

    def graph(self, band: str, limit: int) -> dict[str, Any]:
        claims = self.query("", band, limit)
        nodes: set[str] = set()
        edges: dict[tuple[str, str], dict[str, Any]] = {}
        for claim in claims:
            source = str(claim["source"])
            destination = str(claim["destination"])
            if not destination:
                continue
            nodes.update((source, destination))
            key = (source, destination)
            edge = edges.setdefault(key, {"from": source, "to": destination, "kinds": [], "latest": 0})
            if claim["kind"] not in edge["kinds"]:
                edge["kinds"].append(claim["kind"])
            edge["latest"] = max(edge["latest"], int(claim["observed_at_ms"]))
        return {"protocol": PROTOCOL, "band": band, "nodes": sorted(nodes), "edges": list(edges.values())}


class Handler(BaseHTTPRequestHandler):
    store: Store

    def log_message(self, *_args: object) -> None:
        return

    def send_json(self, status: int, value: dict[str, Any]) -> None:
        data = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/healthz":
            self.send_json(200, {"ok": True, "protocol": PROTOCOL})
            return
        if parsed.path == "/v1/evidence":
            target = clean_call(query.get("target", [""])[0])
            band = str(query.get("band", [""])[0]).strip().lower()
            if not band:
                self.send_json(400, {"error": "band is required"})
                return
            try:
                limit = int(query.get("limit", [MAX_RESPONSE])[0])
            except ValueError:
                limit = MAX_RESPONSE
            self.send_json(200, {"protocol": PROTOCOL, "generated_at_ms": now_ms(), "evidence": self.store.query(target, band, limit)})
            return
        if parsed.path == "/v1/graph":
            band = str(query.get("band", [""])[0]).strip().lower()
            if not band:
                self.send_json(400, {"error": "band is required"})
                return
            self.send_json(200, self.store.graph(band, int(query.get("limit", [MAX_RESPONSE])[0])))
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/v1/evidence/batch":
            self.send_json(404, {"error": "not found"})
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 256_000)
            body = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "invalid JSON"})
            return
        if body.get("protocol") != PROTOCOL:
            self.send_json(400, {"error": "unsupported protocol"})
            return
        observer = clean_call(body.get("observer"))
        claims = body.get("claims")
        if not observer or not isinstance(claims, list):
            self.send_json(400, {"error": "observer and claims are required"})
            return
        accepted = self.store.put_batch(observer, claims)
        self.send_json(202, {"protocol": PROTOCOL, "accepted": accepted, "received_at_ms": now_ms()})


class RouteHintsServer(ThreadingHTTPServer):
    """Small concurrent front end; SQLite serializes writes safely."""

    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64


def main() -> None:
    host = os.environ.get("ROUTE_HINTS_HOST", "127.0.0.1")
    port = int(os.environ.get("ROUTE_HINTS_PORT", "8787"))
    filename = os.environ.get("ROUTE_HINTS_DATABASE", "route-hints.sqlite3")
    Path(filename).expanduser().parent.mkdir(parents=True, exist_ok=True)
    store = Store(filename)
    Handler.store = store
    def prune_loop() -> None:
        while True:
            time.sleep(5 * 60)
            store.prune()

    threading.Thread(target=prune_loop, name="route-hints-pruner", daemon=True).start()
    server = RouteHintsServer((host, port), Handler)
    print(f"JS8Mail route hints: http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
