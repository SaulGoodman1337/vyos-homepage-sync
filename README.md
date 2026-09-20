# vyos-homepage-sync

Synchronizes domain-based VyOS HAProxy services into a [Homepage](https://gethomepage.dev/) `services.yaml` group.

The tool reads VyOS via the REST API, maps `domain-name` rules to their HAProxy backends, uses the backend `description` as Homepage metadata, detects icons, and rewrites only the generated Homepage group.

## Features

- VyOS REST API; no SSH parsing
- HAProxy `domain-name` rule discovery
- Backend `description` controls the display name, publishing, and optional monitoring
- Known Homepage/Dashboard Icons for common services
- Favicon discovery for unknown services
- Built-in Homepage `siteMonitor` with green/red dot status
- Host suffix handling (`coolercontrol-pve01` remains CoolerControl, not Proxmox)
- Atomic `services.yaml` updates with `.bak` backup
- systemd service + 5 minute timer
- Git-based updater and optional daily update timer

## Backend description convention

Use the VyOS HAProxy backend description as metadata:

```text
Display Name | homepage=on
Display Name | homepage=off
Display Name | homepage=on | monitor=off
```

Examples:

```bash
set load-balancing haproxy backend homeassistant description 'Home Assistant | homepage=on'
set load-balancing haproxy backend coolercontrol-pve01 description 'CoolerControl PVE01 | homepage=on'
set load-balancing haproxy backend vymanager description 'VyManager | homepage=on'
set load-balancing haproxy backend homepage description 'Homepage | homepage=off'
set load-balancing haproxy backend protected-app description 'Protected App | homepage=on | monitor=off'
```

Rules:

- Text before `|` becomes the Homepage tile name.
- `homepage=on` includes the URL.
- `homepage=off` excludes every HAProxy domain that points to that backend.
- `monitor=off` publishes the service but disables the Homepage site monitor for it.
- `monitor=on` is the default. Aliases `health=` and `status=` are also accepted.
- If `homepage=` is omitted, the backend is included by default.
- If there is no description/name, the script derives a name from the domain/backend.
- Aliases `publish=` and `show=` are also accepted.

This eliminates hard-coded `EXCLUDED_BACKENDS` lists.

## Requirements

- Debian/Ubuntu-style Homepage host/LXC
- Python 3
- VyOS REST API enabled
- Homepage installed with a writable `services.yaml`

The installer installs `git`, `python3-requests`, and `python3-yaml` automatically.

## Install from GitHub

```bash
curl -fsSL https://raw.githubusercontent.com/SaulGoodman1337/vyos-homepage-sync/main/install.sh \
  | sudo bash -s -- --repo https://github.com/SaulGoodman1337/vyos-homepage-sync.git
```

To enable the daily updater immediately:

```bash
curl -fsSL https://raw.githubusercontent.com/SaulGoodman1337/vyos-homepage-sync/main/install.sh \
  | sudo bash -s -- \
    --repo https://github.com/SaulGoodman1337/vyos-homepage-sync.git \
    --enable-auto-update
```

For a cloned checkout:

```bash
git clone https://github.com/SaulGoodman1337/vyos-homepage-sync.git
cd vyos-homepage-sync
sudo ./install.sh --local
```

## Configuration

Edit:

```bash
sudo nano /etc/vyos-homepage-sync.conf
```

Example:

```bash
VYOS_URL=https://192.168.148.3:444
VYOS_API_KEY=CHANGE_ME
VYOS_VERIFY_TLS=false
HOMEPAGE_SERVICES=/opt/homepage/config/services.yaml
HOMEPAGE_GROUP=Services
HOMEPAGE_SITE_MONITOR=true
HOMEPAGE_STATUS_STYLE=dot
SERVICE_VERIFY_TLS=true
HTTP_TIMEOUT=5
```

Then test:

```bash
sudo systemctl start vyos-homepage-sync.service
sudo journalctl -u vyos-homepage-sync.service -n 100 --no-pager
```

## Updating

Manual update:

```bash
sudo vyos-homepage-sync-update
```

Enable automatic daily update checks:

```bash
sudo systemctl enable --now vyos-homepage-sync-update.timer
```

Disable automatic updates:

```bash
sudo systemctl disable --now vyos-homepage-sync-update.timer
```

Check timers:

```bash
systemctl list-timers 'vyos-homepage-sync*'
```

## Generated Homepage output

For example:

```yaml
- Services:
    - Home Assistant:
        icon: home-assistant
        href: https://homeassistant.example.net
        siteMonitor: https://homeassistant.example.net
        statusStyle: dot
    - CoolerControl PVE01:
        icon: https://coolercontrol-pve01.example.net/favicon.ico
        href: https://coolercontrol-pve01.example.net
        siteMonitor: https://coolercontrol-pve01.example.net
        statusStyle: dot
```

Other Homepage groups are preserved. Only the configured generated group is replaced.

## Security

The VyOS API key is stored in `/etc/vyos-homepage-sync.conf` with mode `0600`. Do not commit API keys to Git.

If possible, use a certificate trusted by the Homepage host and set:

```bash
VYOS_VERIFY_TLS=true
```

## Availability status

By default every published service also gets Homepage's built-in HTTP site monitor:

```yaml
siteMonitor: https://service.example.net
statusStyle: dot
```

Homepage performs an HTTP `HEAD` request and falls back to `GET`. The `dot` style renders a compact availability indicator. Services behind authentication or special redirect logic can opt out with:

```bash
set load-balancing haproxy backend myapp description 'My App | homepage=on | monitor=off'
```

The feature can also be disabled globally with `HOMEPAGE_SITE_MONITOR=false`.
