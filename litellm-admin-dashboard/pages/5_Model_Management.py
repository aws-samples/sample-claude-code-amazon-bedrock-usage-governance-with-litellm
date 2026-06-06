"""
litellm-admin-dashboard/pages/5_Model_Management.py

Streamlit page: Model Management.

What it does:
  - Tab 1 — View Models: lists every Bedrock model currently registered in the
    LiteLLM proxy, showing the display name, Bedrock ARN/model ID, AWS region,
    input/output pricing in $/token and $/1M tokens, and max token limits.
    A summary pricing table at the bottom allows quick cost comparison across
    all models.
  - Tab 2 — Add Model: form to register a new Amazon Bedrock model or inference
    profile with the LiteLLM proxy at runtime — no container restart needed.
    Accepts a display name, Bedrock model ID or inference profile ARN, region,
    per-token pricing, and token limits. On submit calls the LiteLLM /model/new
    API. A reference table below the form shows the models already in config.yaml
    as a quick lookup for correct Bedrock IDs.

New models added here are immediately available for assignment to users and
teams via the User Management and Group Management pages.

Depends on:
  utils/litellm_client.py  — list_models(), add_model().
  utils/config_loader.py   — get_model_reference() and get_aws_regions() for
                             the form dropdown and reference table.
"""
import streamlit as st
import pandas as pd
from utils.litellm_client import LiteLLMClient
from utils.config_loader import get_model_reference, get_aws_regions

st.set_page_config(page_title="Model Management", page_icon="🤖", layout="wide")
st.title("🤖 Model Management")

client = LiteLLMClient()

# Load configuration
MODEL_REFERENCE = get_model_reference()
AWS_REGIONS = get_aws_regions()

tab1, tab2 = st.tabs(["📋 View Models", "➕ Add Model"])

# ========== TAB 1: View Configured Models ==========
with tab1:
    st.subheader("Currently Configured Bedrock Models")
    try:
        models_response = client.list_models()
        models = models_response.get("data", [])

        if not models:
            st.info("No models configured. Add models in the 'Add Model' tab or via litellm_config.yaml")
        else:
            for model in models:
                model_name = model.get("model_name", "Unknown")
                model_info = model.get("model_info", {})
                litellm_params = model.get("litellm_params", {})

                input_cost = model_info.get("input_cost_per_token", 0)
                output_cost = model_info.get("output_cost_per_token", 0)
                max_tokens = model_info.get("max_tokens", "N/A")
                max_input = model_info.get("max_input_tokens", "N/A")
                region = litellm_params.get("aws_region_name", "N/A")
                bedrock_model = litellm_params.get("model", "N/A")

                with st.expander(f"🤖 {model_name} — Region: {region}"):
                    col1, col2, col3 = st.columns(3)

                    with col1:
                        st.write("**Configuration**")
                        st.write(f"- Display Name: `{model_name}`")
                        st.write(f"- Bedrock ID: `{bedrock_model}`")
                        st.write(f"- Region: `{region}`")

                    with col2:
                        st.write("**Pricing**")
                        st.write(f"- Input: ${input_cost:.8f}/token")
                        st.write(f"- Output: ${output_cost:.8f}/token")
                        st.write(f"- Input: ${input_cost * 1_000_000:.2f}/1M tokens")
                        st.write(f"- Output: ${output_cost * 1_000_000:.2f}/1M tokens")

                    with col3:
                        st.write("**Limits**")
                        st.write(f"- Max Output Tokens: {max_tokens}")
                        st.write(f"- Max Input Tokens: {max_input}")

            # Summary table
            st.divider()
            st.write("### Model Pricing Summary")
            summary_data = []
            for model in models:
                model_info = model.get("model_info", {})
                input_cost = model_info.get("input_cost_per_token", 0)
                output_cost = model_info.get("output_cost_per_token", 0)
                summary_data.append({
                    "Model": model.get("model_name", ""),
                    "Input ($/1M)": f"${input_cost * 1_000_000:.2f}",
                    "Output ($/1M)": f"${output_cost * 1_000_000:.2f}",
                    "Region": model.get("litellm_params", {}).get("aws_region_name", ""),
                    "Max Output": model_info.get("max_tokens", "N/A")
                })
            st.dataframe(pd.DataFrame(summary_data), use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Error fetching models: {e}")

# ========== TAB 2: Add New Model ==========
with tab2:
    st.subheader("Add New Bedrock Model")
    st.info("Add a new model to LiteLLM. It will be available based on user/team model access settings.")

    with st.form("add_model_form"):
        st.write("**Model Configuration**")
        new_model_name = st.text_input(
            "Model Display Name",
            placeholder="claude-sonnet-4-6",
            help="Name developers use in API calls"
        )
        new_bedrock_id = st.text_input(
            "Bedrock Model ID or Inference Profile ARN",
            placeholder="anthropic.claude-sonnet-4-20250514-v1:0",
            help="Bedrock model ID or full inference profile ARN"
        )
        new_region = st.selectbox("AWS Region", AWS_REGIONS, index=0)

        st.divider()
        st.write("**Pricing**")
        col1, col2 = st.columns(2)
        with col1:
            new_input_cost = st.number_input(
                "Input Cost ($/token)", min_value=0.0,
                value=0.000003, step=0.000001, format="%.8f"
            )
        with col2:
            new_output_cost = st.number_input(
                "Output Cost ($/token)", min_value=0.0,
                value=0.000015, step=0.000001, format="%.8f"
            )

        st.divider()
        st.write("**Token Limits**")
        col3, col4 = st.columns(2)
        with col3:
            new_max_tokens = st.number_input("Max Output Tokens", min_value=1000, value=64000, step=1000)
        with col4:
            new_max_input = st.number_input("Max Input Tokens", min_value=1000, value=200000, step=10000)

        submitted = st.form_submit_button("➕ Add Model", type="primary")
        if submitted:
            if not new_model_name or not new_bedrock_id:
                st.error("Model name and Bedrock Model ID are required.")
            else:
                try:
                    model_path = f"bedrock/{new_bedrock_id}"
                    result = client.add_model(
                        model_name=new_model_name,
                        litellm_params={
                            "model": model_path,
                            "aws_region_name": new_region
                        },
                        model_info={
                            "max_tokens": new_max_tokens,
                            "max_input_tokens": new_max_input,
                            "input_cost_per_token": new_input_cost,
                            "output_cost_per_token": new_output_cost
                        }
                    )
                    st.success(f"✅ Model '{new_model_name}' added!")
                except Exception as e:
                    st.error(f"Failed: {e}")

    st.divider()
    st.write("### Common Bedrock Model IDs (Reference)")
    if MODEL_REFERENCE:
        ref_data = {
            "Model": [m["name"] for m in MODEL_REFERENCE],
            "Bedrock Model ID": [m["bedrock_model_id"] for m in MODEL_REFERENCE],
            "Input ($/1M)": [f"${m['input_cost_per_million']:.2f}" for m in MODEL_REFERENCE],
            "Output ($/1M)": [f"${m['output_cost_per_million']:.2f}" for m in MODEL_REFERENCE],
        }
        st.dataframe(pd.DataFrame(ref_data), use_container_width=True, hide_index=True)

