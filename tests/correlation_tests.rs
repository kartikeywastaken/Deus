use deus::correlation::features::{Direction, EvidenceFamily, EvidenceSignal, SignalType};
use deus::correlation::scorer::score_evidence;
use deus::db::models::Classification;

#[test]
fn test_exact_username_match_scoring() {
    let signals = vec![EvidenceSignal {
        signal_type: SignalType::UsernameExact,
        evidence_family: EvidenceFamily::Username,
        direction: Direction::Support,
        normalized_score: 1.0,
        reliability: 1.0,
        explanation: "Exact username match".to_string(),
    }];

    let assessment = score_evidence(&signals);
    assert_eq!(assessment.raw_score, 20.0);
    assert_eq!(assessment.support_family_count, 1);
    assert_eq!(assessment.classification, Classification::Ambiguous);
}

#[test]
fn test_strong_identity_correlation_scoring() {
    let signals = vec![
        EvidenceSignal {
            signal_type: SignalType::EmailExact,
            evidence_family: EvidenceFamily::Email,
            direction: Direction::Support,
            normalized_score: 1.0,
            reliability: 1.0,
            explanation: "Exact email match".to_string(),
        },
        EvidenceSignal {
            signal_type: SignalType::DirectProfileLink,
            evidence_family: EvidenceFamily::Link,
            direction: Direction::Support,
            normalized_score: 1.0,
            reliability: 1.0,
            explanation: "Direct website link".to_string(),
        },
    ];

    let assessment = score_evidence(&signals);
    assert_eq!(assessment.raw_score, 85.0);
    assert_eq!(assessment.support_family_count, 2);
    assert_eq!(assessment.classification, Classification::Strong);
}
