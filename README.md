# HMPPS Veracode Discovery

`hmpps-veracode-discovery` is a scheduled Python job that queries Veracode for the latest SAST scan information for HMPPS services and publishes that data to the Service Catalogue.

The job does the following:

- Reads all components from the HMPPS Service Catalogue.
- Looks up matching Veracode applications by component name.
- Retrieves Veracode summary report data for matched applications.
- Updates each Service Catalogue component with Veracode metadata.

The published data is visible in the HMPPS Developer Portal, for example:

[https://developer-portal.hmpps.service.justice.gov.uk/components/veracode](https://developer-portal.hmpps.service.justice.gov.uk/components/veracode)

## Veracode API Integration

This job depends directly on the Veracode API to retrieve scan and policy data.

- Base URL: `https://api.veracode.com`
- Authentication: `veracode-api-signing` (HMAC request signing)
- Required credentials:
	- `VERACODE_API_KEY_ID`
	- `VERACODE_API_KEY_SECRET`

API calls used by this service:

- Health check: `GET /healthcheck/status`
- Application lookup by component name: `GET /appsec/v1/applications?name=<component_name>`
- Summary report by Veracode GUID: `GET /appsec/v2/applications/<guid>/summary_report`

If Veracode credentials are missing, the job exits with failure. If a component lookup or summary report call is unsuccessful, that component is skipped and the remaining components continue processing.

## Data Written To Service Catalogue

For each matched component, the job attempts to populate:

- `veracode_results_url`
- `veracode_last_completed_scan_date`
- `veracode_results_summary`
- `veracode_policy_rules_status`
- `veracode_exempt` (set to `false` when report data is found)

If a component has no matching Veracode application or the API response is unsuccessful, that component is skipped and processing continues.

## Runtime and Dependencies

- Python: `>=3.13`
- Dependency management and execution: `uv`
- Key dependencies:
	- `hmpps-sre-python-lib`
	- `veracode-api-signing==26.5.0`

Entrypoint:

- `veracode_discovery.py`

Container command:

- `uv run python -u veracode_discovery.py`

## Required Environment Variables

The job requires the following environment variables:

- `SERVICE_CATALOGUE_API_ENDPOINT`
- `SERVICE_CATALOGUE_API_KEY`
- `VERACODE_API_KEY_ID`
- `VERACODE_API_KEY_SECRET`
- `SLACK_BOT_TOKEN`

Optional runtime configuration:

- `LOG_LEVEL` (for example `debug` in dev, `info` in prod)
- `SC_FILTER` (set in dev values as a namespace secret key reference)
- Slack channel variables passed during deployment:
	- `SLACK_NOTIFY_CHANNEL`
	- `SLACK_ALERT_CHANNEL`

## Local Development

Install dependencies:

```bash
uv sync
```

Run the job:

```bash
uv run python -u veracode_discovery.py
```

Run tests:

```bash
uv run pytest
```

## Deployment

Deployment is Kubernetes-based using Helm chart files under `helm_deploy/hmpps-veracode-discovery`.

The CronJob schedule is environment-specific:

- Dev: `25 3,9,15,21 * * *`
- Prod: `25 */6 * * *`

Primary CI/CD workflows:

- `.github/workflows/pipeline.yml` (test/lint/build/deploy)
- `.github/workflows/deploy_to_env.yml` (manual deployment)

## Repository Structure

- `veracode_discovery.py`: main scheduled job.
- `test_veracode_discovery.py`: unit tests.
- `helm_deploy/`: Helm chart and per-environment values.
- `Dockerfile`: container image definition.
- `pyproject.toml`: Python project metadata and dependencies.
