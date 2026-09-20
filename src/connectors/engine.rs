use crate::connectors::{ConnectorOutput, ConnectorStatus, DiscoveredProfile};
use futures::stream::{self, StreamExt};
use rand::Rng;
use regex::Regex;
use scraper::{Html, Selector};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;
use tracing::{info, warn};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum DetectionType {
    StatusCode,
    MessageInBody,
    Redirect,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SiteRule {
    pub name: String,
    pub category: String,
    pub uri_check: String,
    pub uri_pretty: Option<String>,
    pub valid_username_regex: Option<String>,
    pub detection_type: DetectionType,
    pub expected_status_codes: Vec<u16>,
    pub error_messages: Vec<String>,
    pub success_messages: Vec<String>,
    pub nsfw: bool,
}

#[derive(Debug, Clone)]
pub struct ExtractedMetadata {
    pub display_name: Option<String>,
    pub avatar_url: Option<String>,
    pub bio: Option<String>,
    pub location: Option<String>,
    pub organization: Option<String>,
}

pub struct SiteEngine {
    source_name: &'static str,
    rules: Vec<SiteRule>,
    load_error: Option<String>,
}

impl SiteEngine {
    pub fn load_from_dataset(source_name: &'static str, filename: &str) -> Self {
        let data_dir = env::var("SITES_DATA_DIR").unwrap_or_else(|_| "data/sites".to_string());
        let path = PathBuf::from(&data_dir).join(filename);

        match Self::read_rules_from_file(&path) {
            Ok(rules) => {
                info!("Loaded {} site rules for {}", rules.len(), source_name);
                Self {
                    source_name,
                    rules,
                    load_error: None,
                }
            }
            Err(e) => {
                warn!("Failed to load site rules for {} at {:?}: {}", source_name, path, e);
                Self {
                    source_name,
                    rules: vec![],
                    load_error: Some(format!("Failed to load dataset at {:?}: {}", path, e)),
                }
            }
        }
    }

    pub fn new_with_rules(source_name: &'static str, rules: Vec<SiteRule>) -> Self {
        Self {
            source_name,
            rules,
            load_error: None,
        }
    }

    fn read_rules_from_file(path: &Path) -> Result<Vec<SiteRule>, Box<dyn std::error::Error + Send + Sync>> {
        let content = fs::read_to_string(path)?;
        let json_val: serde_json::Value = serde_json::from_str(&content)?;

        let mut rules = Vec::new();

        if let Some(sites_array) = json_val.get("sites").and_then(|v| v.as_array()) {
            // Adler sites_wmn.json format
            for item in sites_array {
                if let Some(rule) = Self::parse_adler_site(item) {
                    rules.push(rule);
                }
            }
        } else if let Some(map) = json_val.as_object() {
            // Raven data.json (Sherlock format)
            for (key, item) in map {
                if key.starts_with('_') || key == "$schema" {
                    continue;
                }
                if let Some(rule) = Self::parse_sherlock_site(key, item) {
                    rules.push(rule);
                }
            }
        }

        if rules.is_empty() {
            return Err("No valid site rules found in file".into());
        }

        Ok(rules)
    }

    fn parse_sherlock_site(name: &str, item: &serde_json::Value) -> Option<SiteRule> {
        let url = item.get("url")?.as_str()?;
        let error_type_str = item.get("errorType").and_then(|v| v.as_str()).unwrap_or("status_code");

        let detection_type = match error_type_str {
            "message" => DetectionType::MessageInBody,
            "response_url" => DetectionType::Redirect,
            _ => DetectionType::StatusCode,
        };

        let mut error_messages = Vec::new();
        if let Some(err_msg) = item.get("errorMsg") {
            if let Some(s) = err_msg.as_str() {
                error_messages.push(s.to_string());
            } else if let Some(arr) = err_msg.as_array() {
                for elem in arr {
                    if let Some(s) = elem.as_str() {
                        error_messages.push(s.to_string());
                    }
                }
            }
        }

        let regex_check = item.get("regexCheck").and_then(|v| v.as_str()).map(String::from);
        let nsfw = item.get("isNSFW").and_then(|v| v.as_bool()).unwrap_or(false);

        Some(SiteRule {
            name: name.to_string(),
            category: "social".to_string(),
            uri_check: url.to_string(),
            uri_pretty: item.get("urlMain").and_then(|v| v.as_str()).map(String::from),
            valid_username_regex: regex_check,
            detection_type,
            expected_status_codes: vec![200],
            error_messages,
            success_messages: vec![],
            nsfw,
        })
    }

    fn parse_adler_site(item: &serde_json::Value) -> Option<SiteRule> {
        let name = item.get("name")?.as_str()?;
        let url = item.get("url")?.as_str()?;

        let mut error_messages = Vec::new();
        let mut success_messages = Vec::new();
        let mut expected_codes = vec![200];
        let mut detection_type = DetectionType::StatusCode;

        if let Some(signals) = item.get("signals").and_then(|v| v.as_array()) {
            for sig in signals {
                let kind = sig.get("kind").and_then(|v| v.as_str()).unwrap_or("");
                match kind {
                    "body_present" => {
                        if let Some(text) = sig.get("text").and_then(|v| v.as_str()) {
                            success_messages.push(text.to_string());
                            detection_type = DetectionType::MessageInBody;
                        }
                    }
                    "body_absent" => {
                        if let Some(text) = sig.get("text").and_then(|v| v.as_str()) {
                            error_messages.push(text.to_string());
                            detection_type = DetectionType::MessageInBody;
                        }
                    }
                    "status_found" => {
                        if let Some(codes) = sig.get("codes").and_then(|v| v.as_array()) {
                            expected_codes = codes.iter().filter_map(|c| c.as_u64().map(|n| n as u16)).collect();
                        }
                    }
                    _ => {}
                }
            }
        }

        let regex_check = item.get("regex_check").and_then(|v| v.as_str()).map(String::from);

        Some(SiteRule {
            name: name.to_string(),
            category: "social".to_string(),
            uri_check: url.to_string(),
            uri_pretty: None,
            valid_username_regex: regex_check,
            detection_type,
            expected_status_codes: expected_codes,
            error_messages,
            success_messages,
            nsfw: false,
        })
    }

    pub async fn run_search(&self, username: &str) -> ConnectorOutput {
        if let Some(ref err) = self.load_error {
            return ConnectorOutput::unavailable(err.clone());
        }

        if self.rules.is_empty() {
            return ConnectorOutput::unavailable(format!("No site rules configured for {}", self.source_name));
        }

        let concurrency: usize = env::var("CONNECTOR_CONCURRENCY")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(35);

        let timeout_secs: u64 = env::var("CONNECTOR_TIMEOUT_SECONDS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(5);

        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(timeout_secs))
            .redirect(reqwest::redirect::Policy::limited(5))
            .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            .build()
            .unwrap_or_default();

        let source_name = self.source_name;
        let rules_ref = Arc::new(self.rules.clone());
        let client_ref = Arc::new(client);
        let target_username = username.to_string();

        let futures = stream::iter(rules_ref.as_ref().clone()).map(move |rule| {
            let client = Arc::clone(&client_ref);
            let username = target_username.clone();
            async move {
                Self::evaluate_rule_for_user(&client, &rule, &username, source_name).await
            }
        });

        let results: Vec<SiteCheckResult> = futures.buffer_unordered(concurrency).collect().await;

        let mut profiles = Vec::new();
        let mut sites_checked = 0;
        let mut sites_errored = 0;
        let mut sites_rate_limited = 0;

        for res in results {
            match res {
                SiteCheckResult::Found(prof) => {
                    sites_checked += 1;
                    profiles.push(prof);
                }
                SiteCheckResult::NotFound => {
                    sites_checked += 1;
                }
                SiteCheckResult::Skipped => {}
                SiteCheckResult::Errored => {
                    sites_checked += 1;
                    sites_errored += 1;
                }
                SiteCheckResult::RateLimited => {
                    sites_checked += 1;
                    sites_rate_limited += 1;
                }
            }
        }

        let status = if sites_checked == 0 {
            ConnectorStatus::NoResults
        } else if sites_rate_limited > sites_checked / 2 {
            ConnectorStatus::RateLimited
        } else if sites_errored > sites_checked / 2 {
            ConnectorStatus::Partial
        } else if !profiles.is_empty() {
            ConnectorStatus::Success
        } else {
            ConnectorStatus::NoResults
        };

        ConnectorOutput {
            profiles,
            status,
            error: None,
            sites_checked,
            sites_errored,
            sites_rate_limited,
        }
    }

    async fn evaluate_rule_for_user(
        client: &reqwest::Client,
        rule: &SiteRule,
        username: &str,
        source_name: &'static str,
    ) -> SiteCheckResult {
        // Step 1: Username regex validation
        if let Some(ref reg_str) = rule.valid_username_regex {
            if let Ok(reg) = Regex::new(reg_str) {
                if !reg.is_match(username) {
                    return SiteCheckResult::Skipped;
                }
            }
        }

        let target_url = rule.uri_check.replace("{}", username).replace("{username}", username);

        // Step 2: Target request
        let target_res = Self::send_http_request(client, &target_url).await;
        match target_res {
            Ok((status_code, body, final_url)) => {
                if status_code == 429 {
                    return SiteCheckResult::RateLimited;
                }
                if Self::eval_site_hit(rule, status_code, &body) {
                    // Target hit! Now run false-positive baseline verification
                    let random_user = format!("rnd_{}", generate_random_alphanumeric(20));
                    let baseline_url = rule.uri_check.replace("{}", &random_user).replace("{username}", &random_user);

                    if let Ok((b_status, ref b_body, _)) = Self::send_http_request(client, &baseline_url).await {
                        if Self::eval_site_hit(rule, b_status, b_body) {
                            // Baseline also returned positive for random non-existent user -> false positive site!
                            return SiteCheckResult::NotFound;
                        }
                    }

                    let meta = Self::extract_html_metadata(&body);
                    let display_name = meta.display_name.filter(|d| d != username && !d.is_empty());

                    let prof = DiscoveredProfile {
                        platform: rule.name.clone(),
                        username: username.to_string(),
                        canonical_url: final_url.unwrap_or(target_url),
                        display_name,
                        avatar_url: meta.avatar_url,
                        bio: meta.bio,
                        location: meta.location,
                        organization: meta.organization,
                        raw_json: json!({
                            "source": source_name,
                            "site_name": rule.name,
                            "category": rule.category,
                            "http_status": status_code,
                            "detection_method": format!("{:?}", rule.detection_type),
                            "verified": true,
                        }),
                    };
                    SiteCheckResult::Found(prof)
                } else {
                    SiteCheckResult::NotFound
                }
            }
            Err(_) => SiteCheckResult::Errored,
        }
    }

    async fn send_http_request(
        client: &reqwest::Client,
        url: &str,
    ) -> Result<(u16, String, Option<String>), reqwest::Error> {
        let res = client.get(url).send().await?;
        let status = res.status().as_u16();
        let final_url = res.url().to_string();
        let body = res.text().await.unwrap_or_default();
        Ok((status, body, Some(final_url)))
    }

    pub fn eval_site_hit(rule: &SiteRule, status_code: u16, body: &str) -> bool {
        match rule.detection_type {
            DetectionType::StatusCode => rule.expected_status_codes.contains(&status_code),
            DetectionType::MessageInBody => {
                if status_code != 200 {
                    return false;
                }
                for err_msg in &rule.error_messages {
                    if body.contains(err_msg) {
                        return false;
                    }
                }
                if !rule.success_messages.is_empty() {
                    return rule.success_messages.iter().any(|msg| body.contains(msg));
                }
                true
            }
            DetectionType::Redirect => status_code == 200 || status_code == 302,
        }
    }

    pub fn extract_html_metadata(body: &str) -> ExtractedMetadata {
        let document = Html::parse_document(body);

        let og_title_sel = Selector::parse("meta[property='og:title']").ok();
        let tw_title_sel = Selector::parse("meta[name='twitter:title']").ok();
        let title_tag_sel = Selector::parse("title").ok();

        let og_img_sel = Selector::parse("meta[property='og:image']").ok();
        let tw_img_sel = Selector::parse("meta[name='twitter:image']").ok();

        let og_desc_sel = Selector::parse("meta[property='og:description']").ok();
        let meta_desc_sel = Selector::parse("meta[name='description']").ok();
        let tw_desc_sel = Selector::parse("meta[name='twitter:description']").ok();

        let display_name = extract_meta_content(&document, og_title_sel.as_ref())
            .or_else(|| extract_meta_content(&document, tw_title_sel.as_ref()))
            .or_else(|| extract_text(&document, title_tag_sel.as_ref()));

        let avatar_url = extract_meta_content(&document, og_img_sel.as_ref())
            .or_else(|| extract_meta_content(&document, tw_img_sel.as_ref()));

        let bio = extract_meta_content(&document, og_desc_sel.as_ref())
            .or_else(|| extract_meta_content(&document, meta_desc_sel.as_ref()))
            .or_else(|| extract_meta_content(&document, tw_desc_sel.as_ref()));

        ExtractedMetadata {
            display_name,
            avatar_url,
            bio,
            location: None,
            organization: None,
        }
    }
}

enum SiteCheckResult {
    Found(DiscoveredProfile),
    NotFound,
    Skipped,
    Errored,
    RateLimited,
}

fn extract_meta_content(doc: &Html, selector: Option<&Selector>) -> Option<String> {
    let sel = selector?;
    let element = doc.select(sel).next()?;
    let content = element.value().attr("content")?;
    let trimmed = content.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn extract_text(doc: &Html, selector: Option<&Selector>) -> Option<String> {
    let sel = selector?;
    let element = doc.select(sel).next()?;
    let text: String = element.text().collect();
    let trimmed = text.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn generate_random_alphanumeric(len: usize) -> String {
    let mut rng = rand::thread_rng();
    (0..len)
        .map(|_| {
            let idx = rng.gen_range(0..36);
            if idx < 10 {
                (b'0' + idx) as char
            } else {
                (b'a' + (idx - 10)) as char
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detection_rules_status_code() {
        let rule = SiteRule {
            name: "test".into(),
            category: "social".into(),
            uri_check: "https://example.com/{}".into(),
            uri_pretty: None,
            valid_username_regex: None,
            detection_type: DetectionType::StatusCode,
            expected_status_codes: vec![200],
            error_messages: vec![],
            success_messages: vec![],
            nsfw: false,
        };

        assert!(SiteEngine::eval_site_hit(&rule, 200, ""));
        assert!(!SiteEngine::eval_site_hit(&rule, 404, ""));
    }

    #[test]
    fn test_detection_rules_message_in_body() {
        let rule = SiteRule {
            name: "test".into(),
            category: "social".into(),
            uri_check: "https://example.com/{}".into(),
            uri_pretty: None,
            valid_username_regex: None,
            detection_type: DetectionType::MessageInBody,
            expected_status_codes: vec![200],
            error_messages: vec!["Page Not Found".into()],
            success_messages: vec!["User Profile".into()],
            nsfw: false,
        };

        assert!(SiteEngine::eval_site_hit(&rule, 200, "<html>User Profile</html>"));
        assert!(!SiteEngine::eval_site_hit(&rule, 200, "<html>Page Not Found</html>"));
        assert!(!SiteEngine::eval_site_hit(&rule, 404, "<html>User Profile</html>"));
    }

    #[test]
    fn test_username_regex_skipping() {
        let regex_str = "^[A-Za-z0-9]{4,10}$";
        let reg = Regex::new(regex_str).unwrap();

        assert!(reg.is_match("validUser"));
        assert!(!reg.is_match("usr")); // too short
        assert!(!reg.is_match("invalid_user_name_too_long")); // too long / contains underscores
    }
}
