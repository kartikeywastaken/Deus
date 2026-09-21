use crate::photo_match::prepare::{compute_grayscale_stats, PreparedPhoto};
use image::{imageops::FilterType, GenericImageView};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Verdict {
    SamePhoto,
    PossibleMatch,
    NoMatch,
    TooSmall,
    Unavailable,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MatchMethod {
    ExactFile,
    CropMatch,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PhotoMatchResult {
    pub verdict: Verdict,
    pub strength: f32,
    pub method: MatchMethod,
}

pub fn match_avatar(upload: &PreparedPhoto, avatar_bytes: &[u8]) -> PhotoMatchResult {
    // 1. Exact file match via SHA-256
    let mut hasher = Sha256::new();
    hasher.update(avatar_bytes);
    let avatar_sha256: [u8; 32] = hasher.finalize().into();

    if avatar_sha256 == upload.sha256 {
        return PhotoMatchResult {
            verdict: Verdict::SamePhoto,
            strength: 1.0,
            method: MatchMethod::ExactFile,
        };
    }

    // 2. Decode avatar image
    let avatar_img = match image::load_from_memory(avatar_bytes) {
        Ok(img) => img,
        Err(_) => {
            return PhotoMatchResult {
                verdict: Verdict::Unavailable,
                strength: 0.0,
                method: MatchMethod::CropMatch,
            }
        }
    };

    let (aw, ah) = avatar_img.dimensions();
    let min_dim = aw.min(ah);

    // Skip tiny avatars (< 24 px)
    if min_dim < 24 {
        return PhotoMatchResult {
            verdict: Verdict::TooSmall,
            strength: 0.0,
            method: MatchMethod::CropMatch,
        };
    }

    // Center-crop to square
    let crop_x = (aw - min_dim) / 2;
    let crop_y = (ah - min_dim) / 2;
    let cropped = avatar_img.crop_imm(crop_x, crop_y, min_dim, min_dim);
    let luma_avatar = cropped.to_luma8();

    // Skip flat avatars (std dev < 6.0)
    let (_mean, std_dev) = compute_grayscale_stats(luma_avatar.as_raw());
    if std_dev < 6.0 {
        return PhotoMatchResult {
            verdict: Verdict::NoMatch,
            strength: 0.0,
            method: MatchMethod::CropMatch,
        };
    }

    // 3. Multi-scale crop match
    let uw = upload.prepared_width as usize;
    let uh = upload.prepared_height as usize;
    let min_u = upload.prepared_width.min(upload.prepared_height);

    let num_fractions = 6;
    let mut best_strength: f32 = 0.0;

    for i in 0..num_fractions {
        let f = 0.50 + (i as f32) * (1.00 - 0.50) / ((num_fractions - 1) as f32);
        let side = ((min_u as f32) * f).floor() as u32;

        if side < 16 || side > upload.prepared_width || side > upload.prepared_height {
            continue;
        }

        let side_sz = side as usize;
        let count_full = (side_sz * side_sz) as f32;

        // Stride 2 for fine sub-pixel position alignment
        let stride = 2;

        // Resize square avatar to side x side (Triangle filter for speed)
        let t_img = image::imageops::resize(&luma_avatar, side, side, FilterType::Triangle);
        let t_pixels: Vec<f32> = t_img.as_raw().iter().map(|&p| p as f32).collect();

        // Horizontal mirror of template
        let mut t_flip_pixels = vec![0.0f32; t_pixels.len()];
        for r in 0..side_sz {
            for c in 0..side_sz {
                t_flip_pixels[r * side_sz + c] = t_pixels[r * side_sz + (side_sz - 1 - c)];
            }
        }

        // Inscribed circle mask: 0.46 * side radius to avoid boundary Lanczos/JPEG artifacts
        let center = (side_sz as f32 - 1.0) / 2.0;
        let radius_sq = (side_sz as f32 * 0.46).powi(2);
        let mut circle_mask = vec![false; side_sz * side_sz];
        let mut count_circle = 0.0f32;
        for r in 0..side_sz {
            let dy = r as f32 - center;
            for c in 0..side_sz {
                let dx = c as f32 - center;
                if dx * dx + dy * dy <= radius_sq {
                    circle_mask[r * side_sz + c] = true;
                    count_circle += 1.0;
                }
            }
        }

        let templates = [&t_pixels, &t_flip_pixels];

        for template in templates {
            // Precompute Template stats and mean-centered template vectors
            let sum_t: f32 = template.iter().sum();
            let mean_t = sum_t / count_full;
            let mut dt_full = vec![0.0f32; template.len()];
            let mut ss_t = 0.0f32;
            for (j, &val) in template.iter().enumerate() {
                let dt = val - mean_t;
                dt_full[j] = dt;
                ss_t += dt * dt;
            }

            if ss_t <= 0.0 {
                continue;
            }

            let (ss_t_c, dt_circle) = if count_circle > 0.0 {
                let mut sum_t_c = 0.0f32;
                for (j, &inc) in circle_mask.iter().enumerate() {
                    if inc {
                        sum_t_c += template[j];
                    }
                }
                let mean_c = sum_t_c / count_circle;
                let mut ss_c = 0.0f32;
                let mut dt_c = vec![0.0f32; template.len()];
                for (j, &inc) in circle_mask.iter().enumerate() {
                    if inc {
                        let dt = template[j] - mean_c;
                        dt_c[j] = dt;
                        ss_c += dt * dt;
                    }
                }
                (ss_c, dt_c)
            } else {
                (0.0, vec![])
            };

            let denom_t_full = ss_t.sqrt();
            let denom_t_circle = ss_t_c.sqrt();

            // Slide over upload U with stride 2
            let mut y = 0;
            while y + side_sz <= uh {
                let mut x = 0;
                while x + side_sz <= uw {
                    let mut sum_w = 0.0f32;
                    let mut sum_w2 = 0.0f32;
                    let mut sum_tw = 0.0f32;

                    let mut sum_w_c = 0.0f32;
                    let mut sum_w2_c = 0.0f32;
                    let mut sum_tw_c = 0.0f32;

                    for r in 0..side_sz {
                        let u_row = (y + r) * uw;
                        let t_row = r * side_sz;
                        for c in 0..side_sz {
                            let idx_t = t_row + c;
                            let val = upload.prepared_f32[u_row + x + c];

                            sum_w += val;
                            sum_w2 += val * val;
                            sum_tw += dt_full[idx_t] * val;

                            if count_circle > 0.0 && circle_mask[idx_t] {
                                sum_w_c += val;
                                sum_w2_c += val * val;
                                sum_tw_c += dt_circle[idx_t] * val;
                            }
                        }
                    }

                    // Full box ZNCC
                    let mean_w = sum_w / count_full;
                    let ss_w_full = (sum_w2 - count_full * mean_w * mean_w).max(0.0);
                    if ss_w_full > 0.0 && denom_t_full > 0.0 {
                        let zncc_full = sum_tw / (denom_t_full * ss_w_full.sqrt());
                        if zncc_full > best_strength {
                            best_strength = zncc_full;
                        }
                    }

                    // Circle mask ZNCC
                    if count_circle > 0.0 && ss_t_c > 0.0 && denom_t_circle > 0.0 {
                        let mean_w_c = sum_w_c / count_circle;
                        let ss_w_c = (sum_w2_c - count_circle * mean_w_c * mean_w_c).max(0.0);
                        if ss_w_c > 0.0 {
                            let zncc_circle = sum_tw_c / (denom_t_circle * ss_w_c.sqrt());
                            if zncc_circle > best_strength {
                                best_strength = zncc_circle;
                            }
                        }
                    }

                    x += stride;
                }
                y += stride;
            }
        }
    }

    let clamped_strength = best_strength.clamp(0.0, 1.0);

    let verdict = if clamped_strength >= 0.90 {
        Verdict::SamePhoto
    } else if clamped_strength >= 0.85 {
        Verdict::PossibleMatch
    } else {
        Verdict::NoMatch
    };

    PhotoMatchResult {
        verdict,
        strength: (clamped_strength * 1000.0).round() / 1000.0,
        method: MatchMethod::CropMatch,
    }
}
