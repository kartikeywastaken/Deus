# Optional image-reuse checks

This feature compares whole images, not people or faces. It never adds identity
evidence, changes rankings, or merges accounts. No API key or new dependency is needed.

## Try it

1. Start a username/profile search. Optionally choose a JPEG, PNG or WebP in the
   **Check image reuse** panel. The file stays local to the tab until comparison.
2. On completion, a selected image is checked automatically. Alternatively click
   **Check current candidates**, or select an image after completion and click that button.
3. Read the per-profile results and open the public source to review it. Another
   image can be selected afterward. The input is cleared after every attempt.

No photo is required to run a search. Closing/reloading the tab loses pending
photos and image results. Results remain visible in the tab until cleared or a new
search is started; they are not included in the saved identity report.

## API and retention

`POST /api/searches/{search_id}/image-matches` accepts **raw image bytes** with
`Content-Type: image/jpeg`, `image/png`, `image/webp`, or `application/octet-stream`.
It returns per-profile status, profile/avatar URLs, source observation IDs, check
time, limits and method version. Responses use `Cache-Control: no-store`.

Only avatar URLs observed within that search are fetched. No URL from the upload
is followed; EXIF location is neither read into results nor stored. Reference bytes,
downloaded bytes, hashes and thumbnails are request-local. Nothing is inserted in
PostgreSQL, the evidence ledger, vectors, jobs or application files. No background
retry retains the image. The old fingerprint-persisting `/images` endpoint now
returns 410. Existing historical artifacts are not deleted by this change.

Memory release is not a guarantee of cryptographic RAM erasure. Production hosting
must separately disable proxy/body logging, core dumps, and persistent request
capture. Aborting the browser request clears its UI; bounded server work may finish.
The original image on the user's device and the public source are never deleted.

## Methods and honest limitations

- `EXACT_FILE`: SHA-256 of bytes agrees — “Same image appears on this profile.”
- `SAME_PIXELS`: decoded RGBA pixels and dimensions agree after EXIF orientation.
- `POSSIBLE_REUSE`: pHash and dHash distances at most 4/64 each, normalized thumbnail
  MSE at most 0.006, aspect ratio within 2%. This is a conservative heuristic for
  resizing/compression, **not** a calibrated probability. Review manually.
- `NO_REUSE_DETECTED`: no whole-image match. Different photographs, crops and edits
  may not match. This supplies no negative evidence about a person.
- `INCONCLUSIVE`: low-detail images cannot be reliably compared perceptually.
- `NO_PUBLIC_IMAGE`, `UNAVAILABLE`, `TIMEOUT`, `LIMIT_REACHED`: explicit coverage gaps.

Copied photos, stock images, logos and default avatars can match; this never proves
who controls an account. No face detection, face embeddings, facial recognition,
reverse-face search or biometric inference is performed.

## Bounds

5 MB encoded upload/download, 16 MP decoded, still images only; 32 distinct avatar
URLs, four concurrent downloads, 15 seconds per image, 45 seconds for comparison.
Uploads have a 20-second deadline. At most two checks per API process and one per
search per process are admitted. Repeated avatar URLs are fetched once per request.
This is a local-app concurrency guard, not multi-instance production rate limiting.

The existing HTTPS fetcher validates/pins public DNS, rejects private destinations
on redirects, restricts content types and size, and uses no operator cookies or
authentication. Login walls and inaccessible avatars are not bypassed.

## Tests

`python -m pytest tests/unit/test_image_reuse.py -q` covers algorithmic image fixtures,
validation, stateless API behavior, missing avatars, duplicates, private destinations,
budgets and timeouts. These fixtures never enter production results. For a real
test, upload an image you possess against an actual completed search in the UI.
