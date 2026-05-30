"""Malleable C2 profile presets — curated Sliver http-c2 configs.

Sliver's HTTP/S listener config (`http-c2.json` in its config dir) defines
URI paths, headers, jitter, file extensions used for staging — Sliver's
analogue of Cobalt Strike's Malleable C2 profile. This module ships a few
hand-tuned presets covering common mimicry targets.

These are CONFIGS the operator saves into their Sliver server; the BFF does
not push them — wire-level deployment requires server-side file mutation
that's out of scope for the operator UI.

To apply on the operator box:
    cp downloaded.json ~/.sliver/configs/http-c2.json
    # then restart sliver-server, or use `https --c2profile <name>` per listener.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from models import ProfilePreset

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


# JSON blobs are written as Python dicts then serialized — easier to maintain
# than embedded JSON strings. Keys match Sliver's HttpC2Config schema
# (github.com/BishopFox/sliver/blob/master/server/configs/http-c2.go).

_AMAZON_CLOUDFRONT = {
    "implant_config": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/121.0.0.0 Safari/537.36",
        "chrome_base_version": 121,
        "macos_version": "10_15_7",
        "url_parameters": [
            {"method": "GET", "name": "ttl", "value": "{{rand_int}}"},
            {"method": "GET", "name": "ref", "value": "cf-{{rand_alpha 6}}"},
        ],
        "headers": [
            {"name": "Cache-Control", "value": "no-cache"},
            {"name": "Pragma",        "value": "no-cache"},
            {"name": "X-Amz-Cf-Id",   "value": "{{rand_alpha 22}}"},
        ],
        "poll_file_ext": ".js",
        "start_session_file_ext": ".png",
        "session_file_ext":  ".html",
        "close_file_ext":    ".css",
        "poll_paths":          ["assets/static", "v2/manifest", "_next/data"],
        "start_session_paths": ["i", "static/media", "cdn-cgi/image"],
        "session_paths":       ["app", "v1/render", "edge"],
        "close_paths":         ["v1/log", "ping"],
        "max_files": 8,
        "min_files": 2,
        "max_paths": 8,
        "min_paths": 2,
    },
    "server_config": {
        "random_version_headers": True,
        "headers": [
            {"name": "Server", "value": "cloudfront", "probability": 100},
            {"name": "X-Cache", "value": "Hit from cloudfront", "probability": 80},
            {"name": "Via", "value": "1.1 {{rand_alpha 14}}.cloudfront.net (CloudFront)", "probability": 60},
        ],
        "cookies": [
            {"name": "CloudFront-Key-Pair-Id"},
            {"name": "CloudFront-Policy"},
            {"name": "CloudFront-Signature"},
        ],
    },
}

_WINDOWS_UPDATE = {
    "implant_config": {
        "user_agent": "Windows-Update-Agent/10.0.10011.16384 Client-Protocol/2.32",
        "url_parameters": [],
        "headers": [
            {"name": "Cache-Control", "value": "no-cache"},
            {"name": "Pragma",        "value": "no-cache"},
            {"name": "Connection",    "value": "Keep-Alive"},
        ],
        "poll_file_ext":          ".cab",
        "start_session_file_ext": ".xml",
        "session_file_ext":       ".cab",
        "close_file_ext":         ".cab",
        "poll_paths":          ["v6", "v9", "msdownload"],
        "start_session_paths": ["client", "v6/Client"],
        "session_paths":       ["msdownload/update/v3-19990518/cabpool",
                                "msdownload/update/software/secu"],
        "close_paths":         ["client/etag", "msdownload/log"],
        "max_files": 6,
        "min_files": 1,
        "max_paths": 4,
        "min_paths": 1,
    },
    "server_config": {
        "headers": [
            {"name": "Server", "value": "Microsoft-IIS/10.0", "probability": 100},
            {"name": "X-Powered-By", "value": "ASP.NET", "probability": 60},
        ],
    },
}

_GENERIC_CDN = {
    "implant_config": {
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "url_parameters": [
            {"method": "GET", "name": "v", "value": "{{rand_int}}"},
        ],
        "headers": [{"name": "Accept", "value": "*/*"}],
        "poll_file_ext":          ".woff2",
        "start_session_file_ext": ".js",
        "session_file_ext":       ".css",
        "close_file_ext":         ".png",
        "poll_paths":          ["static", "assets"],
        "start_session_paths": ["api/v1"],
        "session_paths":       ["api/v2"],
        "close_paths":         ["api/v3"],
        "max_files": 4,
        "min_files": 1,
        "max_paths": 4,
        "min_paths": 1,
    },
    "server_config": {
        "headers": [
            {"name": "Server", "value": "nginx/1.25.3", "probability": 100},
        ],
    },
}


_PRESETS: list[ProfilePreset] = [
    ProfilePreset(
        name="amazon-cloudfront",
        description="CloudFront-style traffic — long URIs, Amz-Cf-Id header, "
                    ".png/.css/.js routing.",
        category="cdn-mimicry",
        yaml=json.dumps(_AMAZON_CLOUDFRONT, indent=2),
    ),
    ProfilePreset(
        name="windows-update",
        description="Mimics Windows Update Agent — .cab files, v6/v9 URIs, "
                    "Microsoft-IIS server banner.",
        category="update-traffic",
        yaml=json.dumps(_WINDOWS_UPDATE, indent=2),
    ),
    ProfilePreset(
        name="generic-cdn",
        description="Generic Chrome-on-Linux + nginx CDN-ish profile. "
                    "Bland; good fit for opportunistic engagements.",
        category="generic",
        yaml=json.dumps(_GENERIC_CDN, indent=2),
    ),
]


@router.get("/presets", response_model=list[ProfilePreset])
async def list_presets() -> list[ProfilePreset]:
    return _PRESETS


@router.get("/presets/{name}", response_model=ProfilePreset)
async def get_preset(name: str) -> ProfilePreset:
    for p in _PRESETS:
        if p.name == name:
            return p
    raise HTTPException(status_code=404, detail=f"profile {name!r} not in catalog")
