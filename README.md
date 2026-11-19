# Behance Original Images Plugin

Installable Codex plugin for downloading every original project image from a
Behance gallery. The bundled skill extracts rendered `/project_modules/` image
URLs, downloads Behance's highest-quality `source` variants, and verifies that
each response is an image.

## Install

Add the GitHub-backed marketplace:

```bash
codex plugin marketplace add wspddas-source/behance-original-images-plugin
```

Restart the ChatGPT desktop app. Open the Plugins Directory, select
**wspddas Codex Plugins**, and install **Behance Original Images**.

## Use

```text
Use Behance Original Images to download every image from this Behance project
into a folder on my Desktop:
https://www.behance.net/gallery/PROJECT_ID/PROJECT_SLUG
```

## Standalone skill

The standalone skill and direct downloader are also available at
<https://github.com/wspddas-source/behance-original-images>.

## Rights

The MIT license covers the plugin instructions and downloader code. Downloaded
images remain subject to the original creator's rights and Behance's terms.
