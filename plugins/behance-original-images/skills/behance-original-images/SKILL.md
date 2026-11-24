---
name: behance-original-images
description: Download original Behance project images into a new Desktop folder, rename them sequentially, and skip GIFs. Use when the user supplies a Behance project URL and asks to save or download every image.
---

# Behance Original Images

Download only the images in the project body. Do not include avatars, related
projects, tool icons, recommendation cards, or other page assets.

## Workflow

1. Open the exact gallery URL in the browser automation tab. Behance may return
   HTTP 403 to a direct page request even when the browser can load it.
2. Read the project title and rendered project images in DOM order:

   ```js
   ({
     title:
       document.querySelector("h1")?.textContent?.trim() ||
       document.title.split("|")[0].trim(),
     images: Array.from(document.images)
       .map((img) => img.currentSrc || img.src)
       .filter((url) => url.includes("/project_modules/"))
   })
   ```

3. Map those CDN URLs to their highest-quality variants. Replace the variant
   segment after `/project_modules/` with `source`, keeping the filename:

   ```text
   /project_modules/1400_webp/example.jpg
   /project_modules/source/example.jpg
   ```

   Use `source`, not `max_3840`, `2800_webp`, or `1400_webp`.

4. Pass the project title to the script. It creates a new, uniquely named folder
   on the Desktop, with this structure:

   ```text
   ~/Desktop/<project-title>_原图/
     <project-title>_01.jpg
     <project-title>_02.png
   ```

   If the folder already exists, the script adds `_2`, `_3`, and so on to both
   the folder and image names. It does not overwrite earlier downloads.
5. Pass the extracted URLs to [scripts/download_behance_images.py](scripts/download_behance_images.py):

   ```bash
   python3 scripts/download_behance_images.py --project-title "<project-title>" <<'EOF'
   <one project_modules URL per line>
   EOF
   ```

   The script deduplicates by filename, downloads in parallel, preserves the
   original extension, skips GIF files by URL extension, response content type,
   or file signature, and rejects other non-image content. It auto-detects the
   macOS system HTTP proxy. Pass `--proxy URL` when needed.

6. Verify the number of valid files equals the number of unique non-GIF
   project-image URLs. Report the folder, image count, GIF skip count, total
   size, and resolution range.

## Boundaries

- A gallery can contain text or video modules. Download their images only when
  the user specifically asks for that media type too.
- Rename images sequentially in DOM order. Do not preserve source filenames.
- Use `file` and `sips` (macOS) or equivalent metadata tools for final checks.
