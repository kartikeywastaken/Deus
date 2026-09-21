use crate::db::models::{ProfileObservationRecord, ProfileRecord};
use scraper::{Html, Selector};
use std::collections::HashMap;

#[derive(Clone, Debug)]
pub struct CandidateAvatarSpec {
    pub profile_id: String,
    pub platform: String,
    pub username: String,
    pub profile_url: String,
    pub avatar_url: Option<String>,
}

pub fn extract_candidate_avatar_specs(
    profiles: &[ProfileRecord],
    observations: &[ProfileObservationRecord],
) -> Vec<CandidateAvatarSpec> {
    // Group observations by profile_id
    let mut obs_by_profile: HashMap<uuid::Uuid, Vec<&ProfileObservationRecord>> = HashMap::new();
    for obs in observations {
        obs_by_profile.entry(obs.profile_id).or_default().push(obs);
    }

    let mut specs = Vec::new();

    for p in profiles {
        let profile_id_str = p.id.to_string();
        let username_str = p
            .username
            .clone()
            .or_else(|| p.normalized_username.clone())
            .unwrap_or_else(|| "unknown".to_string());

        let mut avatar_url = p.avatar_url.clone().filter(|s| !s.trim().is_empty());

        if avatar_url.is_none() {
            if let Some(obs_list) = obs_by_profile.get(&p.id) {
                for obs in obs_list {
                    if let Some(url) = obs.raw_data.get("avatar_url").and_then(|v| v.as_str()) {
                        if !url.trim().is_empty() {
                            avatar_url = Some(url.to_string());
                            break;
                        }
                    }
                    if let Some(url) = obs
                        .raw_data
                        .get("enrichment")
                        .and_then(|e| e.get("avatar_url"))
                        .and_then(|v| v.as_str())
                    {
                        if !url.trim().is_empty() {
                            avatar_url = Some(url.to_string());
                            break;
                        }
                    }
                    if let Some(url) = obs.normalized_data.get("avatar_url").and_then(|v| v.as_str()) {
                        if !url.trim().is_empty() {
                            avatar_url = Some(url.to_string());
                            break;
                        }
                    }
                }
            }
        }

        specs.push(CandidateAvatarSpec {
            profile_id: profile_id_str,
            platform: p.platform.clone(),
            username: username_str,
            profile_url: p.canonical_url.clone(),
            avatar_url,
        });

        if specs.len() >= 64 {
            break;
        }
    }

    specs
}

pub fn extract_og_image_from_html(html_str: &str) -> Option<String> {
    let document = Html::parse_document(html_str);
    if let Ok(og_img_sel) = Selector::parse("meta[property='og:image']") {
        if let Some(meta) = document.select(&og_img_sel).next() {
            if let Some(content) = meta.value().attr("content") {
                let trimmed = content.trim();
                if !trimmed.is_empty() {
                    return Some(trimmed.to_string());
                }
            }
        }
    }
    if let Ok(tw_img_sel) = Selector::parse("meta[name='twitter:image']") {
        if let Some(meta) = document.select(&tw_img_sel).next() {
            if let Some(content) = meta.value().attr("content") {
                let trimmed = content.trim();
                if !trimmed.is_empty() {
                    return Some(trimmed.to_string());
                }
            }
        }
    }
    None
}
