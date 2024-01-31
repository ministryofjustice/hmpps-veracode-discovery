# HMPPS Veracode Discovery

This app queries the Veracode api for information about the latest SAST scans results for all hmpps projects, and pushes that information into the hmpps service catalogue.

The app does the following:
- Retrieves a list of all components (microservices) from the service catalogue.
- For each component it fetches the latest scan summary/results/score.
- It then updates each component in the service catalogue with this data.

Results are visible via the developer portal, e.g.

https://developer-portal.hmpps.service.justice.gov.uk/components/veracode