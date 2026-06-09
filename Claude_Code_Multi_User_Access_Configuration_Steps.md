
# Claude Code on Amazon Bedrock — Multi-User Management

**Multi-User Management with LiteLLM Proxy, Streamlit Admin UI, IAM Identity Center, AWS Client VPN, VPC Endpoints & CloudWatch**

## 1. Executive Summary

Enterprises deploying Claude Code to developer teams face an acute challenge: without central controls, a single developer can consume thousands of dollars in AI API credits in days. This guide solves that problem completely.

This implementation guide delivers a system for deploying Claude Code on Amazon Bedrock across multiple developers with:

- Per-user and per-team budget limits (in USD) with automatic enforcement
- Token-per-minute (TPM) and request-per-minute (RPM) rate limiting
- Model access controls (restrict which Claude models each team can use)
- IAM Identity Center integration for user/group management at scale
- Fully private network path via AWS Client VPN + VPC Endpoints (zero internet exposure)
- Real-time CloudWatch audit logs per user with cost tracking
- Streamlit Admin UI for self-service administration without AWS console access

| Component | Role |
|-----------|------|
| LiteLLM Proxy | OpenAI-compatible gateway that routes requests to Bedrock, enforces budgets, token limits, and model access per user/team |
| PostgreSQL (Amazon RDS) | Stores all users, virtual API keys, budget settings, and spend tracking data |
| Streamlit Admin UI | Web interface for admin to manage users, set limits, view usage dashboards, and sync from Identity Center |
| IAM Identity Center | Source of truth for users and groups; enables bulk import, SSO authentication, and auto-offboarding |
| AWS Client VPN | Encrypted private tunnel from developer laptops to the VPC; keeps all traffic off the public internet |
| VPC Endpoint (Bedrock) | Private AWS backbone route from EC2 to Bedrock; Claude prompts never traverse the public internet |
| CloudWatch Logs | Per-user audit log streams capturing model used, tokens consumed, cost per request, and latency |

## 2. Architecture Overview

### 2.1 Full Architecture Diagram

The following diagram shows the complete end-to-end architecture. All traffic between developers and Bedrock flows entirely within the AWS network once Client VPN and VPC Endpoints are configured.

### 2.2 Data Flow

Developer request flow (full private path):

1. Developer runs Claude Code in IDE with ANTHROPIC_BASE_URL pointing to LiteLLM proxy private IP
2. Request exits laptop through AWS VPN Client as an encrypted TLS tunnel
3. LiteLLM Proxy (port 4000) receives the request, authenticates the virtual API key
4. LiteLLM checks user budget, TPM/RPM limits, and model access permissions against PostgreSQL
5. If allowed, LiteLLM forwards request to Amazon Bedrock via VPC Endpoint (private AWS backbone)
6. Bedrock returns response; LiteLLM records tokens, cost, and metadata to PostgreSQL and CloudWatch
7. Response flows back to developer through the same private path.

## 3. Network Path Analysis

### 3.1 Two Network Segments

The solution has two distinct network segments that must each be secured:

| Segment | Path | Option | Security Level |
|---------|------|--------|----------------|
| Segment 1 | Developer Laptop to LiteLLM EC2 | AWS Client VPN (recommended) | High - encrypted tunnel to VPC |
| Segment 2 | LiteLLM EC2 to Amazon Bedrock | VPC Endpoint (recommended) | Highest - stays on AWS backbone |

### 3.2 Why VPC Endpoint for Bedrock Is Critical

Without a VPC Endpoint, when LiteLLM calls Bedrock, the request goes: EC2 Instance -> Internet Gateway -> Public Internet -> Bedrock public endpoint. Your developers' code, prompts, and AI responses travel over the public internet, even though everything is TLS encrypted.

With a VPC Endpoint (Interface Endpoint for bedrock-runtime), the path becomes: EC2 Instance -> VPC Endpoint (ENI in your subnet) -> AWS Private Network -> Bedrock. The traffic never leaves the AWS backbone. This is required for:

- Enterprises with data residency requirements
- SOC2 / ISO 27001 / PCI DSS compliance
- Organizations where code confidentiality is paramount

## 4. IAM Identity Center

### 4.1 Why Identity Center Is Essential

Without Identity Center, managing large number of developers is an operational nightmare. Here is the comparison:

| Aspect | Without Identity Center | With Identity Center |
|--------|------------------------|---------------------|
| User Creation | Admin manually types 300 usernames + emails one by one | Click "Import Group" - all 300 users imported in seconds |
| Employee Offboarding | Admin must remember to delete key when someone leaves. Forgotten = security risk | Disable user in HR/IdP -> syncs to Identity Center -> admin revokes keys in periodic sync |
| Group/Team Setup | Admin manually creates every team and assigns every member | Engineering, QA, DataScience groups already exist - just import with budget settings |
| Security / Audit | Key is tied to a username string - no proof of identity | Key tied to verified corporate identity - audit trail meets SOC2/ISO 27001 |
| New Joiner Onboarding | HR notifies admin -> admin creates user manually -> delays of hours/days | HR adds user to Azure AD/Okta -> syncs to Identity Center -> next import run picks them up |
| Admin Overhead | HIGH - constant manual work as team changes | LOW - admin runs sync periodically or on-demand |

### 4.2 Enable IAM Identity Center

1. Go to AWS Console > IAM Identity Center > Click "Enable"
2. Choose identity source: "Identity Center directory" (built-in) OR connect an external IdP
3. For external IdP (Azure AD, Okta, Google Workspace): Settings > Identity source > Change > External identity provider
4. Note two values (you'll need these): Instance ARN and Identity Store ID (format: d-xxxxxxxxxx)
   - Instance ARN: `arn:aws:sso:::instance/ssoins-6595b27210834a74`
   - Identity Store ID: `d-xxxx`
5. The Identity Store ID goes into the IDENTITY_STORE_ID environment variable in docker-compose.yml

### 4.3 Create Users and Groups

Create groups that map to different access tiers (recommended group structure for your customer):

| Group Name | Budget/Month | Models Allowed | TPM Limit | Use Case |
|------------|-------------|----------------|-----------|----------|
| ClaudeCode-Engineering | $100 USD | Sonnet 4 + Haiku 4 | 200,000 | Full stack devs |
| ClaudeCode-DataScience | $200 USD | Sonnet 4 + Opus 4 | 300,000 | ML/AI engineers |
| ClaudeCode-QA | $25 USD | Haiku 4 only | 50,000 | Test automation |
| ClaudeCode-Senior | $300 USD | All models | 500,000 | Tech leads |
| ClaudeCode-Admins | Unlimited | All models | Unlimited | Administrators |

Console steps to create a group:

1. IAM Identity Center > Groups > Create group
2. Group name: ClaudeCode-Engineering, Description: Full-stack developers with Claude Code access
3. Click "Create group"
4. Open the group > Add users > search and select members
5. Repeat for each group tier

## 5. AWS Client VPN Setup — Developer Connectivity

### 5.1 Overview

AWS Client VPN creates an encrypted TLS tunnel from each developer's laptop directly into your VPC. Once connected, their laptop behaves as if it's physically inside the AWS network. This means they can reach the LiteLLM proxy using a private IP address, and traffic never touches the public internet.

### 5.2: Generate Certificates Using easy-rsa

Client VPN uses mutual TLS authentication. You need to generate a server certificate and a shared client certificate using easy-rsa. Instructions are provided for both Linux/macOS and Windows (PowerShell).

> **IMPORTANT (200+ Developers):** For large teams, use a single shared client certificate combined with SAML/SSO authentication (Section 4.9). Individual certificates per developer are operationally expensive at scale and are NOT recommended. The shared certificate proves "this device is authorized to connect" while SAML/SSO proves "this is a specific person."

#### 5.2.1 Linux / macOS Instructions

Run these commands on your local machine or use AWS CloudShell:

```bash
# Install easy-rsa
git clone https://github.com/OpenVPN/easy-rsa.git
cd easy-rsa/easyrsa3

# Step 1: Initialize PKI directory
./easyrsa init-pki

# Step 2: Build Certificate Authority (CA)
# When prompted for Common Name, enter: claude-code-vpn-ca
./easyrsa build-ca nopass

# Step 3: Generate Server Certificate
# When prompted for Common Name, use: server
./easyrsa build-server-full server nopass

# Step 4: Generate Shared Client Certificate (one for all developers)
# For individual certs, repeat with different names: dev-john, dev-jane, etc.
./easyrsa build-client-full client1.domain.tld nopass

# Your certificates are now at:
#   pki/ca.crt                          <- CA certificate
#   pki/issued/server.crt               <- Server certificate
#   pki/private/server.key              <- Server private key
#   pki/issued/client1.domain.tld.crt   <- Client certificate (shared)
#   pki/private/client1.domain.tld.key  <- Client private key (shared)
```

#### 5.2.2 Windows (PowerShell) Instructions

Follow these steps on a Windows laptop using PowerShell. The certificate naming conventions are identical to Linux/macOS so all downstream steps (4.3 onwards) work without any changes.

Prerequisites:
- Download EasyRSA for Windows from: https://github.com/OpenVPN/easy-rsa/releases
- Download the .zip file (e.g., EasyRSA-3.2.x-win64.zip) and extract to C:\easy-rsa
- Open PowerShell as Administrator

```powershell
# Step 0: Allow script execution (run once)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# Navigate to the extracted EasyRSA directory
cd C:\easy-rsa

# Set non-interactive mode (avoids manual prompts)
$env:EASYRSA_BATCH = "1"

# Step 1: Initialize PKI directory
$env:EASYRSA_REQ_CN = "claude-code-vpn-ca"

.\EasyRSA-Start.bat
# Inside the EasyRSA shell, run:
./easyrsa init-pki

# Step 2: Build Certificate Authority (CA)
# Common Name will be set to "claude-code-vpn-ca" via env var
./easyrsa build-ca nopass

# Exit EasyRSA shell when done
exit

# Step 3: Generate Server Certificate
$env:EASYRSA_REQ_CN = "server"
.\EasyRSA-Start.bat

./easyrsa --san=DNS:server build-server-full server nopass

# Exit EasyRSA shell when done
exit

# Step 4: Generate Shared Client Certificate
$env:EASYRSA_REQ_CN = "client1.domain.tld"
.\EasyRSA-Start.bat

./easyrsa build-client-full client1.domain.tld nopass

# Exit EasyRSA shell when done
exit

# Your certificates are at (same paths as Linux/macOS):
#   pki\ca.crt                          <- CA certificate
#   pki\issued\server.crt               <- Server certificate
#   pki\private\server.key              <- Server private key
#   pki\issued\client1.domain.tld.crt   <- Client certificate (shared)
#   pki\private\client1.domain.tld.key  <- Client private key (shared)
```

Output file locations on Windows:

| File | Windows Path |
|------|-------------|
| CA Certificate | C:\easy-rsa\pki\ca.crt |
| Server Certificate | C:\easy-rsa\pki\issued\server.crt |
| Server Private Key | C:\easy-rsa\pki\private\server.key |
| Client Certificate | C:\easy-rsa\pki\issued\client1.domain.tld.crt |
| Client Private Key | C:\easy-rsa\pki\private\client1.domain.tld.key |

#### 5.2.3 Windows PowerShell Batch Script (Automated)

For automating certificate generation for multiple developers, use the following PowerShell script. Update the $DEVELOPERS array with your team members:

```powershell
# Save as: Generate-Certificates.ps1
# Run: .\Generate-Certificates.ps1

$EasyRSAPath = "C:\easy-rsa"
$CA_COMMON_NAME = "claude-code-vpn-ca"
$OUTPUT_DIR = "C:\certificates\claude-code"

# For shared cert (recommended for 200+ developers):
$CLIENT_NAME = "client1.domain.tld"

# Set environment for non-interactive
$env:EASYRSA_BATCH = "1"
$env:EASYRSA = $EasyRSAPath

Push-Location $EasyRSAPath

# Initialize PKI
$env:EASYRSA_REQ_CN = $CA_COMMON_NAME
.\easyrsa init-pki

# Build CA
.\easyrsa build-ca nopass

# Build Server Certificate
$env:EASYRSA_REQ_CN = "server"
.\easyrsa build-server-full server nopass

# Build Shared Client Certificate
$env:EASYRSA_REQ_CN = $CLIENT_NAME
.\easyrsa build-client-full $CLIENT_NAME nopass

Pop-Location
Write-Host "Certificates generated successfully!" -ForegroundColor Green
```

### 5.3: Import Certificates to AWS Certificate Manager (ACM)

Go to AWS Console > Certificate Manager (ACM) > ap-south-1 region:

1. Click "Import certificate"
2. Certificate body: paste contents of pki/issued/server.crt
3. Certificate private key: paste contents of pki/private/server.key
4. Certificate chain: paste contents of pki/ca.crt
5. Click "Import". Note the Certificate ARN (e.g., arn:aws:acm:ap-south-1:123456:certificate/xxx)
6. Repeat the import for the client certificate (client1.domain.tld.crt + client1.domain.tld.key + ca.crt)

### 5.4 SAML/SSO Dual Authentication

This section provides complete instructions for configuring SAML/SSO authentication via IAM Identity Center alongside the shared mutual TLS certificate.

| Layer | Authentication Method | Proves |
|-------|----------------------|--------|
| Layer 1 | Shared Client Certificate (Mutual TLS) | "This device is authorized to connect" — Team-level gate. One shared certificate for all developers. |
| Layer 2 | SAML/SSO via IAM Identity Center | "This is a specific person" — User-level identity. Corporate credentials required. |
| Layer 3 | LiteLLM API Key (per-user) | "What is this person's budget and model access?" — Individual spend control. |

Benefits of this approach:
- Onboarding: Give new developer the shared .ovpn file; they log in with their existing SSO credentials immediately
- Offboarding: Disable IAM Identity Center account → instant VPN access revoked. No certificate rotation needed
- Audit: SAML provides individual user identity in CloudWatch VPN connection logs
- Compromised device: Disable user's SSO account; only rotate shared cert if the device itself is compromised
- Budget control: LiteLLM per-user API keys remain the individual spending control layer

#### 5.4.1 Create SAML Application in IAM Identity Center

Follow these steps to create a custom SAML 2.0 application in IAM Identity Center:

1. Navigate to IAM Identity Center > Applications > Add application
2. Select "I have an application I want to set up" > Custom SAML 2.0 application
3. Display name: AWS Client VPN - Claude Code
4. Description: VPN authentication for Claude Code Bedrock access
5. Application ACS URL: http://127.0.0.1:35001 (this is the AWS VPN Client callback address)
6. Application SAML audience: urn:amazon:webservices:clientvpn
7. Click "Submit" to create the application
8. Download the IAM Identity Center SAML metadata XML file (click "Download" under IAM Identity Center SAML metadata). Save as idp-metadata.xml
9. Configure attribute mappings (click "Edit attribute mappings"):

| Attribute | Maps to | Format |
|-----------|---------|--------|
| Subject | ${user:email} | emailAddress |
| memberOf | ${user:groups} | unspecified (for group-based authorization) |

#### 5.4.2 Create IAM SAML Identity Provider

1. Navigate to IAM > Identity providers > Add provider
2. Provider type: SAML
3. Provider name: IAMIdentityCenter-ClientVPN
4. Upload the metadata XML file downloaded in step 5.4.1 (idp-metadata.xml)
5. Click "Add provider"
6. Note the Provider ARN: `arn:aws:iam::<ACCOUNT_ID>:saml-provider/IAMIdentityCenter-ClientVPN`

Create NAT gateway and add it to the route table of the private subnet.
> Destination ip address while adding route in route table is 0.0.0.0

### 5.5: Create Client VPN Endpoint

Go to AWS Console > VPC > Client VPN Endpoints > Create Client VPN Endpoint.

For 200+ developers, configure dual authentication (Mutual TLS + SAML/SSO). This is the recommended option.

**Mutual TLS + SAML/SSO Dual Authentication:**

| Setting | Value |
|---------|-------|
| Name tag | claude-code-vpn |
| Client IPv4 CIDR | [IP_ADDRESS] (must not overlap with your VPC CIDR) |
| Server certificate ARN | Select the server certificate imported to ACM |
| Authentication type | Mutual authentication AND User-based authentication (Federated / SAML) |
| Client certificate ARN | Select the shared client certificate imported to ACM |
| SAML provider ARN | arn:aws:iam::<ACCOUNT_ID>:saml-provider/IAMIdentityCenter-ClientVPN (see Section 5.4.2 to copy this) |
| Connection logging | Enable > Create CloudWatch log group: /aws/clientvpn/connections |
| DNS servers | Leave empty (uses VPC DNS resolver automatically) |
| Split-tunnel | ENABLE - only VPC traffic routes through VPN (internet works normally) |
| VPC | Select the VPC where your private ALB runs |

#### 5.5.1: Associate Target Network

After creating the endpoint, you must associate it with a subnet so it knows where to route VPN traffic:

1. Select your newly created VPN endpoint > Actions > Associate target network
2. VPC: select your VPC
3. Subnet: select the subnet where private ALB runs (e.g., ap-south-1a private subnet)
4. Click Associate. Status will change to "Associating" > "Associated" (takes 5-10 minutes)

#### 5.5.2: Add Authorization Rules and Routes

**Authorization rule (who can access):**

1. Select endpoint > Authorization rules tab > Add authorization rule
2. Destination network: your VPC CIDR (e.g., [IP_ADDRESS])
3. Grant access to: All users
4. Click Add authorization rule

**Route entry:**

1. Select endpoint > Route table tab > Create route
2. Route destination: your VPC CIDR (e.g., [IP_ADDRESS])
3. Target VPC subnet: select the associated subnet
4. Click Create route

#### 5.5.3 Assign Users/Groups to the SAML Application

1. In IAM Identity Center > Applications > "AWS Client VPN - Claude Code"
2. Click "Assign users and groups"
3. Select the groups that should have VPN access: ClaudeCode-Engineering, ClaudeCode-DataScience, ClaudeCode-QA, ClaudeCode-Senior, ClaudeCode-Admins
4. Click "Assign"
5. Only users in these assigned groups will be able to authenticate via SAML — even if they have the .ovpn file

#### 5.5.4: Download and Prepare VPN Configuration File

The .ovpn file is what developers use to connect. It needs the shared client certificate embedded:

1. Select endpoint > Actions > Download client configuration
2. Open the downloaded .ovpn file in a text editor
3. Add the following at the END of the file (append after all existing content):

The .ovpn file format requires an additional directive for SAML authentication. The auth-federate directive triggers browser-based SSO when the developer connects.

```bash
# Open Git Bash, then:
# Download a fresh .ovpn from AWS Console first:
# Console: VPC → Client VPN Endpoints → Your endpoint → Download Client Configuration

# Then in Git Bash:
FRESH_OVPN="C:/Users/<username>/Downloads/downloaded-client-config.ovpn"
CLIENT_CERT="C:/Users/<username>/EasyRSA-3.2.6/pki/issued/client1.domain.tld.crt"
CLIENT_KEY="C:/Users/<username>/EasyRSA-3.2.6/pki/private/client1.domain.tld.key"
OUTPUT="C:/Users/<username>/Desktop/claude-vpn-final.ovpn"

# Build clean file
cp "$FRESH_OVPN" "$OUTPUT"
echo "" >> "$OUTPUT"
echo "<cert>" >> "$OUTPUT"
sed -n '/-----BEGIN CERTIFICATE-----/,/-----END CERTIFICATE-----/p' "$CLIENT_CERT" >> "$OUTPUT"
echo "</cert>" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo "<key>" >> "$OUTPUT"
cat "$CLIENT_KEY" >> "$OUTPUT"
echo "</key>" >> "$OUTPUT"

echo "Done! Use: $OUTPUT"
```

Recommended .ovpn file storage locations:

| OS | Recommended .ovpn File Location |
|----|-------------------------------|
| Windows | C:\Users\<username>\OpenVPN\config\claude-code-vpn.ovpn |
| Linux | ~/.config/openvpn/claude-code-vpn.ovpn  or  /etc/openvpn/client/ |
| macOS | ~/Library/Application Support/OpenVPN/config/ |

#### 5.5.5 Developer Connection Flow with SAML/SSO

Once SAML is configured, the developer connection flow is:

**Windows:**

1. Install AWS VPN Client from https://aws.amazon.com/vpn/client-vpn-download/ (Windows version)
2. Open AWS VPN Client > File > Manage Profiles > Add Profile
3. Display Name: "Claude Code - AWS"; VPN Configuration File: browse to claude-code-vpn.ovpn
4. Click Connect → A browser window opens automatically to your corporate SSO login page
5. Log in with corporate credentials (same as email/Okta/Azure AD)
6. Browser shows "Authentication successful" → return to VPN Client
7. VPN Client shows "Connected" (green indicator)

**Linux (Ubuntu/Debian):**

1. Install AWS VPN Client (.deb package from https://aws.amazon.com/vpn/client-vpn-download/) OR use OpenVPN:

```bash
# Ubuntu/Debian - install AWS VPN Client
sudo apt install ./awsvpnclient_amd64.deb

# Or use OpenVPN directly:
sudo apt install openvpn
sudo openvpn --config ~/claude-code-vpn.ovpn
```

2. Using AWS VPN Client on Linux: same GUI flow as Windows (browser opens for SSO)
3. Using OpenVPN CLI: browser will open automatically for SAML authentication
4. After SSO completes, VPN connects

#### 5.5.6 Verifying SAML Authentication in CloudWatch

After SAML is configured, CloudWatch VPN connection logs will show the authenticated username for every connection. Go to CloudWatch > Log groups > /aws/clientvpn/connections to verify:

```json
{
  "connection-log-type": "connection-attempt",
  "connection-attempt-status": "successful",
  "connection-id": "cvpn-connection-abc123",
  "client-vpn-endpoint-id": "cvpn-endpoint-xyz",
  "transport-protocol": "udp",
  "connection-start-time": "2026-05-24T10:30:00.000Z",
  "common-name": "client1.domain.tld",
  "username": "abc@company.com",
  "device-type": "win",
  "device-ip": "[IP_ADDRESS]",
  "port": "443",
  "ingress-bytes": "0",
  "egress-bytes": "0"
}
```

> **NOTE** The "username" field shows the SAML-authenticated identity. Combined with LiteLLM per-user logging, this gives you complete end-to-end audit from VPN connection through to Bedrock API usage.

## 6. AWS Console Infrastructure Setup

### 6.1 Create Security Groups

| Security Group | Direction | Port | Source/Dest | Purpose |
|---------------|-----------|------|-------------|---------|
| litellm-ec2-sg | Inbound | 8502 | litellm-alb-sg | Streamlit chat UI - users only |
| litellm-ec2-sg | Inbound | 4000 | litellm-alb-sg | LiteLLM proxy - developer traffic via VPN through VPC |
| litellm-ec2-sg | Inbound | 8501 | litellm-alb-sg | Streamlit Admin UI - admin only |
| litellm-ec2-sg | Outbound | 5432 | litellm-rds-sg | Allow EC2 to reach RDS |
| litellm-ec2-sg | Outbound | 443 | bedrock-vpce-sg | Allow EC2 to reach Bedrock VPC Endpoint |
| litellm-ec2-sg | Outbound | 443 | [IP_ADDRESS]/0 | S3 config pulls, Docker Hub pulls via NAT |
| litellm-rds-sg | Inbound | 5432 | litellm-ec2-sg (SG reference) | PostgreSQL from EC2 only |
| litellm-alb-sg | Inbound | 80 | VPC Client CIDR [IP_ADDRESS] | LiteLLM proxy - developer traffic via VPN through VPC |
| litellm-alb-sg | Outbound | 4000 | litellm-ec2-sg (SG reference) | LiteLLM proxy - developer traffic via VPN through VPC |
| litellm-alb-sg | Outbound | 8501 | litellm-ec2-sg (SG reference) | Streamlit Admin UI - admin only |
| litellm-alb-sg | Outbound | 8502 | litellm-ec2-sg (SG reference) | Streamlit chat UI - users only |
| bedrock-vpce-sg | Inbound | 443 | litellm-ec2-sg (SG reference) | HTTPS for Bedrock API from EC2 only |

### 6.2 Create IAM Role for EC2

Go to IAM > Roles > Create role:

1. Trusted entity: AWS service > EC2. Click Next
2. Click "Create policy" (opens new tab). Paste this JSON:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "BedrockAccess",
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream"
            ],
            "Resource": "*"
        },
        {
            "Sid": "S3ConfigAccess",
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:ListBucket"
            ],
            "Resource": "*"
        },
        {
            "Sid": "CloudWatchLogs",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:DescribeLogStreams",
                "logs:DescribeLogGroups"
            ],
            "Resource": "*"
        },
        {
            "Sid": "IdentityCenterReadWrite",
            "Effect": "Allow",
            "Action": [
                "identitystore:ListUsers",
                "identitystore:ListGroups",
                "identitystore:ListGroupMemberships",
                "identitystore:ListGroupMembershipsForMember",
                "identitystore:DescribeUser",
                "identitystore:DescribeGroup",
                "identitystore:CreateUser",
                "identitystore:DeleteUser",
                "identitystore:CreateGroup",
                "identitystore:DeleteGroup",
                "identitystore:CreateGroupMembership",
                "identitystore:DeleteGroupMembership"
            ],
            "Resource": "*"
        }
    ]
}
```

3. Policy name: LiteLLM-Claude-Code-Policy. Click Create policy
4. Back on the role creation page, refresh and search for LiteLLM-Claude-Code-Policy, select it
5. Role name: LiteLLM-Bedrock-EC2-Role. Click Create role

### 6.3 Create VPC Endpoint for Bedrock Runtime

This is the key step that keeps all Claude prompts and responses within the AWS network. Go to VPC console > Endpoints > Create endpoint:

| Setting | Value |
|---------|-------|
| Name tag | bedrock-runtime-vpce |
| Service category | AWS services |
| Service name | Search "bedrock" > select: com.amazonaws.us-east-1.bedrock-runtime |
| VPC | Same VPC as your EC2 instance |
| Subnets | Select the subnet(s) where EC2 runs |
| Security group | Use bedrock-vpce-sg |
| Policy | Full access (or restrict to specific model ARNs) |

> **NOTE** Also create a second VPC Endpoint for com.amazonaws.us-east-1.bedrock (the management API, separate from bedrock-runtime). This is needed for model listing calls.

### 6.4 Create RDS PostgreSQL Instance

Go to Amazon RDS console > Create database:

| Setting | Value |
|---------|-------|
| Engine type | PostgreSQL |
| Engine version | PostgreSQL 15.x (latest) |
| DB instance identifier | litellm-db |
| Master username | litellm_admin |
| Master password | Choose strong password (save it!). Use Secrets Manager for production |
| DB instance class | db.t3.medium |
| Storage | 20 GB GP3 (auto-scaling enabled) |
| VPC | Same VPC as your EC2 instance |
| Public access | NO - keep it private (only EC2 can connect) |
| VPC security group | Use created litellm-rds-sg |
| Initial database name | litellm |
| Encryption | Enable (KMS default key) |
| Backup retention | 7 days |

After creation, note the Endpoint address (format: litellm-db.xxxxx.ap-south-1.rds.amazonaws.com). You will use this in the DATABASE_URL environment variable.

### 6.5 Create S3 Bucket for Configuration

An S3 bucket is used to centrally store all configuration files. Every new EC2 instance launched by the Auto Scaling Group will pull this config at boot time, ensuring all instances run with identical configuration.

#### 6.5.1 Create the S3 Bucket

| Setting | Value |
|---------|-------|
| Bucket Name | litellm-config-<your-account-id> |
| Region | ap-south-1 (Mumbai) |
| Block Public Access | All options checked (all public access blocked) |
| Versioning | Optional but recommended (to track config changes) |
| Encryption | SSE-S3 (default) |

#### 6.5.2 Upload Configuration Files to S3

From your existing EC2 instance (or your local machine), upload the entire project directory to S3. Run the following AWS CLI commands:

```bash
# Replace YOUR_ACCOUNT_ID with your actual AWS Account ID
BUCKET="litellm-config-YOUR_ACCOUNT_ID"

# Upload litellm config
aws s3 cp litellm_config.yaml s3://${BUCKET}/litellm_config.yaml

# Upload docker-compose (after updating it per Step 3 below)
aws s3 cp docker-compose.yml s3://${BUCKET}/docker-compose.yml

# Upload custom callback
aws s3 cp custom_callback.py s3://${BUCKET}/custom_callback.py

# Upload Streamlit Admin Dashboard folder
aws s3 cp litellm-admin-dashboard/ s3://${BUCKET}/litellm-admin-dashboard/ --recursive

# Upload Claude Chat App folder
aws s3 cp claude-chat-app/ s3://${BUCKET}/claude-chat-app/ --recursive

# Verify all files are uploaded
aws s3 ls s3://${BUCKET}/ --recursive
```

### 6.6 Create Target Groups

Three target groups are required — one for each service. The Auto Scaling Group will register EC2 instances into all three target groups automatically.

Console path: EC2 → Target Groups → Create target group

#### 6.6.1 Target Group 1: litellm-proxy-tg (LiteLLM API)

| Setting | Value |
|---------|-------|
| Name | litellm-proxy-tg |
| Target Type | Instances |
| Protocol | HTTP |
| Port | 4000 |
| VPC | Select your existing VPC (litellm-vpc) |
| Health Check Protocol | HTTP |
| Health Check Path | /health/liveliness |
| Healthy Threshold | 2 |
| Unhealthy Threshold | 3 |
| Interval | 30 seconds |
| Timeout | 10 seconds |
| Success Codes | 200 |

#### 6.6.2 Target Group 2: streamlit-admin-tg (Admin Dashboard)

| Setting | Value |
|---------|-------|
| Name | streamlit-admin-tg |
| Target Type | Instances |
| Protocol | HTTP |
| Port | 8501 |
| VPC | Select your existing VPC (litellm-vpc) |
| Health Check Protocol | HTTP |
| Health Check Path | /admin/_stcore/health |
| Healthy Threshold | 2 |
| Unhealthy Threshold | 3 |
| Interval | 30 seconds |
| Timeout | 10 seconds |
| Success Codes | 200 |

#### 6.6.3 Target Group 3: claude-chat-tg (Chat App)

| Setting | Value |
|---------|-------|
| Name | claude-chat-tg |
| Target Type | Instances |
| Protocol | HTTP |
| Port | 8502 |
| VPC | Select your existing VPC (litellm-vpc) |
| Health Check Protocol | HTTP |
| Health Check Path | /chat/_stcore/health |
| Healthy Threshold | 2 |
| Unhealthy Threshold | 3 |
| Interval | 30 seconds |
| Timeout | 10 seconds |
| Success Codes | 200 |

### 6.7 Create Application Load Balancer

Create an private Application Load Balancer. For testing without a custom domain, you will use the auto-generated ALB DNS name (HTTP only). HTTPS and custom domain can be added in production.

Console path: EC2 → Load Balancers → Create load balancer → Application Load Balancer

| Setting | Value |
|---------|-------|
| Load Balancer Name | litellm-claude-code-alb |
| Scheme | Internal |
| IP Address Type | IPv4 |
| VPC | Select your existing VPC (litellm-vpc) |
| Availability Zones | Select ap-south-1a and ap-south-1b (check both checkboxes) |
| Subnets | Select private-subnet-1a (ap-south-1a) and private-subnet-1b (ap-south-1b) |
| Security Groups | Remove default; add litellm-alb-sg only |

#### 6.7.1 Listener Configuration

| Protocol | Port | Default Action |
|----------|------|---------------|
| HTTP | 80 | Forward to: litellm-proxy-tg (default — handles Claude Code CLI/IDE requests) |

> **PRODUCTION NOTE:** For production, add a second listener on port 443 (HTTPS) with an ACM certificate. Set the port 80 listener to redirect HTTP to HTTPS. The DNS name would then be an ACM-secured endpoint at your custom domain via Route 53.

#### 6.7.2 Record the ALB DNS Name

After the ALB is created, note down the auto-generated DNS name from the Load Balancer details page. It will look like:

```
litellm-claude-code-alb-1234567890.ap-south-1.elb.amazonaws.com
```

This DNS name is used in all developer configuration files and for accessing the Admin Dashboard and Chat App from a browser.

#### 6.7.3 Configure ALB Listener Rules (Path-Based Routing)

Add path-based routing rules to the HTTP:80 listener so the ALB can route requests to the correct service based on the URL path.

Console path: EC2 → Load Balancers → litellm-claude-code-alb → Listeners tab → HTTP:80 → View/edit rules

Click "Add rule" and create the following two rules. The default rule was already set when the ALB was created:

| Priority | Condition | Action | Service |
|----------|-----------|--------|---------|
| 1 | Path pattern is /admin* | Forward to: streamlit-admin-tg | Admin Dashboard |
| 2 | Path pattern is /chat* | Forward to: claude-chat-tg | Chat App |
| Default | All other requests (no condition) | Forward to: litellm-proxy-tg | LiteLLM API (Claude Code) |

#### 6.7.4 Resulting Access URLs

After the rules are configured, the three services will be accessible at the following URLs (replace ALB_DNS with your actual ALB DNS name):

| Service | URL | Who Uses It |
|---------|-----|-------------|
| LiteLLM API / Claude Code | http://<ALB_DNS>/ | Developers — VS Code / Terminal / IDE |
| Streamlit Admin Dashboard | http://<ALB_DNS>/admin | Admin only — manage users, budgets, keys |
| Claude Chat App | http://<ALB_DNS>/chat | Developers — browser-based chat with Claude |

### 6.8 Create Launch Template

The Launch Template defines the EC2 instance configuration used by the Auto Scaling Group. It includes the instance specifications and a User Data bootstrap script that automatically pulls config from S3 and starts all Docker services.

Console path: EC2 → Launch Templates → Create launch template

| Setting | Value |
|---------|-------|
| Launch Template Name | litellm-claude-code-lt |
| Template Version Description | ALB-based deployment with auto scaling |
| AMI | Amazon Linux 2023 AMI (x86_64) — latest version in ap-south-1 |
| Instance Type | t3.xlarge (same as current EC2) |
| Key Pair | Select your existing key pair (for SSH debugging access) |
| Security Groups | litellm-ec2-sg (the updated one from Step 3) |
| IAM Instance Profile | LiteLLM-Bedrock-EC2-Role (your existing IAM role) |
| Storage (Root Volume) | 100 GB GP3 — same as current instance |

#### 6.8.1 User Data Bootstrap Script

In the "Advanced details" section, paste the following script in the "User data" field. This script runs automatically when a new EC2 instance launches. It installs Docker, pulls the configuration from S3, and starts all containers.

```bash
#!/bin/bash
set -e

# Update system (--allowerasing fixes curl-minimal vs curl conflict on AL2023)
yum update -y --allowerasing

# Install Docker and tools
yum install -y docker git --allowerasing

# Start Docker
systemctl start docker
systemctl enable docker
usermod -aG docker ec2-user

# Install docker-compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Download correct x86_64 buildx
mkdir -p /usr/local/lib/docker/cli-plugins
curl -L "https://github.com/docker/buildx/releases/download/v0.21.2/buildx-v0.21.2.linux-amd64" -o /usr/local/lib/docker/cli-plugins/docker-buildx
chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx

# Create working directory
mkdir -p /home/ec2-user/claude-code-admin
cd /home/ec2-user/claude-code-admin

# Pull config from S3
aws s3 cp s3://litellm-config-123456/ . --recursive

# Set permissions
chown -R ec2-user:ec2-user /home/ec2-user/claude-code-admin

# Start services
docker-compose up -d

# Log completion
echo "$(date) - LiteLLM startup complete" >> /var/log/litellm-startup.log
```

> **IMPORTANT:** Before creating the Launch Template, replace YOUR_ACCOUNT_ID in the User Data script with your actual AWS Account ID. Also ensure the BUCKET variable matches the bucket name you created in Step 1.

### 6.9 Create Auto Scaling Group

The Auto Scaling Group manages the fleet of EC2 instances, automatically launching new instances when demand increases and terminating them when demand decreases. All instances automatically register with all three ALB target groups.

Console path: EC2 → Auto Scaling Groups → Create Auto Scaling group

| Setting | Value |
|---------|-------|
| Auto Scaling Group Name | litellm-claude-code-asg |
| Launch Template | litellm-claude-code-lt |
| Version | Latest (always uses newest version) |

**Network Configuration**

| Setting | Value |
|---------|-------|
| VPC | litellm-vpc (your existing VPC) |
| Availability Zones and Subnets | private-subnet-1a (ap-south-1a) and private-subnet-1b (ap-south-1b) |

> **NOTE:** EC2 instances are placed in private subnets. They are NOT directly accessible from the internet. Only the ALB (in private subnets) can reach them via the security group rules configured in Step 3.

**Load Balancing Configuration**

| Setting | Value |
|---------|-------|
| Load Balancer | Attach to an existing load balancer |
| Attach to Target Groups | litellm-proxy-tg, streamlit-admin-tg, claude-chat-tg (select all three) |
| Health Check Type | ELB (uses ALB health checks to determine instance health) |
| Health Check Grace Period | 180 seconds (allows Docker containers time to start up) |

**Group Size and Scaling**

| Parameter | Value |
|-----------|-------|
| Desired Capacity | 1 (for testing; set to 2 for production high availability) |
| Minimum Capacity | 1 (set to 2 in production) |
| Maximum Capacity | 4 (adjust based on expected concurrent users) |

**Scaling Policies**

Add a Target Tracking Scaling Policy to automatically scale based on CPU utilization:

| Parameter | Value |
|-----------|-------|
| Scaling Policy Type | Target tracking scaling policy |
| Scaling Policy Name | litellm-cpu-scaling-policy |
| Metric Type | Average CPU Utilization |
| Target Value | 60% (ASG adds instances when average CPU exceeds 60%) |
| Instance Warmup | 120 seconds (time for new instance to boot and register) |
| Disable scale in | Unchecked (allow scale-in when load drops) |

### 6.10 Launch EC2 Instance

Go to EC2 > Launch instance:

| Setting | Value |
|---------|-------|
| Name | litellm-claude-code-proxy |
| AMI | Amazon Linux 2023 (latest) - x86_64 |
| Instance type | t3.xlarge |
| Key pair | Select existing or create new. Download .pem file. Keep it secure |
| VPC/Subnet | Same VPC. Use a private subnet (EC2 connects to Bedrock via VPC Endpoint) |
| Auto-assign public IP | Enable only if you need direct admin access. Otherwise use VPN/bastion |
| Security group | Select litellm-ec2-sg |
| IAM instance profile | Advanced details > IAM instance profile > select LiteLLM-Bedrock-EC2-Role |
| Storage | 100 GB GP3 |
| Elastic IP | After launch: Allocate Elastic IP > Associate to this instance (stable IP for VPN routing) |

### 6.7 Install Docker and Docker Compose on EC2

```bash
# SSH into your EC2 instance via session manager

# Update the system
sudo yum update -y

# Install Docker
sudo yum install -y docker git
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ec2-user

# Install Docker Compose (latest)
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose

sudo chmod +x /usr/local/bin/docker-compose

# Log out and back in for docker group to take effect
exit

# Verify installation
docker --version        # Should show Docker version 24.x
docker-compose --version  # Should show Docker Compose version 2.x
```

## 7. LiteLLM Proxy Configuration

### 7.1 litellm_config.yaml

This is the complete LiteLLM configuration file. Save as ~/claude-code-admin/litellm_config.yaml:

### 7.2 docker-compose.yml

This file runs LiteLLM and the Streamlit Admin UI as Docker containers. Save as ~/claude-code-admin/docker-compose.yml:

### 7.3 Verify Deployment

```bash
# Launch all services
cd ~/claude-code-admin
docker-compose up -d

# Check container status
docker-compose ps
# Expected: litellm-proxy and litellm-admin-dashboard both showing "Up (healthy)"

# Test LiteLLM health
curl http://localhost:4000/health
# Expected: {"status": "healthy"}

# View logs if something is wrong
docker-compose logs -f litellm
docker-compose logs -f litellm-admin-dashboard

#if need to bring down container
docker-compose down
docker compose down --remove-orphons
docker-compose logs litellm --tail 50

#if need to delete container
docker system prune -a -f --volumes

# if need to restart
docker compose restart litellm
```

## 8. CloudWatch Integration — Per-User Audit Logs

### 8.1 Create CloudWatch Log Group (Console)

1. Go to CloudWatch > Log groups > Create log group
2. Log group name: /litellm/claude-code-usage
3. Retention setting: 90 days (adjust based on compliance requirements)
4. Click Create

### 8.2 Custom Detailed Logger

For more detailed per-user log streams and custom metadata, create custom_callback.py on your EC2. Mount it in the LiteLLM container:

### 8.3 What You See in CloudWatch

After deploying with CloudWatch callbacks, your log structure looks like this:

```
CloudWatch Log Groups:
/litellm/claude-code-usage
   |--- Log Stream: user-john.doe
   |       {"timestamp":"2025-05-20T09:15:23Z","event":"success","user_id":"john.doe",
   |        "model":"claude-sonnet-4","prompt_tokens":4521,"completion_tokens":892,
   |        "total_tokens":5413,"cost_usd":0.02982,"latency_seconds":8.4}
   |--- Log Stream: user-jane.smith
   |       {"timestamp":"2025-05-20T09:16:01Z","event":"success","user_id":"jane.smith",
   |        "model":"claude-haiku-4","total_tokens":1540,"cost_usd":0.00233}
   |--- Log Stream: team-engineering
           {"timestamp":"2025-05-20T09:16:01Z","team_id":"team-engineering-abc",...}
```

## 9. Streamlit Admin UI

### 9.1 Project Directory Structure

```
litellm-admin-dashboard/
├── Dockerfile
├── requirements.txt
├── app.py                          # Main dashboard page
├── auth.py
├── pages/
│   ├── 1_User_Management.py        # Add/remove users, generate keys, sync
│   ├── 2_Group_Management.py       # Create teams, import Identity Center groups
│   ├── 3_Budget_Controls.py        # Set/modify limits, bulk actions
│   ├── 4_Usage_Dashboard.py        # Real-time spend tracking, per-user logs
│   └── 5_Model_Management.py       # Configure available Bedrock models
    └── 6_Spend_Audit_History
├── utils/
│   ├── __init__.py
│   ├── litellm_client.py           # LiteLLM Admin API wrapper
│   └── identity_center.py          # IAM Identity Center helper
   └── config_loader
   └── spend_tracker
└── .streamlit/
    └── config.toml                 # AWS dark theme
    └── secrets.toml                # AWS dark theme
```

### 9.2 Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
# HEALTHCHECK CMD curl --fail http://localhost:8501/admin/_stcore/health || exit 1
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/admin/_stcore/health')" || exit 1
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=[IP_ADDRESS]","--server.baseUrlPath=/admin"]
```

### 9.3 requirements.txt

```
streamlit==1.38.0
pandas==2.2.2
requests==2.32.3
psycopg2-binary==2.9.9
pyyaml==6.0.1
boto3==1.35.0
```

### 9.4 .streamlit/config.toml

```toml
[theme]
primaryColor = "#FF9900"
backgroundColor = "#232F3E"
secondaryBackgroundColor = "#37475A"
textColor = "#FFFFFF"

[server]
headless = true
enableCORS = false
enableXsrfProtection = true
```

### 9.5 utils/litellm_client.py

Complete LiteLLM Admin API wrapper covering users, teams, keys, spend tracking, and model management:

### 9.6 utils/identity_center.py

### 9.7 app.py — Main Dashboard

The main Streamlit dashboard shows an overview of users, teams, models, and total spend. See the project directory structure in 9.1 for the full file layout. The app connects to LiteLLM using the LITELLM_API_URL and LITELLM_MASTER_KEY environment variables.

## 10. Developer Onboarding Instructions

Share this section with each developer. The steps assume Client VPN has been set up and the admin has already created their user account and generated an API key.

### 10.1 Step 1: Install AWS VPN Client

Download and install the official AWS VPN Client:

1. Windows: https://aws.amazon.com/vpn/client-vpn-download/ -> "AWS VPN Client for Windows"
2. macOS: https://aws.amazon.com/vpn/client-vpn-download/ -> "AWS VPN Client for macOS"
3. Linux: Download the .deb/.rpm package from the same URL, or use OpenVPN with the .ovpn file directly

### 10.2 Step 2: Import VPN Configuration

1. Admin provides you with a .ovpn file via secure channel (email with password, Slack DM, etc.)
2. Open AWS VPN Client
3. Click File > Manage Profiles
4. Click "Add Profile"
5. Display name: "Claude Code - AWS" (or any name you prefer)
6. VPN configuration file: browse to and select the .ovpn file
7. Click "Add Profile"

### 10.3 Step 3: Connect to VPN

Connecting to VPN with SAML/SSO authentication (recommended for 200+ developer deployments):

**Windows:**

1. In the AWS VPN Client, select "Claude Code - AWS" from the dropdown
2. Click "Connect"
3. A browser window opens automatically → log in with your corporate SSO credentials (same as email/Okta/Azure AD)
4. Browser shows "Authentication successful" → return to VPN Client
5. VPN Client shows "Connected" (green indicator)

**Linux:**

1. Using AWS VPN Client: same steps as Windows above
2. Using OpenVPN CLI: run "sudo openvpn --config ~/claude-code-vpn.ovpn"
3. A browser window opens for SAML authentication → log in with corporate credentials
4. After SSO completes, VPN connects in the terminal

> **NOTE** If your deployment uses mutual-auth-only (without SAML), the VPN connects directly without opening a browser. For dual-auth (Mutual TLS + SAML), the browser SSO step is mandatory and appears automatically on every new connection.

### 10.4 Step 4: Configure Claude Code in IDE

Set these environment variables in your terminal (or add to your shell profile for permanence):

```json
// if claude code cli is installed then find the below folder and paste this json
// ~/.claude/settings.json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://paste alb dns name here",
    "ANTHROPIC_API_KEY": "sk-<your-key-from-admin>"
  }
}
```

```bash
# Linux / macOS - add to ~/.bashrc or ~/.zshrc for permanent setup
export ANTHROPIC_BASE_URL=http://paste alb dns name here
export ANTHROPIC_API_KEY=sk-<your-key-from-admin>

# Windows PowerShell
$env:ANTHROPIC_BASE_URL = "http://paste alb dns name here"
$env:ANTHROPIC_API_KEY = "sk-<your-key-from-admin>"

# Windows Command Prompt
set ANTHROPIC_BASE_URL=http://paste alb dns name here
set ANTHROPIC_API_KEY=sk-<your-key-from-admin>

# For VS Code: add to .vscode/settings.json in your project
# "terminal.integrated.env.linux": {
#   "ANTHROPIC_BASE_URL": "http://paste alb dns name here",
#   "ANTHROPIC_API_KEY": "sk-<your-key-from-admin>"
# }
```

### 10.5 Step 5: Launch Claude Code

```bash
# Make sure VPN is connected first!

# Launch Claude Code from terminal
claude

# Or use it inline
claude "Explain this function and suggest improvements"

# In VS Code: the Claude Code extension automatically picks up ANTHROPIC_BASE_URL
# and ANTHROPIC_API_KEY from environment variables
```

### 10.6 What Happens When Budget Is Exhausted

When a developer has used up their monthly budget, Claude Code will return an error like: "Budget exceeded for user john.doe. Current spend: $50.00, limit: $50.00"

Action: Contact your admin. The admin will either:

1. Increase your max budget in the Streamlit Admin UI (Budget Controls page)
2. Reset your spend counter to $0 for the current period
3. Both - increasing the budget AND resetting spend

After the admin makes the change, your next Claude Code request will work immediately after 5 minutes. No restart required.

## 11. Security Best Practices

1. Rotate the LiteLLM master key (LITELLM_MASTER_KEY) quarterly using docker-compose down && update env && docker-compose up
2. Set key expiration for user API keys: use duration="90d" in generate_key() for 90-day auto-expiry
3. Enable VPC Flow Logs on your VPC to capture all network traffic metadata for audit
4. Restrict Streamlit UI (port 8501) to admin IPs only via security group
5. Use AWS Secrets Manager instead of plain env vars for DATABASE_URL and LITELLM_MASTER_KEY in production
6. Enable MFA for the IAM Identity Center - developers must have MFA to authenticate
7. Store .ovpn files in a secrets manager; do not email them without encryption
8. Enable RDS encryption at rest (KMS) - this is set at creation time and cannot be changed after
9. Regularly run IAM Access Analyzer to detect overly permissive policies on the EC2 role
10. Consider placing LiteLLM behind an Application Load Balancer (ALB) with HTTPS for production (add ACM c
