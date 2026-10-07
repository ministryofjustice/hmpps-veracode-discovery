import unittest
import pytest
from unittest.mock import patch, MagicMock
from requests.exceptions import RequestException
from veracode_discovery import run_veracode_connection

class RunVeracodeDiscovery(unittest.TestCase):
    def setUp(self):
      # Initialize mock_services as a class-level attribute
      self.mock_services = MagicMock()
      self.mock_services.auth = MagicMock()
      self.mock_services.headers = {"Authorization": "Bearer dummy_token"}

    @patch('veracode_discovery.run_veracode_connection')
    def test_missing_veracode_api_key_id(self, mock_get):
        with pytest.raises(SystemExit) as excinfo:
            run_veracode_connection(None, "dummy_secret", self.mock_services)
        assert "VERACODE_API_KEY_ID environment variable not set" in str(excinfo.value)
        mock_get.assert_not_called()

    @patch('veracode_discovery.run_veracode_connection')
    def test_missing_veracode_api_key_secret(self, mock_get):
        with pytest.raises(SystemExit) as excinfo:
            run_veracode_connection("dummy_id", None, self.mock_services)
        assert "VERACODE_API_KEY_SECRET environment variable not set" in str(excinfo.value)
        mock_get.assert_not_called()

    @patch('veracode_discovery.requests.get')
    def test_successful_connection(self, mock_get):
        # Mock the response object
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        # Mock the auth and headers explicitly
        mock_auth = MagicMock()
        mock_headers = {"Authorization": "Bearer dummy_token"}
        self.mock_services.auth = mock_auth
        self.mock_services.headers = mock_headers
        
        # Call the function being tested
        response = run_veracode_connection("dummy_id", "dummy_secret", self.mock_services)

        # Assertions
        mock_get.assert_called_once_with(
            "https://api.veracode.com/healthcheck/status",
            auth=self.mock_services.auth,
            headers=self.mock_services.headers,
            timeout=30,
        )
        assert response == mock_response
        self.mock_services.log_debug.assert_called_once_with("Veracode connection test successful.")

    # Uncomment and refactor this test if needed
    # @patch('veracode_discovery.run_veracode_connection')
    # def test_exception_handling(self, mock_log_critical, mock_get, mock_auth):
    #   # Mock the authentication plugin to avoid reading credentials from the file
    #   mock_auth.return_value = MagicMock()
      
    #   # Simulate an exception during the requests.get call
    #   mock_get.side_effect = RequestException("Connection error")

    #   # Call the function and verify it raises SystemExit
    #   with self.assertRaises(SystemExit) as cm:
    #     run_veracode_connection("dummy_id", "dummy_secret", mock_services)

    #   # Verify the log message
    #   mock_log_critical.assert_called_once_with("Unable to connect to the veracode API.")

    #   # Verify the exception message
    #   self.assertIn("Connection error", str(cm.exception))

if __name__ == '__main__':
    unittest.main()