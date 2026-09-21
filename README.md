# JS8Mail route hints

An optional, short-lived HTTPS service for exchanging small amounts of
band-scoped RF route evidence between JS8Mail installations.

This service is deliberately not a mailbox, telemetry archive, or delivery
authority. It stores only expiring claims such as `heard` and
`observed_traffic`. Clients must continue to work normally when the service is
offline, slow, or unavailable.

## Development

```sh
./start.sh
curl http://127.0.0.1:8787/healthz
```

The default listen port is `8787`; set `ROUTE_HINTS_PORT` to change it.

## Container

`start.sh` detects Podman first and Docker second:

```sh
ROUTE_HINTS_PORT=8787 ROUTE_HINTS_DATA=./data ./start.sh
```

The container listens on `0.0.0.0` inside the container and publishes the
configured port. Put a TLS reverse proxy in front of a public deployment, for
example at `https://js8mail.oh3spn.fi:8787` or at a normal HTTPS port.

## Protocol

The initial protocol identifier is `j8rh/1`.

`POST /v1/evidence/batch` accepts:

```json
{
  "protocol": "j8rh/1",
  "observer": "OH3SPN",
  "claims": [
    {
      "kind": "heard",
      "source": "F4LPU",
      "band": "20m",
      "dial_frequency": 14078000,
      "observed_at_ms": 1780000000000,
      "snr": -14
    },
    {
      "kind": "observed_traffic",
      "source": "F4LPU",
      "destination": "HB9TLY",
      "band": "20m",
      "observed_at_ms": 1780000000000
    }
  ]
}
```

`GET /v1/evidence?target=HB9TLY&band=20m` returns bounded, unexpired hints.
No message content, route history, or mailbox data is accepted.

The service expires `heard` claims after 60 minutes and traffic/path claims
after 6 hours. Expired rows are deleted periodically and opportunistically on
requests. SQLite indexes cover target, band, expiry, and observation time.

## ARM host deployment

On a host such as `arm.track3.org.uk`, clone this repository and run:

```sh
git clone git@github.com:snetting/JS8Mail-route-hints.git /home/steve/git/JS8Mail-route-hints
cd /home/steve/git/JS8Mail-route-hints
ROUTE_HINTS_PORT=8787 ROUTE_HINTS_DATA=/data/container-run/js8mail-route-hints ./start.sh
```

The script builds the image, detects Docker or Podman, publishes the selected
port on all host interfaces, and mounts the persistent data directory. It
replaces the named container with `--restart unless-stopped`, so a host or
container restart does not lose the evidence database. The account running
the script needs access to the container runtime; on Docker installations this
normally means membership of the `docker` group or running the deployment
script with the host's approved administrative procedure.

For a public deployment, put TLS in front of the service and point DNS such as
`js8mail.oh3spn.fi` at the host. The JS8Mail client should use the resulting
HTTPS URL. Port `8787` is only the reference direct-publication port; a reverse
proxy on 443 is preferable.
