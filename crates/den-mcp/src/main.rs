mod tools;

use async_trait::async_trait;
use rust_mcp_sdk::error::SdkResult;
use rust_mcp_sdk::mcp_server::{server_runtime, McpServerOptions, ServerHandler, ToMcpServerHandler};
use rust_mcp_sdk::schema::schema_utils::CallToolError;
use rust_mcp_sdk::schema::{
    CallToolRequestParams, CallToolResult, Implementation, InitializeResult,
    ListToolsResult, PaginatedRequestParams, ProtocolVersion, RpcError,
    ServerCapabilities, ServerCapabilitiesTools,
};
use rust_mcp_sdk::{McpServer, StdioTransport, TransportOptions};
use std::sync::Arc;

use tools::{DiagnoseDenTool, OperateDenTool, ProvisionDenTool};

struct DenHandler;

#[async_trait]
impl ServerHandler for DenHandler {
    async fn handle_list_tools_request(
        &self,
        _request: Option<PaginatedRequestParams>,
        _runtime: Arc<dyn McpServer>,
    ) -> std::result::Result<ListToolsResult, RpcError> {
        Ok(ListToolsResult {
            tools: vec![
                ProvisionDenTool::tool(),
                OperateDenTool::tool(),
                DiagnoseDenTool::tool(),
            ],
            meta: None,
            next_cursor: None,
        })
    }

    async fn handle_call_tool_request(
        &self,
        params: CallToolRequestParams,
        _runtime: Arc<dyn McpServer>,
    ) -> std::result::Result<CallToolResult, CallToolError> {
        let args_value = match params.arguments {
            Some(map) => serde_json::Value::Object(map),
            None => serde_json::Value::Object(Default::default()),
        };

        match params.name.as_str() {
            "provision_den" => {
                let tool: ProvisionDenTool = serde_json::from_value(args_value)
                    .map_err(|e| CallToolError::from_message(e.to_string()))?;
                tools::provision_den(tool).await
            }
            "operate_den" => {
                let tool: OperateDenTool = serde_json::from_value(args_value)
                    .map_err(|e| CallToolError::from_message(e.to_string()))?;
                tools::operate_den(tool).await
            }
            "diagnose_den" => {
                let tool: DiagnoseDenTool = serde_json::from_value(args_value)
                    .map_err(|e| CallToolError::from_message(e.to_string()))?;
                tools::diagnose_den(tool).await
            }
            _ => Err(CallToolError::unknown_tool(params.name)),
        }
    }
}

#[tokio::main]
async fn main() -> SdkResult<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("warn")),
        )
        .init();

    let server_details = InitializeResult {
        server_info: Implementation {
            name: "den-mcp".into(),
            version: env!("CARGO_PKG_VERSION").to_string(),
            title: Some("Den MCP Server".into()),
            description: Some(
                "Deep workflow MCP server for den. Use the smallest number of tool calls possible: \
                 provision_den for create/setup flows, operate_den for lifecycle actions, and \
                 diagnose_den for test and health checks."
                    .into(),
            ),
            icons: vec![],
            website_url: None,
        },
        capabilities: ServerCapabilities {
            tools: Some(ServerCapabilitiesTools {
                list_changed: None,
            }),
            ..Default::default()
        },
        meta: None,
        instructions: None,
        protocol_version: ProtocolVersion::V2025_11_25.into(),
    };

    let transport = StdioTransport::new(TransportOptions::default())?;
    let handler = DenHandler.to_mcp_server_handler();
    let server = server_runtime::create_server(McpServerOptions {
        server_details,
        transport,
        handler,
        task_store: None,
        client_task_store: None,
        message_observer: None,
    });

    server.start().await
}
