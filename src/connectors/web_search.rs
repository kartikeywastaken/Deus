/*
 * Free-Text Web & Name Search Connector
 *
 * SOURCING & REASONING MODEL:
 * ---------------------------
 * - Endpoints:
 *   1. DuckDuckGo Instant Answer API (https://api.duckduckgo.com/?q=...&format=json)
 *   2. GitHub Name Search API (https://api.github.com/search/users?q=...)
 *   3. DuckDuckGo HTML Endpoint (https://html.duckduckgo.com/html/?q=...)
 * - Auth required: None (Free public endpoints; optional GITHUB_TOKEN increases rate limit).
 *
 * TRADE-OFFS & LIMITATIONS:
 * -------------------------
 * 1. Web Search Index vs Proprietary Search APIs: Uses free non-commercial APIs and HTML endpoints.
 * 2. Rate Limits & Fragility: DDG HTML endpoint may block raw scrapers; Instant Answer API & GitHub Search
 *    provide structured JSON fallbacks that never break on HTML layout changes.
 * 3. Evidence Weight: Name search mentions are corroborating signals (`SignalType::NameSearchMention`),
 *    weighted lower than exact identifier matches to prevent false positive identity merges.
 */

use crate::connectors::{ConnectorHealth, ConnectorOutput, DiscoveredProfile, OsintConnector};
use async_trait::async_trait;
use reqwest::Client;
use scraper::{Html, Selector};
use serde_json::json;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;
use tracing::info;
use url::Url;

const DEFAULT_TARGET_SITES: &[&str] = &[
    "linkedin.com",
    "github.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
];

struct CacheEntry {
    output: ConnectorOutput,
    cached_at: Instant,
}

pub struct WebSearchConnector {
    client: Client,
    cache: Arc<Mutex<HashMap<String, CacheEntry>>>,
    ttl: Duration,
}

impl WebSearchConnector {
    pub fn new() -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(10))
            .user_agent("Deus/1.0 (OSINT Engine; +https://github.com/kartikeywastaken/Deus)")
            .build()
            .unwrap_or_else(|_| Client::new());

        Self {
            client,
            cache: Arc::new(Mutex::new(HashMap::new())),
            ttl: Duration::from_secs(300),
        }
    }

    async fn fetch_ddg_instant_answer(&self, name_query: &str) -> Vec<DiscoveredProfile> {
        let mut profiles = Vec::new();
        let encoded_q: String = url::form_urlencoded::byte_serialize(name_query.as_bytes()).collect();
        let url = format!("https://api.duckduckgo.com/?q={}&format=json", encoded_q);

        if let Ok(resp) = self.client.get(&url).send().await {
            if resp.status().is_success() {
                if let Ok(val) = resp.json::<serde_json::Value>().await {
                    if let Some(abs_url) = val.get("AbstractURL").and_then(|v| v.as_str()) {
                        if !abs_url.trim().is_empty() {
                            let heading = val.get("Heading").and_then(|v| v.as_str()).unwrap_or(name_query);
                            let abs_text = val.get("AbstractText").and_then(|v| v.as_str());
                            let source = val.get("AbstractSource").and_then(|v| v.as_str()).unwrap_or("duckduckgo");

                            profiles.push(DiscoveredProfile {
                                platform: source.to_lowercase(),
                                username: name_query.to_string(),
                                canonical_url: abs_url.to_string(),
                                display_name: Some(heading.to_string()),
                                avatar_url: None,
                                bio: abs_text.map(String::from),
                                location: None,
                                organization: None,
                                raw_json: json!({
                                    "source": "ddg_instant_answer",
                                    "heading": heading,
                                    "abstract": abs_text,
                                    "url": abs_url,
                                }),
                            });
                        }
                    }

                    if let Some(topics) = val.get("RelatedTopics").and_then(|v| v.as_array()) {
                        for topic in topics.iter().take(10) {
                            if let Some(first_url) = topic.get("FirstURL").and_then(|v| v.as_str()) {
                                if !first_url.trim().is_empty() {
                                    let text = topic.get("Text").and_then(|v| v.as_str());
                                    let platform = derive_platform_from_url(first_url);
                                    profiles.push(DiscoveredProfile {
                                        platform,
                                        username: name_query.to_string(),
                                        canonical_url: first_url.to_string(),
                                        display_name: text.map(|t| t.chars().take(80).collect()),
                                        avatar_url: None,
                                        bio: text.map(String::from),
                                        location: None,
                                        organization: None,
                                        raw_json: json!({
                                            "source": "ddg_related_topic",
                                            "text": text,
                                            "url": first_url,
                                        }),
                                    });
                                }
                            }
                        }
                    }
                }
            }
        }

        profiles
    }

    async fn fetch_github_name_search(&self, name_query: &str) -> Vec<DiscoveredProfile> {
        let mut profiles = Vec::new();
        let encoded_q: String = url::form_urlencoded::byte_serialize(name_query.as_bytes()).collect();
        let url = format!("https://api.github.com/search/users?q={}", encoded_q);

        if let Ok(resp) = self.client.get(&url).send().await {
            if resp.status().is_success() {
                if let Ok(val) = resp.json::<serde_json::Value>().await {
                    if let Some(items) = val.get("items").and_then(|v| v.as_array()) {
                        for item in items.iter().take(5) {
                            let login = item.get("login").and_then(|v| v.as_str()).unwrap_or("");
                            let html_url = item.get("html_url").and_then(|v| v.as_str()).unwrap_or("");
                            let avatar_url = item.get("avatar_url").and_then(|v| v.as_str());

                            if !login.is_empty() && !html_url.is_empty() {
                                profiles.push(DiscoveredProfile {
                                    platform: "github".to_string(),
                                    username: login.to_string(),
                                    canonical_url: html_url.to_string(),
                                    display_name: Some(format!("GitHub user @{}", login)),
                                    avatar_url: avatar_url.map(String::from),
                                    bio: Some(format!("Discovered via name search query '{}'", name_query)),
                                    location: None,
                                    organization: None,
                                    raw_json: json!({
                                        "source": "github_name_search",
                                        "name_query": name_query,
                                        "login": login,
                                        "html_url": html_url,
                                    }),
                                });
                            }
                        }
                    }
                }
            }
        }

        profiles
    }

    async fn fetch_ddg_html_results(&self, query: &str) -> Result<Vec<DiscoveredProfile>, String> {
        let encoded_q: String = url::form_urlencoded::byte_serialize(query.as_bytes()).collect();
        let ddg_url = format!("https://html.duckduckgo.com/html/?q={}", encoded_q);

        let response = self
            .client
            .get(&ddg_url)
            .header("Accept-Language", "en-US,en;q=0.9")
            .send()
            .await
            .map_err(|e| format!("HTTP request failed for query '{}': {}", query, e))?;

        if !response.status().is_success() {
            return Err(format!("DuckDuckGo returned HTTP status {}", response.status()));
        }

        let body = response
            .text()
            .await
            .map_err(|e| format!("Failed to read response body for query '{}': {}", query, e))?;

        if body.contains("anomaly-detected") || body.contains("ip-blocked") {
            return Err("DuckDuckGo returned bot detection / rate limit response".to_string());
        }

        self.parse_ddg_html(&body, query)
    }

    pub fn parse_ddg_html(&self, html_content: &str, search_query: &str) -> Result<Vec<DiscoveredProfile>, String> {
        let document = Html::parse_document(html_content);

        let result_selector = match Selector::parse("div.result, div.web-result") {
            Ok(s) => s,
            Err(_) => return Err("Failed to compile CSS selector for results".to_string()),
        };
        let title_selector = Selector::parse("a.result__url, a.result__title, h2.result__title a").ok();
        let snippet_selector = Selector::parse("a.result__snippet, div.result__snippet").ok();

        let mut profiles = Vec::new();

        for element in document.select(&result_selector) {
            let mut raw_url = String::new();
            let mut title = String::new();
            let mut snippet = String::new();

            if let Some(ref sel) = title_selector {
                if let Some(link_elem) = element.select(sel).next() {
                    title = link_elem.text().collect::<Vec<_>>().join(" ").trim().to_string();
                    if let Some(href) = link_elem.value().attr("href") {
                        raw_url = href.to_string();
                    }
                }
            }

            if let Some(ref sel) = snippet_selector {
                if let Some(snip_elem) = element.select(sel).next() {
                    snippet = snip_elem.text().collect::<Vec<_>>().join(" ").trim().to_string();
                }
            }

            let clean_url = extract_real_url(&raw_url);
            if clean_url.is_empty() || clean_url.contains("duckduckgo.com") {
                continue;
            }

            let platform = derive_platform_from_url(&clean_url);
            let username_slug = derive_username_from_url(&clean_url, search_query);

            profiles.push(DiscoveredProfile {
                platform,
                username: username_slug,
                canonical_url: clean_url.clone(),
                display_name: if title.is_empty() { None } else { Some(title.clone()) },
                avatar_url: None,
                bio: if snippet.is_empty() { None } else { Some(snippet.clone()) },
                location: None,
                organization: None,
                raw_json: json!({
                    "source": "web_search_html",
                    "search_query": search_query,
                    "title": title,
                    "snippet": snippet,
                    "canonical_url": clean_url,
                }),
            });
        }

        Ok(profiles)
    }
}

fn extract_real_url(raw_href: &str) -> String {
    if raw_href.starts_with("http://") || raw_href.starts_with("https://") {
        return raw_href.to_string();
    }
    if raw_href.contains("uddg=") {
        if let Some(pos) = raw_href.find("uddg=") {
            let encoded = &raw_href[pos + 5..];
            let end_pos = encoded.find('&').unwrap_or(encoded.len());
            let target = &encoded[..end_pos];
            let decoded: String = url::form_urlencoded::parse(target.as_bytes())
                .map(|(k, v)| if v.is_empty() { k.into_owned() } else { format!("{}={}", k, v) })
                .collect();
            if !decoded.is_empty() {
                return decoded;
            }
        }
    }
    raw_href.to_string()
}

fn derive_platform_from_url(url_str: &str) -> String {
    if let Ok(parsed) = Url::parse(url_str) {
        if let Some(host) = parsed.host_str() {
            let host_clean = host.trim_start_matches("www.");
            return host_clean.to_string();
        }
    }
    "web_search".to_string()
}

fn derive_username_from_url(url_str: &str, search_query: &str) -> String {
    if let Ok(parsed) = Url::parse(url_str) {
        let segments: Vec<&str> = parsed.path_segments().map(|c| c.collect()).unwrap_or_default();
        if let Some(last) = segments.last() {
            if !last.trim().is_empty() && *last != "index.html" {
                return last.trim_start_matches('@').to_string();
            }
        }
    }
    search_query.to_string()
}

#[async_trait]
impl OsintConnector for WebSearchConnector {
    fn name(&self) -> &'static str {
        "web_search"
    }

    fn availability(&self) -> &'static str {
        "AVAILABLE"
    }

    fn healthcheck(&self) -> ConnectorHealth {
        ConnectorHealth {
            connector: self.name().to_string(),
            availability: self.availability().to_string(),
            auth_required: false,
            supported_seeds: vec!["name".to_string(), "username".to_string()],
        }
    }

    async fn search_username(&self, input_name: &str) -> ConnectorOutput {
        let name_trimmed = input_name.trim();
        if name_trimmed.is_empty() {
            return ConnectorOutput::unavailable("Search name query is empty");
        }

        // Check cache
        {
            let mut cache = self.cache.lock().await;
            if let Some(entry) = cache.get(name_trimmed) {
                if entry.cached_at.elapsed() < self.ttl {
                    info!("WebSearchConnector cache hit for '{}'", name_trimmed);
                    return entry.output.clone();
                } else {
                    cache.remove(name_trimmed);
                }
            }
        }

        let mut all_profiles = Vec::new();

        // 1. DuckDuckGo Instant Answer API
        let ddg_profiles = self.fetch_ddg_instant_answer(name_trimmed).await;
        all_profiles.extend(ddg_profiles);

        // 2. GitHub Name Search API
        let gh_profiles = self.fetch_github_name_search(name_trimmed).await;
        all_profiles.extend(gh_profiles);

        // 3. DuckDuckGo HTML endpoint query (plain + site filters)
        let mut queries = vec![format!("\"{}\"", name_trimmed)];
        for site in DEFAULT_TARGET_SITES {
            queries.push(format!("\"{}\" site:{}", name_trimmed, site));
        }

        let total_sites_checked = 2 + queries.len();

        for query in queries {
            if let Ok(profiles) = self.fetch_ddg_html_results(&query).await {
                all_profiles.extend(profiles);
            }
        }

        // Deduplicate profiles by canonical_url
        let mut seen_urls = std::collections::HashSet::new();
        all_profiles.retain(|p| seen_urls.insert(p.canonical_url.clone()));

        let output = ConnectorOutput::success(all_profiles, total_sites_checked);

        // Save to cache
        {
            let mut cache = self.cache.lock().await;
            cache.insert(name_trimmed.to_string(), CacheEntry {
                output: output.clone(),
                cached_at: Instant::now(),
            });
        }

        output
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::db::models::ConnectorStatus;

    #[test]
    fn test_parse_ddg_html_sample() {
        let sample_html = r#"
        <html>
        <body>
            <div class="result web-result">
                <h2 class="result__title">
                    <a class="result__url" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Flinkedin.com%2Fin%2Fjohndoe">John Doe - Software Engineer | LinkedIn</a>
                </h2>
                <a class="result__snippet">View John Doe's profile on LinkedIn, the world's largest professional community.</a>
            </div>
            <div class="result web-result">
                <h2 class="result__title">
                    <a class="result__url" href="https://github.com/johndoe">johndoe (John Doe) · GitHub</a>
                </h2>
                <a class="result__snippet">John Doe has 15 repositories available. Follow their code on GitHub.</a>
            </div>
        </body>
        </html>
        "#;

        let connector = WebSearchConnector::new();
        let profiles = connector.parse_ddg_html(sample_html, "John Doe").unwrap();

        assert_eq!(profiles.len(), 2);
        assert_eq!(profiles[0].canonical_url, "https://linkedin.com/in/johndoe");
        assert_eq!(profiles[0].platform, "linkedin.com");
        assert!(profiles[0].display_name.as_ref().unwrap().contains("John Doe"));

        assert_eq!(profiles[1].canonical_url, "https://github.com/johndoe");
        assert_eq!(profiles[1].platform, "github.com");
    }

    #[test]
    fn test_parse_ddg_html_malformed_graceful() {
        let connector = WebSearchConnector::new();
        let profiles = connector.parse_ddg_html("<div>invalid no links</div>", "Test Query").unwrap();
        assert!(profiles.is_empty());
    }

    #[tokio::test]
    async fn test_web_search_empty_input_returns_unavailable() {
        let connector = WebSearchConnector::new();
        let output = connector.search_username("   ").await;
        assert_eq!(output.status, ConnectorStatus::Unavailable);
        assert!(output.error.unwrap().contains("empty"));
    }

    #[test]
    fn test_extract_real_url_uddg_redirect() {
        let raw = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Foctocat&rut=123";
        let clean = extract_real_url(raw);
        assert_eq!(clean, "https://github.com/octocat");
    }
}
