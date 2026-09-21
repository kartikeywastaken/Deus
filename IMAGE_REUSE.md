# In-Memory Photo Matching for Profile Candidates

This feature compares an optional user-attached photo against profile pictures of candidate profiles found during a username search using local, zero-third-party image matching (cross-correlation, center crop matching, inscribed circle masking, and SHA-256 exact matching).

It does **not** recognize faces, detect facial landmarks, calculate facial embeddings, or perform biometric identification. It only matches instances of the **same photo** (allowing crops, resizes, horizontal mirrors, circular crops, and JPEG recompression).

## Privacy and Storage Guarantees

- **Memory Only**: The uploaded photo is stored exclusively in an in-memory `PhotoStore` (TTL 30 minutes, LRU max capacity 16 entries).
- **Zero Disk / DB Storage**: The photo is never written to disk, database, logs, or persistent storage.
- **Zero Third-Party Services**: Comparison runs strictly on the local server process. The photo never leaves the machine, and no third-party reverse image search APIs (Google Lens, SerpAPI, TinEye, etc.) are called.
- **Cache-Control**: All matching responses use `Cache-Control: no-store`.

## Endpoints

- `POST /api/searches/:id/photo` (multipart field `"photo"`): Prepares the photo (EXIF orientation applied, checked for format/size/dimensions/detail) and returns `{ "token": token, "width": w, "height": h }`.
- `GET /api/searches/:id/photo-matches?token=`: Polls match results for the current candidates of the search run. Cached per `(token, avatar_url)`.
- `DELETE /api/searches/:id/photo?token=`: Explicitly clears the photo session from memory.

## Matching Algorithm and Verdicts

1. **Pre-processing**:
   - Magic bytes check: JPEG, PNG, or WebP only.
   - Max size: 5 MB. Max dimensions: 16 MP (checked before full decode).
   - EXIF orientation applied using `kamadak-exif`.
   - Low detail rejection: grayscale standard deviation must be $\ge 12.0$.
   - Prepared image: grayscale, downscaled so longest side = 96 px (`Lanczos3`).

2. **Avatar Matching**:
   - `EXACT_FILE`: SHA-256 hash of avatar bytes equals upload byte hash (strength 1.0).
   - `SAME_PHOTO`: Normalized Zero-mean Cross-Correlation (ZNCC) strength $\ge 0.90$ across multi-scale window fractions ($f \in [0.30, 1.0]$), horizontal mirrors, and inscribed circle masking.
   - `POSSIBLE_MATCH`: ZNCC strength $0.85 \le \text{strength} < 0.90$.
   - `NO_MATCH`: strength $< 0.85$.
   - `TOO_SMALL`: Avatar side $< 24$ px.
   - `UNAVAILABLE`: Avatar URL could not be fetched (SSRF blocked, timeout, HTTP 404/500).

3. **Known Limitations**:
   - Rotated copies (e.g. 45° or 90° rotated) are not matched.
   - Different photographs of the same individual will **not** match.

## Rate Limits and SSRF Safety

- Upload rate limit: default 20 uploads per IP per hour (configurable via `PHOTO_MATCH_PER_IP_HOURLY`).
- Avatar fetches are performed using `safe_fetch` with strict DNS validation blocking loopback (`127.0.0.0/8`, `::1`), private, link-local, and multicast IP addresses, with redirect re-validation at every hop.
