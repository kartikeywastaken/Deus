use async_trait::async_trait;
use reqwest::header::{CONTENT_TYPE, LOCATION};
use reqwest::redirect::Policy;
use std::net::{IpAddr, ToSocketAddrs};
use std::time::Duration;
use url::Url;

#[async_trait]
pub trait AvatarFetcher: Send + Sync {
    async fn fetch_avatar(&self, url: &str) -> Result<Vec<u8>, String>;
}

#[derive(Default, Clone, Copy, Debug)]
pub struct DefaultAvatarFetcher;

#[async_trait]
impl AvatarFetcher for DefaultAvatarFetcher {
    async fn fetch_avatar(&self, url: &str) -> Result<Vec<u8>, String> {
        safe_fetch(url).await
    }
}

pub fn is_safe_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ipv4) => {
            if ipv4.is_loopback()
                || ipv4.is_private()
                || ipv4.is_link_local()
                || ipv4.is_broadcast()
                || ipv4.is_documentation()
                || ipv4.is_unspecified()
            {
                return false;
            }
        }
        IpAddr::V6(ipv6) => {
            if ipv6.is_loopback() || ipv6.is_unspecified() {
                return false;
            }
            if let Some(ipv4) = ipv6.to_ipv4_mapped() {
                return is_safe_ip(IpAddr::V4(ipv4));
            }
            let segments = ipv6.segments();
            // Unique local fc00::/7
            if (segments[0] & 0xfe00) == 0xfc00 {
                return false;
            }
            // Link local fe80::/10
            if (segments[0] & 0xffc0) == 0xfe80 {
                return false;
            }
        }
    }
    true
}

pub fn validate_url_host_ip(url_str: &str) -> Result<Url, String> {
    let parsed = Url::parse(url_str).map_err(|e| format!("Invalid URL: {e}"))?;
    let scheme = parsed.scheme();
    if scheme != "http" && scheme != "https" {
        return Err(format!("Unsupported scheme: {scheme}"));
    }
    let host = parsed.host_str().ok_or_else(|| "Missing host in URL".to_string())?;
    let port = parsed.port_or_known_default().unwrap_or(80);

    // Resolve DNS to IP addresses
    let socket_addr_str = format!("{}:{}", host, port);
    let addrs = socket_addr_str
        .to_socket_addrs()
        .map_err(|e| format!("DNS resolution failed for {host}: {e}"))?;

    let mut found_any = false;
    for addr in addrs {
        found_any = true;
        if !is_safe_ip(addr.ip()) {
            return Err(format!("SSRF blocked: host {host} resolved to restricted IP {}", addr.ip()));
        }
    }

    if !found_any {
        return Err(format!("No IP addresses found for {host}"));
    }

    Ok(parsed)
}

pub async fn safe_fetch(initial_url: &str) -> Result<Vec<u8>, String> {
    let max_bytes: usize = 5 * 1024 * 1024; // 5 MB
    let timeout_duration = Duration::from_secs(8);

    let client = reqwest::Client::builder()
        .timeout(timeout_duration)
        .redirect(Policy::none()) // We manually validate each redirect hop
        .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Deus/1.0 (OSINT Avatar Matcher)")
        .build()
        .map_err(|e| format!("Client builder error: {e}"))?;

    let mut current_url = validate_url_host_ip(initial_url)?;
    let mut redirects = 0;
    const MAX_REDIRECTS: usize = 5;

    loop {
        let res = client
            .get(current_url.as_str())
            .header("Accept", "image/jpeg, image/png, image/webp, image/*, */*")
            .send()
            .await
            .map_err(|e| format!("HTTP request error: {e}"))?;

        let status = res.status();
        if status.is_redirection() {
            if redirects >= MAX_REDIRECTS {
                return Err("Too many redirects".to_string());
            }
            redirects += 1;

            let location = res
                .headers()
                .get(LOCATION)
                .ok_or_else(|| "Redirect missing Location header".to_string())?
                .to_str()
                .map_err(|_| "Invalid Location header UTF-8".to_string())?;

            let next_url = current_url
                .join(location)
                .map_err(|e| format!("Failed to parse redirect location: {e}"))?;

            current_url = validate_url_host_ip(next_url.as_str())?;
            continue;
        }

        if !status.is_success() {
            return Err(format!("HTTP error status {}", status));
        }

        if let Some(content_type) = res.headers().get(CONTENT_TYPE) {
            if let Ok(ct_str) = content_type.to_str() {
                let ct_lower = ct_str.to_lowercase();
                if !ct_lower.starts_with("image/")
                    && !ct_lower.starts_with("application/octet-stream")
                {
                    return Err(format!("Invalid Content-Type for image: {ct_str}"));
                }
            }
        }

        let bytes = res
            .bytes()
            .await
            .map_err(|e| format!("Failed to read response body: {e}"))?;

        if bytes.len() > max_bytes {
            return Err(format!(
                "Avatar file too large ({} bytes > 5 MB)",
                bytes.len()
            ));
        }

        return Ok(bytes.to_vec());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_safe_ip() {
        assert!(!is_safe_ip("127.0.0.1".parse().unwrap()));
        assert!(!is_safe_ip("10.0.0.1".parse().unwrap()));
        assert!(!is_safe_ip("172.16.0.1".parse().unwrap()));
        assert!(!is_safe_ip("192.168.1.1".parse().unwrap()));
        assert!(!is_safe_ip("::1".parse().unwrap()));
        assert!(!is_safe_ip("0.0.0.0".parse().unwrap()));
        assert!(is_safe_ip("8.8.8.8".parse().unwrap()));
        assert!(is_safe_ip("1.1.1.1".parse().unwrap()));
    }
}
