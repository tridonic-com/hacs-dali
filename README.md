# Tridonic DALI — HACS test distribution

Pre-release distribution of the **Tridonic DALI** Home Assistant integration for
early testers, before it is available in Home Assistant core. It supports the
Tridonic/Lunatone DALI-USB dongle (USB `17B5:0201`).

> This is a temporary channel. Once the integration ships in Home Assistant core,
> install it from there and remove this custom repository.

## Requirements

- A running Home Assistant instance (OS, Container, or Supervised recommended;
  these ship `git`, which is needed to install the `python-dali` dependency).
- [HACS](https://hacs.xyz) installed and linked to a GitHub account that has been
  **granted read access to this private repository**.
- Network access on the Home Assistant host (first setup clones `python-dali`
  from GitHub via pip).

## Install

1. Ask the maintainer to grant your GitHub account read access to this repo, and
   make sure HACS on your instance is logged in as that account
   (HACS → three-dot menu → *Reload* after access is granted).
2. In Home Assistant: **HACS → Integrations → three-dot menu → Custom
   repositories**.
3. Add this repository's URL with category **Integration**.
4. Find **Tridonic DALI** in HACS, install it, then **restart Home Assistant**.
5. Plug in the DALI-USB dongle. Go to **Settings → Devices & Services → Add
   Integration → Tridonic DALI** and follow the config flow.

On first setup Home Assistant installs the `python-dali` dependency from the
[Tridonic fork](https://github.com/tridonic-com/python-dali/tree/to-upstream)
via pip; this can take a minute and requires network access.

## Updating

HACS offers updates when a new release is published here. Update from HACS, then
restart Home Assistant.

## For maintainers

The integration under `custom_components/dali/` is a generated copy of
`homeassistant/components/dali/` from a local Home Assistant core checkout. Do
not edit it by hand — change it in core, then re-sync:

```bash
python scripts/sync.py                 # uses ../core and the pinned python-dali ref
python scripts/sync.py --version 0.2.0 # bump the integration version
```

The sync makes exactly two changes to the manifest versus core: it adds a
`version` field (required for custom integrations) and replaces the
`python-dali==0.12` PyPI pin with a git-URL requirement pointing at the fork.
After syncing, commit, tag with the matching version, and push to the GitHub
remote so HACS picks up the release.
