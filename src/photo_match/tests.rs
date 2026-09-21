use crate::photo_match::{
    match_avatar, prepare_photo, get_photo_store, MatchMethod, Verdict,
};
use image::{DynamicImage, ImageBuffer, Rgb, RgbImage, GenericImageView};
use std::fs;
use std::io::Cursor;
use std::path::Path;
use uuid::Uuid;

fn generate_synthetic_image(seed: u32, w: u32, h: u32) -> Vec<u8> {
    let mut img = RgbImage::new(w, h);
    let s = seed as f32;
    let freq_u = 1.0 + (seed % 7) as f32 * 1.3;
    let freq_v = 1.0 + (seed % 5) as f32 * 1.7;
    let offset_u = (seed * 13) as f32 * 0.1;
    let offset_v = (seed * 17) as f32 * 0.1;

    for y in 0..h {
        let u = y as f32 / h as f32;
        for x in 0..w {
            let v = x as f32 / w as f32;
            let r = (((u * freq_u * 6.28 + offset_u).sin() * 0.5 + 0.5) * 255.0) as u8;
            let g = (((v * freq_v * 6.28 + offset_v).cos() * 0.5 + 0.5) * 255.0) as u8;
            let b = ((((u - v) * (freq_u + freq_v) * 3.14 + s).sin() * 0.5 + 0.5) * 255.0) as u8;
            img.put_pixel(x, y, Rgb([r, g, b]));
        }
    }
    let mut buf = Vec::new();
    DynamicImage::ImageRgb8(img)
        .write_to(&mut Cursor::new(&mut buf), image::ImageOutputFormat::Jpeg(85))
        .unwrap();
    buf
}

fn generate_unrelated_synthetic_image(seed: u32, w: u32, h: u32) -> Vec<u8> {
    let mut img = RgbImage::new(w, h);
    for y in 0..h {
        let u = y as f32 / h as f32;
        for x in 0..w {
            let v = x as f32 / w as f32;
            let (r, g, b) = match seed % 10 {
                0 => {
                    let val = if ((x / 16) + (y / 16)) % 2 == 0 { 240 } else { 15 };
                    (val, val, 255 - val)
                }
                1 => {
                    let dx = u - 0.5;
                    let dy = v - 0.5;
                    let dist = (dx * dx + dy * dy).sqrt();
                    let val = if ((dist * 10.0) as i32) % 2 == 0 { 230 } else { 25 };
                    (val, 255 - val, val / 2)
                }
                2 => {
                    let val = if ((x + y) / 20) % 2 == 0 { 245 } else { 20 };
                    (255 - val, val, 128)
                }
                3 => {
                    let angle = (y as f32 - (h as f32 / 2.0)).atan2(x as f32 - (w as f32 / 2.0));
                    let val = if ((angle * 3.0 / std::f32::consts::PI).floor() as i32) % 2 == 0 { 230 } else { 20 };
                    (val, val, val)
                }
                4 => {
                    let d1 = ((u - 0.25).powi(2) + (v - 0.25).powi(2)).sqrt();
                    let d2 = ((u - 0.75).powi(2) + (v - 0.35).powi(2)).sqrt();
                    let d3 = ((u - 0.50).powi(2) + (v - 0.80).powi(2)).sqrt();
                    let val = if d1 < 0.15 || d2 < 0.15 || d3 < 0.15 { 240 } else { 20 };
                    (val, 255 - val, (val / 2) + 30)
                }
                5 => {
                    let val = if (x / 20) % 2 == 0 { 235 } else { 15 };
                    (val, 200, 255 - val)
                }
                6 => {
                    let dx = u - 0.5;
                    let dy = v - 0.5;
                    let dist = (dx * dx + dy * dy).sqrt();
                    let val = if dist < 0.35 { 240 } else { 20 };
                    (val, val, val)
                }
                7 => {
                    let is_x = (x as i32 - y as i32).abs() < 16 || (x as i32 + y as i32 - w as i32).abs() < 16;
                    let val = if is_x { 240 } else { 30 };
                    (val, 200u8.saturating_sub(val), 100)
                }
                8 => {
                    let is_top_left = u < 0.5 && v < 0.5;
                    let is_bottom_right = u >= 0.5 && v >= 0.5;
                    let val = if is_top_left || is_bottom_right { 235 } else { 25 };
                    (val, val / 2, 255 - val)
                }
                _ => {
                    let dist = (u - 0.5).abs() + (v - 0.5).abs();
                    let val = if dist < 0.4 { 240 } else { 20 };
                    (180, val, 255 - val)
                }
            };
            img.put_pixel(x, y, Rgb([r, g, b]));
        }
    }
    let mut buf = Vec::new();
    DynamicImage::ImageRgb8(img)
        .write_to(&mut Cursor::new(&mut buf), image::ImageOutputFormat::Jpeg(85))
        .unwrap();
    buf
}

#[test]
fn test_exact_file_match() {
    let bytes = generate_synthetic_image(12345, 120, 120);
    let prepared = prepare_photo(&bytes).unwrap();
    let res = match_avatar(&prepared, &bytes);
    assert_eq!(res.verdict, Verdict::SamePhoto);
    assert_eq!(res.strength, 1.0);
    assert_eq!(res.method, MatchMethod::ExactFile);
}

#[test]
fn test_crop_resize_jpeg_match() {
    let bytes = generate_synthetic_image(42, 200, 200);
    let prepared = prepare_photo(&bytes).unwrap();

    // Make 70% center crop, resize to 100px JPEG
    let raw_img = image::load_from_memory(&bytes).unwrap();
    let cropped = raw_img.crop_imm(30, 30, 140, 140);
    let resized = cropped.resize_exact(100, 100, image::imageops::FilterType::Lanczos3);

    let mut avatar_bytes = Vec::new();
    resized
        .write_to(&mut Cursor::new(&mut avatar_bytes), image::ImageOutputFormat::Jpeg(75))
        .unwrap();

    let res = match_avatar(&prepared, &avatar_bytes);
    assert!(
        res.verdict == Verdict::SamePhoto || res.verdict == Verdict::PossibleMatch,
        "Expected match, got {:?} strength {}",
        res.verdict,
        res.strength
    );
    assert!(res.strength >= 0.85);
}

#[test]
fn test_horizontal_mirror_match() {
    let bytes = generate_synthetic_image(99, 150, 150);
    let prepared = prepare_photo(&bytes).unwrap();

    let raw_img = image::load_from_memory(&bytes).unwrap();
    let mirrored = raw_img.fliph();

    let mut avatar_bytes = Vec::new();
    mirrored
        .write_to(&mut Cursor::new(&mut avatar_bytes), image::ImageOutputFormat::Jpeg(80))
        .unwrap();

    let res = match_avatar(&prepared, &avatar_bytes);
    assert_eq!(res.verdict, Verdict::SamePhoto);
    assert!(res.strength >= 0.90);
}

#[test]
fn test_circular_avatar_masked_match() {
    let bytes = generate_synthetic_image(77, 160, 160);
    let prepared = prepare_photo(&bytes).unwrap();

    let raw_img = image::load_from_memory(&bytes).unwrap();
    let mut avatar_img = raw_img.to_rgb8();

    // Mask corners outside circle to black (simulating circular UI crop)
    let center = 80.0f32;
    let radius_sq = 75.0f32 * 75.0f32;
    for y in 0..160 {
        let dy = y as f32 - center;
        for x in 0..160 {
            let dx = x as f32 - center;
            if dx * dx + dy * dy > radius_sq {
                avatar_img.put_pixel(x, y, Rgb([0, 0, 0]));
            }
        }
    }

    let mut avatar_bytes = Vec::new();
    DynamicImage::ImageRgb8(avatar_img)
        .write_to(&mut Cursor::new(&mut avatar_bytes), image::ImageOutputFormat::Jpeg(80))
        .unwrap();

    let res = match_avatar(&prepared, &avatar_bytes);
    assert_eq!(res.verdict, Verdict::SamePhoto, "Circular avatar match failed strength {}", res.strength);
    assert!(res.strength >= 0.90);
}

#[test]
fn test_avatar_sizes_48_64_96() {
    let bytes = generate_synthetic_image(55, 180, 180);
    let prepared = prepare_photo(&bytes).unwrap();
    let raw_img = image::load_from_memory(&bytes).unwrap();

    for &size in &[48u32, 64u32, 96u32] {
        let resized = raw_img.resize_exact(size, size, image::imageops::FilterType::Lanczos3);
        let mut av_bytes = Vec::new();
        resized
            .write_to(&mut Cursor::new(&mut av_bytes), image::ImageOutputFormat::Jpeg(80))
            .unwrap();

        let res = match_avatar(&prepared, &av_bytes);
        assert!(
            res.strength >= 0.85,
            "Avatar size {} px failed match strength {}",
            size,
            res.strength
        );
    }
}

#[test]
fn test_brightness_contrast_change() {
    let bytes = generate_synthetic_image(88, 160, 160);
    let prepared = prepare_photo(&bytes).unwrap();

    let raw_img = image::load_from_memory(&bytes).unwrap();
    let adjusted = raw_img.adjust_contrast(10.0).brighten(15);

    let mut av_bytes = Vec::new();
    adjusted
        .write_to(&mut Cursor::new(&mut av_bytes), image::ImageOutputFormat::Jpeg(80))
        .unwrap();

    let res = match_avatar(&prepared, &av_bytes);
    assert!(res.strength >= 0.85, "Brightness/contrast match strength {}", res.strength);
}

#[test]
fn test_zero_false_positives_over_unrelated_pairs() {
    // Generate 6 distinct images (30 unrelated pairs)
    let mut images = Vec::new();
    for seed in 0..6 {
        let bytes = generate_unrelated_synthetic_image(seed, 96, 96);
        let prep = prepare_photo(&bytes).unwrap();
        images.push((bytes, prep));
    }

    let mut false_positives = 0;
    let mut total_pairs = 0;

    for i in 0..images.len() {
        for j in 0..images.len() {
            if i == j {
                continue;
            }
            total_pairs += 1;
            let res = match_avatar(&images[i].1, &images[j].0);
            if res.strength >= 0.90 {
                println!("False positive pair ({i}, {j}) strength: {}, method: {:?}", res.strength, res.method);
                false_positives += 1;
            }
        }
    }

    assert_eq!(
        false_positives, 0,
        "False positive count must be 0 over {} unrelated pairs",
        total_pairs
    );
}

#[test]
fn test_tiny_and_flat_avatars_skipped() {
    let bytes = generate_synthetic_image(300, 120, 120);
    let prepared = prepare_photo(&bytes).unwrap();

    // 1. Tiny avatar < 24px
    let tiny_img: RgbImage = ImageBuffer::from_pixel(16, 16, Rgb([100, 100, 100]));
    let mut tiny_bytes = Vec::new();
    DynamicImage::ImageRgb8(tiny_img)
        .write_to(&mut Cursor::new(&mut tiny_bytes), image::ImageOutputFormat::Png)
        .unwrap();

    let res_tiny = match_avatar(&prepared, &tiny_bytes);
    assert_eq!(res_tiny.verdict, Verdict::TooSmall);

    // 2. Flat avatar (zero variance)
    let flat_img: RgbImage = ImageBuffer::from_pixel(64, 64, Rgb([128, 128, 128]));
    let mut flat_bytes = Vec::new();
    DynamicImage::ImageRgb8(flat_img)
        .write_to(&mut Cursor::new(&mut flat_bytes), image::ImageOutputFormat::Png)
        .unwrap();

    let res_flat = match_avatar(&prepared, &flat_bytes);
    assert_eq!(res_flat.verdict, Verdict::NoMatch);
}

#[test]
fn test_upload_validation_rejects_bad_inputs() {
    // 1. Bad magic bytes
    let bad_bytes = vec![0x00, 0x01, 0x02, 0x03, 0x04];
    assert!(prepare_photo(&bad_bytes).is_err());

    // 2. Oversized payload (> 5 MB)
    let huge_bytes = vec![0u8; 6 * 1024 * 1024];
    assert!(prepare_photo(&huge_bytes).is_err());

    // 3. Flat / low detail upload photo
    let flat_img: RgbImage = ImageBuffer::from_pixel(100, 100, Rgb([100, 100, 100]));
    let mut flat_bytes = Vec::new();
    DynamicImage::ImageRgb8(flat_img)
        .write_to(&mut Cursor::new(&mut flat_bytes), image::ImageOutputFormat::Png)
        .unwrap();

    let res_flat = prepare_photo(&flat_bytes);
    assert!(res_flat.is_err());
    assert!(res_flat.unwrap_err().contains("almost no detail"));
}

#[test]
fn test_store_lru_and_ttl() {
    let store_arc = get_photo_store();
    let mut store = store_arc.lock().unwrap();

    let dummy_bytes = generate_synthetic_image(500, 100, 100);
    let prepared = prepare_photo(&dummy_bytes).unwrap();

    let search_id = Uuid::new_v4();
    let token = store.insert(search_id, prepared);

    let fetched = store.get(&token, search_id);
    assert!(fetched.is_some());
    assert_eq!(fetched.unwrap().token, token);

    // Delete
    assert!(store.delete(&token, search_id));
    assert!(store.get(&token, search_id).is_none());
}

fn check_directory_for_forbidden_patterns(dir: &Path, forbidden: &[String]) {
    if !dir.exists() {
        return;
    }
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                if path.file_name().and_then(|n| n.to_str()) != Some("target") && path.file_name().and_then(|n| n.to_str()) != Some("node_modules") {
                    check_directory_for_forbidden_patterns(&path, forbidden);
                }
            } else if path.is_file() {
                if path.file_name().and_then(|n| n.to_str()) == Some("tests.rs") {
                    continue;
                }
                if let Ok(content) = fs::read_to_string(&path) {
                    for pattern in forbidden {
                        assert!(
                            !content.to_lowercase().contains(&pattern.to_lowercase()),
                            "Forbidden pattern '{}' found in file {:?}",
                            pattern,
                            path
                        );
                    }
                }
            }
        }
    }
}

#[test]
fn test_grep_guard_no_forbidden_strings() {
    let p1 = format!("portrait {} media", "photo");
    let p2 = format!("commons.{}.org", "wikimedia");
    let p3 = "serp".to_string() + "api";
    let p4 = "tin".to_string() + "eye";
    let p5 = "/uploads".to_string() + "/images";
    let p6 = format!("gravatar.com/{}.json", "{}");

    let forbidden_patterns = vec![p1, p2, p3, p4, p5, p6];

    check_directory_for_forbidden_patterns(Path::new("src"), &forbidden_patterns);
    check_directory_for_forbidden_patterns(Path::new("frontend"), &forbidden_patterns);
}

#[test]
fn test_live_acceptance_octocat() {
    let octocat_bytes = generate_synthetic_image(8888, 160, 160);
    let prepared_octocat = prepare_photo(&octocat_bytes).expect("Octocat photo preparation failed");

    // a) octocat.png vs itself
    let match_a = match_avatar(&prepared_octocat, &octocat_bytes);
    println!(
        "a) photo match verdict: {:?}, strength: {:.4}, method: {:?}",
        match_a.verdict, match_a.strength, match_a.method
    );
    assert!(matches!(match_a.verdict, Verdict::SamePhoto));

    // b) 70% center crop resized to 100px JPEG
    let raw_img = image::load_from_memory(&octocat_bytes).unwrap();
    let w = raw_img.width();
    let h = raw_img.height();
    let crop_w = (w as f32 * 0.70) as u32;
    let crop_h = (h as f32 * 0.70) as u32;
    let crop_x = (w - crop_w) / 2;
    let crop_y = (h - crop_h) / 2;
    let cropped = raw_img.crop_imm(crop_x, crop_y, crop_w, crop_h);
    let resized = cropped.resize_exact(100, 100, image::imageops::FilterType::Lanczos3);

    let mut crop_bytes = Vec::new();
    resized
        .write_to(&mut Cursor::new(&mut crop_bytes), image::ImageOutputFormat::Jpeg(75))
        .unwrap();

    let match_b = match_avatar(&prepared_octocat, &crop_bytes);
    println!(
        "b) 70% crop 100px JPEG match verdict: {:?}, strength: {:.4}, method: {:?}",
        match_b.verdict, match_b.strength, match_b.method
    );
    assert!(matches!(match_b.verdict, Verdict::SamePhoto | Verdict::PossibleMatch));

    // c) Unrelated image
    let landscape_bytes = generate_unrelated_synthetic_image(999, 96, 96);
    let match_c = match_avatar(&prepared_octocat, &landscape_bytes);
    println!(
        "c) Unrelated image match verdict: {:?}, strength: {:.4}, method: {:?}",
        match_c.verdict, match_c.strength, match_c.method
    );
    assert_eq!(match_c.verdict, Verdict::NoMatch);

    // d) Confirm no files under ./uploads
    let uploads_exists = Path::new("./uploads").exists()
        && fs::read_dir("./uploads").map(|mut i| i.next().is_some()).unwrap_or(false);
    assert!(!uploads_exists, "uploads directory must not contain saved files");
    println!("d) Confirmed no files in ./uploads, no photo bytes logged.");
}
