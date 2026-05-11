use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ToolPackageInfo {
    pub name: String,
    pub source: String,
    #[serde(default)]
    pub upstream_url: Option<String>,
    #[serde(default)]
    pub locked_version: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ToolOperation {
    pub name: String,
    pub description: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ToolManifest {
    pub tool_id: String,
    pub name: String,
    pub description: String,
    pub version: String,
    pub source_type: String,
    pub license: String,
    pub entrypoint: String,
    pub input_schema: Value,
    pub output_schema: Value,
    pub permissions: Vec<String>,
    pub examples: Vec<Value>,
    pub error_codes: Vec<String>,
    pub timeout_policy: Value,
    pub artifact_policy: Value,
    #[serde(default)]
    pub runtime: Option<String>,
    #[serde(default)]
    pub package: Option<ToolPackageInfo>,
    #[serde(default)]
    pub capabilities: Vec<String>,
    #[serde(default)]
    pub operations: Vec<ToolOperation>,
    #[serde(default)]
    pub dependency_policy: Value,
    #[serde(default)]
    pub security_policy: Value,
    #[serde(default)]
    pub node_templates: Vec<Value>,
}

impl ToolManifest {
    pub fn from_path(path: impl AsRef<Path>) -> Result<Self, String> {
        let path = path.as_ref();
        let contents = fs::read_to_string(path)
            .map_err(|error| format!("failed to read manifest '{}': {error}", path.display()))?;
        let manifest: Self = serde_json::from_str(&contents)
            .map_err(|error| format!("failed to parse manifest '{}': {error}", path.display()))?;

        manifest.validate()?;

        Ok(manifest)
    }

    fn validate(&self) -> Result<(), String> {
        validate_required_text("tool_id", &self.tool_id)?;
        validate_required_text("name", &self.name)?;
        validate_required_text("description", &self.description)?;
        validate_required_text("version", &self.version)?;
        validate_required_text("source_type", &self.source_type)?;
        validate_required_text("license", &self.license)?;
        validate_required_text("entrypoint", &self.entrypoint)?;

        if self.permissions.is_empty() {
            return Err("permissions must not be empty".to_string());
        }

        if self
            .permissions
            .iter()
            .any(|permission| permission.trim().is_empty())
        {
            return Err("permissions must not contain empty values".to_string());
        }

        if self.examples.is_empty() {
            return Err("examples must not be empty".to_string());
        }

        if self.error_codes.is_empty() {
            return Err("error_codes must not be empty".to_string());
        }

        if self
            .error_codes
            .iter()
            .any(|error_code| error_code.trim().is_empty())
        {
            return Err("error_codes must not contain empty values".to_string());
        }

        if !self.input_schema.is_object() {
            return Err("input_schema must be a JSON object".to_string());
        }

        if !self.output_schema.is_object() {
            return Err("output_schema must be a JSON object".to_string());
        }

        if !self.timeout_policy.is_object() {
            return Err("timeout_policy must be a JSON object".to_string());
        }

        if !self.artifact_policy.is_object() {
            return Err("artifact_policy must be a JSON object".to_string());
        }

        if self
            .capabilities
            .iter()
            .any(|capability| capability.trim().is_empty())
        {
            return Err("capabilities must not contain empty values".to_string());
        }

        if self
            .operations
            .iter()
            .any(|operation| operation.name.trim().is_empty())
        {
            return Err("operations must not contain empty names".to_string());
        }

        validate_optional_object_policy("dependency_policy", &self.dependency_policy)?;
        validate_optional_object_policy("security_policy", &self.security_policy)?;

        Ok(())
    }
}

fn validate_required_text(field_name: &str, value: &str) -> Result<(), String> {
    if value.trim().is_empty() {
        return Err(format!("{field_name} must not be empty"));
    }

    Ok(())
}

fn validate_optional_object_policy(field_name: &str, value: &Value) -> Result<(), String> {
    if !value.is_null() && !value.is_object() {
        return Err(format!("{field_name} must be null or a JSON object"));
    }

    Ok(())
}
