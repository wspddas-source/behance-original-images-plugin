---
name: behance-original-images
description: Download all original project images from a Behance gallery into a local folder. Use when the user supplies a Behance project URL and asks to save or download every image.
---

# Behance Original Images

Download only the images in the project body. Do not include avatars, related
projects, tool icons, recommendation cards, or other page assets.

## Workflow

1. Open the exact gallery URL in the browser automation tab. Behance may return
   HTTP 403 to a direct page request even when the browser can load it.
2. Read the rendered project images in DOM order:

   ```js
   Array.from(document.images)
     .map((img) => img.currentSrc || img.src)
     .filter((url) => url.includes("/project_modules/"))
   ```

3. Map those CDN URLs to their highest-quality variants. Replace the variant
   segment after `/project_modules/` with `source`, keeping the filename:

   ```text
   /project_modules/1400_webp/example.jpg
   /project_modules/source/example.jpg
   ```

   Use `source`, not `max_3840`, `2800_webp`, or `1400_webp`.

4. Save into a project-named folder under the requested destination. If the
   user does not specify a location, use `~/Desktop/<project-title>`.
5. Pass the extracted URLs to [scripts/download_behance_images.py](scripts/download_behance_images.py):

   ```bash
   python3 scripts/download_behance_images.py "/path/to/output" <<'EOF'
   <one project_modules URL per line>
   EOF
   ```

   The script deduplicates by filename, downloads in parallel, preserves the
   original extension, skips already valid files, and rejects non-image content.
   It auto-detects the macOS system HTTP proxy. Pass `--proxy URL` when needed.

6. Verify the number of valid files equals the number of unique project-image
   filenames. Report the folder, image count, total size, and resolution range.

## Boundaries

- A gallery can contain text or video modules. Download their images only when
  the user specifically asks for that media type too.
- Preserve source filenames. Do not reorder images into invented descriptive
  names.
- Use `file` and `sips` (macOS) or equivalent metadata tools for final checks.
