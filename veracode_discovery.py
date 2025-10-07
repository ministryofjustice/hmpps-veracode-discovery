#!/usr/bin/env python
"""Github discovery - queries the github API for info about hmpps services and stores the results in the service catalogue"""

import os
import threading
import logging
from time import sleep
from veracode_api_signing.plugin_requests import RequestsAuthPluginVeracodeHMAC
import requests
from hmpps import ServiceCatalogue, Slack
from hmpps.services.job_log_handling import log_critical, log_error, log_warning, log_info, log_debug, job

SC_API_ENDPOINT = os.getenv('SERVICE_CATALOGUE_API_ENDPOINT')
SC_API_TOKEN = os.getenv('SERVICE_CATALOGUE_API_KEY')

# Set maximum number of concurrent threads to run, try to avoid secondary github api limits.
MAX_THREADS = 5

# limit results for testing/dev
# See strapi filter syntax https://docs.strapi.io/dev-docs/api/rest/filters-locale-publication
# Example filter string = '&filters[name][$contains]=example'
SC_FILTER = os.getenv('SC_FILTER', '')

VERACODE_API_KEY_ID = os.getenv('VERACODE_API_KEY_ID')
VERACODE_API_KEY_SECRET = os.getenv('VERACODE_API_KEY_SECRET')
VERACODE_API_BASE = 'https://api.veracode.com'
VERACODE_HEADERS = {'User-Agent': 'Python HMAC script'}

class Services:
  def __init__(self, sc_params, slack_params):
    self.slack = Slack(slack_params)
    self.sc = ServiceCatalogue(sc_params)

def process_component(component, services):
  sc = services.sc
  c_name = component.get('name')
  c_id = component.get('documentId')
  log_info(f'Processing component: {c_name} ({c_id})')
  # Empty data dict gets populated along the way, and finally used in PUT request to service catalogue
  data = {}
  veracode_guid = None

  try:
    response = requests.get(
      VERACODE_API_BASE + f'/appsec/v1/applications?name={c_name}',
      auth=RequestsAuthPluginVeracodeHMAC(),
      headers=VERACODE_HEADERS,
      timeout=30,
    )
  except requests.RequestException as e:
    log_error(f'error in response from veracode for {c_name}: (e)')
    job.error_messages.append(f'error in response from veracode for {c_name}: (e)')
    return None
  
  if response.ok:
    try:
      veracode_r = response.json()
      # Valid data is within the _embedded dictionary
      if app_list := veracode_r.get('_embedded'):
        for app in app_list.get('applications'):
          if app['profile']['name'] == c_name:
            veracode_guid = app['guid']
            veracode_results_url = (
              'https://analysiscenter.veracode.com/auth/index.jsp#' + app['results_url']
            )
            data.update({'veracode_results_url': veracode_results_url})
            veracode_last_completed_scan_date = app['last_completed_scan_date']
            data.update(
              {'veracode_last_completed_scan_date': veracode_last_completed_scan_date}
            )
            log_debug(f'Found vericode app guid: {veracode_guid}')
            break
      else:
        log_info(f'No veracode data for {c_name} - skipping.')
        return None

    except Exception as e:
        log_info(f'Failed to extract veracode data: {e}')
  else:
    log_warning(
      f'Veracode API returned an unexpected response looking for {c_name} GUID: {response.status_code}'
    )

  if veracode_guid:
    try:
      veracode_r = requests.get(
        VERACODE_API_BASE + f'/appsec/v2/applications/{veracode_guid}/summary_report',
        auth=RequestsAuthPluginVeracodeHMAC(),
        headers=VERACODE_HEADERS,
        timeout=30,
      )
    except requests.RequestException as e:
      log_warning(
        f'Veracode API returned an unexpected response looking for a {c_name} (GUID {veracode_guid}) summary report: {response.status_code} ({e})'
      )
      return None

    if veracode_r.ok:
      try:
        results_summary_data = veracode_r.json()
        data.update({'veracode_results_summary': results_summary_data})

        veracode_policy_rules_status = results_summary_data['policy_rules_status']
        data.update({'veracode_policy_rules_status': veracode_policy_rules_status})

        # If there is a report - assume the project shouldn't be exempt.
        data.update({'veracode_exempt': False})
        # log_debug(json.dumps(results_summary_data, indent=2))
      except Exception as e:
        log_debug(f'Unable to extract summary data from veracode: {e}')
    else:
      log_warning(
        f'Failure response from veracode for {c_name} (guid: {veracode_guid}): {response.status_code}'
      )

    log_debug(f'Veracode data: {data}')
    # Update component with all results in data dict.
    sc.update('components', c_id, data)
  else:
    log_info(f'No veracode scan found for {c_name}')


def process_components(data, services):
  log_info(f'Processing batch of {len(data)} components...')
  for component in data:
    component_name = component.get('name')
    t_repo = threading.Thread(
      target=process_component, args=(component,services), daemon=True
    )

    # Apply limit on total active threads, avoid github secondary API rate limit
    while threading.active_count() > (MAX_THREADS - 1):
      log_debug(f'Active Threads={threading.active_count()}, Max Threads={MAX_THREADS}')
      sleep(10)

    t_repo.start()
    log_info(f'Started thread for {component_name}')

  t_repo.join()
  log_info(f'Finished all threads for batch of {len(data)} components.')


def main():
  
  # service catalogue parameters
  sc_params = {
    'url': os.getenv('SERVICE_CATALOGUE_API_ENDPOINT'),
    'key': os.getenv('SERVICE_CATALOGUE_API_KEY'),
    'filter': os.getenv('SC_FILTER', ''),
  }
  # slack parameters
  slack_params = {
    'token': os.getenv('SLACK_BOT_TOKEN', ''),
    'notify_channel': os.getenv('SLACK_NOTIFY_CHANNEL', ''),
    'alert_channel': os.getenv('SLACK_ALERT_CHANNEL', ''),
  }
  job.name ='hmpps-veracode-discovery'

  services = Services(sc_params, slack_params)
  sc = services.sc
  slack = services.slack
  if not sc.connection_ok:
    log_error('Service Catalogue connection not OK, exiting.')
    slack.alert('hmpps-veracode-discovery failed: unable to reach Service Catalogue')
    raise SystemExit

  # Test connection to veracode
  if not VERACODE_API_KEY_ID:
    slack.alert('VERACODE_API_KEY_ID environment variable not set')
    job.error_messages.append("VERACODE_API_KEY_ID environment variable not set")
    sc.update_scheduled_job('Failed')
    raise SystemExit('hmpps-veracode-discovery failed: VERACODE_API_KEY_ID environment variable not set')

  if not VERACODE_API_KEY_SECRET:
    slack.alert('VERACODE_API_KEY_SECRET environment variable not set')
    job.error_messages.append("VERACODE_API_KEY_SECRET environment variable not set")
    sc.update_scheduled_job('Failed')
    raise SystemExit('hmpps-veracode-discovery failed: VERACODE_API_KEY_SECRET environment variable not set')

  try:
    response = requests.get(
      VERACODE_API_BASE + '/healthcheck/status',
      auth=RequestsAuthPluginVeracodeHMAC(),
      headers=VERACODE_HEADERS,
      timeout=30,
    )
    if response.status_code == 200:
      log_debug('Successfully connected to veracode API.')
  except Exception as e:
    log_critical('Unable to connect to the veracode API.')
    slack.alert('Unable to connect to the veracode API.')
    job.error_messages.append(f"Unable to connect to the veracode API")
    sc.update_scheduled_job('Failed')
    raise SystemExit(e) from e

  components = sc.get_all_records(sc.components_get)
  process_components(components, services)

  if job.error_messages:
    sc.update_scheduled_job('Errors')
    log_info("Veracode discovery job completed  with errors.")
  else:
    sc.update_scheduled_job('Succeeded')
    log_info("Veracode discovery job completed successfully.")

if __name__ == '__main__':
  main()
