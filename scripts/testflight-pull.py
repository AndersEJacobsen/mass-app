#!/usr/bin/env python3
"""
testflight-pull — Pull TestFlight crash reports and tester feedback for this
app into ./testflight-reports/ so they can be read locally.

Usage:
    scripts/testflight-pull                    # pull everything new
    scripts/testflight-pull --limit 20         # cap per endpoint
    scripts/testflight-pull --bundle-id X      # override bundle id
    scripts/testflight-pull --skip-crashes     # feedback only
    scripts/testflight-pull --skip-feedback    # crashes only

Credentials (all three required; env wins over Keychain):

    APP_STORE_CONNECT_API_KEY_ID        10-char key ID (e.g. ABCD1234EF)
    APP_STORE_CONNECT_API_ISSUER_ID     issuer UUID
    APP_STORE_CONNECT_API_KEY_P8        PEM contents of the .p8 (multi-line ok)
        — or —
    APP_STORE_CONNECT_API_KEY_PATH      path to the .p8 file

Intentionally mirrors the env var names used in .github/workflows/ios-release.yml
so the same shape works locally and in CI.

First-time macOS Keychain setup (optional — anything in env wins over this):

    security add-generic-password -s music-assistant-asc -a key-id     -w ABCD1234EF
    security add-generic-password -s music-assistant-asc -a issuer-id  -w <uuid>
    # either the file path…
    security add-generic-password -s music-assistant-asc -a key-path   -w ~/Keys/AuthKey_ABCD1234EF.p8
    # …or the contents directly (handy if you don't want a .p8 on disk):
    security add-generic-password -s music-assistant-asc -a key-p8     -w "$(cat ~/Keys/AuthKey_ABCD1234EF.p8)"

Using 1Password CLI instead? Just export env vars from it before running:

    export APP_STORE_CONNECT_API_KEY_ID=$(op read "op://Private/ASC API/key-id")
    export APP_STORE_CONNECT_API_ISSUER_ID=$(op read "op://Private/ASC API/issuer-id")
    export APP_STORE_CONNECT_API_KEY_P8=$(op read "op://Private/ASC API/private-key")
    scripts/testflight-pull

Output lands in ./testflight-reports/ (gitignored). Re-running overwrites the
index.md summary but preserves already-downloaded files (idempotent by id).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator

# --------------------------------------------------------------------------- #
# Constants

DEFAULT_BUNDLE_ID = "io.music-assistant.client"
KEYCHAIN_SERVICE = "music-assistant-asc"
API_BASE = "https://api.appstoreconnect.apple.com"
JWT_LIFETIME_SEC = 20 * 60  # Apple caps at 20 min
USER_AGENT = "music-assistant-testflight-pull/1"
HTTP_TIMEOUT = 30

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTPUT_ROOT = REPO_ROOT / "testflight-reports"


# --------------------------------------------------------------------------- #
# Credential loading

@dataclass
class Credentials:
    key_id: str
    issuer_id: str
    key_pem: bytes  # PEM-encoded .p8 contents
    source: str     # human-readable origin ("env", "keychain", "mixed")


def _keychain_get(account: str) -> str | None:
    """Read a generic password from the login keychain, or None if absent."""
    try:
        out = subprocess.run(
            ["security", "find-generic-password",
             "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return None  # `security` CLI somehow missing — not on mac?
    if out.returncode != 0:
        return None
    return out.stdout.rstrip("\n") or None


def _resolve_p8(value: str, source_label: str) -> tuple[bytes, str]:
    """
    Interpret a value meant for APP_STORE_CONNECT_API_KEY_P8 (or keychain
    key-p8) into PEM bytes. Tolerates the common mistake of pointing it at a
    file path instead of the contents.
    """
    stripped = value.strip()
    # Single-line value that points at a real file → read the file.
    if "\n" not in stripped:
        candidate = pathlib.Path(os.path.expanduser(stripped))
        if candidate.is_file():
            return candidate.read_bytes(), f"{source_label}→file({candidate.name})"
    # Otherwise treat as PEM (or headerless base64 — handled downstream).
    return value.encode("utf-8"), source_label


def load_credentials() -> Credentials:
    sources: list[str] = []

    key_id = os.environ.get("APP_STORE_CONNECT_API_KEY_ID")
    if key_id:
        sources.append("env:key_id")
    else:
        key_id = _keychain_get("key-id")
        if key_id:
            sources.append("keychain:key-id")

    issuer_id = os.environ.get("APP_STORE_CONNECT_API_ISSUER_ID")
    if issuer_id:
        sources.append("env:issuer_id")
    else:
        issuer_id = _keychain_get("issuer-id")
        if issuer_id:
            sources.append("keychain:issuer-id")

    # For the key itself: prefer raw PEM (env P8 > keychain key-p8), otherwise
    # fall back to a file path (env PATH > keychain key-path). As a kindness,
    # if someone sets KEY_P8 to a file path by mistake, treat it as if they'd
    # set KEY_PATH.
    key_pem: bytes | None = None
    pem_str = os.environ.get("APP_STORE_CONNECT_API_KEY_P8")
    p8_source = "env:key_p8"
    if not pem_str:
        pem_str = _keychain_get("key-p8")
        p8_source = "keychain:key-p8" if pem_str else p8_source
    if pem_str:
        key_pem, p8_source = _resolve_p8(pem_str, p8_source)
        sources.append(p8_source)

    if key_pem is None:
        key_path_str = os.environ.get("APP_STORE_CONNECT_API_KEY_PATH") \
            or _keychain_get("key-path")
        if key_path_str:
            key_path = pathlib.Path(os.path.expanduser(key_path_str))
            if not key_path.is_file():
                die(f"Key path does not exist or is not a file: {key_path}")
            key_pem = key_path.read_bytes()
            sources.append(f"file:{key_path.name}")

    missing = [label for value, label in (
        (key_id, "key-id"),
        (issuer_id, "issuer-id"),
        (key_pem, "private-key (P8 or PATH)"),
    ) if not value]
    if missing:
        die(
            "Missing ASC API credentials: " + ", ".join(missing) + "\n\n"
            "Set env vars:\n"
            "  APP_STORE_CONNECT_API_KEY_ID\n"
            "  APP_STORE_CONNECT_API_ISSUER_ID\n"
            "  APP_STORE_CONNECT_API_KEY_P8   (PEM contents)\n"
            "    — or —\n"
            "  APP_STORE_CONNECT_API_KEY_PATH (path to .p8)\n\n"
            "…or store them in macOS Keychain (see header of this script)."
        )

    # Normalize PEM: accept a "raw" p8 (no header) by wrapping it.
    assert key_pem is not None
    if b"BEGIN PRIVATE KEY" not in key_pem:
        body = key_pem.strip().decode("ascii", errors="replace")
        key_pem = (
            "-----BEGIN PRIVATE KEY-----\n"
            + body + "\n"
            + "-----END PRIVATE KEY-----\n"
        ).encode("ascii")

    return Credentials(
        key_id=key_id,           # type: ignore[arg-type]
        issuer_id=issuer_id,     # type: ignore[arg-type]
        key_pem=key_pem,
        source=", ".join(sources),
    )


# --------------------------------------------------------------------------- #
# JWT minting via openssl (ES256 — no pip deps)

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _der_ecdsa_to_raw(der: bytes) -> bytes:
    """
    Convert an ASN.1 DER-encoded ECDSA signature (what openssl emits) into the
    raw 64-byte r||s form that the JOSE spec requires.

    ES256 signatures are always small enough that length bytes fit in a single
    octet, so we can parse without a full DER library.
    """
    if len(der) < 8 or der[0] != 0x30:
        raise ValueError("not a DER SEQUENCE")
    # der[1] is total length; we don't bother validating it, we just trust
    # openssl and walk the two INTEGERs.
    i = 2
    if der[i] != 0x02:
        raise ValueError("expected INTEGER for r")
    r_len = der[i + 1]
    r = der[i + 2 : i + 2 + r_len]
    i = i + 2 + r_len
    if i >= len(der) or der[i] != 0x02:
        raise ValueError("expected INTEGER for s")
    s_len = der[i + 1]
    s = der[i + 2 : i + 2 + s_len]

    # Strip ASN.1 leading-zero padding used to keep the integer positive.
    r = r.lstrip(b"\x00") or b"\x00"
    s = s.lstrip(b"\x00") or b"\x00"

    if len(r) > 32 or len(s) > 32:
        raise ValueError("r or s larger than 32 bytes — not ES256?")

    return r.rjust(32, b"\x00") + s.rjust(32, b"\x00")


def mint_jwt(creds: Credentials) -> str:
    now = int(time.time())
    header = {"alg": "ES256", "kid": creds.key_id, "typ": "JWT"}
    claims = {
        "iss": creds.issuer_id,
        "iat": now,
        "exp": now + JWT_LIFETIME_SEC,
        "aud": "appstoreconnect-v1",
    }
    signing_input = f"{_b64url(_compact_json(header))}.{_b64url(_compact_json(claims))}".encode("ascii")

    # openssl's `-sign` wants a file path, not a stream. Write the key to a
    # 0600-permissioned tempfile that auto-deletes when this block exits.
    import tempfile
    with tempfile.NamedTemporaryFile(
        "wb", suffix=".p8", delete=True, dir=os.environ.get("TMPDIR") or "/tmp",
    ) as key_file:
        key_file.write(creds.key_pem)
        key_file.flush()
        os.chmod(key_file.name, 0o600)
        sign = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_file.name, "-binary"],
            input=signing_input,
            capture_output=True,
            check=False,
        )
    if sign.returncode != 0:
        hint = ""
        head = creds.key_pem[:64].decode("ascii", errors="replace")
        if b"BEGIN PRIVATE KEY" not in creds.key_pem:
            hint = (
                "\n  hint: key contents don't look like PEM. If you meant to "
                "point at a file, use APP_STORE_CONNECT_API_KEY_PATH instead "
                "of APP_STORE_CONNECT_API_KEY_P8.\n"
                f"  key starts with: {head!r}"
            )
        die(
            "openssl failed to sign JWT (is the .p8 key valid?)\n"
            f"  stderr: {sign.stderr.decode('utf-8', errors='replace').strip()}"
            + hint
        )

    raw_sig = _der_ecdsa_to_raw(sign.stdout)
    return signing_input.decode("ascii") + "." + _b64url(raw_sig)


def _compact_json(obj: Any) -> bytes:
    return json.dumps(obj, separators=(",", ":"), sort_keys=False).encode("utf-8")


# --------------------------------------------------------------------------- #
# ASC API client

class AscClient:
    def __init__(self, token: str) -> None:
        self._token = token

    def _request(self, url: str, *, auth: bool = True) -> tuple[bytes, dict[str, str]]:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        if auth:
            req.add_header("Authorization", f"Bearer {self._token}")
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                return resp.read(), dict(resp.headers.items())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"HTTP {e.code} {e.reason} for {url}\n{body}"
            ) from None

    def get_json(self, path_or_url: str) -> dict[str, Any]:
        url = path_or_url if path_or_url.startswith("http") else f"{API_BASE}{path_or_url}"
        body, _headers = self._request(url, auth=True)
        return json.loads(body)

    def iter_pages(self, path: str) -> Iterator[dict[str, Any]]:
        """
        Yield each full response page (data + included + links) from a
        paginated collection endpoint. Callers typically want the whole page
        so they can cross-reference `included[]` resources against the
        relationships on each `data[]` item.
        """
        url: str | None = path if path.startswith("http") else f"{API_BASE}{path}"
        while url:
            payload = self.get_json(url)
            yield payload
            url = payload.get("links", {}).get("next")

    def download(self, url: str, dest: pathlib.Path) -> None:
        """Download a (usually pre-signed) URL to dest. Skips if present."""
        if dest.exists() and dest.stat().st_size > 0:
            return
        body, _ = self._request(url, auth=False)  # pre-signed URLs are self-authed
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)


# --------------------------------------------------------------------------- #
# Pull logic

def find_app_id(client: AscClient, bundle_id: str) -> str:
    q = urllib.parse.urlencode({"filter[bundleId]": bundle_id})
    payload = client.get_json(f"/v1/apps?{q}")
    data = payload.get("data") or []
    if not data:
        die(f"No app found for bundle id '{bundle_id}'. "
            f"Does the API key have access to this app?")
    return data[0]["id"]


def _iso_to_filename(iso: str) -> str:
    # "2026-04-20T10:30:00.000+0000" -> "2026-04-20T10-30-00Z"
    iso = iso.replace(":", "-")
    if "." in iso:
        iso = iso.split(".", 1)[0] + "Z"
    return iso


def _build_index(page: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map of builds-resource id -> attributes, harvested from `included[]`."""
    return {
        inc["id"]: inc.get("attributes", {}) or {}
        for inc in page.get("included") or []
        if inc.get("type") == "builds"
    }


def _rel_id(item: dict[str, Any], rel_name: str) -> str | None:
    rel = (item.get("relationships") or {}).get(rel_name) or {}
    data = rel.get("data")
    if isinstance(data, dict):
        return data.get("id")
    return None


def pull_crashes(client: AscClient, app_id: str, limit: int | None) -> list[dict[str, Any]]:
    """
    Pull crash submissions. `include=build` gives us the build version inline;
    the actual crash log text is fetched per-item from the `crashLog` sub-
    endpoint, whose `betaCrashLogs.attributes.logText` carries the whole
    symbolicated report — no binary download required.
    """
    out_dir = OUTPUT_ROOT / "crashes"
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, Any]] = []
    q = urllib.parse.urlencode({"include": "build", "limit": min(limit or 200, 200)})
    count = 0
    for page in client.iter_pages(f"/v1/apps/{app_id}/betaFeedbackCrashSubmissions?{q}"):
        builds = _build_index(page)
        for item in page.get("data") or []:
            if limit and count >= limit:
                break
            count += 1
            summary = _write_crash(client, item, builds, out_dir)
            summaries.append(summary)
        if limit and count >= limit:
            break
    print(f"  crashes: {count}")
    return summaries


def _write_crash(
    client: AscClient,
    item: dict[str, Any],
    builds: dict[str, dict[str, Any]],
    out_dir: pathlib.Path,
) -> dict[str, Any]:
    crash_id = item["id"]
    attrs = item.get("attributes", {}) or {}
    created = attrs.get("createdDate") or ""
    stem = f"{_iso_to_filename(created)}_{crash_id}" if created else crash_id
    build_attrs = builds.get(_rel_id(item, "build") or "", {})

    # Persist the raw item + build attrs for posterity / future diffing.
    meta_path = out_dir / f"{stem}.json"
    meta_path.write_text(json.dumps(
        {"item": item, "build": build_attrs}, indent=2, sort_keys=True
    ))

    # Fetch the crash log text inline. Apple returns it as a single string on
    # the betaCrashLogs resource — no separate pre-signed download.
    log_path: pathlib.Path | None = None
    log_text_preview: str | None = None
    rel_link = ((item.get("relationships") or {}).get("crashLog") or {}) \
               .get("links", {}).get("related")
    if rel_link:
        try:
            log = client.get_json(rel_link)
            log_text = ((log.get("data") or {}).get("attributes") or {}).get("logText")
            if log_text:
                log_path = out_dir / f"{stem}.crash"
                log_path.write_text(log_text)
                # Grab the first non-empty exception line for the index summary.
                log_text_preview = _summarize_crash_log(log_text)
        except RuntimeError as e:
            print(f"  WARN: crashLog fetch failed for {crash_id}: {e}", file=sys.stderr)

    return {
        "id": crash_id,
        "created": created,
        "comment": attrs.get("comment"),
        "email": attrs.get("email"),
        "device": attrs.get("deviceModel"),
        "os": attrs.get("osVersion"),
        "build": build_attrs.get("version"),
        "meta_path": str(meta_path.relative_to(REPO_ROOT)),
        "log_path": str(log_path.relative_to(REPO_ROOT)) if log_path else None,
        "preview": log_text_preview,
    }


def _summarize_crash_log(log: str) -> str:
    """Pull the most telling line out of a .crash file for index display."""
    exc_type = exc_reason = first_frame = None
    for line in log.splitlines():
        if line.startswith("Exception Type:") and not exc_type:
            exc_type = line.split(":", 1)[1].strip()
        elif line.startswith("Termination Reason:") and not exc_reason:
            exc_reason = line.split(":", 1)[1].strip()
        # First symbolicated frame after the backtrace header.
        elif first_frame is None and line.lstrip().startswith("0 "):
            first_frame = line.strip()
        if exc_type and exc_reason and first_frame:
            break
    parts = [p for p in (exc_type, exc_reason, first_frame) if p]
    return " | ".join(parts)[:400] if parts else ""


def pull_feedback(client: AscClient, app_id: str, limit: int | None) -> list[dict[str, Any]]:
    out_dir = OUTPUT_ROOT / "feedback"
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, Any]] = []
    q = urllib.parse.urlencode({"include": "build", "limit": min(limit or 200, 200)})
    count = 0
    for page in client.iter_pages(f"/v1/apps/{app_id}/betaFeedbackScreenshotSubmissions?{q}"):
        builds = _build_index(page)
        for item in page.get("data") or []:
            if limit and count >= limit:
                break
            count += 1
            summaries.append(_write_feedback(client, item, builds, out_dir))
        if limit and count >= limit:
            break
    print(f"  feedback: {count}")
    return summaries


def _write_feedback(
    client: AscClient,
    item: dict[str, Any],
    builds: dict[str, dict[str, Any]],
    out_dir: pathlib.Path,
) -> dict[str, Any]:
    fb_id = item["id"]
    attrs = item.get("attributes", {}) or {}
    created = attrs.get("createdDate") or ""
    stem = f"{_iso_to_filename(created)}_{fb_id}" if created else fb_id
    build_attrs = builds.get(_rel_id(item, "build") or "", {})

    # attributes.screenshots is a flat list of {url, width, height,
    # expirationDate}. URLs are short-lived pre-signed (~days), so we download
    # greedily.
    screenshot_paths: list[str] = []
    for idx, shot in enumerate(attrs.get("screenshots") or [], start=1):
        url = shot.get("url")
        if not url:
            continue
        ext = pathlib.Path(urllib.parse.urlparse(url).path).suffix or ".jpg"
        dest = out_dir / f"{stem}-{idx}{ext}"
        try:
            client.download(url, dest)
            screenshot_paths.append(str(dest.relative_to(REPO_ROOT)))
        except RuntimeError as e:
            print(f"  WARN: screenshot download failed for {fb_id}: {e}", file=sys.stderr)

    meta_path = out_dir / f"{stem}.md"
    _write_feedback_markdown(meta_path, attrs, build_attrs, screenshot_paths, fb_id)

    return {
        "id": fb_id,
        "created": created,
        "comment": attrs.get("comment"),
        "email": attrs.get("email"),
        "device": attrs.get("deviceModel"),
        "os": attrs.get("osVersion"),
        "locale": attrs.get("locale"),
        "build": build_attrs.get("version"),
        "meta_path": str(meta_path.relative_to(REPO_ROOT)),
        "screenshots": screenshot_paths,
    }


def _write_feedback_markdown(
    path: pathlib.Path,
    attrs: dict[str, Any],
    build_attrs: dict[str, Any],
    screenshots: list[str],
    fb_id: str,
) -> None:
    lines = [f"# Feedback {fb_id}", ""]
    if build_attrs.get("version"):
        lines.append(f"- **buildVersion**: {build_attrs['version']}")
    for key in ("createdDate", "email", "deviceModel", "osVersion",
                "locale", "timeZone", "architecture", "connectionType",
                "batteryPercentage", "diskBytesAvailable", "diskBytesTotal",
                "screenWidthInPoints", "screenHeightInPoints",
                "appPlatform", "devicePlatform", "deviceFamily",
                "appUptimeInMilliseconds"):
        if attrs.get(key) is not None:
            lines.append(f"- **{key}**: {attrs[key]}")
    lines.append("")
    comment = attrs.get("comment")
    if comment:
        lines += ["## Comment", "", comment, ""]
    if screenshots:
        lines.append("## Screenshots")
        lines.append("")
        for shot in screenshots:
            lines.append(f"- {shot}")
    path.write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# Index generation

def write_index(
    bundle_id: str,
    crashes: list[dict[str, Any]],
    feedback: list[dict[str, Any]],
) -> pathlib.Path:
    path = OUTPUT_ROOT / "index.md"
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    lines = [
        f"# TestFlight reports — {bundle_id}",
        "",
        f"_Pulled {now}. {len(crashes)} crash(es), {len(feedback)} feedback item(s)._",
        "",
    ]

    if crashes:
        lines += ["## Crashes", ""]
        for c in sorted(crashes, key=lambda x: x.get("created") or "", reverse=True):
            title = f"{c.get('created') or '(no date)'} — "\
                    f"{c.get('device') or '?'} / iOS {c.get('os') or '?'} / "\
                    f"build {c.get('build') or '?'}"
            lines.append(f"### {title}")
            if c.get("email"):
                lines.append(f"- reporter: {c['email']}")
            if c.get("comment"):
                lines.append(f"- comment: _{c['comment']}_")
            if c.get("preview"):
                lines.append(f"- summary: `{c['preview']}`")
            if c.get("log_path"):
                lines.append(f"- log: `{c['log_path']}`")
            lines.append(f"- meta: `{c['meta_path']}`")
            lines.append("")
    else:
        lines += ["## Crashes", "", "_None._", ""]

    if feedback:
        lines += ["## Feedback", ""]
        for f in sorted(feedback, key=lambda x: x.get("created") or "", reverse=True):
            title = f"{f.get('created') or '(no date)'} — "\
                    f"{f.get('device') or '?'} / iOS {f.get('os') or '?'} / "\
                    f"build {f.get('build') or '?'}"
            lines.append(f"### {title}")
            if f.get("email"):
                lines.append(f"- reporter: {f['email']}")
            if f.get("comment"):
                lines.append(f"- comment: _{f['comment']}_")
            lines.append(f"- details: `{f['meta_path']}`")
            for shot in f.get("screenshots") or []:
                lines.append(f"- screenshot: `{shot}`")
            lines.append("")
    else:
        lines += ["## Feedback", "", "_None._", ""]

    path.write_text("\n".join(lines))
    return path


# --------------------------------------------------------------------------- #
# Entry point

def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Pull TestFlight crashes + feedback.")
    ap.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    ap.add_argument("--limit", type=int, default=None,
                    help="Max items per endpoint (default: everything)")
    ap.add_argument("--skip-crashes", action="store_true")
    ap.add_argument("--skip-feedback", action="store_true")
    args = ap.parse_args(argv)

    creds = load_credentials()
    print(f"credentials: {creds.source}")

    token = mint_jwt(creds)
    client = AscClient(token)

    app_id = find_app_id(client, args.bundle_id)
    print(f"app: {args.bundle_id} (id={app_id})")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    crashes: list[dict[str, Any]] = []
    feedback: list[dict[str, Any]] = []
    if not args.skip_crashes:
        crashes = pull_crashes(client, app_id, args.limit)
    if not args.skip_feedback:
        feedback = pull_feedback(client, app_id, args.limit)

    idx = write_index(args.bundle_id, crashes, feedback)
    print(f"index: {idx.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
