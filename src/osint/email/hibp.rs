use crate::osint::email::types::{BreachExposure, EmailCtx};
use serde_json::Value;
use url::form_urlencoded;

pub async fn check(ctx: &EmailCtx) -> Vec<BreachExposure> {
    if !ctx.self_audit_confirmed {
        return vec![];
    }

    let api_key = match ctx.hibp_api_key {
        Some(ref k) if !k.trim().is_empty() => k.trim(),
        _ => return vec![],
    };

    let email = &ctx.normalized_email;
    let encoded_email = form_urlencoded::byte_serialize(email.as_bytes()).collect::<String>();
    let url = format!(
        "{}/{}?truncateResponse=false",
        ctx.endpoints.hibp_api_url, encoded_email
    );

    let resp = ctx
        .client
        .get(&url)
        .header("hibp-api-key", api_key)
        .header("User-Agent", "Deus-OSINT-Engine/1.0")
        .send()
        .await;

    if let Ok(r) = resp {
        if r.status().is_success() {
            if let Ok(json) = r.json::<Value>().await {
                if let Some(arr) = json.as_array() {
                    let mut breaches = Vec::new();
                    for item in arr {
                        let name = item
                            .get("Name")
                            .and_then(|v| v.as_str())
                            .unwrap_or("Unknown Breach")
                            .to_string();
                        let domain = item
                            .get("Domain")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string();
                        breaches.push(BreachExposure { name, domain });
                    }
                    return breaches;
                }
            }
        }
    }

    vec![]
}
