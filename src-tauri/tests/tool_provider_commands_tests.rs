use alita_lib::{
    commands::refresh_mcp_tool_provider_tools_for_preferences,
    preferences::{
        delete_mcp_tool_provider_config, upsert_mcp_tool_provider_config, AppPreferences,
        McpToolProviderInput,
    },
};

fn valid_mcp_provider_input() -> McpToolProviderInput {
    McpToolProviderInput {
        provider_id: None,
        display_name: "Docs MCP".to_string(),
        transport: "stdio".to_string(),
        command: Some("npx".to_string()),
        args: vec!["@example/docs-mcp".to_string()],
        url: None,
        enabled: true,
    }
}

#[test]
fn refresh_mcp_tool_provider_tools_rejects_unknown_provider() {
    let preferences = AppPreferences::default();

    let error =
        refresh_mcp_tool_provider_tools_for_preferences(&preferences, "missing").unwrap_err();

    assert!(error.contains("unknown MCP tool provider id"));
}

#[test]
fn refresh_mcp_tool_provider_tools_rejects_internal_provider() {
    let preferences = AppPreferences::default();

    let error =
        refresh_mcp_tool_provider_tools_for_preferences(&preferences, "internal").unwrap_err();

    assert!(error.contains("tool provider is not MCP"));
}

#[test]
fn refresh_mcp_tool_provider_tools_accepts_enabled_mcp_provider() {
    let mut preferences = AppPreferences::default();
    let provider =
        upsert_mcp_tool_provider_config(&mut preferences, valid_mcp_provider_input()).unwrap();

    let tools =
        refresh_mcp_tool_provider_tools_for_preferences(&preferences, &provider.provider_id)
            .unwrap();

    assert_eq!(tools.len(), 1);
    assert_eq!(
        tools[0].tool_id,
        format!("mcp:{}:status", provider.provider_id)
    );
    assert_eq!(tools[0].provider_id, provider.provider_id);
}

#[test]
fn delete_mcp_tool_provider_config_rejects_internal_provider() {
    let mut preferences = AppPreferences::default();

    let error = delete_mcp_tool_provider_config(&mut preferences, "internal").unwrap_err();

    assert!(error.contains("internal tool provider cannot be deleted"));
}
