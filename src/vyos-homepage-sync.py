#!/usr/bin/env python3

import json
import os
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests
import urllib3
import yaml

VERSION = "1.1.0"

VYOS_URL = os.environ.get("VYOS_URL", "").strip()
VYOS_API_KEY = os.environ.get("VYOS_API_KEY")
SERVICES_FILE = Path(os.environ.get("HOMEPAGE_SERVICES", "/opt/homepage/config/services.yaml"))
GROUP_NAME = os.environ.get("HOMEPAGE_GROUP", "Services")
VYOS_VERIFY_TLS = os.environ.get("VYOS_VERIFY_TLS", "false").lower() in ("1", "true", "yes", "on")
SERVICE_VERIFY_TLS = os.environ.get("SERVICE_VERIFY_TLS", "true").lower() in ("1", "true", "yes", "on")
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "5"))
HOMEPAGE_SITE_MONITOR = os.environ.get("HOMEPAGE_SITE_MONITOR", "true").lower() in ("1", "true", "yes", "on")
HOMEPAGE_STATUS_STYLE = os.environ.get("HOMEPAGE_STATUS_STYLE", "dot").strip() or "dot"

MANAGED_GROUP_NAMES = {GROUP_NAME, "VyOS HAProxy"}

if not VYOS_VERIFY_TLS or not SERVICE_VERIFY_TLS:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


SERVICE_RULES = [
    {"keywords": ["homeassistant", "home-assistant", "hass"], "name": "Home Assistant", "icon": "home-assistant"},
    {"keywords": ["coolercontrol", "cooler-control"], "name": "CoolerControl", "icon": None},
    {"keywords": ["immich"], "name": "Immich", "icon": "immich"},
    {"keywords": ["plex"], "name": "Plex", "icon": "plex"},
    {"keywords": ["unifi", "ubiquiti"], "name": "UniFi", "icon": "unifi"},
    {"keywords": ["vymanager", "vy-manager"], "name": "VyManager", "icon": "mdi-router-network"},
    {"keywords": ["grafana"], "name": "Grafana", "icon": "grafana"},
    {"keywords": ["prometheus"], "name": "Prometheus", "icon": "prometheus"},
    {"keywords": ["nextcloud"], "name": "Nextcloud", "icon": "nextcloud"},
    {"keywords": ["jellyfin"], "name": "Jellyfin", "icon": "jellyfin"},
    {"keywords": ["emby"], "name": "Emby", "icon": "emby"},
    {"keywords": ["sonarr"], "name": "Sonarr", "icon": "sonarr"},
    {"keywords": ["radarr"], "name": "Radarr", "icon": "radarr"},
    {"keywords": ["sabnzbd"], "name": "SABnzbd", "icon": "sabnzbd"},
    {"keywords": ["qbittorrent", "qbit"], "name": "qBittorrent", "icon": "qbittorrent"},
    {"keywords": ["vaultwarden", "bitwarden"], "name": "Vaultwarden", "icon": "vaultwarden"},
    {"keywords": ["portainer"], "name": "Portainer", "icon": "portainer"},
    {"keywords": ["paperless", "paperless-ngx"], "name": "Paperless-ngx", "icon": "paperless-ngx"},
    {"keywords": ["adguard"], "name": "AdGuard Home", "icon": "adguard-home"},
    {"keywords": ["pihole", "pi-hole"], "name": "Pi-hole", "icon": "pi-hole"},
    {"keywords": ["uptime-kuma", "uptimekuma"], "name": "Uptime Kuma", "icon": "uptime-kuma"},
]


class FaviconParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.icons = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "link":
            return
        attrs = {str(key).lower(): value for key, value in attrs if key}
        rel = (attrs.get("rel") or "").lower()
        href = attrs.get("href")
        if href and ("icon" in rel or "apple-touch-icon" in rel or "mask-icon" in rel):
            self.icons.append({"rel": rel, "href": href})


def normalize(value):
    if not value:
        return ""
    value = str(value).lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def strip_host_suffix(value):
    value = normalize(value)
    stripped = re.sub(r"-(?:pve|node|host|vm|srv|server)\d*$", "", value)
    return stripped or value


def extract_host_suffix(value):
    value = normalize(value)
    match = re.search(r"-(pve|node|host|vm|srv|server)(\d*)$", value)
    if not match:
        return None
    labels = {
        "pve": "PVE",
        "node": "Node",
        "host": "Host",
        "vm": "VM",
        "srv": "Server",
        "server": "Server",
    }
    suffix = labels.get(match.group(1), match.group(1).upper())
    if match.group(2):
        suffix += match.group(2)
    return suffix


def pretty_name(value):
    parts = [part for part in normalize(value).split("-") if part]
    replacements = {
        "api": "API",
        "dns": "DNS",
        "vpn": "VPN",
        "nas": "NAS",
        "pve": "PVE",
        "mysql": "MySQL",
        "mariadb": "MariaDB",
        "postgres": "PostgreSQL",
        "postgresql": "PostgreSQL",
        "unifi": "UniFi",
        "vymanager": "VyManager",
        "qbittorrent": "qBittorrent",
        "pihole": "Pi-hole",
    }
    return " ".join(replacements.get(part.lower(), part.capitalize()) for part in parts)


def parse_backend_description(description):
    result = {
        "name": None,
        "homepage": True,
        "monitor": True,
        "raw": description or "",
    }

    if not description:
        return result

    parts = [part.strip() for part in str(description).split("|")]
    option_re = re.compile(r"^[a-zA-Z0-9_-]+\s*=\s*.+$")

    if parts and parts[0] and not option_re.match(parts[0]):
        result["name"] = parts[0]
        option_parts = parts[1:]
    else:
        option_parts = parts

    for part in option_parts:
        if "=" not in part:
            continue
        key, value = [item.strip().lower() for item in part.split("=", 1)]
        false_values = {"0", "false", "no", "off", "hide", "disabled"}
        true_values = {"1", "true", "yes", "on", "show", "enabled"}

        if key in {"homepage", "publish", "show"}:
            if value in false_values:
                result["homepage"] = False
            elif value in true_values:
                result["homepage"] = True
        elif key in {"monitor", "health", "status"}:
            if value in false_values:
                result["monitor"] = False
            elif value in true_values:
                result["monitor"] = True

    return result


def url_exists(url):
    try:
        response = requests.get(
            url,
            timeout=HTTP_TIMEOUT,
            verify=SERVICE_VERIFY_TLS,
            allow_redirects=True,
            stream=True,
            headers={"User-Agent": f"vyos-homepage-sync/{VERSION}"},
        )
        return 200 <= response.status_code < 400
    except requests.RequestException:
        return False


def discover_favicon(domain):
    base_url = f"https://{domain}"
    try:
        response = requests.get(
            base_url,
            timeout=HTTP_TIMEOUT,
            verify=SERVICE_VERIFY_TLS,
            allow_redirects=True,
            headers={"User-Agent": f"vyos-homepage-sync/{VERSION}"},
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" in content_type or not content_type:
            parser = FaviconParser()
            parser.feed(response.text)
            preferred = ["apple-touch-icon", "icon", "mask-icon"]
            for wanted in preferred:
                for icon in parser.icons:
                    rel = icon["rel"]
                    if wanted == "icon" and "mask-icon" in rel:
                        continue
                    if wanted in rel:
                        icon_url = urljoin(response.url, icon["href"])
                        if url_exists(icon_url):
                            return icon_url
    except requests.RequestException:
        pass

    fallback = f"https://{domain}/favicon.ico"
    if url_exists(fallback):
        return fallback
    return "mdi-web"


def detect_service(domain, backend):
    subdomain = domain.split(".")[0]
    original_candidates = [normalize(subdomain), normalize(backend)]
    application_candidates = [strip_host_suffix(candidate) for candidate in original_candidates if candidate]

    for rule in SERVICE_RULES:
        for candidate in application_candidates:
            matched = any(candidate == keyword or candidate.startswith(keyword + "-") for keyword in rule["keywords"])
            if not matched:
                continue
            name = rule["name"]
            suffix = extract_host_suffix(subdomain)
            if suffix:
                name = f"{name} {suffix}"
            icon = rule.get("icon") or discover_favicon(domain)
            return {"name": name, "icon": icon, "confidence": "known"}

    for candidate in original_candidates:
        if re.fullmatch(r"(?:proxmox|pve\d*)", candidate):
            return {"name": pretty_name(subdomain), "icon": "proxmox", "confidence": "known"}

    return {
        "name": pretty_name(subdomain),
        "icon": discover_favicon(domain),
        "confidence": "favicon",
    }


def vyos_retrieve(path):
    if not VYOS_API_KEY:
        raise RuntimeError("VYOS_API_KEY ist nicht gesetzt")

    payload = {"op": "showConfig", "path": path}
    response = requests.post(
        f"{VYOS_URL}/retrieve",
        data={"data": json.dumps(payload), "key": VYOS_API_KEY},
        timeout=15,
        verify=VYOS_VERIFY_TLS,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("success"):
        raise RuntimeError(f"VyOS API Fehler: {result.get('error')}")
    return result.get("data")


def get_haproxy_config():
    return vyos_retrieve(["load-balancing", "haproxy"])


def extract_backend_metadata(data):
    backends = {}

    def walk(node, path=None):
        path = path or []
        if isinstance(node, dict):
            if path and path[-1] == "backend":
                for backend_name, backend_cfg in node.items():
                    if not isinstance(backend_cfg, dict):
                        continue
                    if not any(key in backend_cfg for key in ("mode", "server", "description", "balance", "ssl")):
                        continue
                    description = backend_cfg.get("description")
                    parsed = parse_backend_description(description)
                    backends[str(backend_name)] = {
                        "description": description,
                        "display_name": parsed["name"],
                        "homepage": parsed["homepage"],
                        "monitor": parsed["monitor"],
                    }
            for key, value in node.items():
                walk(value, path + [str(key)])
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, path + [str(index)])

    walk(data)
    return backends


def extract_services(data, backend_metadata):
    found = []

    def walk(node, path=None):
        path = path or []
        if isinstance(node, dict):
            domain = node.get("domain-name")
            if domain:
                backend = None
                set_node = node.get("set")
                if isinstance(set_node, dict):
                    backend = set_node.get("backend")
                rule_id = None
                if "rule" in path:
                    try:
                        index = path.index("rule")
                        rule_id = str(path[index + 1])
                    except (ValueError, IndexError):
                        pass
                found.append({"rule": rule_id or "?", "domain": domain, "backend": backend})
            for key, value in node.items():
                walk(value, path + [str(key)])
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, path + [str(index)])

    walk(data)

    unique = {}
    for item in found:
        domains = item["domain"] if isinstance(item["domain"], list) else [item["domain"]]
        backend_name = str(item["backend"] or "")
        metadata = backend_metadata.get(backend_name, {})

        if metadata.get("homepage") is False:
            for domain in domains:
                print(f"Ueberspringe {domain} (Backend {backend_name}: homepage=off)")
            continue

        for domain in domains:
            key = (str(domain), backend_name)
            unique[key] = {
                "rule": item["rule"],
                "domain": str(domain),
                "backend": item["backend"],
                "display_name": metadata.get("display_name"),
                "backend_description": metadata.get("description"),
                "monitor": metadata.get("monitor", True),
            }

    services = list(unique.values())

    def sort_key(item):
        try:
            return int(item["rule"])
        except (ValueError, TypeError):
            return 999999

    return sorted(services, key=sort_key)


def make_homepage_service(item):
    detected = detect_service(item["domain"], item["backend"])
    name = item.get("display_name") or detected["name"]
    href = f'https://{item["domain"]}'

    service = {
        "icon": detected["icon"],
        "href": href,
    }

    if HOMEPAGE_SITE_MONITOR and item.get("monitor", True):
        service["siteMonitor"] = href
        service["statusStyle"] = HOMEPAGE_STATUS_STYLE

    return {name: service}


def load_services():
    if not SERVICES_FILE.exists():
        return []
    with SERVICES_FILE.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if data is None:
        return []
    if not isinstance(data, list):
        raise RuntimeError(f"{SERVICES_FILE} ist keine gueltige Homepage services.yaml")
    return data


def remove_generated_groups(services):
    result = []
    for group in services:
        if not isinstance(group, dict):
            result.append(group)
            continue
        if any(name in group for name in MANAGED_GROUP_NAMES):
            continue
        result.append(group)
    return result


def write_services(services):
    SERVICES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if SERVICES_FILE.exists():
        shutil.copy2(SERVICES_FILE, Path(str(SERVICES_FILE) + ".bak"))

    temp_file = Path(str(SERVICES_FILE) + ".tmp")
    with temp_file.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            services,
            file,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
    temp_file.replace(SERVICES_FILE)


def main():
    print(f"vyos-homepage-sync {VERSION}")
    print(f"Verbinde mit VyOS API: {VYOS_URL}")

    haproxy_config = get_haproxy_config()
    backend_metadata = extract_backend_metadata(haproxy_config)
    services = extract_services(haproxy_config, backend_metadata)

    if not services:
        raise RuntimeError("Keine importierbaren HAProxy domain-name Regeln gefunden")

    homepage_services = remove_generated_groups(load_services())
    generated = []

    print("\nErkannte Services:\n")
    for item in services:
        detected = detect_service(item["domain"], item["backend"])
        display_name = item.get("display_name") or detected["name"]
        generated.append(make_homepage_service(item))
        print(f'  {item["domain"]:<45} -> {display_name}')
        print(f'      Backend: {item["backend"] or "-"}')
        if item.get("backend_description"):
            print(f'      Description: {item["backend_description"]}')
        print(f'      Icon: {detected["icon"]}')
        monitor_state = "on" if HOMEPAGE_SITE_MONITOR and item.get("monitor", True) else "off"
        print(f'      Monitor: {monitor_state}')

    homepage_services.append({GROUP_NAME: generated})
    write_services(homepage_services)

    print(f"\n{len(services)} Services importiert.")
    print(f"Homepage aktualisiert: {SERVICES_FILE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        sys.exit(1)
