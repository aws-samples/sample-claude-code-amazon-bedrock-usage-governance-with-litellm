
# 1. Developer Onboarding Instructions

Share this section with each developer. The steps assume Client VPN has been set up and the admin has already created their user account and generated an API key.

## 1.1 Step 1: Install AWS VPN Client

Download and install the official AWS VPN Client:

1. **Windows:** https://aws.amazon.com/vpn/client-vpn-download/ → "AWS VPN Client for Windows"
2. **macOS:** https://aws.amazon.com/vpn/client-vpn-download/ → "AWS VPN Client for macOS"
3. **Linux:** Download the .deb/.rpm package from the same URL, or use OpenVPN with the .ovpn file directly

## 1.2 Step 2: Import VPN Configuration

1. Admin provides you with a `.ovpn` file via secure channel (email with password, Slack DM, etc.)
2. Open AWS VPN Client
3. Click **File > Manage Profiles**
4. Click **"Add Profile"**
5. Display name: `"Claude Code - AWS"` (or any name you prefer)
6. VPN configuration file: browse to and select the `.ovpn` file
7. Click **"Add Profile"**

## 1.3 Step 3: Connect to VPN

Connecting to VPN with SAML/SSO authentication (recommended for 200+ developer deployments):

**Windows:**

1. In the AWS VPN Client, select "Claude Code - AWS" from the dropdown
2. Click "Connect"
3. A browser window opens automatically → log in with your corporate SSO credentials (same as email/Okta/Azure AD)
4. Browser shows "Authentication successful" → return to VPN Client
5. VPN Client shows "Connected" (green indicator)

**Linux:**

1. Using AWS VPN Client: same steps as Windows above
2. Using OpenVPN CLI: run `sudo openvpn --config ~/claude-code-vpn.ovpn`
3. A browser window opens for SAML authentication → log in with corporate credentials
4. After SSO completes, VPN connects in the terminal

> **NOTE:** If your deployment uses mutual-auth-only (without SAML), the VPN connects directly without opening a browser. For dual-auth (Mutual TLS + SAML), the browser SSO step is mandatory and appears automatically on every new connection.

## 1.4 Step 4: Configure Claude Code in IDE

Set these environment variables in your terminal (or add to your shell profile for permanence):

If Claude Code CLI is installed then find the below folder and paste this json:

**~/.claude/settings.json**

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://<alb dns name>",
    "ANTHROPIC_API_KEY": "sk-<your-key-from-admin>"
  }
}
```

```bash
# Linux / macOS - add to ~/.bashrc or ~/.zshrc for permanent setup
export ANTHROPIC_BASE_URL=http://<alb dns name>
export ANTHROPIC_API_KEY=sk-<your-key-from-admin>
```

```powershell
# Windows PowerShell
$env:ANTHROPIC_BASE_URL = "http://<alb dns name>"
$env:ANTHROPIC_API_KEY = "sk-<your-key-from-admin>"
```

```cmd
# Windows Command Prompt
set ANTHROPIC_BASE_URL=http://<alb dns name>
set ANTHROPIC_API_KEY=sk-<your-key-from-admin>
```

```json
// For VS Code: add to .vscode/settings.json in your project
{
  "terminal.integrated.env.linux": {
    "ANTHROPIC_BASE_URL": "http://<alb dns name>",
    "ANTHROPIC_API_KEY": "sk-<your-key-from-admin>"
  }
}
```

## 1.5 Step 5: Launch Claude Code

```bash
# Make sure VPN is connected first!

# Launch Claude Code from terminal
claude

# Or use it inline
claude "Explain this function and suggest improvements"

# In VS Code: the Claude Code extension automatically picks up ANTHROPIC_BASE_URL
# and ANTHROPIC_API_KEY from environment variables
```
