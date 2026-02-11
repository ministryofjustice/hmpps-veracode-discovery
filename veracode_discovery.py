#!/usr/bin/env python
"""Github discovery - queries the github API for info about hmpps services and
stores the results in the service catalogue"""

import os
import threading
from time import sleep
from veracode_api_signing.plugin_requests import RequestsAuthPluginVeracodeHMAC
import requests
from hmpps import ServiceCatalogue, Slack
from hmpps.services.job_log_handling import (
  log_debug,
  log_error,
  log_info,
  log_warning,
  log_critical,
  job,
)

# Set maximum number of concurrent threads to run, try to avoid secondary
# github api limits.
MAX_THREADS = 5

# Other globals
VERACODE_API_KEY_ID = os.getenv('VERACODE_API_KEY_ID')
VERACODE_API_KEY_SECRET = os.getenv('VERACODE_API_KEY_SECRET')
VERACODE_API_BASE = 'https://api.veracode.com'
VERACODE_HEADERS = {'User-Agent': 'Python HMAC script'}


def run_veracode_connection(sc, slack):
  # Test connection to veracode
  if not VERACODE_API_KEY_ID:
    slack.alert('VERACODE_API_KEY_ID environment variable not set')
    job.error_messages.append('VERACODE_API_KEY_ID environment variable not set')
    sc.update_scheduled_job('Failed')
    raise SystemExit(
      'hmpps-veracode-discovery failed: '
      'VERACODE_API_KEY_ID environment variable not set'
    )

  if not VERACODE_API_KEY_SECRET:
    slack.alert('VERACODE_API_KEY_SECRET environment variable not set')
    job.error_messages.append('VERACODE_API_KEY_SECRET environment variable not set')
    sc.update_scheduled_job('Failed')
    raise SystemExit(
      'hmpps-veracode-discovery failed: '
      'VERACODE_API_KEY_SECRET environment variable not set'
    )
  try:
    response = requests.get(
      VERACODE_API_BASE + '/healthcheck/status',
      auth=RequestsAuthPluginVeracodeHMAC(),
      headers=VERACODE_HEADERS,
      timeout=30,
    )
    if response.status_code == 200:
      log_debug('Veracode connection test successful.')
      return response
  except Exception as e:
    log_critical('Unable to connect to the veracode API.')
    slack.alert('Unable to connect to the veracode API.')
    job.error_messages.append('Unable to connect to the veracode API')
    sc.update_scheduled_job('Failed')
    raise SystemExit(e) from e


def process_component(component, sc):
  c_name = component.get('name')
  c_id = component.get('documentId')
  log_info(f'Processing component: {c_name} ({c_id})')

  # Fetch Veracode data
  try:
    response = fetch_veracode_data(c_name)
  except Exception as e:
    log_error(f'Error fetching Veracode data for {c_name}: {e}')
    job.error_messages.append(f'Error fetching Veracode data for {c_name}: {e}')
    return None

  # Parse the response
  try:
    data, veracode_guid = parse_veracode_response(response, c_name)
    if not data:
      log_info(f'No Veracode data for {c_name} - skipping.')
      return None
  except Exception as e:
    log_error(f'Failed to parse Veracode data for {c_name}: {e}')
    return None
  log_debug(f'Veracode data for {c_name}: {data}')

  # Fetch Veracode summary report
  if veracode_guid:
    data = get_veracode_summary_report(veracode_guid, c_name, data)
    if not data:
      log_info(f'No Veracode summary report for {c_name} - skipping.')
      return None
    log_debug(f'Veracode summary report data for {c_name}: {data}')

  # Update component in Service Catalogue
  sc.update('components', c_id, data)


def fetch_veracode_data(c_name):
  url = f'{VERACODE_API_BASE}/appsec/v1/applications?name={c_name}'
  try:
    response = requests.get(
      url,
      auth=RequestsAuthPluginVeracodeHMAC(),
      headers=VERACODE_HEADERS,
      timeout=30,
    )
  except requests.RequestException as e:
    log_error(f'error in response from veracode for {c_name}: (e)')
    job.error_messages.append(f'error in response from veracode for {c_name}: (e)')
    return None

  if not response.ok:
    log_warning(
      f'Veracode API returned an unexpected response looking for {c_name} GUID: '
      f'{response.status_code}'
    )
    return None
  else:
    log_debug(f'Veracode API response for {c_name} received successfully.')
    return response


def parse_veracode_response(response, c_name):
  data = {}
  veracode_guid = None

  response_json = response.json()
  if app_list := response_json.get('_embedded', {}).get('applications', []):
    for app in app_list:
      if app['profile']['name'] == c_name:
        veracode_guid = app['guid']
        data['veracode_results_url'] = (
          f'https://analysiscenter.veracode.com/auth/index.jsp#{app["results_url"]}'
        )
        data['veracode_last_completed_scan_date'] = app['last_completed_scan_date']
        log_debug(f'Found Veracode app GUID: {veracode_guid}')
        break

  if not veracode_guid:
    log_info(f'No veracode scan found for {c_name}')
    return None, None

  return data, veracode_guid


def get_veracode_summary_report(veracode_guid, c_name, data):
  try:
    response = requests.get(
      VERACODE_API_BASE + f'/appsec/v2/applications/{veracode_guid}/summary_report',
      auth=RequestsAuthPluginVeracodeHMAC(),
      headers=VERACODE_HEADERS,
      timeout=30,
    )
    if response.ok:
      try:
        results_summary_data = response.json()
        data['veracode_results_summary'] = results_summary_data
        data['veracode_policy_rules_status'] = results_summary_data[
          'policy_rules_status'
        ]
        data['veracode_exempt'] = False
      except ValueError as e:
        log_debug(f'Unable to extract summary data from veracode: {e}')
      return data
    else:
      log_warning(
        f'Failure response from Veracode for {c_name} (GUID: {veracode_guid}): '
        f'{response.status_code}'
      )
      return None
  except requests.RequestException as e:
    log_warning(
      f'Veracode API returned an unexpected response looking for a {c_name} '
      f'(GUID {veracode_guid}) summary report: {e}'
    )
    return None


def process_components(data, sc):
  log_info(f'Processing batch of {len(data)} components...')
  threads = []
  for component in data:
    component_name = component.get('name')
    t_repo = threading.Thread(
      target=process_component, args=(component, sc), daemon=True
    )
    threads.append(t_repo)

    # Apply limit on total active threads, avoid github secondary API rate limit
    while threading.active_count() > (MAX_THREADS - 1):
      log_debug(f'Active Threads={threading.active_count()}, Max Threads={MAX_THREADS}')
      sleep(10)

    t_repo.start()
    log_info(f'Started thread for {component_name}')

  for t in threads:
    t.join()
  log_info(f'Finished all threads for batch of {len(data)} components.')


def main():
  # service catalogue parameters

  job.name = 'hmpps-veracode-discovery'

  slack = Slack()
  sc = ServiceCatalogue()

  if not sc.connection_ok:
    log_error('Service Catalogue connection not OK, exiting.')
    slack.alert('hmpps-veracode-discovery failed: unable to reach Service Catalogue')
    raise SystemExit

  run_veracode_connection(sc=sc, slack=slack)

  components = sc.get_all_records(sc.components_get)
  process_components(components, sc=sc, slack=slack)

  if job.error_messages:
    sc.update_scheduled_job('Errors')
    log_info('Veracode discovery job completed  with errors.')
  else:
    sc.update_scheduled_job('Succeeded')
    log_info('Veracode discovery job completed successfully.')


if __name__ == '__main__':
  main()
