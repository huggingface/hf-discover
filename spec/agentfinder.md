# Agent Finder: Discovery Protocol for Agents

**Version**: v0.4 (Draft)  
**Status**: Proposal  
**Date**: April 15, 2026

## 1\. Overview

LLMs increasingly rely on external capabilities  – MCP tools, A2A agents, skills, and other callable services – to extend their functionality. In this document, we refer to these generically as agents or capabilities.

**Agent Finder** is a discovery protocol for these capabilities. It defines how AI artifacts are cataloged, discovered, and searched across federated networks.

This version (v0.4) aligns the discovery protocol with the broader `ai-catalog` specification, shifting towards a media-type-driven approach and mandating standard web protocols (REST) for discovery interfaces to ensure maximum interoperability.

## 2\. Motivation

The prevailing model requires users or developers to explicitly “install” or hardcode each agent before use. As the ecosystem scales to thousands or millions of agents, we need a model where LLMs can discover and invoke agents dynamically, similar to how search engines discover web pages.

Agent descriptions tend to be generic, and most LLMs currently select tools by including all descriptions in the context window – which does not scale. Agent Finder addresses this by moving discovery outside the LLM into a dedicated search service, where richer signals (representative queries, publisher identity, compliance metadata, usage patterns) can be leveraged without consuming context window tokens.

## 3\. Core Design

The Agent Finder protocol is guided by the following core design principles to ensure scalability, interoperability, and ease of adoption:

### 3.1 Search-First Discovery

Rather than requiring users or systems to pre-install agents (analogous to the mobile app store paradigm), Agent Finder promotes a model where agents are discovered dynamically through search. Registries maintain a shared, continuously updated index, making capabilities discoverable the moment they are published.

### 3.2 Scalability Beyond Context Windows

Traditional tool selection relies on injecting all descriptions into the LLM's context window, which does not scale. Agent Finder moves the selection problem outside the LLM into a dedicated search service, leveraging information retrieval techniques to scale to thousands or millions of capabilities without consuming context window tokens.

### 3.3 Artifact Agnostic Envelope

The protocol does not define or constrain the schema of specific agent types (MCP, A2A, etc.). Instead, it acts as a clean envelope that uses IANA Media Types to identify what an artifact is, delegating the definition of artifact-specific metadata to the respective protocol specifications.

### 3.4 Strict Value-or-Reference

To ensure safe parsing and predictable behavior in enterprise environments, a catalog entry must contain exactly one of two mutually exclusive keys for its content delivery:

* **`url`**: A remote reference to the artifact document.  
* **`data`**: An embedded JSON object containing the full artifact document.

### 3.5 Universal Baseline for Federation

To guarantee that any system can participate in discovery regardless of its execution stack, an Agent Registry **MUST** expose a standard HTTP REST search interface. While specialized protocols (A2A/MCP) may be used for execution, discovery requires a universal baseline that any HTTP client can access.

### 3.6 Separation of Concerns

To maintain a clean and implementable standard, the protocol delegates operational details:

* **Authentication is Delegated**: Agent authentication is handled by the specific artifact protocol, not the discovery layer. Registry authentication is handled at the standard HTTP transport layer.  
* **Distribution is Infrastructure**: Physical storage and delivery mechanisms (such as OCI registries, npm packages, or S3 bucket configurations) are backend implementation details. The author of an AI capability should not need to put distribution schemas into their discovery record. Tooling can handle mapping logical records to physical storage behind the scenes.

## 4\. The Data Model

The capability manifest (the file publishers host to advertise their agents) is the central data model.

### 4.1 The Capability Manifest (`ai-catalog.json`)

A manifest file hosted at `/.well-known/ai-catalog.json` lists the available artifacts.

```json
{
  "specVersion": "1.0",
  "host": {
    "displayName": "Acme Enterprise AI",
    "identifier": "did:web:acme.com"
  },
  "entries": [
    {
      "identifier": "urn:acme:agent:assistant",
      "displayName": "Corporate Assistant (A2A)",
      "mediaType": "application/a2a-agent-card+json",
      "url": "https://api.acme.com/agents/assistant.json",
      "description": "General-purpose corporate A2A assistant."
    },
    {
      "identifier": "urn:agentfinder:tool:create-issue",
      "displayName": "Create GitHub Issue",
      "mediaType": "application/mcp-server+json",
      "url": "https://agentfinder.github.com/mcp/github.json",
      "capabilities": ["create_issue"],
      "description": "Create a new issue in a GitHub repository",
      "representativeQueries": [
        "file a bug report on the auth module",
        "create an issue for the memory leak in the parser"
      ]
    },
    {
      "identifier": "urn:agentfinder:tool:search-repos",
      "displayName": "Search GitHub Repositories",
      "mediaType": "application/mcp-server+json",
      "url": "https://agentfinder.github.com/mcp/github.json",
      "capabilities": ["search_repositories"],
      "description": "Search for GitHub repositories by name, topic, or language",
      "representativeQueries": [
        "find popular Rust crates for async HTTP",
        "search for MCP server implementations in Python"
      ]
    },
    {
      "identifier": "urn:agentfinder:tool:create-pull-request",
      "displayName": "Create Pull Request",
      "mediaType": "application/mcp-server+json",
      "url": "https://agentfinder.github.com/mcp/github.json",
      "capabilities": ["create_pull_request"],
      "description": "Create a pull request from one branch to another",
      "representativeQueries": [
        "open a PR from my feature branch to main",
        "submit a pull request with my bug fix"
      ]
    },
    {
      "identifier": "urn:agentfinder:server:travel",
      "displayName": "Travel Planning Server",
      "mediaType": "application/mcp-server+json",
      "url": "https://agentfinder.github.com/mcp/travel.json",
      "description": "MCP server for flight search, hotel booking, and itinerary management."
    },
    {
      "identifier": "urn:acme:server:weather",
      "displayName": "Weather Data Node",
      "mediaType": "application/mcp-server+json",
      "url": "https://api.acme.com/mcp/weather.json",
      "description": "Enterprise weather MCP server for live telemetry."
    },
    {
      "identifier": "urn:acme:plugin:finance-suite",
      "displayName": "Finance Tool Bundle",
      "mediaType": "application/ai-catalog+json",
      "description": "A static nested bundle containing an A2A agent and its required market dataset.",
      "tags": ["finance", "bundle"],
      "data": {
        "specVersion": "1.0",
        "entries": [
          {
            "identifier": "urn:acme:agent:finance-a2a",
            "displayName": "Finance Trading Agent",
            "mediaType": "application/a2a-agent-card+json",
            "url": "https://api.acme.com/agents/finance-trader.json"
          },
          {
            "identifier": "urn:acme:data:market-2026",
            "displayName": "Market Dataset 2026",
            "mediaType": "application/parquet",
            "url": "https://data.acme.com/market-2026.parquet"
          }
        ]
      }
    },
    {
      "identifier": "urn:acme:registry:global",
      "displayName": "Acme Global Agent Registry",
      "mediaType": "application/ai-registry+json",
      "url": "https://registry.acme.com/api/v1/",
      "description": "Dynamic REST API search interface to discover all approved enterprise agents.",
      "tags": ["registry", "search", "dynamic"],
      "trustManifest": {
        "identity": "urn:acme:registry:global",
        "attestations": [
          {
            "type": "SOC2-Type2",
            "uri": "https://trust.acme.com/reports/soc2.pdf",
            "mediaType": "application/pdf"
          }
        ]
      }
    }
  ],
}
```

### 4.2 Catalog Entry Object

Each object in the `entries` array MUST contain:

| Field | Type | Description |
| :---- | :---- | :---- |
| `identifier` | String | Globally unique identifier (URN or URI). |
| `displayName` | String | Human-readable name. |
| `mediaType` | String | IANA Media Type of the artifact. |

Exactly one of the following MUST be present:

| Field | Type | Description |
| :---- | :---- | :---- |
| `url` | String | URL to retrieve the full artifact. |
| `data` | Object | The complete artifact document inline. |

Optional fields:

| Field | Type | Description |
| :---- | :---- | :---- |
| `description` | String | Short description. |
| `tags` | Array | Keywords for filtering. |
| `version` | String | Version of the artifact. |
| `updatedAt` | String | ISO 8601 timestamp. |
| `metadata` | Map | Custom metadata key-value pairs. |
| `trustManifest` | Object | Verifiable identity and trust metadata. |

### 4.3 Host Info Object

Describes the operator of the catalog.

| Field | Type | Description |
| :---- | :---- | :---- |
| `displayName` | String | Human-readable name of the host. |
| `identifier` | String | Optional. Verifiable identifier (DID or domain). |
| `documentationUrl` | String | Optional. URL to documentation. |
| `logoUrl` | String | Optional. URL to logo. |
| `trustManifest` | Object | Optional. Trust metadata for the host. |

### 4.4 Examples

#### The Solo Developer Path

No complex identity ceremony or cloud account required.

An agent hosted on Hugging Face Spaces (MCP), published in a manifest:

```json
{
  "specVersion": "1.0",
  "host": { "displayName": "Alice's AI Tools" },
  "entries": [
    {
      "identifier": "urn:hf:alice-dev:weather-agent",
      "displayName": "Weather Agent",
      "mediaType": "application/mcp-server+json",
      "data": {
        "name": "Weather Agent",
        "description": "Simple weather lookup using open data",
        "tools": [
          {
            "name": "get_weather",
            "description": "Get current weather for a city",
            "inputSchema": {
              "type": "object",
              "properties": { "city": { "type": "string" } },
              "required": ["city"]
            }
          }
        ]
      }
    }
  ]
}
```

A skill hosted on GitHub, published in a manifest:

```
{
  "specVersion": "1.0",
  "host": { "displayName": "Alice's AI Tools" },
  "entries": [
    {
      "identifier": "urn:github:alice-dev:pptx-creator",
      "displayName": "pptx-creator",
      "mediaType": "application/ai-skill",
      "url": "https://github.com/alice-dev/pptx-creator",
      "description": "Create professional PowerPoint presentations following brand guidelines."
    }
  ]
}
```

Discovery via GitHub Pages (combining the above):

```json
{
  "specVersion": "1.0",
  "host": { "displayName": "Alice's AI Tools" },
  "entries": [
    {
      "identifier": "urn:hf:alice-dev:weather-agent",
      "displayName": "Weather Agent",
      "mediaType": "application/mcp-server+json",
      "url": "https://alice-dev.github.io/weather-agent/entry.json"
    },
    {
      "identifier": "urn:github:alice-dev:pptx-creator",
      "displayName": "pptx-creator",
      "mediaType": "application/ai-skill",
      "url": "https://github.com/alice-dev/pptx-creator"
    }
  ]
}
```

#### Enterprise Example:

Using `trustManifest` for compliance, published in a manifest.

```json
{
  "specVersion": "1.0",
  "host": {
    "displayName": "Acme Enterprise AI",
    "identifier": "did:web:acme.com"
  },
  "entries": [
    {
      "identifier": "urn:acme:agent:travel-concierge",
      "displayName": "Travel Concierge",
      "mediaType": "application/a2a-agent-card+json",
      "url": "https://api.acme.com/a2a",
      "description": "AI-powered travel planning",
      "trustManifest": {
        "identity": "urn:acme:agent:travel-concierge",
        "attestations": [
          {
            "type": "SOC2-Type2",
            "uri": "https://trust.acme.com/reports/soc2.pdf",
            "mediaType": "application/pdf"
          },
          {
            "type": "GDPR",
            "uri": "https://trust.acme.com/compliance/gdpr",
            "mediaType": "text/html"
          }
        ]
      }
    }
  ]
}
```

### 4.5 Description Vocabulary

Catalog entries MAY use Schema.org vocabulary (or comparable structured schemas) in their descriptive fields. Any Schema.org-based markup used to describe the agent can be leveraged as filter dimensions in the Search API. This allows domain-specific structured metadata (pricing, geographic coverage, supported languages, certifications) to be attached to records and queried against.

## 5\. Identity and Trust

Identity binding, compliance attestations, provenance, and cryptographic signatures are consolidated into the optional `trustManifest` object, as defined in the `ai-catalog` specification. This keeps the core entry lightweight for simple use cases while providing a robust hook for enterprise compliance, entirely separate from the artifact's native operational metadata.

### 5.1 The Trust Manifest Object

The `trustManifest` object sits alongside the artifact content in a catalog entry and contains the following key members:

| Field | Type | Description |
| :---- | :---- | :---- |
| `identity` | String | **Required**. Globally unique URI (DID, SPIFFE ID, or URL) identifying the artifact. MUST match the entry's `identifier`. |
| `identityType` | String | Optional. Type hint for the identity URI (e.g., "did", "spiffe"). |
| `attestations` | Array | Optional. List of Attestation objects providing verifiable claims. |
| `provenance` | Array | Optional. List of Provenance Link objects recording lineage. |
| `signature` | String | Optional. Detached JWS signature computed over the Trust Manifest content. |

### 5.2 Attestation Object

Provides verifiable proof of a claim (e.g., compliance certifications).

| Field | Type | Description |
| :---- | :---- | :---- |
| `type` | String | **Required**. Attestation type (e.g., "SOC2-Type2", "HIPAA-Audit"). |
| `uri` | String | **Required**. Location of the attestation document. |
| `mediaType` | String | **Required**. Format of the document (e.g., "application/pdf"). |
| `digest` | String | Optional. Cryptographic hash for integrity verification. |

### 5.3 Provenance Link Object

Records lineage and source information.

| Field | Type | Description |
| :---- | :---- | :---- |
| `relation` | String | **Required**. Relationship type (e.g., "derivedFrom", "publishedFrom"). |
| `sourceId` | String | **Required**. Identifier of the source artifact or data. |
| `sourceDigest` | String | Optional. Digest of the source for verification. |

For full verification procedures (signature checking, key resolution), refer to the core `ai-catalog` specification.

## 6\. Discovery

The protocol supports two operational layers:

1. **Static Discovery**: A decentralized publishing mechanism where developers and enterprises host static JSON manifests.  
2. **Dynamic Discovery**: Active, searchable services (Registries) that index static catalogs and expose dynamic search endpoints.

### 6.1 Discovery Mechanisms

Publishers advertise their capability manifests via the following mechanisms:

* **Well-Known URI**: Hosting the manifest at `https://{domain}/.well-known/ai-catalog.json`.  
* **Agentmap Directive**: Adding an entry in `robots.txt` (e.g., `Agentmap: https://example.com/catalog.json`).  
* **HTML Link Tag**: Including `<link rel="ai-catalog" href="...">` in the `<head>` of a document.

### 6.2 Ingestion Pipelines

Agent Registry instances populate their indexes through ingestion pipelines:

* **Web Ingestion (Required)**: Crawling `ai-catalog.json` files from discovered URIs. All Agent Finder implementations MUST support this.  
* **Additional Pipelines (Optional)**: Registries may support scanning git repositories, npm registries, or OCI registries as indicated by their configuration.

## 7\. The Agent Finder API

An Agent Registry **MUST** expose a standard HTTP REST search interface to guarantee universal federation.

### 7.1 Search (`POST /search`)

Accepts a natural language query with optional structured constraints. Returns catalog entries ranked by relevance.

**Request Schema:**

```
{
  "query": {
    "text": "find me a flight booking agent",
    "mediaType": "application/a2a-agent-card+json",
    "compliance": "hipaa",
    "federation": "referrals"
  },
  "pageSize": 5
}
```

| Field | Type | Description |
| :---- | :---- | :---- |
| `text` | String | Required. Natural language description of the need. |
| `mediaType` | String | Optional. Filter by artifact type. |
| `compliance` | String | Optional. Filter by compliance requirement. |
| `publisher` | String | Optional. Filter by publisher name or identifier. |
| `federation` | String | Optional. `auto` (default), `referrals`, or `none`. |

**Response Schema:**

The response returns standard catalog entries with additional relevance scores, plus optional referrals.

```json
{
  "results": [
    {
      "identifier": "urn:acme:agent:assistant",
      "displayName": "Corporate Assistant (A2A)",
      "mediaType": "application/a2a-agent-card+json",
      "url": "https://api.acme.com/agents/assistant.json",
      "score": 95,
      "source": "https://registry.acme.com/api/v1/"
    },
    {
      "identifier": "urn:external:weather-server",
      "displayName": "Global Weather Service",
      "mediaType": "application/mcp-server+json",
      "url": "https://weather.example.com/mcp",
      "score": 88,
      "source": "https://finder.external.org/api/"
    }
  ],
  "referrals": [
    {
      "identifier": "urn:public:registry",
      "displayName": "Public Agent Finder",
      "mediaType": "application/ai-registry+json",
      "url": "https://finder.nlweb.ai/search"
    }
  ],
  "pageToken": "eyJwYWdlIjogMn0="
}
```

### 7.2 List (`GET /agents`) — Optional

Deterministic browsing, designed for developer portals. Highly cacheable, relies on strict database filtering, and does not support relevance-based sorting.

**Parameters:**

| Parameter | Type | Description |
| :---- | :---- | :---- |
| `filter` | String | EBNF filter expression. |
| `orderBy` | String | Sorting fields (e.g., `name`, `created_at DESC`). |
| `pageSize` | Integer | Max results (default: 20, max: 100). |
| `pageToken` | String | Pagination token. |

### 7.3 Protocol Wrappers (Optional)

While the REST API is mandated as the floor for interoperability, a Registry **MAY** additionally expose its search capability natively via an MCP Tool or an A2A Skill to preserve native orchestrator flows.

The return response from these protocol-specific wrappers **MUST** follow the same catalog entry format as defined in this specification. However, the request format for these wrappers may differ slightly to accommodate protocol-specific conventions and is pending further definition.

## 8\. Federation

Because the REST API is mandated, Registry-to-Registry routing (federation) becomes a simple HTTP operation. The client controls federation through the `federation` query parameter:

* **`auto`**: The Registry queries upstream registries automatically, merges their results with its own, and returns a unified response. The client gets a single merged result set.  
* **`referrals`**: The Registry returns its results plus catalog entries for other Registries the client may query. The client decides which to follow.  
* **`none`**: The Registry searches only its own index.

This gives the client full control over the federation topology without requiring complex protocol translation layers.

### Example: Referrals Mode

**Request:**

```json
{
  "query": {
    "text": "find me a flight booking agent",
    "federation": "referrals"
  }
}
```

**Response:**

```json
{
  "results": [
    {
      "identifier": "urn:acme:agent:expense",
      "displayName": "Corporate Expenses",
      "mediaType": "application/a2a-agent-card+json",
      "url": "https://internal.corp/agents/expense.json",
      "score": 97,
      "source": "https://finder.internal.corp"
    }
  ],
  "referrals": [
    {
      "identifier": "urn:public:finder",
      "displayName": "Public Agent Finder",
      "mediaType": "application/ai-registry+json",
      "url": "https://finder.nlweb.ai/search"
    },
    {
      "identifier": "urn:travel:finder",
      "displayName": "Travel Agent Finder",
      "mediaType": "application/ai-registry+json",
      "url": "https://travel.finder.example/search"
    }
  ]
}
```

## 9\. Integration Example

A user asks an orchestrator: “Book me a flight to Tokyo and file the travel expense report.”

1. The orchestrator queries the enterprise Agent Registry with `federation: "referrals"`.  
2. The Registry returns an internal expense agent, plus referrals to other Registries.  
3. The orchestrator follows a referral to a public Agent Registry and queries it for flight booking agents.  
4. The orchestrator now has both capabilities and can proceed to invoke them using their respective protocols (e.g., A2A for booking, MCP for expense filing).

---

## Appendix A: Filter Expression Syntax

The `filter` parameter in the Search API uses a simple EBNF-like format for structured constraints.

| Filter Field | Type | Description |
| :---- | :---- | :---- |
| `displayName` | String | Case-insensitive name filter. |
| `mediaType` | String | Comma-separated media types (OR logic). |
| `publisherId` | String | Comma-separated publisher IDs (OR logic). |
| `createdAfter` | String | ISO 8601 timestamp. |
| `updatedAfter` | String | ISO 8601 timestamp. |

Logical AND is used across different parameters; OR is used within a single parameter with multiple values (comma-separated).

## Appendix B: Standard Error Codes

| HTTP Code | Error Code | Description |
| :---- | :---- | :---- |
| 400 | `INVALID_ARGUMENT` | Malformed query or invalid filter syntax. |
| 401 | `UNAUTHENTICATED` | Invalid or missing credentials. |
| 404 | `NOT_FOUND` | Non-existent agent or registry. |
| 429 | `RATE_LIMIT_EXCEEDED` | Too many requests. |
| 500 | `INTERNAL_ERROR` | Internal server failure. |
