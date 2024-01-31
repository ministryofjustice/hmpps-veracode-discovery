#!/usr/bin/env python
'''Github discovery - queries the github API for info about hmpps services and stores the results in the service catalogue'''
import os
import http.server
import socketserver
import threading
import logging
from time import sleep
from veracode_api_signing.plugin_requests import RequestsAuthPluginVeracodeHMAC
import requests

SC_API_ENDPOINT = os.getenv("SERVICE_CATALOGUE_API_ENDPOINT")
SC_API_TOKEN = os.getenv("SERVICE_CATALOGUE_API_KEY")

REFRESH_INTERVAL_HOURS = int(os.getenv("REFRESH_INTERVAL_HOURS", "6"))
# Set maximum number of concurrent threads to run, try to avoid secondary github api limits.
MAX_THREADS = 5
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

# limit results for testing/dev
# See strapi filter syntax https://docs.strapi.io/dev-docs/api/rest/filters-locale-publication
# Example filter string = '&filters[name][$contains]=example'
SC_FILTER = os.getenv("SC_FILTER", '')
SC_PAGE_SIZE=10
SC_PAGINATION_PAGE_SIZE=f"&pagination[pageSize]={SC_PAGE_SIZE}"
# Example Sort filter
#SC_SORT='&sort=updatedAt:asc'
SC_SORT = ''
SC_ENDPOINT = f"{SC_API_ENDPOINT}/v1/components?populate=environments{SC_FILTER}{SC_PAGINATION_PAGE_SIZE}{SC_SORT}"

VERACODE_API_KEY_ID = os.getenv("VERACODE_API_KEY_ID")
VERACODE_API_KEY_SECRET = os.getenv("VERACODE_API_KEY_SECRET")
VERACODE_API_BASE = "https://api.veracode.com"
VERACODE_HEADERS = {"User-Agent": "Python HMAC Example"}

class HealthHttpRequestHandler(http.server.SimpleHTTPRequestHandler):
  def do_GET(self):
    self.send_response(200)
    self.send_header("Content-type", "text/plain")
    self.end_headers()
    self.wfile.write(bytes("UP", "utf8"))
    return

def process_component(**component):
  c_name = component["attributes"]["name"]
  c_id = component["id"]
  # Empty data dict gets populated along the way, and finally used in PUT request to service catalogue
  data = {}
  veracode_guid = None

  try:
    response = requests.get(VERACODE_API_BASE + f"/appsec/v1/applications?name={c_name}", auth=RequestsAuthPluginVeracodeHMAC(), headers=VERACODE_HEADERS, timeout=30)
  except requests.RequestException as e:
    print(e)

  if response.ok:
    try:
      veracode_r = response.json()
      for app in veracode_r['_embedded']['applications']:
        if app['profile']['name'] == c_name:
          veracode_guid = app['guid']
          veracode_results_url = "https://analysiscenter.veracode.com/auth/index.jsp#" + app['results_url']
          data.update({"veracode_results_url": veracode_results_url})
          veracode_last_completed_scan_date = app['last_completed_scan_date']
          data.update({"veracode_last_completed_scan_date": veracode_last_completed_scan_date})
          log.debug(f"Found vericode app guid: {veracode_guid}")
          break
    except Exception as e:
      log.debug(e)
  else:
    log.debug(f"API returned response: {response.status_code}")

  if veracode_guid:
    try:
      veracode_r = requests.get(VERACODE_API_BASE + f"/appsec/v2/applications/{veracode_guid}/summary_report", auth=RequestsAuthPluginVeracodeHMAC(), headers=VERACODE_HEADERS, timeout=30)
    except requests.RequestException as e:
      log.debug(e)

    if veracode_r.ok:
      try:
        results_summary_data = veracode_r.json()
        data.update({"veracode_results_summary": results_summary_data})

        veracode_policy_rules_status = results_summary_data['policy_rules_status']
        data.update({"veracode_policy_rules_status": veracode_policy_rules_status})

        # If there is a report - assume the project shouldn't be exempt.
        data.update({"veracode_exempt": False})
        #print(json.dumps(results_summary_data, indent=2))
      except Exception as e:
        log.debug(e)
    else:
      print(response.status_code)

    log.debug(data)
    # Update component with all results in data dict.
    update_sc_component(c_id, data)

def startHttpServer():
  handler_object = HealthHttpRequestHandler
  with socketserver.TCPServer(("", 8080), handler_object) as httpd:
    httpd.serve_forever()

def update_sc_component(c_id, data):
  try:
    log.debug(data)
    x = requests.put(f"{SC_API_ENDPOINT}/v1/components/{c_id}", headers=sc_api_headers, json = {"data": data}, timeout=10)
    if x.status_code == 200:
      log.info(f"Successfully updated component id {c_id}: {x.status_code}")
    else:
      log.info(f"Received non-200 response from service catalogue for component id {c_id}: {x.status_code} {x.content}")
  except Exception as e:
    log.error(f"Error updating component in the SC: {e}")

def process_components(data):
  log.info(f"Processing batch of {len(data)} components...")
  for component in data:

    t_repo = threading.Thread(target=process_component, kwargs=component, daemon=True)

    # Apply limit on total active threads, avoid github secondary API rate limit
    while threading.active_count() > (MAX_THREADS-1):
      log.debug(f"Active Threads={threading.active_count()}, Max Threads={MAX_THREADS}")
      sleep(10)

    t_repo.start()
    component_name = component["attributes"]["name"]
    log.info(f"Started thread for {component_name}")

if __name__ == '__main__':
  logging.basicConfig(
      format='[%(asctime)s] %(levelname)s %(threadName)s %(message)s', level=LOG_LEVEL)
  log = logging.getLogger(__name__)

  sc_api_headers = {"Authorization": f"Bearer {SC_API_TOKEN}", "Content-Type":"application/json","Accept": "application/json"}

  # Test connection to Service Catalogue
  try:
    r = requests.head(f"{SC_API_ENDPOINT}/_health", headers=sc_api_headers, timeout=10)
    log.info(f"Successfully connected to the Service Catalogue. {r.status_code}")
  except Exception as e:
    log.critical("Unable to connect to the Service Catalogue.")
    raise SystemExit(e) from e

  # Test connection to veracode
  if not VERACODE_API_KEY_ID:
    raise SystemExit("VERACODE_API_KEY_ID env var not set")

  if not VERACODE_API_KEY_SECRET:
    raise SystemExit("VERACODE_API_KEY_SECRET env var not set")

  try:
    response = requests.get(VERACODE_API_BASE + "/healthcheck/status", auth=RequestsAuthPluginVeracodeHMAC(), headers=VERACODE_HEADERS, timeout=30)
    if response.status_code == 200:
      log.debug("Successfully connected to veracode API.")
  except Exception as e:
    log.critical("Unable to connect to the veracode API.")
    raise SystemExit(e) from e

  while True:
    # Start health endpoint.
    httpHealth = threading.Thread(target=startHttpServer, daemon=True)
    httpHealth.start()

    log.info(SC_ENDPOINT)
    try:
      r = requests.get(SC_ENDPOINT, headers=sc_api_headers, timeout=10)
      log.debug(r)
      if r.status_code == 200:
        j_meta = r.json()["meta"]["pagination"]
        log.debug(f"Got result page: {j_meta['page']} from SC")
        j_data = r.json()["data"]
        process_components(j_data)
      else:
        raise Exception(f"Received non-200 response from Service Catalogue: {r.status_code}")

      # Loop over the remaining pages and return one at a time
      num_pages = j_meta['pageCount']
      for p in range(2, num_pages+1):
        page=f"&pagination[page]={p}"
        r = requests.get(f"{SC_ENDPOINT}{page}", headers=sc_api_headers, timeout=10)
        if r.status_code == 200:
          j_meta = r.json()["meta"]["pagination"]
          log.debug(f"Got result page: {j_meta['page']} from SC")
          j_data = r.json()["data"]
          process_components(j_data)
        else:
          raise Exception(f"Received non-200 response from Service Catalogue: {r.status_code}")

    except Exception as e:
      log.error(f"Problem with Service Catalogue API. {e}")

    sleep((REFRESH_INTERVAL_HOURS * 60 * 60))
