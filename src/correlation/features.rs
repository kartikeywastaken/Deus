use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum SignalType {
    EmailExact,
    DirectProfileLink,
    SharedPersonalDomain,
    DomainExact,
    UrlExact,
    SharedIdentifier,
    UsernameExact,
    RepositoryRelationship,
    UsernameSimilarity,
    DisplayNameSimilarity,
    ProjectOverlap,
    OrganizationOverlap,
    BioSimilarity,
    TopicOverlap,
    LocationOverlap,
    ExactAvatar,
    ImageSimilarity,
    FaceSimilarity,
    DifferentFace,
    ExplicitIdentityConflict,
    PersonalDomainConflict,
    BiographicalContradiction,
    LocationConflict,
    OrganizationConflict,
    NameSearchMention,
}

impl SignalType {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::EmailExact => "EMAIL_EXACT",
            Self::DirectProfileLink => "DIRECT_PROFILE_LINK",
            Self::SharedPersonalDomain => "SHARED_PERSONAL_DOMAIN",
            Self::DomainExact => "DOMAIN_EXACT",
            Self::UrlExact => "URL_EXACT",
            Self::SharedIdentifier => "SHARED_IDENTIFIER",
            Self::UsernameExact => "USERNAME_EXACT",
            Self::RepositoryRelationship => "REPOSITORY_RELATIONSHIP",
            Self::UsernameSimilarity => "USERNAME_SIMILARITY",
            Self::DisplayNameSimilarity => "DISPLAY_NAME_SIMILARITY",
            Self::ProjectOverlap => "PROJECT_OVERLAP",
            Self::OrganizationOverlap => "ORGANIZATION_OVERLAP",
            Self::BioSimilarity => "BIO_SIMILARITY",
            Self::TopicOverlap => "TOPIC_OVERLAP",
            Self::LocationOverlap => "LOCATION_OVERLAP",
            Self::ExactAvatar => "EXACT_AVATAR",
            Self::ImageSimilarity => "IMAGE_SIMILARITY",
            Self::FaceSimilarity => "FACE_SIMILARITY",
            Self::DifferentFace => "DIFFERENT_FACE",
            Self::ExplicitIdentityConflict => "EXPLICIT_IDENTITY_CONFLICT",
            Self::PersonalDomainConflict => "PERSONAL_DOMAIN_CONFLICT",
            Self::BiographicalContradiction => "BIOGRAPHICAL_CONTRADICTION",
            Self::LocationConflict => "LOCATION_CONFLICT",
            Self::OrganizationConflict => "ORGANIZATION_CONFLICT",
            Self::NameSearchMention => "NAME_SEARCH_MENTION",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum EvidenceFamily {
    Email,
    Link,
    Domain,
    Url,
    Identifier,
    Username,
    Repository,
    DisplayName,
    Project,
    Organization,
    Bio,
    Topic,
    Location,
    Avatar,
    Image,
    Face,
    Conflict,
}

impl EvidenceFamily {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Email => "email",
            Self::Link => "link",
            Self::Domain => "domain",
            Self::Url => "url",
            Self::Identifier => "identifier",
            Self::Username => "username",
            Self::Repository => "repository",
            Self::DisplayName => "display_name",
            Self::Project => "project",
            Self::Organization => "organization",
            Self::Bio => "bio",
            Self::Topic => "topic",
            Self::Location => "location",
            Self::Avatar => "avatar",
            Self::Image => "image",
            Self::Face => "face",
            Self::Conflict => "conflict",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Direction {
    Support,
    Contradict,
    Neutral,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvidenceSignal {
    pub signal_type: SignalType,
    pub evidence_family: EvidenceFamily,
    pub direction: Direction,
    pub normalized_score: f64,
    pub reliability: f64,
    pub explanation: String,
}
