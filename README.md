<img src="icon.png" alt="Tridonic DALI" width="128" align="right" />

# Tridonic DALI — HACS test distribution

Pre-release distribution of the **Tridonic DALI** Home Assistant integration for
early testers, before it is available in Home Assistant core. It supports the
Tridonic/Lunatone DALI-USB dongle (USB `17B5:0201`).

> This is a temporary channel. Once the integration ships in Home Assistant core,
> install it from there and remove this custom repository.

## Requirements

- A running Home Assistant instance (OS, Container, or Supervised recommended).
- [HACS](https://hacs.xyz) installed and linked to a GitHub account that has been
  **granted read access to this private repository**.
- Network access on the Home Assistant host (first setup installs `python-dali`
  from PyPI via pip).

## Install

1. Ask the maintainer to grant your GitHub account read access to this repo, and
   make sure HACS on your instance is logged in as that account
   (HACS → three-dot menu → *Reload* after access is granted).
2. Add the repository to HACS, either with the button below or manually via
   **HACS → Integrations → three-dot menu → Custom repositories** (add this
   repository's URL with category **Integration**):

   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tridonic-com&repository=hacs-dali&category=integration)
3. Find **Tridonic DALI** in HACS, install it, then **restart Home Assistant**.
4. Plug in the DALI-USB dongle. Go to **Settings → Devices & Services → Add
   Integration → Tridonic DALI** and follow the config flow.

On first setup Home Assistant installs the released
[`python-dali`](https://pypi.org/project/python-dali/) dependency from PyPI via
pip; this can take a minute and requires network access.

## Updating

HACS offers updates when a new release is published here. Update from HACS, then
restart Home Assistant.

## For maintainers

The integration under `custom_components/dali/` is a generated copy of
`homeassistant/components/dali/` from a local Home Assistant core checkout. Do
not edit it by hand — change it in core, then re-sync:

```bash
python scripts/sync.py                 # uses ../core, keeps the current version
python scripts/sync.py --version 0.2.0 # bump the integration version
```

The sync makes exactly one change to the manifest versus core: it adds a
`version` field (required for custom integrations). The `python-dali==0.14`
PyPI pin is copied verbatim now that the release is published. Translations
(`translations/en.json`) are generated in the core checkout
(`python3 -m script.translations develop --integration dali`) before syncing,
since core does not commit them. After syncing, commit, tag with the matching
version, and push to the GitHub remote so HACS picks up the release.
