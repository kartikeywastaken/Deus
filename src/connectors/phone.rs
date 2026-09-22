/*
 * Phone Number Structural Metadata Connector
 *
 * SOURCING & REASONING MODEL:
 * ---------------------------
 * - Purpose: Parse phone number structure, ITU E.164 country prefixes, and numbering plan ranges.
 * - Auth required: None.
 *
 * HONESTY & TRANSPARENCY DISCLAIMER:
 * ----------------------------------
 * This connector performs STRUCTURAL METADATA DERIVATION ONLY (country, ITU country code,
 * region, and line-type range estimation). It DOES NOT query private subscriber databases,
 * cell tower logs, or carrier CRM portals.
 */

use crate::connectors::{ConnectorHealth, ConnectorOutput, DiscoveredProfile, OsintConnector};
use async_trait::async_trait;
use serde_json::json;

pub struct PhoneConnector;

impl PhoneConnector {
    pub fn new() -> Self {
        Self
    }
}

pub struct PhoneMetadata {
    pub raw_input: String,
    pub e164_normalized: String,
    pub country_code: String,
    pub country_name: String,
    pub region: String,
    pub estimated_line_type: String,
}

pub fn parse_phone_metadata(input: &str) -> Option<PhoneMetadata> {
    let digits: String = input.chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.len() < 7 || digits.len() > 15 {
        return None;
    }

    let e164 = if input.trim().starts_with('+') {
        format!("+{}", digits)
    } else if digits.starts_with("00") {
        format!("+{}", &digits[2..])
    } else if digits.len() == 10 {
        // Assume US/Canada NANP default for 10-digit un-prefixed numbers
        format!("+1{}", digits)
    } else {
        format!("+{}", digits)
    };

    let (country_code, country_name, region, line_type) = derive_country_from_e164(&e164);

    Some(PhoneMetadata {
        raw_input: input.to_string(),
        e164_normalized: e164,
        country_code,
        country_name,
        region,
        estimated_line_type: line_type,
    })
}

fn derive_country_from_e164(e164: &str) -> (String, String, String, String) {
    if e164.starts_with("+1") {
        let area_code = e164.get(2..5).unwrap_or("");
        let line_type = if area_code.starts_with("800") || area_code.starts_with("888") || area_code.starts_with("877") || area_code.starts_with("866") {
            "Toll-Free Range"
        } else {
            "Mobile / Fixed-Line NANP Range"
        };
        ("+1".to_string(), "United States / Canada (NANP)".to_string(), "North America".to_string(), line_type.to_string())
    } else if e164.starts_with("+44") {
        let line_type = if e164.starts_with("+447") { "Mobile Range" } else { "Geographic Fixed-Line" };
        ("+44".to_string(), "United Kingdom".to_string(), "Europe".to_string(), line_type.to_string())
    } else if e164.starts_with("+91") {
        let line_type = if e164.starts_with("+916") || e164.starts_with("+917") || e164.starts_with("+918") || e164.starts_with("+919") {
            "Mobile Range"
        } else {
            "Geographic Fixed-Line"
        };
        ("+91".to_string(), "India".to_string(), "South Asia".to_string(), line_type.to_string())
    } else if e164.starts_with("+33") {
        let line_type = if e164.starts_with("+336") || e164.starts_with("+337") { "Mobile Range" } else { "Geographic Fixed-Line" };
        ("+33".to_string(), "France".to_string(), "Europe".to_string(), line_type.to_string())
    } else if e164.starts_with("+49") {
        let line_type = if e164.starts_with("+4915") || e164.starts_with("+4916") || e164.starts_with("+4917") { "Mobile Range" } else { "Geographic Fixed-Line" };
        ("+49".to_string(), "Germany".to_string(), "Europe".to_string(), line_type.to_string())
    } else if e164.starts_with("+81") {
        let line_type = if e164.starts_with("+8170") || e164.starts_with("+8180") || e164.starts_with("+8190") { "Mobile Range" } else { "Geographic Fixed-Line" };
        ("+81".to_string(), "Japan".to_string(), "East Asia".to_string(), line_type.to_string())
    } else if e164.starts_with("+86") {
        let line_type = if e164.starts_with("+8613") || e164.starts_with("+8615") || e164.starts_with("+8618") || e164.starts_with("+8619") { "Mobile Range" } else { "Geographic Fixed-Line" };
        ("+86".to_string(), "China".to_string(), "East Asia".to_string(), line_type.to_string())
    } else if e164.starts_with("+61") {
        let line_type = if e164.starts_with("+614") { "Mobile Range" } else { "Geographic Fixed-Line" };
        ("+61".to_string(), "Australia".to_string(), "Oceania".to_string(), line_type.to_string())
    } else if e164.starts_with("+55") {
        ("+55".to_string(), "Brazil".to_string(), "South America".to_string(), "Mobile / Fixed-Line Range".to_string())
    } else {
        ("International".to_string(), "Global E.164 Prefix".to_string(), "International".to_string(), "Standard E.164 Number".to_string())
    }
}

#[async_trait]
impl OsintConnector for PhoneConnector {
    fn name(&self) -> &'static str {
        "phone_metadata"
    }

    fn availability(&self) -> &'static str {
        "AVAILABLE"
    }

    fn healthcheck(&self) -> ConnectorHealth {
        ConnectorHealth {
            connector: self.name().to_string(),
            availability: self.availability().to_string(),
            auth_required: false,
            supported_seeds: vec!["phone".to_string()],
        }
    }

    async fn search_username(&self, input_phone: &str) -> ConnectorOutput {
        let Some(meta) = parse_phone_metadata(input_phone) else {
            return ConnectorOutput::unavailable(format!("Invalid phone number format: '{}'", input_phone));
        };

        let disclaimer_bio = format!(
            "[Phone Metadata Only] Country: {} ({}) | Region: {} | Line Type: {}. Note: Structural ITU metadata; no private carrier lookup performed.",
            meta.country_name, meta.country_code, meta.region, meta.estimated_line_type
        );

        let profile = DiscoveredProfile {
            platform: "phone_metadata".to_string(),
            username: meta.e164_normalized.clone(),
            canonical_url: format!("tel:{}", meta.e164_normalized),
            display_name: Some(format!("Phone {}", meta.e164_normalized)),
            avatar_url: None,
            bio: Some(disclaimer_bio.clone()),
            location: Some(meta.country_name.clone()),
            organization: None,
            raw_json: json!({
                "source": "phone_metadata",
                "raw_input": meta.raw_input,
                "e164_normalized": meta.e164_normalized,
                "country_code": meta.country_code,
                "country_name": meta.country_name,
                "region": meta.region,
                "estimated_line_type": meta.estimated_line_type,
                "disclaimer": "Phone number metadata derived from standard ITU E.164 numbering plans."
            }),
        };

        ConnectorOutput::success(vec![profile], 1)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_phone_metadata_valid() {
        let meta = parse_phone_metadata("+14155552671").unwrap();
        assert_eq!(meta.e164_normalized, "+14155552671");
        assert_eq!(meta.country_code, "+1");
        assert_eq!(meta.country_name, "United States / Canada (NANP)");

        let meta_uk = parse_phone_metadata("+447911123456").unwrap();
        assert_eq!(meta_uk.country_code, "+44");
        assert_eq!(meta_uk.estimated_line_type, "Mobile Range");
    }

    #[test]
    fn test_parse_phone_metadata_invalid() {
        assert!(parse_phone_metadata("abc").is_none());
        assert!(parse_phone_metadata("123").is_none());
    }
}
